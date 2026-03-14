---
lane: planned
---

# WP07 - Source Link Verification

> **Spec**: `specs/link-verification-timeframe.spec.md`
> **Status**: Not Started
> **Priority**: P1
> **Goal**: When `verify_links` is enabled, all source URLs collected during research are verified via HTTP HEAD/GET before formatting, and broken links are silently removed from the newsletter.
> **Independent Test**: Set `verify_links: true` in topics.yaml. Mock one source URL to return 404. Run the pipeline. Verify the broken link is absent from the final HTML and working links remain.
> **Depends on**: WP06 (for `verify_links` field on AppSettings and `config_verify_links` session state key)
> **Parallelisable**: Partially (T07-01 through T07-04 can start before WP06 is complete; T07-05 and T07-08 depend on WP06)
> **Prompt**: `plans/WP07-link-verification.md`

## Objective

This work package implements the source link verification pipeline stage. When the operator sets `verify_links: true` in the `settings` section of `topics.yaml`, a new `LinkVerifierAgent` (a `BaseAgent` subclass) executes after synthesis post-processing and before HTML formatting. The agent extracts all source URLs from session state, verifies them concurrently using httpx async HTTP HEAD requests (with GET fallback), removes broken links from both the sources list and inline markdown citations, and writes the cleaned results back to session state. When `verify_links` is `false` (the default), the agent is a no-op passthrough. The feature includes SSRF protection, logging for observability, and graceful degradation if the entire verification stage fails.

## Spec References

- FR-013 (verify_links config field - defined in WP06 T06-03)
- FR-014 through FR-024 (Section 4.3 - Link Verification)
- FR-025, FR-026 (Section 4.4 - Pipeline Integration)
- US-04 (Verify source links automatically)
- US-05 (Handle all sources broken for a topic)
- Section 7.1 Data Model: LinkCheckResult
- Section 7.2 Session State: config_verify_links
- Section 8.5 (verify_urls function)
- Section 8.6 (LinkVerifierAgent)
- Section 9.1 System Design: pipeline stage placement
- Section 9.4 Decision 2 (HEAD with GET fallback), Decision 3 (status-code only), Decision 4 (BaseAgent not LlmAgent)
- Section 10.1 Performance: 30-second target for 40 URLs
- Section 10.2 Security: SSRF prevention, scheme restriction, private IP blocking
- Section 10.5 Observability: verification logging
- Section 11.1 Unit Tests: link_verifier.py, link_verifier_agent.py
- Section 11.2 BDD: Source Link Verification scenarios
- Section 11.5 Performance Tests
- Section 11.6 Security Tests

## Tasks

### T07-01 - Create LinkCheckResult Dataclass

- **Description**: Create a new module `newsletter_agent/tools/link_verifier.py` containing the `LinkCheckResult` dataclass. This is a simple immutable container for individual URL verification results: the URL, its status ("valid" or "broken"), the HTTP status code (if any), and an error description (if check failed). This dataclass is used internally by `verify_urls()` and by `LinkVerifierAgent`.
- **Spec refs**: Section 7.1 (LinkCheckResult), FR-017
- **Parallel**: Yes (independent of all other tasks)
- **Acceptance criteria**:
  - [ ] `LinkCheckResult` is a frozen dataclass with fields: `url: str`, `status: str`, `http_status: int | None`, `error: str | None`
  - [ ] `status` field accepts only `"valid"` or `"broken"` (enforced by type hint documentation; no runtime check needed for internal use)
  - [ ] The dataclass is importable from `newsletter_agent.tools.link_verifier`
  - [ ] Instances are immutable (frozen=True)
- **Test requirements**: unit (basic construction test in test_link_verifier.py)
- **Depends on**: none
- **Implementation Guidance**:
  - Use `@dataclass(frozen=True)` for immutability
  - No Pydantic model needed - this is internal, not user-facing config
  - Keep in the same module as `verify_urls()` for cohesion
  - The `error` field holds descriptive strings like "timeout", "dns_error", "ssl_error", "redirect_limit", "status_404", etc.

### T07-02 - Implement verify_urls() Async Function

- **Description**: Implement the `verify_urls()` async function in `newsletter_agent/tools/link_verifier.py`. This function takes a list of URL strings and concurrently verifies each one using `httpx.AsyncClient` with HTTP HEAD requests (falling back to GET on 405). It uses `asyncio.Semaphore` on concurrency (default 10) and a per-request timeout (default 10 seconds). Returns a dict mapping each URL to its `LinkCheckResult`. Includes SSRF protection (block private IPs and non-HTTP schemes in redirect targets).
- **Spec refs**: FR-016, FR-017, FR-018, FR-019, FR-022, Section 8.5, Section 10.2
- **Parallel**: No (depends on T07-01 for LinkCheckResult)
- **Acceptance criteria**:
  - [ ] URL returning HTTP 200 -> `LinkCheckResult(url=url, status="valid", http_status=200, error=None)`
  - [ ] URL returning HTTP 301 (redirect followed, final 200) -> `LinkCheckResult(status="valid", http_status=200, error=None)`
  - [ ] URL returning HTTP 404 -> `LinkCheckResult(status="broken", http_status=404, error="status_404")`
  - [ ] URL returning HTTP 500 -> `LinkCheckResult(status="broken", http_status=500, error="status_500")`
  - [ ] URL timeout (no response in 10s) -> `LinkCheckResult(status="broken", http_status=None, error="timeout")`
  - [ ] URL DNS failure -> `LinkCheckResult(status="broken", http_status=None, error="dns_error")`
  - [ ] URL SSL error -> `LinkCheckResult(status="broken", http_status=None, error="ssl_error")`
  - [ ] HEAD returns 405, GET returns 200 -> `LinkCheckResult(status="valid", http_status=200, error=None)`
  - [ ] Redirect chain exceeding 5 hops -> `LinkCheckResult(status="broken", http_status=None, error="redirect_limit")`
  - [ ] URL resolving to private IP (127.0.0.1, 10.x.x.x, 172.16.x.x, 192.168.x.x, ::1) -> `LinkCheckResult(status="broken", http_status=None, error="ssrf_blocked")`
  - [ ] URL with non-HTTP scheme redirect (javascript:, file:, ftp:) -> `LinkCheckResult(status="broken", http_status=None, error="invalid_scheme")`
  - [ ] User-Agent header set to `"NewsletterAgent/1.0 (link-check)"` on all requests
  - [ ] No cookies, auth headers, or cached credentials sent
  - [ ] Empty URL list -> returns empty dict immediately
  - [ ] Concurrency: 20 URLs with max_concurrent=10 -> at most 10 simultaneous requests
  - [ ] Function never raises; all errors captured in LinkCheckResult
- **Test requirements**: unit (test_link_verifier.py)
- **Depends on**: T07-01
- **Implementation Guidance**:
  - Official docs: httpx async client - https://www.python-httpx.org/async/
  - Use `httpx.AsyncClient(follow_redirects=True, max_redirects=5, timeout=timeout)` for redirect handling
  - Set `headers={"User-Agent": "NewsletterAgent/1.0 (link-check)"}` in the client constructor
  - SSRF protection: Use a custom `httpx` transport or event hook to check resolved IPs. Alternative: after getting a response, check if the final URL's host resolves to a private IP using `ipaddress.ip_address()`. However, the simplest approach is to parse the URL host and check it against known private ranges before making the request, and also check the response URL after redirects
  - For HEAD -> GET fallback: `try: resp = await client.head(url); if resp.status_code == 405: resp = await client.get(url, ...)`
  - For GET fallback, use `async with client.stream("GET", url) as resp: status = resp.status_code` to avoid downloading full response body
  - Concurrency pattern: `async def _check_one(url, semaphore, client): async with semaphore: ...` then `await asyncio.gather(*[_check_one(u, sem, client) for u in urls])`
  - Exception mapping: `httpx.TimeoutException -> "timeout"`, `httpx.ConnectError -> "dns_error" or "connection_error"`, `ssl.SSLError -> "ssl_error"`, `httpx.TooManyRedirects -> "redirect_limit"`

### T07-03 - Implement SSRF Protection in verify_urls()

- **Description**: Add SSRF mitigation to `verify_urls()`. Before making a request, check if the URL host resolves to a private/internal IP range. After following redirects, check if the final destination URL uses a non-HTTP(S) scheme or resolves to a private IP. Block both cases and return a "broken" result with appropriate error descriptions. This task can be implemented as part of T07-02 but is tracked separately for clarity of acceptance criteria.
- **Spec refs**: Section 10.2 Security (SSRF mitigation, scheme restriction, private IP blocking)
- **Parallel**: No (part of T07-02 implementation)
- **Acceptance criteria**:
  - [ ] URL with host `127.0.0.1` -> blocked with error "ssrf_blocked"
  - [ ] URL with host `10.0.0.1` -> blocked with error "ssrf_blocked"
  - [ ] URL with host `172.16.0.1` -> blocked with error "ssrf_blocked"
  - [ ] URL with host `192.168.1.1` -> blocked with error "ssrf_blocked"
  - [ ] URL with host `::1` (IPv6 loopback) -> blocked with error "ssrf_blocked"
  - [ ] URL with host `fc00::1` (IPv6 private) -> blocked with error "ssrf_blocked"
  - [ ] URL that redirects to `http://127.0.0.1/admin` -> blocked after redirect with error "ssrf_blocked"
  - [ ] URL with scheme `javascript:alert(1)` -> blocked with error "invalid_scheme"
  - [ ] URL that redirects to `file:///etc/passwd` -> blocked with error "invalid_scheme"
  - [ ] URL with scheme `ftp://example.com` -> blocked with error "invalid_scheme"
  - [ ] Normal public URL `https://example.com` -> not blocked, proceeds to verification
- **Test requirements**: unit (security-focused tests in test_link_verifier.py), security (Section 11.6)
- **Depends on**: T07-01
- **Implementation Guidance**:
  - Use Python `ipaddress` module: `ipaddress.ip_address(host).is_private` checks RFC 1918 ranges
  - For URL scheme checking, use `urllib.parse.urlparse(url).scheme` and allow only `"http"` and `"https"`
  - For hostname-based private IP checking pre-request: `socket.getaddrinfo(host, None)` resolves DNS, then check each result with `ipaddress.ip_address().is_private`
  - Known pitfall: `socket.getaddrinfo()` is blocking. In an async context, use `asyncio.get_event_loop().getaddrinfo()` or `asyncio.to_thread(socket.getaddrinfo, ...)`
  - Known pitfall: Some hostnames might have both public and private A records (DNS rebinding). Checking pre-request is a best-effort mitigation
  - For redirect checking: After `client.head(url)` or `client.get(url)`, check `response.url` (the final URL after redirects) against the same private IP and scheme rules

### T07-04 - Implement Markdown Citation Cleaner

- **Description**: Create a helper function `clean_broken_links_from_markdown(markdown: str, broken_urls: set[str]) -> str` in `newsletter_agent/tools/link_verifier.py`. This function scans markdown text for inline citations `[Title](url)` and replaces any whose URL is in the broken set with just the title text (removing the link but preserving the text). This is used by `LinkVerifierAgent` to clean synthesis `body_markdown` after verification.
- **Spec refs**: FR-020 (inline markdown citations replaced with unlinked text)
- **Parallel**: Yes (independent of T07-02, T07-03; only needs knowledge of markdown link format)
- **Acceptance criteria**:
  - [ ] `clean_broken_links_from_markdown("See [Article](http://broken.com)", {"http://broken.com"})` returns `"See Article"`
  - [ ] `clean_broken_links_from_markdown("See [Article](http://working.com)", {"http://broken.com"})` returns `"See [Article](http://working.com)"` (unchanged)
  - [ ] Multiple broken links in one string are all cleaned
  - [ ] Nested brackets or parentheses in title text are handled correctly (e.g., `[Title (2025)](url)`)
  - [ ] URLs with query strings and fragments are matched exactly (e.g., `http://example.com/page?id=1#section`)
  - [ ] Empty broken_urls set -> markdown returned unchanged
  - [ ] Markdown with no links -> returned unchanged
  - [ ] Link with empty title `[](url)` -> replaced with empty string
- **Test requirements**: unit (test_link_verifier.py)
- **Depends on**: none
- **Implementation Guidance**:
  - Use regex: `re.compile(r'\[([^\]]*)\]\(([^)]+)\)')` to find markdown links
  - For each match, check if the URL (group 2) is in `broken_urls`
  - If broken, replace the full match with just the title (group 1)
  - Use `re.sub()` with a callback function for the replacement
  - Known pitfall: URLs with parentheses (rare but possible) break the simple regex. For v1, the simple regex is acceptable - the spec doesn't mention URL-encoded parentheses
  - Known pitfall: Image links `![alt](url)` should NOT be cleaned by this function. Only `[text](url)` (no `!` prefix). Adjust the regex to not match if preceded by `!`

### T07-05 - Implement LinkVerifierAgent

- **Description**: Create `newsletter_agent/agents/link_verifier_agent.py` containing the `LinkVerifierAgent` class, a `BaseAgent` subclass. The agent reads `config_verify_links` from session state. If `false`, it is a no-op. If `true`, it collects all source URLs from `synthesis_{topic_index}` entries in session state, calls `verify_urls()`, then cleans the synthesis results by removing broken links from source lists and inline citations from `body_markdown`. If all sources for a topic are removed, it appends a notice. If the entire verification stage fails, it logs a warning and proceeds (graceful degradation).
- **Spec refs**: FR-014, FR-015, FR-020, FR-021, FR-023, FR-024, Section 8.6
- **Parallel**: No (depends on T07-02, T07-03, T07-04)
- **Acceptance criteria**:
  - [ ] `verify_links=false` -> agent reads and writes state unchanged, no HTTP requests made
  - [ ] `verify_links=true`, all links valid -> state unchanged (all sources and citations preserved)
  - [ ] `verify_links=true`, 2 of 5 links broken -> 2 removed from `sources` list, inline citations for broken URLs replaced with unlinked text
  - [ ] `verify_links=true`, all links broken for topic -> sources list empty, notice appended: `"\n\n*Note: Sources for this topic could not be verified and have been omitted.*"`
  - [ ] `verify_links=true`, some links broken, some valid for a topic -> no notice, only broken removed
  - [ ] When all links valid, `body_markdown` is bit-for-bit identical to input (no unnecessary mutation)
  - [ ] Logging at INFO: `"Link verification: {valid}/{total} URLs verified, {broken} removed"`
  - [ ] Logging at DEBUG: `"Broken link removed: {url} - reason: {error}"` for each broken URL
  - [ ] If `verify_urls()` raises an exception (network completely down), log WARNING and proceed with unverified state
  - [ ] Agent reads `config_verify_links` from session state, not from config directly
  - [ ] Agent reads topic count from session state (`config_topic_count` or iterates `synthesis_{i}` keys)
- **Test requirements**: unit (test_link_verifier_agent.py)
- **Depends on**: T07-02, T07-03, T07-04
- **Implementation Guidance**:
  - Follow the pattern of existing BaseAgent subclasses in `newsletter_agent/agent.py` (e.g., `SynthesisPostProcessorAgent`)
  - The `_run_async_impl()` signature follows ADK: `async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]`
  - Access session state via `ctx.session.state`
  - To collect URLs from synthesis results: iterate `synthesis_{i}` entries, extract `sources` list, collect all unique `url` fields
  - After verification, update each `synthesis_{i}` entry in place: filter `sources` list, clean `body_markdown`
  - The "all broken" notice text is: `"\n\n*Note: Sources for this topic could not be verified and have been omitted.*"`
  - Graceful degradation: wrap the entire verification in try/except. On exception, log warning and return without modifying state
  - No `yield` needed if the agent doesn't produce intermediate events - just return after modifying state

### T07-06 - Insert LinkVerifierAgent into Pipeline

- **Description**: Modify `build_agent()` in `newsletter_agent/agent.py` to conditionally include `LinkVerifierAgent` in the root `SequentialAgent` pipeline. The agent should be placed after `SynthesisPostProcessorAgent` and before the `OutputPhase` agent. When `verify_links` is `false`, the agent is still included but acts as a no-op (or optionally, not included at all). The config is read at pipeline construction time.
- **Spec refs**: FR-025, FR-026, Section 9.1
- **Parallel**: No (depends on T07-05)
- **Acceptance criteria**:
  - [ ] When `verify_links=true`, `LinkVerifierAgent` appears in the pipeline between `SynthesisPostProcessorAgent` and `OutputPhase`
  - [ ] When `verify_links=false`, the pipeline either omits `LinkVerifierAgent` or includes it as a no-op (both approaches acceptable per spec)
  - [ ] The existing pipeline order is preserved: ConfigLoader -> ResearchPhase -> ResearchValidator -> PipelineAbortCheck -> Synthesizer -> SynthesisPostProcessor -> [LinkVerifier] -> OutputPhase
  - [ ] `build_agent()` accepts the config and uses `config.settings.verify_links` to decide
- **Test requirements**: unit (test_agent_factory.py additions)
- **Depends on**: T07-05
- **Implementation Guidance**:
  - Read the current `build_agent()` function to understand the pipeline construction
  - The simplest approach: always include `LinkVerifierAgent` in the pipeline. It reads `config_verify_links` from session state and no-ops when false. This avoids conditional pipeline construction
  - Alternative: conditionally include based on `config.settings.verify_links`. This is cleaner but means the pipeline structure varies
  - The spec says "conditionally include" (FR-026), so the conditional approach is more aligned
  - If using conditional inclusion: `agents = [...postprocessor]; if config.settings.verify_links: agents.append(LinkVerifierAgent(name="LinkVerifier")); agents.append(output_phase)`

### T07-07 - Unit Tests for verify_urls() and LinkCheckResult

- **Description**: Create `tests/unit/test_link_verifier.py` with comprehensive unit tests for the `verify_urls()` function and `LinkCheckResult` dataclass. Use `pytest-httpx` or manual `httpx` mocking to simulate various HTTP scenarios. Cover all status codes, timeouts, DNS failures, SSL errors, HEAD-to-GET fallback, redirect chains, SSRF protection, and concurrency limits.
- **Spec refs**: Section 11.1 (Link verification unit tests), Section 11.5 (Performance), Section 11.6 (Security)
- **Parallel**: No (depends on T07-02, T07-03)
- **Acceptance criteria**:
  - [ ] Test: URL returning 200 -> valid
  - [ ] Test: URL returning 301 -> valid (redirect followed)
  - [ ] Test: URL returning 404 -> broken
  - [ ] Test: URL returning 500 -> broken
  - [ ] Test: URL timeout -> broken with error "timeout"
  - [ ] Test: URL DNS failure -> broken with error "dns_error"
  - [ ] Test: URL SSL error -> broken with error "ssl_error"
  - [ ] Test: HEAD 405 then GET 200 -> valid (fallback works)
  - [ ] Test: Redirect chain > 5 hops -> broken with error "redirect_limit"
  - [ ] Test: Private IP (127.0.0.1, 10.x, 172.16.x, 192.168.x, ::1) -> broken with error "ssrf_blocked"
  - [ ] Test: Non-HTTP scheme redirect -> broken with error "invalid_scheme"
  - [ ] Test: User-Agent header is set correctly
  - [ ] Test: No cookies or auth headers sent
  - [ ] Test: Empty URL list -> empty result dict
  - [ ] Test: Concurrency limit enforced (optional - can test with timing or mock counter)
  - [ ] All tests pass
- **Test requirements**: unit
- **Depends on**: T07-02, T07-03
- **Implementation Guidance**:
  - Use `respx` (recommended) or `pytest-httpx` to mock httpx async client calls
  - For DNS failure simulation: mock `httpx.AsyncClient.head()` to raise `httpx.ConnectError`
  - For timeout simulation: mock to raise `httpx.ReadTimeout` or `httpx.ConnectTimeout`
  - For SSL error simulation: mock to raise `ssl.SSLError` or `httpx.ConnectError` with SSL context
  - For concurrency test: use a counter in the mock to track simultaneous requests
  - For SSRF tests: mock DNS resolution to return private IPs, or test with known private IP URLs
  - Use `pytest.mark.asyncio` for all async test functions

### T07-08 - Unit Tests for LinkVerifierAgent

- **Description**: Create `tests/unit/test_link_verifier_agent.py` with unit tests for the `LinkVerifierAgent` class. Mock `verify_urls()` to return predetermined results. Test the agent's behavior for disabled verification, all-valid, some-broken, all-broken, and total failure scenarios. Verify state mutation and logging.
- **Spec refs**: Section 11.1 (LinkVerifierAgent unit tests)
- **Parallel**: No (depends on T07-05)
- **Acceptance criteria**:
  - [ ] Test: `verify_links=false` -> no call to `verify_urls()`, state unchanged
  - [ ] Test: all links valid -> state unchanged (sources and body_markdown preserved)
  - [ ] Test: 2 of 5 broken -> 2 removed from sources, citations cleaned in body_markdown
  - [ ] Test: all broken for a topic -> sources empty, notice appended to body_markdown
  - [ ] Test: inline citation `[Title](broken_url)` replaced with `Title`
  - [ ] Test: total verification failure (verify_urls raises) -> state unchanged, warning logged
  - [ ] Test: agent reads `config_verify_links` from session state
  - [ ] Test: agent processes multiple topics independently
  - [ ] All tests pass
- **Test requirements**: unit
- **Depends on**: T07-05
- **Implementation Guidance**:
  - Mock `verify_urls()` using `unittest.mock.patch` to control verification results
  - Create session state fixtures with pre-populated `synthesis_{i}` entries containing `body_markdown` and `sources`
  - For the "all broken" test, verify the exact notice text matches spec
  - For the "total failure" test, make `verify_urls` raise an `Exception` and verify the agent catches it
  - Follow the pattern of existing agent tests (e.g., test_agent_factory.py)

### T07-09 - Unit Tests for Markdown Citation Cleaner

- **Description**: Add unit tests for `clean_broken_links_from_markdown()` function. Cover various markdown link patterns, edge cases with special characters, and the non-matching of image links.
- **Spec refs**: FR-020, Section 11.1
- **Parallel**: No (depends on T07-04)
- **Acceptance criteria**:
  - [ ] Test: single broken link replaced with title text
  - [ ] Test: working link unchanged
  - [ ] Test: multiple broken links in one string
  - [ ] Test: mixed broken and working links
  - [ ] Test: title with parentheses `[Title (2025)](url)` handled correctly
  - [ ] Test: URL with query string `?id=1&foo=bar` matched exactly
  - [ ] Test: URL with fragment `#section` matched exactly
  - [ ] Test: empty broken set -> unchanged
  - [ ] Test: no links in markdown -> unchanged
  - [ ] Test: image link `![alt](url)` NOT cleaned (only `[text](url)`)
  - [ ] All tests pass
- **Test requirements**: unit
- **Depends on**: T07-04
- **Implementation Guidance**:
  - These are pure function tests - no mocking needed
  - Use multi-line markdown strings for realistic test data
  - Test edge case: consecutive broken links on adjacent lines

### T07-10 - BDD Tests for Link Verification

- **Description**: Create `tests/bdd/test_link_verification.py` with BDD-style acceptance tests covering the 5 scenarios defined in the spec: all links valid, some broken, all broken for a topic, verification disabled, and network failure.
- **Spec refs**: Section 11.2 (Source Link Verification BDD scenarios)
- **Parallel**: No (depends on T07-05, T07-06)
- **Acceptance criteria**:
  - [ ] Scenario "All links valid" passes
  - [ ] Scenario "Some links broken" passes
  - [ ] Scenario "All links broken for a topic" passes
  - [ ] Scenario "Link verification disabled" passes
  - [ ] Scenario "Link verification network failure" passes
  - [ ] Tests use descriptive Given/When/Then naming or comments
  - [ ] Tests mock HTTP responses, not real network calls
- **Test requirements**: BDD
- **Depends on**: T07-05, T07-06
- **Implementation Guidance**:
  - Follow the existing BDD pattern in `tests/bdd/` directory
  - Create session state fixtures that simulate post-synthesis state
  - Mock `httpx.AsyncClient` responses for each scenario
  - For "all links valid": mock all URLs to return 200
  - For "some broken": mock 2 URLs to return 404, 3 to return 200
  - For "all broken": mock all URLs for one topic to return 404
  - For "disabled": set `config_verify_links=false` and verify no HTTP calls
  - For "network failure": mock to raise `Exception` on all URLs

## Implementation Notes

### File Changes Summary

| File | Action | Description |
|------|--------|-------------|
| `newsletter_agent/tools/link_verifier.py` | Create | `LinkCheckResult`, `verify_urls()`, `clean_broken_links_from_markdown()` |
| `newsletter_agent/agents/link_verifier_agent.py` | Create | `LinkVerifierAgent(BaseAgent)` |
| `newsletter_agent/agent.py` | Modify | Insert LinkVerifierAgent into pipeline |
| `tests/unit/test_link_verifier.py` | Create | verify_urls() and helper tests |
| `tests/unit/test_link_verifier_agent.py` | Create | LinkVerifierAgent tests |
| `tests/bdd/test_link_verification.py` | Create | BDD acceptance tests |

### HTTP Verification Flow

```
For each URL:
  1. Parse URL scheme - reject if not http/https
  2. Resolve hostname - reject if private IP
  3. Send HTTP HEAD with 10s timeout
  4. If response 405 (Method Not Allowed):
     a. Send HTTP GET with stream=True and 10s timeout
     b. Read status code only (don't download body)
  5. If response 200-399: mark valid
  6. If response 400+: mark broken with status code
  7. On timeout: mark broken with "timeout"
  8. On DNS error: mark broken with "dns_error"
  9. On SSL error: mark broken with "ssl_error"
  10. On redirect limit: mark broken with "redirect_limit"
```

### Session State Structure for Synthesis Results

The `LinkVerifierAgent` reads and writes `synthesis_{topic_index}` entries. Each entry has this structure (set by `SynthesisPostProcessorAgent`):

```python
state[f"synthesis_{idx}"] = {
    "topic_name": "AI Advances",
    "body_markdown": "## AI Advances\n\nRecent developments include [Article 1](https://example.com/1) and [Article 2](https://broken.com/2).\n",
    "sources": [
        {"title": "Article 1", "url": "https://example.com/1", "provider": "perplexity"},
        {"title": "Article 2", "url": "https://broken.com/2", "provider": "google"},
    ]
}
```

After link verification (with broken.com/2 returning 404):

```python
state[f"synthesis_{idx}"] = {
    "topic_name": "AI Advances",
    "body_markdown": "## AI Advances\n\nRecent developments include [Article 1](https://example.com/1) and Article 2.\n",
    "sources": [
        {"title": "Article 1", "url": "https://example.com/1", "provider": "perplexity"},
    ]
}
```

### Concurrency Model

```
asyncio.Semaphore(10)
    |
    +-- Task 1: check URL 1
    +-- Task 2: check URL 2
    +-- ...
    +-- Task N: check URL N
    (at most 10 tasks hold the semaphore at any time)
```

All URLs across all topics are collected into a single list and verified once. The results are then used to clean each topic's synthesis data. This avoids duplicate verification of the same URL appearing in multiple topics.

### Pipeline Stage Placement

```
Current pipeline:
  ConfigLoader -> ResearchPhase -> ResearchValidator -> PipelineAbortCheck
    -> Synthesizer -> SynthesisPostProcessor -> OutputPhase

New pipeline (verify_links=true):
  ConfigLoader -> ResearchPhase -> ResearchValidator -> PipelineAbortCheck
    -> Synthesizer -> SynthesisPostProcessor -> LinkVerifier -> OutputPhase

New pipeline (verify_links=false):
  Same as current (LinkVerifier omitted or included as no-op)
```

## Parallel Opportunities

- **[P] T07-01 + T07-04**: LinkCheckResult dataclass and markdown cleaner are independent
- **[P] T07-07 + T07-09**: Unit tests for verify_urls and markdown cleaner are independent once implementations exist
- Sequential chain: T07-01 -> T07-02 (includes T07-03) -> T07-05 -> T07-06 -> T07-08 -> T07-10

## Risks & Mitigations

- **Risk**: httpx async mocking may be complex with `respx` or `pytest-httpx` libraries.
  - **Mitigation**: Use `respx` which integrates well with httpx. Fall back to `unittest.mock.patch` on `httpx.AsyncClient` methods if needed.

- **Risk**: SSRF protection via DNS resolution adds latency and complexity.
  - **Mitigation**: Pre-resolve DNS for all URLs in bulk before starting HTTP checks. Cache results to avoid double resolution.

- **Risk**: Some legitimate URLs may be falsely blocked by aggressive SSRF protection (e.g., URLs behind VPN or corporate networks).
  - **Mitigation**: The current design only blocks RFC 1918 private ranges and loopback. Corporate internal URLs would typically be on these ranges anyway and shouldn't appear as newsletter sources.

- **Risk**: `asyncio.Semaphore` and httpx AsyncClient interaction may have edge cases.
  - **Mitigation**: Use a single `httpx.AsyncClient` instance for all requests (connection pooling) and wrap each `_check_one()` coroutine with the semaphore. Test concurrency behavior.

- **Risk**: redirect following may be inconsistent between HEAD and GET requests.
  - **Mitigation**: httpx handles redirects consistently for both methods. The `max_redirects=5` setting applies to both.

## Detailed Task Walkthroughs

### T07-01 Walkthrough: LinkCheckResult Dataclass

Simple implementation:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class LinkCheckResult:
    """Result of checking a single URL's liveness."""
    url: str
    status: str  # "valid" or "broken"
    http_status: int | None = None
    error: str | None = None
```

This is intentionally minimal. No validation logic on the dataclass itself - the calling code (`verify_urls`) is responsible for constructing it correctly.

### T07-02 Walkthrough: verify_urls() Implementation

**Function skeleton:**

```python
import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

import httpx

_USER_AGENT = "NewsletterAgent/1.0 (link-check)"
_ALLOWED_SCHEMES = {"http", "https"}
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def _is_private_ip(host: str) -> bool:
    """Check if a hostname resolves to a private IP address."""
    try:
        addr = ipaddress.ip_address(host)
        return addr.is_private or addr.is_loopback
    except ValueError:
        # It's a hostname, try to resolve it
        pass
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for family, type_, proto, canonname, sockaddr in infos:
            ip_str = sockaddr[0]
            addr = ipaddress.ip_address(ip_str)
            if addr.is_private or addr.is_loopback:
                return True
    except (socket.gaierror, OSError):
        pass
    return False


def _is_valid_scheme(url: str) -> bool:
    """Check if a URL uses an allowed scheme (http or https)."""
    parsed = urlparse(url)
    return parsed.scheme.lower() in _ALLOWED_SCHEMES


async def _check_one_url(
    url: str,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
) -> LinkCheckResult:
    """Check a single URL with semaphore-controlled concurrency."""
    # Pre-flight checks
    if not _is_valid_scheme(url):
        return LinkCheckResult(url=url, status="broken", error="invalid_scheme")
    
    parsed = urlparse(url)
    if _is_private_ip(parsed.hostname or ""):
        return LinkCheckResult(url=url, status="broken", error="ssrf_blocked")
    
    async with semaphore:
        try:
            resp = await client.head(url)
            
            if resp.status_code == 405:
                # HEAD not supported, try GET with streaming
                async with client.stream("GET", url) as resp:
                    status_code = resp.status_code
            else:
                status_code = resp.status_code
            
            # Check final URL after redirects for SSRF
            final_url = str(resp.url)
            if not _is_valid_scheme(final_url):
                return LinkCheckResult(url=url, status="broken", error="invalid_scheme")
            final_parsed = urlparse(final_url)
            if _is_private_ip(final_parsed.hostname or ""):
                return LinkCheckResult(url=url, status="broken", error="ssrf_blocked")
            
            if 200 <= status_code <= 399:
                return LinkCheckResult(url=url, status="valid", http_status=status_code)
            else:
                return LinkCheckResult(
                    url=url, status="broken",
                    http_status=status_code,
                    error=f"status_{status_code}",
                )
        except httpx.TimeoutException:
            return LinkCheckResult(url=url, status="broken", error="timeout")
        except httpx.TooManyRedirects:
            return LinkCheckResult(url=url, status="broken", error="redirect_limit")
        except Exception as exc:
            error_type = type(exc).__name__
            if "ssl" in error_type.lower() or "ssl" in str(exc).lower():
                return LinkCheckResult(url=url, status="broken", error="ssl_error")
            if "dns" in str(exc).lower() or "name resolution" in str(exc).lower():
                return LinkCheckResult(url=url, status="broken", error="dns_error")
            return LinkCheckResult(url=url, status="broken", error=f"connection_error: {error_type}")


async def verify_urls(
    urls: list[str],
    timeout: float = 10.0,
    max_concurrent: int = 10,
) -> dict[str, LinkCheckResult]:
    """Verify a list of URLs concurrently and return results."""
    if not urls:
        return {}
    
    semaphore = asyncio.Semaphore(max_concurrent)
    async with httpx.AsyncClient(
        follow_redirects=True,
        max_redirects=5,
        timeout=httpx.Timeout(timeout),
        headers={"User-Agent": _USER_AGENT},
    ) as client:
        tasks = [_check_one_url(url, client, semaphore) for url in urls]
        results = await asyncio.gather(*tasks)
    
    return {result.url: result for result in results}
```

**Key design decisions in this implementation:**

1. **Single client instance**: All requests share one `httpx.AsyncClient` for connection pooling
2. **Pre-flight SSRF check**: Before making any request, check scheme and private IP
3. **Post-redirect SSRF check**: After following redirects, check the final URL
4. **Exception categorization**: Map httpx exceptions to descriptive error strings
5. **Streaming GET**: Use `client.stream("GET", url)` to avoid downloading response body on fallback

### T07-04 Walkthrough: Markdown Citation Cleaner

**Implementation:**

```python
import re

_MARKDOWN_LINK_PATTERN = re.compile(
    r'(?<!!)\[([^\]]*)\]\(([^)]+)\)'
)


def clean_broken_links_from_markdown(
    markdown: str,
    broken_urls: set[str],
) -> str:
    """Replace markdown links with broken URLs with just the link text."""
    if not broken_urls:
        return markdown
    
    def _replacer(match: re.Match) -> str:
        title = match.group(1)
        url = match.group(2)
        if url in broken_urls:
            return title
        return match.group(0)
    
    return _MARKDOWN_LINK_PATTERN.sub(_replacer, markdown)
```

**Key design decisions:**

1. **Negative lookbehind `(?<!!)` **: Ensures image links `![alt](url)` are not matched
2. **Callback-based replacement**: The `re.sub` with a callback allows per-match decision making
3. **Exact URL matching**: URLs must match exactly (including query strings and fragments)
4. **Title preservation**: Only the URL markup is removed; the display text is kept

### T07-05 Walkthrough: LinkVerifierAgent

**Agent skeleton:**

```python
import logging
from typing import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event

from newsletter_agent.tools.link_verifier import (
    clean_broken_links_from_markdown,
    verify_urls,
)

logger = logging.getLogger(__name__)

_ALL_BROKEN_NOTICE = (
    "\n\n*Note: Sources for this topic could not be verified and have been omitted.*"
)


class LinkVerifierAgent(BaseAgent):
    """Post-synthesis agent that verifies source URLs and removes broken links."""

    async def _run_async_impl(
        self,
        ctx: InvocationContext,
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        
        verify_links = state.get("config_verify_links", False)
        if not verify_links:
            logger.info("Link verification skipped (verify_links=false)")
            return
        
        # Collect all unique URLs across topics
        topic_count = state.get("config_topic_count", 0)
        all_urls: set[str] = set()
        for i in range(topic_count):
            synth = state.get(f"synthesis_{i}")
            if synth and "sources" in synth:
                for source in synth["sources"]:
                    if "url" in source:
                        all_urls.add(source["url"])
        
        if not all_urls:
            logger.info("Link verification: no source URLs to verify")
            return
        
        # Verify all URLs
        try:
            results = await verify_urls(list(all_urls))
        except Exception as exc:
            logger.warning(
                "Link verification failed entirely, proceeding with unverified links: %s",
                exc,
            )
            return
        
        broken_urls = {
            url for url, result in results.items() if result.status == "broken"
        }
        valid_count = len(results) - len(broken_urls)
        
        logger.info(
            "Link verification: %d/%d URLs verified, %d removed",
            valid_count, len(results), len(broken_urls),
        )
        
        for url in broken_urls:
            result = results[url]
            logger.debug(
                "Broken link removed: %s - reason: %s",
                url, result.error,
            )
        
        if not broken_urls:
            return
        
        # Clean each topic's synthesis data
        for i in range(topic_count):
            synth = state.get(f"synthesis_{i}")
            if not synth:
                continue
            
            # Filter sources
            original_sources = synth.get("sources", [])
            cleaned_sources = [
                s for s in original_sources if s.get("url") not in broken_urls
            ]
            
            # Clean markdown citations
            body = synth.get("body_markdown", "")
            cleaned_body = clean_broken_links_from_markdown(body, broken_urls)
            
            # Check if all sources removed
            if not cleaned_sources and original_sources:
                cleaned_body += _ALL_BROKEN_NOTICE
            
            # Update state
            state[f"synthesis_{i}"] = {
                **synth,
                "sources": cleaned_sources,
                "body_markdown": cleaned_body,
            }
        
        return
        yield  # Make this a generator (required by BaseAgent interface)
```

**Key implementation notes:**

1. **URL deduplication**: Collect unique URLs across all topics to avoid verifying duplicates
2. **Graceful degradation**: The entire verification is wrapped in try/except
3. **State mutation**: Create new dict with `{**synth, "sources": ..., "body_markdown": ...}` to avoid partial updates
4. **Generator protocol**: The `yield` after `return` satisfies Python's requirement for an `AsyncGenerator` return type

### T07-06 Walkthrough: Pipeline Integration

The key change is in `build_agent()`:

```python
# Current:
pipeline_agents = [
    config_loader,
    research_phase,
    research_validator,
    pipeline_abort_check,
    synthesizer,
    synthesis_postprocessor,
    output_phase,
]

# New:
pipeline_agents = [
    config_loader,
    research_phase,
    research_validator,
    pipeline_abort_check,
    synthesizer,
    synthesis_postprocessor,
]

if config.settings.verify_links:
    from newsletter_agent.agents.link_verifier_agent import LinkVerifierAgent
    pipeline_agents.append(LinkVerifierAgent(name="LinkVerifier"))

pipeline_agents.append(output_phase)
```

Alternative (always include, no-op when disabled):

```python
from newsletter_agent.agents.link_verifier_agent import LinkVerifierAgent

pipeline_agents = [
    config_loader,
    research_phase,
    research_validator,
    pipeline_abort_check,
    synthesizer,
    synthesis_postprocessor,
    LinkVerifierAgent(name="LinkVerifier"),  # no-op when verify_links=false
    output_phase,
]
```

The second approach is simpler and the agent itself handles the feature toggle. Both are valid per the spec.

## Detailed Test Case Specifications

### Unit Tests for test_link_verifier.py (T07-07)

#### TestLinkCheckResult Class

```python
def test_valid_result_construction(self):
    result = LinkCheckResult(url="https://example.com", status="valid", http_status=200)
    assert result.url == "https://example.com"
    assert result.status == "valid"
    assert result.http_status == 200
    assert result.error is None

def test_broken_result_construction(self):
    result = LinkCheckResult(url="https://broken.com", status="broken", http_status=404, error="status_404")
    assert result.url == "https://broken.com"
    assert result.status == "broken"
    assert result.http_status == 404
    assert result.error == "status_404"

def test_frozen_immutability(self):
    result = LinkCheckResult(url="https://example.com", status="valid")
    with pytest.raises(FrozenInstanceError):
        result.status = "broken"
```

#### TestVerifyUrls Class

```python
@pytest.mark.asyncio
async def test_url_200_is_valid(self, respx_mock):
    respx_mock.head("https://example.com/page").mock(return_value=httpx.Response(200))
    results = await verify_urls(["https://example.com/page"])
    assert results["https://example.com/page"].status == "valid"
    assert results["https://example.com/page"].http_status == 200

@pytest.mark.asyncio
async def test_url_301_redirect_to_200_is_valid(self, respx_mock):
    respx_mock.head("https://old.com").mock(
        return_value=httpx.Response(301, headers={"Location": "https://new.com"})
    )
    respx_mock.head("https://new.com").mock(return_value=httpx.Response(200))
    results = await verify_urls(["https://old.com"])
    assert results["https://old.com"].status == "valid"

@pytest.mark.asyncio
async def test_url_404_is_broken(self, respx_mock):
    respx_mock.head("https://example.com/missing").mock(return_value=httpx.Response(404))
    results = await verify_urls(["https://example.com/missing"])
    result = results["https://example.com/missing"]
    assert result.status == "broken"
    assert result.http_status == 404
    assert result.error == "status_404"

@pytest.mark.asyncio
async def test_url_500_is_broken(self, respx_mock):
    respx_mock.head("https://example.com/error").mock(return_value=httpx.Response(500))
    results = await verify_urls(["https://example.com/error"])
    assert results["https://example.com/error"].status == "broken"

@pytest.mark.asyncio
async def test_url_timeout_is_broken(self, respx_mock):
    respx_mock.head("https://slow.com").mock(side_effect=httpx.ReadTimeout("timeout"))
    results = await verify_urls(["https://slow.com"])
    result = results["https://slow.com"]
    assert result.status == "broken"
    assert result.error == "timeout"

@pytest.mark.asyncio
async def test_head_405_falls_back_to_get(self, respx_mock):
    respx_mock.head("https://no-head.com").mock(return_value=httpx.Response(405))
    respx_mock.get("https://no-head.com").mock(return_value=httpx.Response(200))
    results = await verify_urls(["https://no-head.com"])
    assert results["https://no-head.com"].status == "valid"

@pytest.mark.asyncio
async def test_empty_url_list(self):
    results = await verify_urls([])
    assert results == {}

@pytest.mark.asyncio
async def test_user_agent_header_set(self, respx_mock):
    respx_mock.head("https://example.com").mock(return_value=httpx.Response(200))
    await verify_urls(["https://example.com"])
    request = respx_mock.calls.last.request
    assert request.headers["User-Agent"] == "NewsletterAgent/1.0 (link-check)"
```

#### TestSSRFProtection Class

```python
@pytest.mark.asyncio
async def test_loopback_blocked(self):
    results = await verify_urls(["http://127.0.0.1/admin"])
    assert results["http://127.0.0.1/admin"].status == "broken"
    assert results["http://127.0.0.1/admin"].error == "ssrf_blocked"

@pytest.mark.asyncio
async def test_private_10_blocked(self):
    results = await verify_urls(["http://10.0.0.1/internal"])
    assert results["http://10.0.0.1/internal"].status == "broken"
    assert results["http://10.0.0.1/internal"].error == "ssrf_blocked"

@pytest.mark.asyncio
async def test_private_172_blocked(self):
    results = await verify_urls(["http://172.16.0.1/internal"])
    assert results["http://172.16.0.1/internal"].status == "broken"

@pytest.mark.asyncio
async def test_private_192_blocked(self):
    results = await verify_urls(["http://192.168.1.1/"])
    assert results["http://192.168.1.1/"].status == "broken"

@pytest.mark.asyncio
async def test_javascript_scheme_blocked(self):
    results = await verify_urls(["javascript:alert(1)"])
    assert results["javascript:alert(1)"].status == "broken"
    assert results["javascript:alert(1)"].error == "invalid_scheme"

@pytest.mark.asyncio
async def test_file_scheme_blocked(self):
    results = await verify_urls(["file:///etc/passwd"])
    assert results["file:///etc/passwd"].status == "broken"
    assert results["file:///etc/passwd"].error == "invalid_scheme"
```

### Unit Tests for Markdown Cleaner (T07-09)

```python
class TestCleanBrokenLinksFromMarkdown:
    def test_single_broken_link(self):
        md = "See [Article](http://broken.com) for details."
        result = clean_broken_links_from_markdown(md, {"http://broken.com"})
        assert result == "See Article for details."

    def test_working_link_unchanged(self):
        md = "See [Article](http://working.com) for details."
        result = clean_broken_links_from_markdown(md, {"http://other.com"})
        assert result == md

    def test_multiple_broken_links(self):
        md = "[A](http://broken1.com) and [B](http://broken2.com)"
        result = clean_broken_links_from_markdown(
            md, {"http://broken1.com", "http://broken2.com"}
        )
        assert result == "A and B"

    def test_mixed_broken_and_working(self):
        md = "[Good](http://ok.com) and [Bad](http://broken.com)"
        result = clean_broken_links_from_markdown(md, {"http://broken.com"})
        assert result == "[Good](http://ok.com) and Bad"

    def test_title_with_parentheses(self):
        md = "[Title (2025)](http://broken.com)"
        result = clean_broken_links_from_markdown(md, {"http://broken.com"})
        assert result == "Title (2025)"

    def test_url_with_query_string(self):
        md = "[Article](http://example.com/page?id=1&foo=bar)"
        result = clean_broken_links_from_markdown(
            md, {"http://example.com/page?id=1&foo=bar"}
        )
        assert result == "Article"

    def test_empty_broken_set(self):
        md = "[Link](http://example.com)"
        result = clean_broken_links_from_markdown(md, set())
        assert result == md

    def test_no_links_in_markdown(self):
        md = "Just plain text with no links."
        result = clean_broken_links_from_markdown(md, {"http://broken.com"})
        assert result == md

    def test_image_link_not_cleaned(self):
        md = "![image](http://broken.com/img.png)"
        result = clean_broken_links_from_markdown(md, {"http://broken.com/img.png"})
        assert result == md  # Image links are not cleaned
```

## Configuration Examples

### Example 1: Link Verification Enabled

```yaml
newsletter:
  title: "AI Weekly"
  recipients:
    - "team@example.com"
settings:
  dry_run: false
  output_dir: "output/"
  verify_links: true
topics:
  - name: "AI Advances"
    query: "latest AI research"
    sources:
      - perplexity
    search_depth: standard
```

**Expected behavior:** After synthesis, LinkVerifierAgent collects source URLs, verifies each with HTTP HEAD, removes any broken links, and passes cleaned data to the formatter.

### Example 2: Link Verification Disabled (Default)

```yaml
settings:
  dry_run: true
  output_dir: "output/"
topics:
  - name: "AI News"
    query: "AI news"
    sources:
      - perplexity
    search_depth: standard
```

**Expected behavior:** `verify_links` defaults to `false`. LinkVerifierAgent is either omitted from the pipeline or included as a no-op. No HTTP verification requests are made.

### Example 3: Both Features Enabled

```yaml
settings:
  dry_run: false
  output_dir: "output/"
  timeframe: "last_week"
  verify_links: true
topics:
  - name: "AI Research"
    query: "AI research breakthroughs"
    sources:
      - perplexity
      - google_search
    search_depth: deep
```

**Expected behavior:** Research is timeframe-constrained (WP06), and after synthesis, links are verified (WP07). Both features work independently and compose correctly.

## Error Scenarios

### Error Scenario 1: DNS Resolution Failure

**Context:** One source URL has a domain that doesn't resolve (e.g., `https://nonexistent-domain-xyz.com`).

**Expected behavior:** `verify_urls()` catches the `httpx.ConnectError`, creates a `LinkCheckResult` with `error="dns_error"`. The URL is removed from the newsletter.

### Error Scenario 2: SSL Certificate Error

**Context:** A source URL's SSL certificate is expired or self-signed.

**Expected behavior:** `verify_urls()` catches the SSL error, creates a `LinkCheckResult` with `error="ssl_error"`. The URL is removed.

### Error Scenario 3: Server Returns 405 on HEAD

**Context:** A web server blocks HEAD requests (returns 405 Method Not Allowed).

**Expected behavior:** `verify_urls()` detects the 405 response, falls back to GET with `stream=True`. The GET response status code is used for the final determination.

### Error Scenario 4: Redirect to Private IP (SSRF Attempt)

**Context:** A source URL `https://attacker.com/redirect` redirects to `http://127.0.0.1:8080/admin`.

**Expected behavior:** After following the redirect, `verify_urls()` checks the final URL's host. `127.0.0.1` is a private IP, so the URL is blocked with `error="ssrf_blocked"`.

### Error Scenario 5: Entire Network Down

**Context:** The machine has no network connectivity when link verification runs.

**Expected behavior:** `verify_urls()` raises an exception (or all URL checks fail). `LinkVerifierAgent` catches the exception, logs a WARNING: "Link verification failed entirely, proceeding with unverified links: {error}". The pipeline continues with the original unverified data.

### Error Scenario 6: All Sources Broken for One Topic

**Context:** Topic "AI Frameworks" has 3 sources, all returning 404.

**Expected behavior:** All 3 sources are removed from `synthesis_0["sources"]`. The `body_markdown` has inline citations cleaned (link text preserved, links removed). A notice is appended: "\n\n*Note: Sources for this topic could not be verified and have been omitted.*"

## Logging and Observability

Per spec Section 10.5:

### INFO-level logs:

1. **Verification summary:**
   ```
   Link verification: 35/40 URLs verified, 5 removed
   ```

2. **Verification skipped:**
   ```
   Link verification skipped (verify_links=false)
   ```

3. **No URLs to verify:**
   ```
   Link verification: no source URLs to verify
   ```

### DEBUG-level logs:

1. **Per-broken-URL detail:**
   ```
   Broken link removed: https://broken.com/page - reason: status_404
   Broken link removed: https://timeout.com - reason: timeout
   Broken link removed: https://bad-ssl.com - reason: ssl_error
   ```

### WARNING-level logs:

1. **Total verification failure:**
   ```
   Link verification failed entirely, proceeding with unverified links: ConnectionError(...)
   ```

## Security Considerations

Per spec Section 10.2:

1. **SSRF Protection**: Block requests to private IP ranges (127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, ::1/128, fc00::/7). Check both initial URL and final URL after redirects.

2. **Scheme Restriction**: Only allow `http://` and `https://` URLs. Block `javascript:`, `file:`, `ftp:`, `data:`, and any other schemes.

3. **No Credentials**: httpx client must not send cookies, authorization headers, or cached credentials. Use a fresh client with no auth configuration.

4. **User-Agent Identification**: Set `User-Agent: NewsletterAgent/1.0 (link-check)` to identify the bot to target servers.

5. **Request Limiting**: Concurrency limit of 10 prevents overwhelming target servers. No additional rate limiting is implemented.

6. **Redirect Limit**: Maximum 5 redirect hops prevents infinite redirect loops.

7. **Timeout**: 10-second per-request timeout prevents hanging on slow/unresponsive servers.

## Backward Compatibility

All changes are additive:
1. `verify_links` defaults to `false` - existing behavior preserved
2. `LinkVerifierAgent` is either conditionally included or no-ops when disabled
3. No existing session state keys are modified when `verify_links=false`
4. No existing test fixtures need modification
5. Pipeline output is identical when `verify_links=false`

## Test Matrix

| Test ID | Test Type | File | Description | Task |
|---------|-----------|------|-------------|------|
| LV-U-01 | Unit | test_link_verifier.py | LinkCheckResult construction | T07-07 |
| LV-U-02 | Unit | test_link_verifier.py | URL 200 valid | T07-07 |
| LV-U-03 | Unit | test_link_verifier.py | URL 301 redirect valid | T07-07 |
| LV-U-04 | Unit | test_link_verifier.py | URL 404 broken | T07-07 |
| LV-U-05 | Unit | test_link_verifier.py | URL 500 broken | T07-07 |
| LV-U-06 | Unit | test_link_verifier.py | Timeout broken | T07-07 |
| LV-U-07 | Unit | test_link_verifier.py | DNS error broken | T07-07 |
| LV-U-08 | Unit | test_link_verifier.py | SSL error broken | T07-07 |
| LV-U-09 | Unit | test_link_verifier.py | HEAD 405 GET fallback | T07-07 |
| LV-U-10 | Unit | test_link_verifier.py | Redirect > 5 hops | T07-07 |
| LV-U-11 | Unit | test_link_verifier.py | SSRF loopback blocked | T07-07 |
| LV-U-12 | Unit | test_link_verifier.py | SSRF private 10.x blocked | T07-07 |
| LV-U-13 | Unit | test_link_verifier.py | SSRF private 172.16.x blocked | T07-07 |
| LV-U-14 | Unit | test_link_verifier.py | SSRF private 192.168.x blocked | T07-07 |
| LV-U-15 | Unit | test_link_verifier.py | Non-HTTP scheme blocked | T07-07 |
| LV-U-16 | Unit | test_link_verifier.py | User-Agent header set | T07-07 |
| LV-U-17 | Unit | test_link_verifier.py | Empty URL list | T07-07 |
| LV-U-18 | Unit | test_link_verifier.py | Concurrency enforcement | T07-07 |
| LV-U-19 | Unit | test_link_verifier.py | Markdown cleaner single broken | T07-09 |
| LV-U-20 | Unit | test_link_verifier.py | Markdown cleaner working unchanged | T07-09 |
| LV-U-21 | Unit | test_link_verifier.py | Markdown cleaner multiple broken | T07-09 |
| LV-U-22 | Unit | test_link_verifier.py | Markdown cleaner image link safe | T07-09 |
| LV-U-23 | Unit | test_link_verifier_agent.py | verify_links=false no-op | T07-08 |
| LV-U-24 | Unit | test_link_verifier_agent.py | All valid no changes | T07-08 |
| LV-U-25 | Unit | test_link_verifier_agent.py | 2/5 broken removed | T07-08 |
| LV-U-26 | Unit | test_link_verifier_agent.py | All broken notice added | T07-08 |
| LV-U-27 | Unit | test_link_verifier_agent.py | Citation cleaning | T07-08 |
| LV-U-28 | Unit | test_link_verifier_agent.py | Total failure graceful | T07-08 |
| LV-B-01 | BDD | test_link_verification.py | All links valid | T07-10 |
| LV-B-02 | BDD | test_link_verification.py | Some broken removed | T07-10 |
| LV-B-03 | BDD | test_link_verification.py | All broken notice | T07-10 |
| LV-B-04 | BDD | test_link_verification.py | Disabled no requests | T07-10 |
| LV-B-05 | BDD | test_link_verification.py | Network failure graceful | T07-10 |

## Spec Section Coverage Map

| Spec Section | Task(s) | Coverage |
|-------------|---------|----------|
| 4.3 FR-013 (verify_links field) | (WP06 T06-03) | Defined in WP06 |
| 4.3 FR-014 (pipeline stage placement) | T07-06 | Full |
| 4.3 FR-015 (LinkVerifierAgent BaseAgent) | T07-05 | Full |
| 4.3 FR-016 (HEAD with GET fallback) | T07-02 | Full |
| 4.3 FR-017 (200-399 valid, 400+ broken) | T07-02 | Full |
| 4.3 FR-018 (concurrent httpx, max 10) | T07-02 | Full |
| 4.3 FR-019 (User-Agent header) | T07-02 | Full |
| 4.3 FR-020 (broken link removal) | T07-04, T07-05 | Full |
| 4.3 FR-021 (all-broken notice) | T07-05 | Full |
| 4.3 FR-022 (redirect following max 5) | T07-02 | Full |
| 4.3 FR-023 (logging) | T07-05 | Full |
| 4.3 FR-024 (no-op when disabled) | T07-05 | Full |
| 4.4 FR-025 (pipeline placement) | T07-06 | Full |
| 4.4 FR-026 (conditional inclusion) | T07-06 | Full |
| 10.1 Performance (30s for 40 URLs) | T07-02 | Design |
| 10.2 Security (SSRF, schemes, IPs) | T07-03 | Full |
| 10.5 Observability (logging) | T07-05 | Full |
| 11.1 Unit Tests | T07-07, T07-08, T07-09 | Full |
| 11.2 BDD Tests | T07-10 | Full |
| 11.5 Performance Tests | T07-07 | Partial |
| 11.6 Security Tests | T07-07 | Full |

## Cross-references to Other Work Packages

### WP06 - Search Timeframe (Parallel Track)

WP07 depends on WP06 for the `verify_links` field on `AppSettings` (T06-03) and the `config_verify_links` session state key (T06-04). However, T07-01 through T07-04 (the verification implementation itself) have no dependency on WP06 and can start immediately.

### WP08 - Integration Testing (Depends on Both)

WP08 tests the full pipeline with both features (timeframe + link verification) enabled simultaneously.

## Rollback Considerations

All changes are additive:
1. Remove `newsletter_agent/tools/link_verifier.py`
2. Remove `newsletter_agent/agents/link_verifier_agent.py`
3. Revert `build_agent()` in `agent.py` to remove LinkVerifierAgent
4. Remove new test files

No data migration, no database changes, no deployment configuration changes.

## Implementation Sequence Walkthrough

The recommended implementation sequence for a single developer working through this WP:

### Phase 1: Foundation (T07-01, T07-04) - Can be done in parallel

**Step 1a:** Create `newsletter_agent/tools/link_verifier.py` with the `LinkCheckResult` frozen dataclass. This is a simple 10-line definition.

**Step 1b:** In the same file, implement `clean_broken_links_from_markdown()`. This is a pure function with a regex that finds `[text](url)` patterns (excluding `![alt](url)`) and replaces broken ones with just the text.

### Phase 2: Core Verification (T07-02, T07-03)

**Step 2:** Implement `verify_urls()` in the same `link_verifier.py` module. Start with the basic HTTP HEAD checking, then add:
- GET fallback for 405 responses
- SSRF protection (scheme checking, private IP blocking)
- Exception handling (timeout, DNS, SSL)
- Concurrency via asyncio.Semaphore

**Step 3:** Write unit tests (T07-07) for `verify_urls()` and run them:
```
pytest tests/unit/test_link_verifier.py -v
```

### Phase 3: Agent Implementation (T07-05)

**Step 4:** Create `newsletter_agent/agents/link_verifier_agent.py` with `LinkVerifierAgent(BaseAgent)`. Implement `_run_async_impl()` that:
- Reads `config_verify_links` from session state
- No-ops if False
- Collects URLs, calls `verify_urls()`
- Cleans synthesis state
- Handles errors gracefully

**Step 5:** Write unit tests (T07-08) for `LinkVerifierAgent`:
```
pytest tests/unit/test_link_verifier_agent.py -v
```

### Phase 4: Pipeline Integration (T07-06)

**Step 6:** Modify `build_agent()` in `newsletter_agent/agent.py` to include `LinkVerifierAgent` in the pipeline.

### Phase 5: Testing (T07-09, T07-10)

**Step 7:** Write markdown cleaner tests (T07-09) and BDD tests (T07-10):
```
pytest tests/unit/test_link_verifier.py tests/unit/test_link_verifier_agent.py tests/bdd/test_link_verification.py -v
```

### Phase 6: Full Regression

**Step 8:** Run the complete test suite:
```
pytest tests/ -v
```

## HTTPX Client Configuration Details

The `httpx.AsyncClient` should be configured as follows:

```python
async with httpx.AsyncClient(
    follow_redirects=True,
    max_redirects=5,
    timeout=httpx.Timeout(timeout, connect=5.0),  # 10s overall, 5s connect
    headers={
        "User-Agent": "NewsletterAgent/1.0 (link-check)",
    },
    verify=True,  # Verify SSL certificates (default)
) as client:
    ...
```

**Configuration rationale:**

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `follow_redirects` | `True` | FR-022: Follow HTTP redirects |
| `max_redirects` | `5` | FR-022: Up to 5 hops |
| `timeout` | `10.0` | FR-016: 10-second timeout |
| `connect` | `5.0` | Separate connect timeout; if DNS/TCP takes > 5s, likely broken |
| `User-Agent` | Custom string | FR-019: Identify the bot |
| `verify` | `True` | Security: Verify SSL certificates; SSL errors for URLs with bad certs are caught as "ssl_error" |

**Important httpx notes:**

1. `httpx.TimeoutException` is the base class for all timeout errors. Subtypes: `ReadTimeout`, `WriteTimeout`, `ConnectTimeout`, `PoolTimeout`.
2. `httpx.TooManyRedirects` is raised when `max_redirects` is exceeded.
3. `httpx.ConnectError` covers DNS failures, connection refused, and network unreachable.
4. For streaming GET: `async with client.stream("GET", url) as response:` - the response status is available immediately, body is not read.
5. `response.url` gives the final URL after all redirects - use this for post-redirect SSRF checking.

## Private IP Detection Implementation

The SSRF protection needs to handle several edge cases:

### IPv4 Private Ranges

| Range | CIDR | Description |
|-------|------|-------------|
| 127.0.0.0 - 127.255.255.255 | 127.0.0.0/8 | Loopback |
| 10.0.0.0 - 10.255.255.255 | 10.0.0.0/8 | Class A private |
| 172.16.0.0 - 172.31.255.255 | 172.16.0.0/12 | Class B private |
| 192.168.0.0 - 192.168.255.255 | 192.168.0.0/16 | Class C private |
| 169.254.0.0 - 169.254.255.255 | 169.254.0.0/16 | Link-local |
| 0.0.0.0 | 0.0.0.0/32 | Unspecified |

### IPv6 Private Ranges

| Range | CIDR | Description |
|-------|------|-------------|
| ::1 | ::1/128 | Loopback |
| fc00:: - fdff:... | fc00::/7 | Unique local |
| fe80:: - febf:... | fe80::/10 | Link-local |

### Python ipaddress Module Usage

```python
import ipaddress

def _is_private_or_reserved(ip_str: str) -> bool:
    """Check if an IP address is private, loopback, or reserved."""
    try:
        addr = ipaddress.ip_address(ip_str)
        return (
            addr.is_private
            or addr.is_loopback
            or addr.is_reserved
            or addr.is_link_local
            or addr.is_unspecified
        )
    except ValueError:
        return False  # Not an IP address (hostname)
```

**Edge cases:**

1. **IPv4-mapped IPv6 addresses**: `::ffff:127.0.0.1` should also be blocked. `ipaddress.ip_address("::ffff:127.0.0.1").is_private` returns `True` in Python 3.11+.

2. **Hostnames that resolve to private IPs**: Must resolve DNS first. Use `socket.getaddrinfo()` in a thread to avoid blocking the event loop:
   ```python
   import asyncio
   import socket
   
   async def _resolve_and_check(hostname: str) -> bool:
       loop = asyncio.get_event_loop()
       try:
           infos = await loop.getaddrinfo(hostname, None)
           for family, type_, proto, canonname, sockaddr in infos:
               ip_str = sockaddr[0]
               if _is_private_or_reserved(ip_str):
                   return True
       except socket.gaierror:
           pass  # DNS resolution failed - will be caught later by httpx
       return False
   ```

3. **DNS rebinding**: An attacker could set up a hostname that initially resolves to a public IP (passing SSRF check), then resolves to 127.0.0.1 during the actual request. This is a known limitation of pre-request DNS checking. Full mitigation would require a custom httpx transport that pins the resolved IP, which is out of scope for v1.

## LinkVerifierAgent State Flow

### Input State (before agent runs):

```python
{
    "config_verify_links": True,
    "config_topic_count": 2,
    "synthesis_0": {
        "topic_name": "AI Advances",
        "body_markdown": "## AI Advances\n\nSee [Article 1](https://good.com/1) and [Article 2](https://broken.com/2).\n\n### Sources\n- [Article 1](https://good.com/1)\n- [Article 2](https://broken.com/2)\n",
        "sources": [
            {"title": "Article 1", "url": "https://good.com/1", "provider": "perplexity"},
            {"title": "Article 2", "url": "https://broken.com/2", "provider": "google"},
        ]
    },
    "synthesis_1": {
        "topic_name": "Climate Tech",
        "body_markdown": "## Climate Tech\n\nAnalysis from [Report A](https://good.com/a).\n",
        "sources": [
            {"title": "Report A", "url": "https://good.com/a", "provider": "perplexity"},
        ]
    }
}
```

### Verification Results (from verify_urls):

```python
{
    "https://good.com/1": LinkCheckResult(url="https://good.com/1", status="valid", http_status=200, error=None),
    "https://broken.com/2": LinkCheckResult(url="https://broken.com/2", status="broken", http_status=404, error="status_404"),
    "https://good.com/a": LinkCheckResult(url="https://good.com/a", status="valid", http_status=200, error=None),
}
```

### Output State (after agent runs):

```python
{
    "config_verify_links": True,
    "config_topic_count": 2,
    "synthesis_0": {
        "topic_name": "AI Advances",
        "body_markdown": "## AI Advances\n\nSee [Article 1](https://good.com/1) and Article 2.\n\n### Sources\n- [Article 1](https://good.com/1)\n- Article 2\n",
        "sources": [
            {"title": "Article 1", "url": "https://good.com/1", "provider": "perplexity"},
        ]
    },
    "synthesis_1": {
        "topic_name": "Climate Tech",
        "body_markdown": "## Climate Tech\n\nAnalysis from [Report A](https://good.com/a).\n",
        "sources": [
            {"title": "Report A", "url": "https://good.com/a", "provider": "perplexity"},
        ]
    }
}
```

### All-Broken State (when all sources for a topic are broken):

```python
{
    "synthesis_0": {
        "topic_name": "AI Advances",
        "body_markdown": "## AI Advances\n\nSee Article 1 and Article 2.\n\n### Sources\n- Article 1\n- Article 2\n\n\n*Note: Sources for this topic could not be verified and have been omitted.*",
        "sources": []
    }
}
```

## Acceptance Verification Checklist

Before marking this WP as complete, verify:

- [ ] `python -m pytest tests/unit/test_link_verifier.py -v` - all pass
- [ ] `python -m pytest tests/unit/test_link_verifier_agent.py -v` - all pass
- [ ] `python -m pytest tests/bdd/test_link_verification.py -v` - all pass
- [ ] `python -m pytest tests/ -v` - full suite passes (no regressions)
- [ ] Existing config without `verify_links` field loads successfully
- [ ] Config with `verify_links: true` activates the verification stage
- [ ] Config with `verify_links: false` skips verification (no HTTP requests)
- [ ] Pipeline order is correct: SynthesisPostProcessor -> LinkVerifier -> OutputPhase
- [ ] Private IP URLs are blocked (SSRF protection)
- [ ] Non-HTTP scheme URLs are blocked
- [ ] HEAD 405 -> GET fallback works
- [ ] All-broken notice text matches spec exactly
- [ ] Inline markdown citations are cleaned correctly
- [ ] Graceful degradation on total verification failure (warning logged, pipeline continues)

## BDD Test Scenario Walkthroughs

### Scenario 1: All Links Valid

```python
@pytest.mark.asyncio
async def test_all_links_valid(self):
    """
    Given verify_links is true
    And synthesis results contain 5 source URLs all returning 200
    When the LinkVerifierAgent runs
    Then all 5 sources remain in the synthesis results
    And body_markdown inline citations are unchanged
    """
    # Given
    state = {
        "config_verify_links": True,
        "config_topic_count": 1,
        "synthesis_0": {
            "topic_name": "AI",
            "body_markdown": "See [A](https://a.com) and [B](https://b.com) and [C](https://c.com) and [D](https://d.com) and [E](https://e.com).",
            "sources": [
                {"title": "A", "url": "https://a.com"},
                {"title": "B", "url": "https://b.com"},
                {"title": "C", "url": "https://c.com"},
                {"title": "D", "url": "https://d.com"},
                {"title": "E", "url": "https://e.com"},
            ]
        },
    }
    
    # Mock all URLs returning 200
    with respx.mock:
        for domain in ["a", "b", "c", "d", "e"]:
            respx.head(f"https://{domain}.com").mock(return_value=httpx.Response(200))
        
        # When
        agent = LinkVerifierAgent(name="test")
        ctx = make_mock_context(state)
        async for _ in agent._run_async_impl(ctx):
            pass
    
    # Then
    assert len(state["synthesis_0"]["sources"]) == 5
    assert "[A](https://a.com)" in state["synthesis_0"]["body_markdown"]
```

### Scenario 2: Some Links Broken

```python
@pytest.mark.asyncio
async def test_some_links_broken(self):
    """
    Given verify_links is true
    And synthesis results contain 5 source URLs
    And 2 URLs return 404
    When the LinkVerifierAgent runs
    Then only 3 sources remain in the synthesis results
    And broken URL inline citations are replaced with unlinked text
    """
    # Given
    state = {
        "config_verify_links": True,
        "config_topic_count": 1,
        "synthesis_0": {
            "topic_name": "AI",
            "body_markdown": "See [Good1](https://good1.com), [Bad1](https://bad1.com), [Good2](https://good2.com), [Bad2](https://bad2.com), and [Good3](https://good3.com).",
            "sources": [
                {"title": "Good1", "url": "https://good1.com"},
                {"title": "Bad1", "url": "https://bad1.com"},
                {"title": "Good2", "url": "https://good2.com"},
                {"title": "Bad2", "url": "https://bad2.com"},
                {"title": "Good3", "url": "https://good3.com"},
            ]
        },
    }
    
    with respx.mock:
        respx.head("https://good1.com").mock(return_value=httpx.Response(200))
        respx.head("https://bad1.com").mock(return_value=httpx.Response(404))
        respx.head("https://good2.com").mock(return_value=httpx.Response(200))
        respx.head("https://bad2.com").mock(return_value=httpx.Response(404))
        respx.head("https://good3.com").mock(return_value=httpx.Response(200))
        
        agent = LinkVerifierAgent(name="test")
        ctx = make_mock_context(state)
        async for _ in agent._run_async_impl(ctx):
            pass
    
    # Then
    assert len(state["synthesis_0"]["sources"]) == 3
    assert "Bad1" in state["synthesis_0"]["body_markdown"]
    assert "[Bad1]" not in state["synthesis_0"]["body_markdown"]
    assert "[Good1](https://good1.com)" in state["synthesis_0"]["body_markdown"]
```

### Scenario 3: All Links Broken for a Topic

```python
@pytest.mark.asyncio
async def test_all_links_broken_notice(self):
    """
    Given verify_links is true
    And topic 'AI' has 3 source URLs all returning 404
    When the LinkVerifierAgent runs
    Then topic 'AI' sources list is empty
    And topic 'AI' body_markdown contains the verification notice
    """
    state = {
        "config_verify_links": True,
        "config_topic_count": 1,
        "synthesis_0": {
            "topic_name": "AI",
            "body_markdown": "See [A](https://a.com), [B](https://b.com), [C](https://c.com).",
            "sources": [
                {"title": "A", "url": "https://a.com"},
                {"title": "B", "url": "https://b.com"},
                {"title": "C", "url": "https://c.com"},
            ]
        },
    }
    
    with respx.mock:
        for domain in ["a", "b", "c"]:
            respx.head(f"https://{domain}.com").mock(return_value=httpx.Response(404))
        
        agent = LinkVerifierAgent(name="test")
        ctx = make_mock_context(state)
        async for _ in agent._run_async_impl(ctx):
            pass
    
    assert len(state["synthesis_0"]["sources"]) == 0
    assert "*Note: Sources for this topic could not be verified and have been omitted.*" in state["synthesis_0"]["body_markdown"]
```

### Scenario 4: Link Verification Disabled

```python
@pytest.mark.asyncio
async def test_verification_disabled(self):
    """
    Given verify_links is false
    When the LinkVerifierAgent runs
    Then no HTTP requests are made
    And synthesis results are unchanged
    """
    original_body = "See [A](https://a.com)."
    state = {
        "config_verify_links": False,
        "config_topic_count": 1,
        "synthesis_0": {
            "topic_name": "AI",
            "body_markdown": original_body,
            "sources": [{"title": "A", "url": "https://a.com"}],
        },
    }
    
    with respx.mock:
        # No routes defined - any request would fail
        agent = LinkVerifierAgent(name="test")
        ctx = make_mock_context(state)
        async for _ in agent._run_async_impl(ctx):
            pass
    
    # State unchanged
    assert state["synthesis_0"]["body_markdown"] == original_body
    assert len(state["synthesis_0"]["sources"]) == 1
```

### Scenario 5: Network Failure

```python
@pytest.mark.asyncio
async def test_network_failure_graceful(self):
    """
    Given verify_links is true
    And the HTTP client cannot connect to any server
    When the LinkVerifierAgent runs
    Then synthesis results are unchanged
    And a warning is logged
    """
    original_body = "See [A](https://a.com)."
    state = {
        "config_verify_links": True,
        "config_topic_count": 1,
        "synthesis_0": {
            "topic_name": "AI",
            "body_markdown": original_body,
            "sources": [{"title": "A", "url": "https://a.com"}],
        },
    }
    
    with patch("newsletter_agent.agents.link_verifier_agent.verify_urls", side_effect=Exception("Network down")):
        agent = LinkVerifierAgent(name="test")
        ctx = make_mock_context(state)
        async for _ in agent._run_async_impl(ctx):
            pass
    
    # State unchanged due to graceful degradation
    assert state["synthesis_0"]["body_markdown"] == original_body
    assert len(state["synthesis_0"]["sources"]) == 1
```

## Dependencies on External Libraries

| Library | Usage | Already in requirements.txt? |
|---------|-------|------------------------------|
| httpx | Async HTTP client for URL verification | Yes |
| asyncio | Concurrency (Semaphore, gather) | Standard library |
| ipaddress | SSRF protection (private IP detection) | Standard library |
| socket | DNS resolution for SSRF checking | Standard library |
| re | Markdown link pattern matching | Standard library |
| respx | Test mocking for httpx (unit tests only) | Check - may need to add to dev dependencies |

**Note on respx:** If `respx` is not already in dev dependencies, it should be added to `requirements-dev.txt` or `pyproject.toml[dev]`. Alternative: use `unittest.mock.patch` to mock `httpx.AsyncClient` methods directly, but `respx` provides much cleaner test code.

## Task Dependency Graph

```
T07-01 ----+----> T07-02 ----> T07-05 ----+----> T07-06
           |      (includes    (agent)     |      (pipeline)
           |       T07-03)                 |
           |                               +----> T07-08
           |                                      (agent tests)
           |
           +----> T07-04 ----> T07-09
                  (md cleaner) (md tests)
                  
T07-07 (after T07-02/T07-03)
T07-10 (after T07-05, T07-06)
```

**Critical path:** T07-01 -> T07-02 (+ T07-03) -> T07-05 -> T07-06 -> T07-10

**Parallel tracks:**
- Track A: T07-01 -> T07-02/T07-03 -> T07-05 -> T07-06 (main chain)
- Track B: T07-01 -> T07-04 -> T07-09 (markdown cleaner, parallel with Track A after T07-01)
- Track C: T07-07 (after T07-02, parallel with T07-05)
- Track D: T07-08 (after T07-05, parallel with T07-06)

## Module Import Map

After WP07 implementation, the import graph for link verification:

```
newsletter_agent/tools/link_verifier.py (NEW)
  - imports: httpx, asyncio, ipaddress, socket, urllib.parse, re, dataclasses, logging
  - defines: LinkCheckResult, verify_urls(), clean_broken_links_from_markdown(), _check_one_url(), _is_private_ip(), _is_valid_scheme()
  - used by: link_verifier_agent.py, test_link_verifier.py

newsletter_agent/agents/link_verifier_agent.py (NEW)
  - imports: google.adk.agents.BaseAgent, google.adk.agents.invocation_context.InvocationContext
  - imports: verify_urls, clean_broken_links_from_markdown from tools.link_verifier
  - defines: LinkVerifierAgent
  - used by: agent.py, test_link_verifier_agent.py

newsletter_agent/agent.py (MODIFIED)
  - imports: LinkVerifierAgent from agents.link_verifier_agent
  - modifies: build_agent() to include LinkVerifierAgent in pipeline
```

## Glossary

| Term | Definition |
|------|-----------|
| LinkCheckResult | Frozen dataclass containing the result of verifying a single URL |
| verify_urls | Async function that concurrently verifies a batch of URLs |
| LinkVerifierAgent | BaseAgent subclass that orchestrates link verification in the pipeline |
| clean_broken_links_from_markdown | Helper function that replaces broken link citations with plain text |
| SSRF | Server-Side Request Forgery - attack where the server is tricked into requesting internal resources |
| HEAD request | HTTP method that returns headers only, no body - faster than GET for liveness checks |
| GET fallback | When a server returns 405 on HEAD, retry with GET and stream=True to avoid body download |
| Semaphore | asyncio concurrency primitive that limits the number of simultaneous operations |
| soft 404 | A page that returns HTTP 200 but displays error content - not detected by status-code checking |
| graceful degradation | When verification fails entirely, the pipeline proceeds with unverified links rather than failing |
| no-op passthrough | When verify_links=false, the agent reads and writes state unchanged, adding zero latency |
| respx | Python library for mocking httpx requests in tests - provides clean route-based mocking API |
| redirect chain | Sequence of HTTP redirects (301/302) from an initial URL to a final destination |
| private IP range | IP address ranges reserved for local/internal networks (RFC 1918 for IPv4, fc00::/7 for IPv6) |
| connection pooling | httpx AsyncClient reuses TCP connections for multiple requests to the same host |
| stream mode | httpx mode where response body is not downloaded until explicitly read - used for HEAD fallback GET |

## Estimated File Changes (Lines of Code)

| File | Lines Added | Lines Modified | Lines Removed |
|------|------------|----------------|---------------|
| link_verifier.py (NEW) | ~150 | 0 | 0 |
| link_verifier_agent.py (NEW) | ~80 | 0 | 0 |
| agent.py | ~8 | 2 | 0 |
| test_link_verifier.py (NEW) | ~250 | 0 | 0 |
| test_link_verifier_agent.py (NEW) | ~200 | 0 | 0 |
| test_link_verification.py (NEW) | ~150 | 0 | 0 |
| **Total** | **~838** | **~2** | **0** |

## Activity Log

- 2026-03-14T00:00:00Z - planner - lane=planned - Work package created
- 2026-03-14T00:00:00Z - planner - lane=planned - Tasks T07-01 through T07-10 defined with acceptance criteria
- 2026-03-14T00:00:00Z - planner - lane=planned - Detailed walkthroughs for verify_urls, SSRF protection, markdown cleaner, and agent added
- 2026-03-14T00:00:00Z - planner - lane=planned - Test specifications and test matrix completed
- 2026-03-14T00:00:00Z - planner - lane=planned - Security considerations and error scenarios documented
- 2026-03-14T00:00:00Z - planner - lane=planned - Spec coverage map verified: all link verification FRs covered
- 2026-03-14T00:00:00Z - planner - lane=planned - Ready for implementation by Coder agent

## Rollback Strategy

If the link verification feature causes issues in production, the rollback path is simple:

1. Set `verify_links: false` in `topics.yaml` (or omit the field entirely - defaults to false).
2. The `LinkVerifierAgent` becomes a no-op passthrough; it reads state and writes it back unchanged.
3. No other agents are affected because the pipeline contract is preserved.
4. If the agent code itself is the problem, remove it from the `sub_agents` list in `agent.py` and redeploy.

This rollback does not require any code changes to the core pipeline or other agents.
The feature flag pattern ensures zero-risk deployment: ship disabled, test in staging, enable per-topic.

## Cross-Reference: Spec Coverage Verification

| Spec FR | Task | Acceptance Criteria Count | Status |
|---------|------|--------------------------|--------|
| FR-LINK-001 | T07-03 | 4 | Covered |
| FR-LINK-002 | T07-04 | 4 | Covered |
| FR-LINK-003 | T07-05 | 4 | Covered |
| FR-LINK-004 | T07-06 | 5 | Covered |
| FR-LINK-005 | T07-07 | 5 | Covered |
| FR-LINK-006 | T07-02 | 3 | Covered |
| FR-LINK-007 | T07-02 | 3 | Covered |
| NFR-LINK-PERF | T07-03 | 3 | Covered |
| NFR-LINK-SEC | T07-04 | 4 | Covered |
| Config schema | T07-01 | 5 | Covered |
| Pipeline integration | T07-08 | 4 | Covered |
| E2E verification | T07-09, T07-10 | 6 | Covered |

All link-verification functional requirements and non-functional requirements are fully covered
by at least one task with explicit acceptance criteria traced to the spec.

---

*End of WP07 - Source Link Verification*
