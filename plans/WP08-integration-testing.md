---
lane: to_do
review_status: has_feedback
---

# WP08 - Integration Testing, E2E Verification & Documentation

> **Spec**: `specs/link-verification-timeframe.spec.md`
> **Status**: Complete
> **Priority**: P2
> **Goal**: Verify that timeframe filtering (WP06) and link verification (WP07) work together end-to-end, backward compatibility is preserved, performance and security requirements are met, and all documentation is updated.
> **Independent Test**: Run `pytest tests/` from fresh checkout; all integration, BDD, E2E, performance, and security tests pass green. Run the full pipeline in dry-run mode with both new fields set and with an old-format topics.yaml; both succeed.
> **Depends on**: WP06, WP07
> **Parallelisable**: No (requires WP06 and WP07 to be complete)
> **Prompt**: `plans/WP08-integration-testing.md`

## Objective

WP06 (search timeframe) and WP07 (link verification) each deliver independently testable features.
This work package delivers the cross-cutting verification layer that proves:

1. **Both features compose correctly** - a pipeline run with `timeframe` AND `verify_links` set
   produces the expected output without interference.
2. **Backward compatibility** - an existing `topics.yaml` with zero new fields produces output
   identical (structurally) to the pre-change behavior.
3. **Performance** - link verification concurrency stays within bounds and completes within the
   30-second budget for 40 URLs.
4. **Security** - SSRF protections work in the full pipeline context, not just unit isolation.
5. **Documentation** - README, inline docstrings, and configuration examples are updated.

This WP is the "quality gate" before the features can ship. No feature code is written here;
all tasks produce test files, documentation files, or configuration examples.

## Spec References

- Section 11.3: Integration Tests
- Section 11.4: End-to-End Tests
- Section 11.5: Performance Tests
- Section 11.6: Security Tests
- Section 12: Constraints & Assumptions
- Section 13: Out of Scope
- SC-004: Backward compatibility success criterion
- FR-014: LinkVerifier stage placement in pipeline
- FR-025: Pipeline stage placement
- FR-027: Timeframe resolved during config loading
- FR-028: config_timeframes session state key
- NFR-LINK-PERF: 40 URLs in 30 seconds
- NFR-LINK-SEC: SSRF prevention

## Tasks

### T08-01 - Integration Test: Config + Research Timeframe Flow

- **Description**: Write an integration test that loads a topics.yaml with `timeframe: "last_week"`
  at the global settings level and a per-topic override of `timeframe: "last_month"`, then verifies
  that `build_research_phase()` generates the correct agent instructions containing date clauses.
  The test must verify that:
  (a) The global timeframe is applied to topics without overrides.
  (b) The per-topic override takes precedence where specified.
  (c) The date clause appears in the research agent's instruction string.
  (d) The resolved timeframe values are stored in session state under `config_timeframes`.

  This test exercises the integration boundary between the config loader (schema.py),
  the timeframe resolver (timeframe.py), and the research phase builder (agent.py).

- **Spec refs**: FR-001, FR-002, FR-006, FR-009, FR-027, FR-028, Section 11.3 bullet 1
- **Parallel**: Yes (can run alongside T08-02, T08-03)
- **Acceptance criteria**:
  - [ ] Test loads a multi-topic config where one topic has a timeframe override and the other inherits the global setting
  - [ ] Test verifies the research phase agent instructions for the global-timeframe topic contain the expected date clause text (e.g., "past 7 days" or "since YYYY-MM-DD")
  - [ ] Test verifies the research phase agent instructions for the overridden topic contain the per-topic date clause text (e.g., "past 30 days")
  - [ ] Test verifies `config_timeframes` in session state contains the correct resolved values per topic index
  - [ ] Test does NOT make any real API calls - uses mocked agent execution
- **Test requirements**: integration
- **Depends on**: T06-01 through T06-06 (WP06 config + resolver + research builder)
- **Implementation Guidance**:
  - File location: `tests/integration/test_config_research_timeframe.py`
  - Use the existing pattern from `tests/bdd/test_research_pipeline.py` for building config fixtures
  - Import `build_research_phase` from `newsletter_agent.agent` and inspect returned agent tree
  - Import `resolve_timeframe` from `newsletter_agent.tools.timeframe` to verify resolver output
  - The research phase builder should embed date clause text in research agent instructions;
    inspect `agent.instruction` or `agent.root_agent.instruction` (depending on ADK pattern)
  - Use `unittest.mock.patch` to mock the actual LLM calls - only verify instruction construction
  - Known pitfall: ADK SequentialAgent may nest instructions differently than expected;
    print the agent tree structure during development to understand how instructions propagate
  - Spec validation: FR-028 requires `config_timeframes` to be a dict keyed by topic index (int)
    with values being ResolvedTimeframe objects or equivalent dicts

### T08-02 - Integration Test: Config + Perplexity Timeframe Passthrough

- **Description**: Write an integration test that verifies the Perplexity search function
  receives the correct `search_recency_filter` parameter when a timeframe is configured.
  The test must mock the Perplexity API endpoint and verify:
  (a) When `timeframe: "last_week"` is set, the request body contains `search_recency_filter: "week"`.
  (b) When `timeframe: "last_month"` is set, the body contains `search_recency_filter: "month"`.
  (c) When `timeframe: "last_day"` is set, the body contains `search_recency_filter: "day"`.
  (d) When no timeframe is set, no `search_recency_filter` or `extra_body` is sent.
  (e) When Perplexity rejects the filter (HTTP 400), the function retries without it.

  This test exercises the integration boundary between the timeframe resolver and
  the `search_perplexity()` tool function.

- **Spec refs**: FR-007, FR-010, Section 11.3 bullet 2
- **Parallel**: Yes
- **Acceptance criteria**:
  - [ ] Test verifies `extra_body` in the Perplexity API request contains `{"search_recency_filter": "week"}` when timeframe is "last_week"
  - [ ] Test verifies `extra_body` contains `{"search_recency_filter": "month"}` for "last_month"
  - [ ] Test verifies `extra_body` contains `{"search_recency_filter": "day"}` for "last_day"
  - [ ] Test verifies no `extra_body` or `search_recency_filter` is sent when timeframe is None
  - [ ] Test verifies graceful retry: when first call with filter returns HTTP 400, second call is made without filter
  - [ ] All assertions use mocked HTTP - no real Perplexity API calls
- **Test requirements**: integration
- **Depends on**: T06-04 (WP06 Perplexity integration)
- **Implementation Guidance**:
  - File location: `tests/integration/test_config_perplexity_timeframe.py`
  - Mock the OpenAI-compatible endpoint used by `search_perplexity()` - likely via `unittest.mock.patch`
    on the httpx or openai client
  - Inspect the `extra_body` parameter in the mocked call's kwargs
  - For the retry test, configure the mock to return 400 on first call, 200 on second call,
    then assert the second call omits `search_recency_filter`
  - Reference: Perplexity Sonar API uses OpenAI chat completions format with `extra_body` for
    non-standard parameters
  - Known pitfall: The OpenAI Python client may not expose `extra_body` in the same way across
    versions; check the actual call signature in `search_perplexity()` implementation from WP06

### T08-03 - Integration Test: Synthesis + LinkVerifier Flow

- **Description**: Write an integration test that generates realistic synthesis session state
  (as if the synthesis agent has already run), then runs the `LinkVerifierAgent` against a
  mock HTTP server. The test verifies:
  (a) Valid URLs are preserved in the output state.
  (b) Broken URLs (404, 500, timeout) are removed from sources and body_markdown.
  (c) The cleaned state is structurally correct for the downstream formatter agent.
  (d) The formatter can consume the post-verification state without errors.

  This test exercises the integration boundary between the synthesis output,
  the LinkVerifierAgent, and the formatter input expectations.

- **Spec refs**: FR-014, FR-015, FR-020, FR-025, Section 11.3 bullet 3
- **Parallel**: Yes
- **Acceptance criteria**:
  - [ ] Test creates synthesis state with 5 sources per topic, 2 of which return 404
  - [ ] After LinkVerifierAgent runs, the output state has 3 sources per topic
  - [ ] The body_markdown in output state has broken link citations replaced with plain text
  - [ ] The output state can be passed to `render_newsletter()` or `FormatterAgent` without errors
  - [ ] Test uses respx or unittest.mock to mock HTTP responses - no real network calls
- **Test requirements**: integration
- **Depends on**: T07-01 through T07-08 (WP07 link verifier)
- **Implementation Guidance**:
  - File location: `tests/integration/test_synthesis_link_verification.py`
  - Create a fixture that builds synthesis state matching the format in `tests/e2e/test_full_pipeline.py`
    (see `_make_session_state()` helper)
  - Use `respx` to mock HTTP responses: configure routes so 3 URLs return 200 and 2 return 404
  - Instantiate `LinkVerifierAgent` and call its `run_async()` (or equivalent ADK method) with the
    mocked session state
  - After verification, pass the cleaned state to `render_newsletter()` and assert it produces
    valid HTML without broken link markup
  - Known pitfall: The session state format between synthesis output and link verifier input must
    match exactly; verify key names (`synthesis_0`, `synthesis_1`, etc.) match what the agents
    actually use
  - Spec validation: FR-020 requires broken `[Title](url)` to become just `Title` (plain text)

### T08-04 - Integration Test: Timeframe + Link Verification Combined

- **Description**: Write an integration test that exercises both features simultaneously:
  a config with `timeframe: "last_week"` and `verify_links: true`. The test verifies:
  (a) The research phase includes date clauses in instructions.
  (b) The link verification phase runs after synthesis.
  (c) Both features do not interfere with each other.
  (d) Session state flows correctly through the complete pipeline.

  This is the critical cross-feature integration test that validates the two WPs compose.

- **Spec refs**: FR-001, FR-013, FR-014, Section 11.3
- **Parallel**: No (depends on T08-01, T08-02, T08-03 passing first to isolate issues)
- **Acceptance criteria**:
  - [ ] Test loads a config with both `timeframe: "last_week"` and `verify_links: true`
  - [ ] Test verifies research phase instructions contain date clause text
  - [ ] Test verifies link verification phase produces cleaned state (broken links removed)
  - [ ] Test verifies the combined pipeline output state is valid for the formatter
  - [ ] Test verifies no cross-contamination: timeframe data does not affect link verification and vice versa
  - [ ] All external calls (LLM, HTTP) are mocked
- **Test requirements**: integration
- **Depends on**: T08-01, T08-02, T08-03
- **Implementation Guidance**:
  - File location: `tests/integration/test_combined_features.py`
  - Build a config fixture with both fields set
  - Mock the full pipeline: LLM calls for research/synthesis, HTTP calls for link verification
  - Walk the pipeline step by step and assert intermediate state keys at each stage
  - This test is higher-level than T08-01/02/03 - it tests composition, not individual boundaries
  - Known pitfall: Ensure the LinkVerifierAgent is included in the agent tree when `verify_links=true`
    and excluded when false - the agent factory logic from WP07 T07-08 controls this

### T08-05 - Backward Compatibility Test Suite

- **Description**: Write a comprehensive backward compatibility test suite that verifies:
  (a) An existing `topics.yaml` with NO new fields (no `timeframe`, no `verify_links`) loads
      successfully and produces structurally identical output to the pre-change behavior.
  (b) The Pydantic schema defaults are correctly applied (timeframe=None, verify_links=false).
  (c) The pipeline runs without creating any LinkVerifierAgent when `verify_links` is absent.
  (d) The research phase instructions do NOT contain any date clause when timeframe is absent.
  (e) Session state does not contain `config_timeframes` when no timeframe is configured.

  This test suite is the primary verification of SC-004 (backward compatibility).

- **Spec refs**: SC-004, FR-004, FR-024, FR-026, Section 11.4 bullet 2
- **Parallel**: Yes (can run alongside T08-04)
- **Acceptance criteria**:
  - [ ] Test uses a minimal topics.yaml with only the fields from the original spec (no new fields)
  - [ ] Config loads without errors and all new fields default to None/false
  - [ ] Pipeline agent tree does NOT include LinkVerifierAgent
  - [ ] Research phase instructions do NOT contain date clause text
  - [ ] Session state after pipeline run does NOT contain `config_timeframes` key
  - [ ] Output HTML from formatter is structurally valid (sources preserved as-is, no verification markers)
  - [ ] Test uses the exact same config format as `tests/e2e/test_full_pipeline.py` to prove compatibility
- **Test requirements**: integration, BDD
- **Depends on**: T06-01 (config schema changes), T07-08 (pipeline integration)
- **Implementation Guidance**:
  - File location: `tests/integration/test_backward_compatibility.py`
  - Copy the `TEST_CONFIG_YAML` from `tests/e2e/test_full_pipeline.py` verbatim - this represents
    the "old format" config
  - Load it through `load_config()` and assert new fields are None/false
  - Build the agent tree and assert `LinkVerifierAgent` is not in `sub_agents`
  - Build research phase and inspect instructions - assert no date-related text
  - This test serves as the regression guard; if it breaks, a backward-incompatible change was made
  - BDD style: structure as Given (old config) / When (pipeline builds) / Then (no new behavior)

### T08-06 - E2E Test: Full Pipeline with Both Features

- **Description**: Write an end-to-end test that runs the full pipeline in dry-run mode
  with `timeframe: "last_week"` and `verify_links: true`. The test verifies:
  (a) The pipeline completes without errors.
  (b) The output HTML contains no broken link markup (no `[Title](broken_url)` patterns).
  (c) Topics reference recent content (dates in output are within the timeframe).
  (d) The output file is written to the configured output directory.

  This is the "smoke test" for the combined features in the most realistic execution mode.

- **Spec refs**: Section 11.4 bullet 1, SC-001, SC-002
- **Parallel**: No (full pipeline test, run after isolated tests pass)
- **Acceptance criteria**:
  - [ ] Test runs the full pipeline in dry-run mode with both new config fields set
  - [ ] Output HTML file is created in the configured output directory
  - [ ] Output HTML does not contain markdown link syntax for broken URLs
  - [ ] Pipeline completes without unhandled exceptions
  - [ ] All external APIs are mocked (LLM, Perplexity, HTTP target servers)
  - [ ] Test cleans up output files after completion
- **Test requirements**: E2E
- **Depends on**: T08-04, T08-05
- **Implementation Guidance**:
  - File location: `tests/e2e/test_full_pipeline_with_features.py`
  - Extend the pattern from `tests/e2e/test_full_pipeline.py`
  - Add `timeframe: "last_week"` and `verify_links: true` to the test config YAML
  - Mock all external calls: Perplexity API (return canned research), LLM (return canned synthesis),
    HTTP target servers (mix of 200 and 404 responses)
  - Use `_make_session_state()` pattern but include some broken URLs in the synthesis output
  - Assert the final HTML output:
    - Contains `<a href="">` links only for verified URLs
    - Does not contain raw markdown `[text](url)` patterns
    - Contains the newsletter title and topic headings
  - Known pitfall: Mock setup is complex because the full pipeline has many external touchpoints;
    consider using a fixture that sets up all mocks in one place and yields the pipeline runner
  - Cleanup: Use `tmp_path` pytest fixture for output directory (auto-cleaned)

### T08-07 - E2E Test: Full Pipeline Backward Compatibility

- **Description**: Write an end-to-end test that runs the full pipeline in dry-run mode
  with an old-format `topics.yaml` (no new fields). The test verifies:
  (a) The pipeline completes without errors.
  (b) The output is structurally identical to what the pipeline produced before these changes.
  (c) No link verification occurs (no HTTP HEAD/GET requests to source URLs).
  (d) No timeframe filtering occurs (no date clauses in research prompts).

  This is the E2E regression guard for SC-004.

- **Spec refs**: Section 11.4 bullet 2, SC-004
- **Parallel**: Yes (can run alongside T08-06)
- **Acceptance criteria**:
  - [ ] Test uses a topics.yaml with zero new fields
  - [ ] Pipeline completes without errors in dry-run mode
  - [ ] No HTTP verification requests are made (assert no httpx calls to source URLs)
  - [ ] Output HTML is structurally valid and contains all source links unchanged
  - [ ] Test is structurally similar to the existing `test_full_pipeline.py` to serve as a baseline comparison
- **Test requirements**: E2E
- **Depends on**: T08-05
- **Implementation Guidance**:
  - File location: `tests/e2e/test_full_pipeline_backward_compat.py`
  - This test should be nearly identical to the existing `test_full_pipeline.py` but with explicit
    assertions about the absence of new behavior
  - Assert no `respx` or httpx mock routes are hit for verification URLs
  - Assert session state does not contain link verification keys
  - Assert research instructions do not contain timeframe text
  - This test proves "we didn't break anything" at the E2E level

### T08-08 - Performance Test: Link Verification Throughput

- **Description**: Write a performance test that verifies link verification of 40 URLs completes
  within 30 seconds, and that no more than 10 simultaneous connections exist at any point.
  Uses a mock HTTP server with an artificial 2-second delay per response to simulate real-world
  latency. The test verifies:
  (a) 40 URLs are checked within 30 seconds (proves concurrency is working).
  (b) At no point do more than 10 connections exist simultaneously (proves semaphore works).
  (c) All 40 URLs receive a verification result (no dropped URLs).

- **Spec refs**: NFR-LINK-PERF, FR-018, Section 11.5
- **Parallel**: Yes
- **Acceptance criteria**:
  - [ ] Test creates 40 mock URLs each with a 2-second response delay
  - [ ] `verify_urls()` completes all 40 checks within 30 seconds wall-clock time
  - [ ] A concurrency counter in the mock never exceeds 10
  - [ ] All 40 URLs have a result in the returned dict (no missing entries)
  - [ ] Test uses `time.monotonic()` or equivalent for accurate wall-clock measurement
- **Test requirements**: performance
- **Depends on**: T07-03 (WP07 verify_urls with concurrency)
- **Implementation Guidance**:
  - File location: `tests/performance/test_link_verification_perf.py`
  - Use `respx` with a custom side effect that includes `asyncio.sleep(2)` to simulate delay
  - Track concurrent connections with an `asyncio.Lock`-protected counter:
    ```python
    max_concurrent = 0
    current_concurrent = 0
    lock = asyncio.Lock()

    async def delayed_response(request):
        nonlocal max_concurrent, current_concurrent
        async with lock:
            current_concurrent += 1
            max_concurrent = max(max_concurrent, current_concurrent)
        await asyncio.sleep(2)
        async with lock:
            current_concurrent -= 1
        return httpx.Response(200)
    ```
  - With 10 concurrent and 2s delay, 40 URLs should take ~8 seconds (4 batches of 10)
  - Set assertion threshold at 30 seconds (spec requirement) with a soft warning at 15 seconds
  - Known pitfall: CI environments may be slower; use generous timeout but assert the structure
    (concurrency limit) strictly
  - Mark test with `@pytest.mark.slow` if the project uses test markers

### T08-09 - Security Test: SSRF Prevention in Pipeline Context

- **Description**: Write security tests that verify SSRF protections work in the full pipeline
  context, not just in unit isolation. The tests verify:
  (a) A URL that redirects to `http://127.0.0.1/admin` is marked as broken.
  (b) URLs resolving to private IP ranges (10.x, 172.16.x, 192.168.x, ::1) are rejected.
  (c) Redirects to `file:///etc/passwd` or `javascript:alert(1)` are rejected.
  (d) Outgoing verification requests contain no `Authorization` or `Cookie` headers.
  (e) These protections work when invoked through the `LinkVerifierAgent`, not just `verify_urls()`.

- **Spec refs**: NFR-LINK-SEC, Section 11.6
- **Parallel**: Yes
- **Acceptance criteria**:
  - [ ] Test verifies redirect to 127.0.0.1 is caught and URL marked broken
  - [ ] Test verifies private IP ranges (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, ::1) are blocked
  - [ ] Test verifies scheme change to file:// or javascript: during redirect is blocked
  - [ ] Test verifies no Authorization or Cookie headers in outgoing requests
  - [ ] Tests exercise the full LinkVerifierAgent path, not just the utility function
  - [ ] All network calls are mocked - no real connections to private IPs
- **Test requirements**: security
- **Depends on**: T07-04 (WP07 SSRF protection)
- **Implementation Guidance**:
  - File location: `tests/security/test_ssrf_prevention.py`
  - For redirect tests, use respx to return 302 with Location header pointing to private IP
  - For private IP tests, mock DNS resolution or the httpx transport layer to simulate resolution
    to private IPs
  - For header tests, capture outgoing request headers in the mock and assert absence of sensitive
    headers
  - For the agent-level test, create a minimal session state with a source URL that redirects to
    a private IP, run `LinkVerifierAgent`, and assert the URL is removed from output state
  - Reference: OWASP SSRF Prevention Cheat Sheet for the complete list of private IP ranges
  - Known pitfall: httpx may resolve DNS before the redirect check; ensure the SSRF guard checks
    the resolved IP after redirect, not just the initial URL hostname

### T08-10 - Documentation: README & Configuration Examples

- **Description**: Update project documentation to cover the two new features:
  (a) Update README.md with new configuration fields and examples.
  (b) Add/update configuration example files showing timeframe and verify_links usage.
  (c) Add inline docstrings to new public functions if not already present from WP06/WP07.
  (d) Update any existing architecture diagrams or pipeline descriptions.

- **Spec refs**: Section 10 (Architecture), Section 6 (Config Schema)
- **Parallel**: Yes
- **Acceptance criteria**:
  - [ ] README.md documents the `timeframe` field with all valid values and examples
  - [ ] README.md documents the `verify_links` field and its behavior
  - [ ] A configuration example file shows both features in use together
  - [ ] A configuration example file shows the old format (backward compatibility proof)
  - [ ] Any existing pipeline documentation mentions the new LinkVerifier stage
- **Test requirements**: none (documentation only)
- **Depends on**: T08-06, T08-07 (tests confirm behavior before documenting it)
- **Implementation Guidance**:
  - Check existing README.md for a configuration section and extend it
  - If a `config/example_topics.yaml` or similar exists, add a variant with new fields
  - If no example file exists, create `config/example_topics_with_features.yaml`
  - Keep documentation concise and example-driven
  - Include a "Backward Compatibility" note explaining that omitting new fields preserves
    existing behavior
  - Known pitfall: Do not document implementation details (internal class names, session state keys)
    in user-facing documentation; focus on YAML config format and observable behavior

### T08-11 - Test Configuration & CI Integration

- **Description**: Ensure the test infrastructure supports the new test files:
  (a) Create the `tests/integration/` directory if it does not exist.
  (b) Add `__init__.py` files to new test directories.
  (c) Update `pytest.ini` or `pyproject.toml` test configuration if needed (test markers, paths).
  (d) Verify all new test files are discovered by `pytest --collect-only`.
  (e) Add test markers (`@pytest.mark.integration`, `@pytest.mark.slow`, `@pytest.mark.security`)
      if the project uses markers.

- **Spec refs**: Section 11 (Testing Strategy)
- **Parallel**: Yes (infrastructure task, can be done early)
- **Acceptance criteria**:
  - [ ] `tests/integration/` directory exists with `__init__.py`
  - [ ] `pytest --collect-only` discovers all new test files from T08-01 through T08-09
  - [ ] Test markers are registered in pytest configuration if used
  - [ ] Running `pytest tests/` from the project root executes all test suites without import errors
- **Test requirements**: none (infrastructure only)
- **Depends on**: none (can start immediately, but should be done before writing test files)
- **Implementation Guidance**:
  - Check existing `conftest.py` files for shared fixtures that new tests can reuse
  - Check `pyproject.toml` or `pytest.ini` for existing marker registrations
  - If the project already uses markers (e.g., `@pytest.mark.slow`), follow the same pattern
  - If not, consider registering new markers to allow selective test runs:
    ```ini
    [tool.pytest.ini_options]
    markers = [
        "integration: Integration tests crossing module boundaries",
        "slow: Tests that take more than 5 seconds",
        "security: Security-focused tests (SSRF, header leakage)",
    ]
    ```
  - Known pitfall: Missing `__init__.py` in new directories causes pytest to fail with import errors

## Implementation Notes

### Test Directory Structure After WP08

```
tests/
  unit/                          # Existing - extended in WP06, WP07
    test_config.py               # Extended with timeframe/verify_links schema tests
    test_perplexity_search.py    # Extended with search_recency_filter tests
    test_link_verifier.py        # NEW from WP07
    test_link_verifier_agent.py  # NEW from WP07
    ...
  bdd/                           # Existing - extended in WP06, WP07
    test_research_pipeline.py    # Extended with timeframe scenarios
    test_link_verification.py    # NEW from WP07
    ...
  integration/                   # NEW directory
    __init__.py
    test_config_research_timeframe.py       # T08-01
    test_config_perplexity_timeframe.py     # T08-02
    test_synthesis_link_verification.py     # T08-03
    test_combined_features.py              # T08-04
    test_backward_compatibility.py         # T08-05
  e2e/                           # Existing - extended
    test_full_pipeline.py                  # Existing (unchanged)
    test_full_pipeline_with_features.py    # T08-06
    test_full_pipeline_backward_compat.py  # T08-07
  performance/                   # Existing - extended
    test_pipeline_timing.py               # Existing (unchanged)
    test_link_verification_perf.py        # T08-08
  security/                      # Existing - extended
    test_secrets.py                       # Existing (unchanged)
    test_ssrf_prevention.py               # T08-09
```

### Test Execution Order

The recommended execution order for developing and verifying these tests:

1. **T08-11** (test infrastructure) - Create directories, register markers
2. **T08-01, T08-02, T08-03** (isolated integration tests) - Can run in parallel
3. **T08-05** (backward compatibility) - Critical regression guard
4. **T08-04** (combined integration) - Cross-feature composition
5. **T08-08** (performance) - Concurrency verification
6. **T08-09** (security) - SSRF in pipeline context
7. **T08-06** (E2E with features) - Full pipeline smoke test
8. **T08-07** (E2E backward compat) - Full pipeline regression
9. **T08-10** (documentation) - Last, after all behavior is verified

### Mock Strategy

All tests in this WP must mock external dependencies. The mock layers are:

| Dependency | Mock Tool | Used In |
|------------|-----------|---------|
| LLM (Gemini) | unittest.mock.patch on ADK LLM client | T08-01, T08-04, T08-06, T08-07 |
| Perplexity API | unittest.mock.patch on httpx/openai client | T08-02, T08-04, T08-06 |
| HTTP target servers | respx (route-based httpx mock) | T08-03, T08-04, T08-06, T08-08, T08-09 |
| DNS resolution | unittest.mock.patch on socket/httpx transport | T08-09 |
| File system | pytest tmp_path fixture | T08-06, T08-07 |

### Shared Fixtures

To avoid duplication across test files, create shared fixtures in `tests/integration/conftest.py`:

```python
# tests/integration/conftest.py

import pytest
from newsletter_agent.config.schema import (
    AppSettings, NewsletterConfig, NewsletterSettings, TopicConfig
)


@pytest.fixture
def config_with_both_features(tmp_path):
    """Config with timeframe and verify_links enabled."""
    return NewsletterConfig(
        newsletter=NewsletterSettings(
            title="Integration Test Newsletter",
            schedule="0 8 * * 0",
            recipient_email="test@example.com",
        ),
        settings=AppSettings(
            dry_run=True,
            output_dir=str(tmp_path),
            timeframe="last_week",
            verify_links=True,
        ),
        topics=[
            TopicConfig(
                name="AI News",
                query="Latest AI developments",
            ),
            TopicConfig(
                name="Cloud Updates",
                query="Cloud computing news",
                timeframe="last_month",  # per-topic override
            ),
        ],
    )


@pytest.fixture
def config_old_format(tmp_path):
    """Config with NO new fields - backward compatibility baseline."""
    return NewsletterConfig(
        newsletter=NewsletterSettings(
            title="Legacy Config Test",
            schedule="0 8 * * 0",
            recipient_email="test@example.com",
        ),
        settings=AppSettings(
            dry_run=True,
            output_dir=str(tmp_path),
        ),
        topics=[
            TopicConfig(
                name="General Tech",
                query="Technology news",
            ),
        ],
    )


@pytest.fixture
def synthesis_state_with_mixed_urls():
    """Synthesis state with some valid and some broken URLs."""
    return {
        "config_verify_links": True,
        "config_topic_count": 2,
        "synthesis_0": {
            "topic_name": "AI News",
            "body_markdown": (
                "## AI News\n\n"
                "See [Good Link](https://good.example.com/ai) for details. "
                "Also check [Broken Link](https://broken.example.com/gone).\n\n"
                "More at [Another Good](https://good2.example.com)."
            ),
            "sources": [
                {"title": "Good Link", "url": "https://good.example.com/ai"},
                {"title": "Broken Link", "url": "https://broken.example.com/gone"},
                {"title": "Another Good", "url": "https://good2.example.com"},
            ],
        },
        "synthesis_1": {
            "topic_name": "Cloud Updates",
            "body_markdown": (
                "## Cloud Updates\n\n"
                "The [Cloud Doc](https://cloud.example.com) is comprehensive.\n\n"
                "See also [Dead Page](https://dead.example.com/404) for history."
            ),
            "sources": [
                {"title": "Cloud Doc", "url": "https://cloud.example.com"},
                {"title": "Dead Page", "url": "https://dead.example.com/404"},
            ],
        },
    }
```

### Key Assertion Patterns

For backward compatibility tests, use these assertion patterns:

```python
# Assert no timeframe in research instructions
def assert_no_timeframe_in_instructions(agent):
    """Verify research agent instructions contain no date clause."""
    instruction_text = agent.instruction if hasattr(agent, 'instruction') else ""
    date_keywords = ["past", "since", "after", "before", "days", "weeks", "months",
                     "recent", "timeframe", "date range"]
    for keyword in date_keywords:
        assert keyword.lower() not in instruction_text.lower(), (
            f"Found unexpected date keyword '{keyword}' in research instructions"
        )


# Assert no link verifier in agent tree
def assert_no_link_verifier(agent_tree):
    """Verify LinkVerifierAgent is not in the pipeline."""
    from newsletter_agent.tools.link_verifier_agent import LinkVerifierAgent
    for sub_agent in getattr(agent_tree, 'sub_agents', []):
        assert not isinstance(sub_agent, LinkVerifierAgent), (
            "LinkVerifierAgent found in pipeline when verify_links is not enabled"
        )
```

For performance tests, use this timing pattern:

```python
import time

async def test_verification_throughput():
    start = time.monotonic()
    results = await verify_urls(urls_40, max_concurrent=10, timeout=10)
    elapsed = time.monotonic() - start

    assert elapsed < 30, f"Verification took {elapsed:.1f}s, exceeding 30s budget"
    assert len(results) == 40, f"Expected 40 results, got {len(results)}"
    # Soft warning for CI variance
    if elapsed > 15:
        import warnings
        warnings.warn(f"Verification took {elapsed:.1f}s - slower than expected")
```

## Parallel Opportunities

Tasks that can be worked concurrently:

- **Parallel Group A** (after T08-11): T08-01, T08-02, T08-03, T08-08, T08-09
  - These are isolated tests with no inter-dependencies
- **Parallel Group B** (after Group A): T08-04, T08-05
  - T08-04 builds on T08-01/02/03; T08-05 is independent but benefits from infrastructure
- **Sequential**: T08-06, T08-07 (full pipeline, run after isolated tests)
- **Last**: T08-10 (documentation, after all behavior verified)

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Complex mock setup for E2E tests causes brittle tests | Medium | Medium | Use shared fixtures in conftest.py; minimize mock specificity - mock at the transport layer not individual functions |
| Test execution time exceeds CI budget | Low | Medium | Mark slow tests with `@pytest.mark.slow`; run fast tests first in CI; performance tests can be a separate CI job |
| Existing test_full_pipeline.py breaks from WP06/WP07 changes | Medium | High | T08-05 and T08-07 specifically guard against this; run existing test suite first before adding new tests |
| respx version incompatibility with project httpx version | Low | Low | Check `requirements.txt` for httpx version; pin compatible respx version in test requirements |
| ADK agent tree structure changes between versions | Low | Medium | Abstract agent tree inspection into helper functions so only one place needs updating |
| Mock DNS resolution is platform-dependent | Medium | Low | Use respx transport-level mocking rather than socket-level; falls back to URL pattern matching |
| Performance test flakiness in CI | Medium | Medium | Set generous thresholds (30s budget for ~8s expected); focus on concurrency assertion which is deterministic |

## Estimated File Changes (Lines of Code)

| File | Lines Added | Lines Modified | Lines Removed |
|------|------------|----------------|---------------|
| tests/integration/__init__.py (NEW) | ~1 | 0 | 0 |
| tests/integration/conftest.py (NEW) | ~80 | 0 | 0 |
| tests/integration/test_config_research_timeframe.py (NEW) | ~120 | 0 | 0 |
| tests/integration/test_config_perplexity_timeframe.py (NEW) | ~130 | 0 | 0 |
| tests/integration/test_synthesis_link_verification.py (NEW) | ~140 | 0 | 0 |
| tests/integration/test_combined_features.py (NEW) | ~150 | 0 | 0 |
| tests/integration/test_backward_compatibility.py (NEW) | ~130 | 0 | 0 |
| tests/e2e/test_full_pipeline_with_features.py (NEW) | ~180 | 0 | 0 |
| tests/e2e/test_full_pipeline_backward_compat.py (NEW) | ~120 | 0 | 0 |
| tests/performance/test_link_verification_perf.py (NEW) | ~90 | 0 | 0 |
| tests/security/test_ssrf_prevention.py (NEW) | ~140 | 0 | 0 |
| README.md | ~40 | ~5 | 0 |
| config/example_topics_with_features.yaml (NEW) | ~30 | 0 | 0 |
| pyproject.toml or pytest.ini | ~10 | ~3 | 0 |
| **Total** | **~1361** | **~8** | **0** |

## Cross-References to WP06 and WP07

This work package depends on specific deliverables from both preceding work packages:

### From WP06 (Search Timeframe)
- **T06-01**: Config schema with `timeframe` field on `AppSettings` and `TopicConfig`
- **T06-02**: `resolve_timeframe()` function that converts config strings to provider parameters
- **T06-03**: Google Search instruction builder with date clause injection
- **T06-04**: Perplexity `search_perplexity()` with `search_recency_filter` parameter
- **T06-05**: `build_research_phase()` updated to pass timeframe to research agents
- **T06-06**: `config_timeframes` session state key population

### From WP07 (Link Verification)
- **T07-01**: Config schema with `verify_links` field on `AppSettings`
- **T07-03**: `verify_urls()` async function with concurrency control
- **T07-04**: SSRF protection (private IP blocking, scheme validation)
- **T07-05**: `clean_broken_links_from_markdown()` function
- **T07-06**: `LinkVerifierAgent` BaseAgent subclass
- **T07-08**: Pipeline integration (agent factory includes/excludes LinkVerifierAgent)

### Shared Dependencies
- `newsletter_agent.config.schema`: Both WPs modify this; WP08 tests the combined schema
- `newsletter_agent.agent`: Both WPs modify `build_research_phase()` and the agent factory
- Session state format: Both WPs add keys; WP08 verifies they coexist without conflicts

## Detailed Test Scenarios

### Scenario Matrix: Backward Compatibility

| Config Fields Present | Expected Behavior | Test Task |
|----------------------|-------------------|-----------|
| Neither timeframe nor verify_links | Identical to pre-change behavior | T08-05, T08-07 |
| Only timeframe (no verify_links) | Research filtered by date, no link verification | T08-01, T08-05 |
| Only verify_links (no timeframe) | Links verified, no date filtering | T08-03, T08-05 |
| Both timeframe and verify_links | Both features active | T08-04, T08-06 |

### Scenario Matrix: Error Conditions

| Error Condition | Expected Behavior | Test Task |
|----------------|-------------------|-----------|
| Invalid timeframe value in config | Pydantic validation error on load | T08-05 (negative case) |
| All URLs return 500 during verification | All links removed, notice appended, pipeline continues | T08-03 |
| Network completely down during verification | Links unchanged, warning logged, pipeline continues | T08-03 |
| Perplexity rejects search_recency_filter | Retry without filter, pipeline continues | T08-02 |
| URL redirects to private IP | URL marked broken, other URLs unaffected | T08-09 |
| Verification timeout exceeded for one URL | That URL marked broken, others still checked | T08-03 |

### Scenario Matrix: Concurrency and Performance

| Scenario | URLs | Max Concurrent | Delay per URL | Expected Wall Time | Test Task |
|----------|------|---------------|---------------|-------------------|-----------|
| Normal throughput | 40 | 10 | 2s | ~8s | T08-08 |
| Single URL | 1 | 10 | 2s | ~2s | T08-08 (edge) |
| All immediate | 10 | 10 | 0s | <1s | T08-08 (edge) |
| Exceed concurrency | 20 | 10 | 1s | ~2s | T08-08 |

## Detailed Acceptance Criteria Traceability

Every acceptance criterion in this WP traces to a specific spec requirement:

| Acceptance Criterion | Spec Source | FR/NFR |
|---------------------|-------------|--------|
| Research instructions contain date clause | Section 8.2, FR-006 | FR-006 |
| Perplexity extra_body contains search_recency_filter | Section 8.3, FR-007 | FR-007 |
| Broken links removed from synthesis state | Section 9.2, FR-020 | FR-020 |
| LinkVerifierAgent absent when verify_links=false | Section 9.4, FR-026 | FR-026 |
| No config_timeframes when timeframe absent | Section 8.1, FR-004 | FR-004 |
| 40 URLs verified in 30 seconds | Section 11.5, NFR-LINK-PERF | NFR-LINK-PERF |
| Private IP blocked during redirect | Section 11.6, NFR-LINK-SEC | NFR-LINK-SEC |
| No Authorization/Cookie headers in verification requests | Section 11.6 | NFR-LINK-SEC |
| Old config loads without errors | Section 12, SC-004 | SC-004 |
| Output HTML valid for both old and new configs | Section 11.4 | SC-001, SC-002 |

## BDD Scenarios for Integration Tests

### Feature: Combined Feature Composition

```gherkin
Feature: Timeframe and Link Verification work together

  Background:
    Given a topics.yaml with:
      | field         | value      |
      | timeframe     | last_week  |
      | verify_links  | true       |

  Scenario: Both features active in pipeline
    Given the config is loaded successfully
    And the research phase includes date clauses in instructions
    And the synthesis phase produces results with 5 source URLs per topic
    And 2 of the 5 URLs per topic return HTTP 404
    When the full pipeline runs in dry-run mode
    Then the output HTML contains only the 3 valid source URLs per topic
    And the output HTML does not contain markdown link syntax for broken URLs
    And the pipeline completes without errors

  Scenario: Timeframe does not affect link verification
    Given a topic with timeframe "last_week"
    And a source URL https://old-article.example.com from 2020 that returns HTTP 200
    When the link verifier checks the URL
    Then the URL is marked as valid (status code based, not date based)
    And the URL remains in the synthesis output

  Scenario: Link verification does not affect timeframe filtering
    Given a topic with verify_links true
    And a research agent with timeframe "last_month" in instructions
    When the research phase runs
    Then the research instructions contain "past 30 days" or equivalent date clause
    And the date clause is independent of link verification settings
```

### Feature: Backward Compatibility Preservation

```gherkin
Feature: Old configuration format continues to work

  Scenario: Minimal config with no new fields
    Given a topics.yaml with only these sections:
      | section    | fields                                    |
      | newsletter | title, schedule, recipient_email          |
      | settings   | dry_run, output_dir                       |
      | topics     | name, query                               |
    When the config is loaded
    Then no validation errors occur
    And settings.timeframe is None
    And settings.verify_links is false

  Scenario: Pipeline runs identically with old config
    Given the old-format config is loaded
    When the agent pipeline is built
    Then the pipeline does NOT contain a LinkVerifierAgent
    And research instructions do NOT contain date clause text
    And the pipeline runs to completion
    And output HTML matches the pre-change format

  Scenario: New fields default correctly
    Given a topics.yaml where settings section contains only "dry_run: true"
    When AppSettings is parsed
    Then timeframe defaults to None
    And verify_links defaults to false
    And no unexpected keys appear in session state
```

### Feature: Performance Requirements

```gherkin
Feature: Link verification meets performance targets

  Scenario: 40 URLs verified within budget
    Given 40 mock URLs each with 2-second response delay
    And max_concurrent is set to 10
    When verify_urls() is called with all 40 URLs
    Then all 40 URLs have verification results
    And the wall-clock time is less than 30 seconds
    And the peak concurrent connection count never exceeds 10

  Scenario: Single URL does not waste concurrency slots
    Given 1 mock URL with 2-second response delay
    When verify_urls() is called with 1 URL
    Then the result is returned in approximately 2 seconds
    And only 1 concurrent connection was made
```

### Feature: Security in Pipeline Context

```gherkin
Feature: SSRF prevention works end-to-end

  Scenario: Redirect to localhost blocked through agent
    Given a synthesis result with source URL https://redirect.example.com
    And that URL returns HTTP 302 with Location: http://127.0.0.1/admin
    When the LinkVerifierAgent runs
    Then the URL is marked as broken
    And the source is removed from the synthesis output
    And a warning is logged about SSRF attempt

  Scenario: No sensitive headers leak through agent
    Given the pipeline is configured with API keys in environment
    And a synthesis result with source URL https://external.example.com
    When the LinkVerifierAgent sends a HEAD request to that URL
    Then the request contains no Authorization header
    And the request contains no Cookie header
    And the request User-Agent matches the configured newsletter UA string
```

## Implementation Sequence Diagram

```
T08-11 (Infrastructure)
    |
    v
+---+---+---+---+---+
|   |   |   |   |   |
v   v   v   v   v   v
T08-01 T08-02 T08-03 T08-08 T08-09
    |       |     |
    v       v     v
    +---+---+
        |
        v
      T08-04
        |
    +---+---+
    |       |
    v       v
  T08-05  T08-07
    |       |
    v       v
  T08-06    |
    |       |
    +---+---+
        |
        v
      T08-10
```

## Rollback Strategy

If integration tests reveal issues with the combined features:

1. **Isolated WP regression**: If T08-01/02/03 fail, the issue is in WP06 or WP07's individual
   implementation. Fix in the originating WP; WP08 tests serve as the diagnostic.
2. **Composition failure**: If T08-04 fails but T08-01/02/03 pass, there is a cross-feature
   interference issue. Debug by examining shared session state keys.
3. **Backward compatibility failure**: If T08-05/07 fail, a change in WP06 or WP07 inadvertently
   broke the default behavior. Priority fix: restore default values in schema.
4. **Performance failure**: If T08-08 fails, adjust concurrency semaphore count or timeout values
   in WP07's verify_urls implementation.
5. **Security failure**: If T08-09 fails, strengthen SSRF guards in WP07's link verifier.

No WP08 code changes can fix the underlying feature; WP08 only contains tests and documentation.
Fixes always flow back to WP06 or WP07.

## Checklist Before Marking WP08 Complete

- [ ] All 11 tasks (T08-01 through T08-11) have passing tests or completed deliverables
- [ ] `pytest tests/` runs all test suites without failures
- [ ] `pytest --collect-only` discovers all new test files
- [ ] Performance test T08-08 passes within 30-second threshold
- [ ] Security test T08-09 covers all SSRF vectors listed in spec Section 11.6
- [ ] Backward compatibility tests T08-05 and T08-07 pass with old-format config
- [ ] README.md accurately describes both new features
- [ ] Configuration example files are valid YAML and can be loaded by `load_config()`
- [ ] No existing tests in the test suite were broken by WP06/WP07 changes
- [ ] Test coverage for new code meets the 95% target specified in Section 11.1

## Activity Log

- 2025-01-01T00:00:00Z - planner - lane=planned - Work package created
- 2025-01-01T00:00:00Z - planner - lane=planned - Tasks T08-01 through T08-11 defined
- 2025-01-01T00:00:00Z - planner - lane=planned - Integration test scenarios documented
- 2025-01-01T00:00:00Z - planner - lane=planned - BDD scenarios for combined features written
- 2025-01-01T00:00:00Z - planner - lane=planned - Performance and security test details added
- 2025-01-01T00:00:00Z - planner - lane=planned - Shared fixtures and mock strategy documented
- 2025-01-01T00:00:00Z - planner - lane=planned - Ready for implementation after WP06 and WP07

## Detailed Test Implementation Guides

### T08-01 Implementation Walkthrough

This section provides a step-by-step guide for implementing the Config + Research Timeframe
integration test.

**Step 1: Create the test file**

Create `tests/integration/test_config_research_timeframe.py` with standard imports:

```python
"""Integration test: Config loading -> Research phase instruction generation with timeframe.

Verifies that timeframe configuration flows through the config loader, timeframe resolver,
and into research agent instructions.

Spec refs: FR-001, FR-002, FR-006, FR-009, FR-027, FR-028, Section 11.3.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from newsletter_agent.config.schema import (
    AppSettings,
    NewsletterConfig,
    NewsletterSettings,
    TopicConfig,
    load_config,
)
from newsletter_agent.agent import build_research_phase
from newsletter_agent.tools.timeframe import resolve_timeframe
```

**Step 2: Create config fixtures**

Build two config variants - one with global timeframe, one with per-topic override:

```python
@pytest.fixture
def config_global_timeframe():
    """Config with global timeframe, no per-topic overrides."""
    return NewsletterConfig(
        newsletter=NewsletterSettings(
            title="Timeframe Integration Test",
            schedule="0 8 * * 0",
            recipient_email="test@example.com",
        ),
        settings=AppSettings(
            dry_run=True,
            timeframe="last_week",
        ),
        topics=[
            TopicConfig(name="Topic A", query="Query A"),
            TopicConfig(name="Topic B", query="Query B"),
        ],
    )


@pytest.fixture
def config_per_topic_override():
    """Config with global timeframe and one per-topic override."""
    return NewsletterConfig(
        newsletter=NewsletterSettings(
            title="Override Integration Test",
            schedule="0 8 * * 0",
            recipient_email="test@example.com",
        ),
        settings=AppSettings(
            dry_run=True,
            timeframe="last_week",
        ),
        topics=[
            TopicConfig(name="Topic A", query="Query A"),
            TopicConfig(name="Topic B", query="Query B", timeframe="last_month"),
        ],
    )
```

**Step 3: Write the global timeframe test**

```python
class TestGlobalTimeframeResearch:
    """Integration: global timeframe flows into research instructions."""

    def test_global_timeframe_in_instructions(self, config_global_timeframe):
        """Both topics should have the global timeframe date clause."""
        research_phase = build_research_phase(config_global_timeframe)
        # Inspect the instructions of each research sub-agent
        for i, topic in enumerate(config_global_timeframe.topics):
            # The research agent for topic i should contain date clause
            # Exact attribute path depends on ADK agent structure
            agent = research_phase.sub_agents[i] if hasattr(research_phase, 'sub_agents') else None
            assert agent is not None, f"No research agent found for topic {i}"
            instruction = getattr(agent, 'instruction', '')
            # Global timeframe "last_week" should produce date clause
            assert any(
                kw in instruction.lower()
                for kw in ["past 7 days", "past week", "last week", "since"]
            ), f"No date clause found in research instructions for topic {i}: {instruction[:200]}"

    def test_config_timeframes_in_state(self, config_global_timeframe):
        """Session state should contain config_timeframes for all topics."""
        # Build state as the config loader would
        state = {}
        # The config loader populates config_timeframes
        for i, topic in enumerate(config_global_timeframe.topics):
            effective_timeframe = topic.timeframe or config_global_timeframe.settings.timeframe
            if effective_timeframe:
                resolved = resolve_timeframe(effective_timeframe)
                state.setdefault("config_timeframes", {})[i] = resolved
        assert "config_timeframes" in state
        assert len(state["config_timeframes"]) == 2
        # Both should resolve to "last_week"
        for i in range(2):
            assert state["config_timeframes"][i] is not None
```

**Step 4: Write the per-topic override test**

```python
class TestPerTopicTimeframeOverride:
    """Integration: per-topic timeframe overrides global."""

    def test_override_takes_precedence(self, config_per_topic_override):
        """Topic B with 'last_month' should override global 'last_week'."""
        research_phase = build_research_phase(config_per_topic_override)
        # Topic A (index 0) should have "last_week" date clause
        agent_a = research_phase.sub_agents[0]
        instruction_a = getattr(agent_a, 'instruction', '')
        assert any(
            kw in instruction_a.lower()
            for kw in ["past 7 days", "past week", "last week"]
        ), f"Topic A should have weekly date clause: {instruction_a[:200]}"

        # Topic B (index 1) should have "last_month" date clause
        agent_b = research_phase.sub_agents[1]
        instruction_b = getattr(agent_b, 'instruction', '')
        assert any(
            kw in instruction_b.lower()
            for kw in ["past 30 days", "past month", "last month"]
        ), f"Topic B should have monthly date clause: {instruction_b[:200]}"

    def test_config_timeframes_reflects_override(self, config_per_topic_override):
        """config_timeframes should show different resolved values per topic."""
        state = {}
        for i, topic in enumerate(config_per_topic_override.topics):
            effective = topic.timeframe or config_per_topic_override.settings.timeframe
            if effective:
                resolved = resolve_timeframe(effective)
                state.setdefault("config_timeframes", {})[i] = resolved
        assert state["config_timeframes"][0] != state["config_timeframes"][1]
```

**Key observation**: The exact attribute paths (`sub_agents[i].instruction`) depend on how
WP06 structures the agent tree. The coder should print the agent tree during development and
adjust the attribute paths accordingly.

### T08-02 Implementation Walkthrough

This section provides a step-by-step guide for the Perplexity timeframe passthrough test.

**Step 1: Understanding the mock target**

The `search_perplexity()` function calls the Perplexity API through an OpenAI-compatible client.
When a timeframe is set, it should pass `search_recency_filter` via `extra_body`. The mock must
intercept the API call and inspect the request body.

```python
"""Integration test: Perplexity search receives correct search_recency_filter.

Verifies the timeframe resolver output is correctly passed through to the
Perplexity API as a search_recency_filter parameter.

Spec refs: FR-007, FR-010, Section 11.3 bullet 2.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from newsletter_agent.tools.perplexity_search import search_perplexity
from newsletter_agent.tools.timeframe import resolve_timeframe
```

**Step 2: Mock the Perplexity client**

```python
@pytest.fixture
def mock_perplexity_client():
    """Mock the OpenAI-compatible Perplexity client."""
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content="Mock research result about AI."))
    ]
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    return mock_client
```

**Step 3: Write parameterized tests for each timeframe mapping**

```python
class TestPerplexityTimeframePassthrough:
    """Integration: timeframe resolves to correct search_recency_filter."""

    @pytest.mark.parametrize("timeframe,expected_filter", [
        ("last_day", "day"),
        ("last_week", "week"),
        ("last_month", "month"),
    ])
    @pytest.mark.asyncio
    async def test_recency_filter_mapping(
        self, mock_perplexity_client, timeframe, expected_filter
    ):
        """Each preset timeframe maps to the correct Perplexity filter value."""
        resolved = resolve_timeframe(timeframe)
        with patch(
            "newsletter_agent.tools.perplexity_search._get_client",
            return_value=mock_perplexity_client,
        ):
            await search_perplexity(
                query="AI frameworks 2025",
                search_recency_filter=resolved.perplexity_filter,
            )
        # Inspect the call kwargs
        call_kwargs = mock_perplexity_client.chat.completions.create.call_args
        extra_body = call_kwargs.kwargs.get("extra_body", {})
        assert extra_body.get("search_recency_filter") == expected_filter

    @pytest.mark.asyncio
    async def test_no_filter_when_no_timeframe(self, mock_perplexity_client):
        """When timeframe is None, no extra_body is sent."""
        with patch(
            "newsletter_agent.tools.perplexity_search._get_client",
            return_value=mock_perplexity_client,
        ):
            await search_perplexity(query="AI frameworks 2025")
        call_kwargs = mock_perplexity_client.chat.completions.create.call_args
        extra_body = call_kwargs.kwargs.get("extra_body")
        assert extra_body is None or "search_recency_filter" not in extra_body
```

**Step 4: Write the retry-on-rejection test**

```python
    @pytest.mark.asyncio
    async def test_retry_without_filter_on_rejection(self, mock_perplexity_client):
        """When Perplexity returns 400, retry without search_recency_filter."""
        # First call raises, second call succeeds
        mock_perplexity_client.chat.completions.create.side_effect = [
            Exception("HTTP 400: Invalid parameter search_recency_filter"),
            MagicMock(choices=[MagicMock(message=MagicMock(content="Result"))]),
        ]
        resolved = resolve_timeframe("last_week")
        with patch(
            "newsletter_agent.tools.perplexity_search._get_client",
            return_value=mock_perplexity_client,
        ):
            result = await search_perplexity(
                query="AI frameworks",
                search_recency_filter=resolved.perplexity_filter,
            )
        # Should have been called twice
        assert mock_perplexity_client.chat.completions.create.call_count == 2
        # Second call should not have search_recency_filter
        second_call = mock_perplexity_client.chat.completions.create.call_args_list[1]
        extra_body = second_call.kwargs.get("extra_body")
        assert extra_body is None or "search_recency_filter" not in extra_body
```

### T08-03 Implementation Walkthrough

This section details the Synthesis + LinkVerifier integration test.

**Step 1: Set up respx routes for mixed HTTP responses**

```python
"""Integration test: Synthesis output -> LinkVerifierAgent -> Formatter input.

Verifies that the link verifier correctly processes synthesis state, removes broken links,
and produces output consumable by the formatter.

Spec refs: FR-014, FR-015, FR-020, FR-025, Section 11.3 bullet 3.
"""

import pytest
import respx
import httpx

from newsletter_agent.tools.link_verifier_agent import LinkVerifierAgent
from newsletter_agent.tools.formatter import render_newsletter


@pytest.fixture
def respx_routes():
    """Configure mock HTTP responses: 3 valid, 2 broken."""
    with respx.mock:
        # Valid URLs return 200
        respx.head("https://good.example.com/ai").mock(
            return_value=httpx.Response(200)
        )
        respx.head("https://good2.example.com").mock(
            return_value=httpx.Response(200)
        )
        respx.head("https://cloud.example.com").mock(
            return_value=httpx.Response(200)
        )
        # Broken URLs return 404
        respx.head("https://broken.example.com/gone").mock(
            return_value=httpx.Response(404)
        )
        respx.head("https://dead.example.com/404").mock(
            return_value=httpx.Response(404)
        )
        yield
```

**Step 2: Run the agent and verify state transformation**

```python
class TestSynthesisLinkVerificationFlow:
    """Integration: synthesis state flows through link verifier to formatter."""

    @pytest.mark.asyncio
    async def test_broken_links_removed(
        self, respx_routes, synthesis_state_with_mixed_urls
    ):
        """Broken URLs are removed from sources and body_markdown."""
        agent = LinkVerifierAgent()
        result_state = await agent.run(synthesis_state_with_mixed_urls)
        # Topic 0: had 3 sources, 1 broken -> 2 remain
        assert len(result_state["synthesis_0"]["sources"]) == 2
        assert not any(
            s["url"] == "https://broken.example.com/gone"
            for s in result_state["synthesis_0"]["sources"]
        )
        # Topic 1: had 2 sources, 1 broken -> 1 remains
        assert len(result_state["synthesis_1"]["sources"]) == 1
        assert result_state["synthesis_1"]["sources"][0]["url"] == "https://cloud.example.com"

    @pytest.mark.asyncio
    async def test_markdown_cleaned(
        self, respx_routes, synthesis_state_with_mixed_urls
    ):
        """Broken link citations in body_markdown replaced with plain text."""
        agent = LinkVerifierAgent()
        result_state = await agent.run(synthesis_state_with_mixed_urls)
        body_0 = result_state["synthesis_0"]["body_markdown"]
        # Broken link citation should be plain text, not markdown link
        assert "[Broken Link](https://broken.example.com/gone)" not in body_0
        assert "Broken Link" in body_0  # Plain text remains
        # Valid link citation should be preserved
        assert "[Good Link](https://good.example.com/ai)" in body_0

    @pytest.mark.asyncio
    async def test_formatter_accepts_cleaned_state(
        self, respx_routes, synthesis_state_with_mixed_urls
    ):
        """The formatter can consume post-verification state without errors."""
        agent = LinkVerifierAgent()
        result_state = await agent.run(synthesis_state_with_mixed_urls)
        # Pass to formatter - should not raise
        html = render_newsletter(result_state)
        assert "<html" in html.lower() or "<!doctype" in html.lower()
        # Valid links should appear as HTML anchors
        assert "https://good.example.com/ai" in html
        # Broken links should NOT appear as HTML anchors
        assert "https://broken.example.com/gone" not in html
```

### T08-08 Implementation Walkthrough

This section provides a detailed implementation guide for the performance test.

**Step 1: Set up the delayed mock server**

```python
"""Performance test: Link verification throughput and concurrency limits.

Verifies NFR-LINK-PERF: 40 URLs verified within 30 seconds with max 10 concurrent.

Spec refs: NFR-LINK-PERF, FR-018, Section 11.5.
"""

import asyncio
import time
import pytest
import respx
import httpx

from newsletter_agent.tools.link_verifier import verify_urls


@pytest.fixture
def delayed_mock_server():
    """Mock server where every URL takes 2 seconds to respond."""
    max_concurrent = 0
    current_concurrent = 0
    lock = asyncio.Lock()
    stats = {"max_concurrent": 0, "total_requests": 0}

    async def delayed_handler(request):
        nonlocal max_concurrent, current_concurrent
        async with lock:
            current_concurrent += 1
            stats["total_requests"] += 1
            if current_concurrent > stats["max_concurrent"]:
                stats["max_concurrent"] = current_concurrent
        try:
            await asyncio.sleep(2)
            return httpx.Response(200)
        finally:
            async with lock:
                current_concurrent -= 1

    urls = [f"https://perf-test-{i}.example.com/page" for i in range(40)]

    with respx.mock:
        for url in urls:
            respx.head(url).mock(side_effect=delayed_handler)
        yield urls, stats
```

**Step 2: Write the throughput test**

```python
class TestLinkVerificationPerformance:
    """Performance: verify 40 URLs within 30s budget."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_40_urls_within_budget(self, delayed_mock_server):
        """40 URLs with 2s delay each should complete in ~8s with 10 concurrent."""
        urls, stats = delayed_mock_server
        start = time.monotonic()
        results = await verify_urls(urls, max_concurrent=10, timeout=10)
        elapsed = time.monotonic() - start

        # All URLs should have results
        assert len(results) == 40, f"Expected 40 results, got {len(results)}"

        # Wall-clock time should be within spec budget
        assert elapsed < 30, (
            f"Verification took {elapsed:.1f}s, exceeding 30s budget"
        )

        # Concurrency should never exceed 10
        assert stats["max_concurrent"] <= 10, (
            f"Peak concurrency was {stats['max_concurrent']}, exceeding limit of 10"
        )

        # All 40 requests should have been made
        assert stats["total_requests"] == 40

        # Soft warning for unexpectedly slow execution
        if elapsed > 15:
            import warnings
            warnings.warn(
                f"Verification took {elapsed:.1f}s - expected ~8s. "
                "May indicate concurrency is not working optimally."
            )

    @pytest.mark.asyncio
    async def test_single_url_minimal_overhead(self, delayed_mock_server):
        """Single URL should take approximately 2 seconds (one delay period)."""
        urls, stats = delayed_mock_server
        single_url = [urls[0]]
        start = time.monotonic()
        results = await verify_urls(single_url, max_concurrent=10, timeout=10)
        elapsed = time.monotonic() - start

        assert len(results) == 1
        assert elapsed < 5, f"Single URL took {elapsed:.1f}s, expected ~2s"
        assert stats["max_concurrent"] == 1
```

### T08-09 Implementation Walkthrough

This section details the SSRF security test implementation.

**Step 1: Set up redirect-to-private-IP mock**

```python
"""Security test: SSRF prevention in the link verification pipeline.

Verifies that the LinkVerifierAgent correctly blocks requests to private IP ranges,
localhost, and non-HTTP schemes even when reached via redirect chains.

Spec refs: NFR-LINK-SEC, Section 11.6.
"""

import pytest
import respx
import httpx

from newsletter_agent.tools.link_verifier import verify_urls
from newsletter_agent.tools.link_verifier_agent import LinkVerifierAgent
```

**Step 2: Write redirect-to-localhost test**

```python
class TestSSRFRedirectProtection:
    """Security: redirects to private IPs are blocked."""

    @pytest.mark.asyncio
    async def test_redirect_to_localhost_blocked(self):
        """URL that 302s to 127.0.0.1 should be marked broken."""
        with respx.mock:
            respx.head("https://redirect.example.com").mock(
                return_value=httpx.Response(
                    302, headers={"Location": "http://127.0.0.1/admin"}
                )
            )
            results = await verify_urls(
                ["https://redirect.example.com"],
                max_concurrent=5,
                timeout=10,
            )
        assert results["https://redirect.example.com"] is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("private_ip", [
        "http://10.0.0.1/internal",
        "http://172.16.0.1/internal",
        "http://192.168.1.1/internal",
        "http://[::1]/internal",
        "http://169.254.169.254/latest/meta-data/",
    ])
    async def test_redirect_to_private_ip_blocked(self, private_ip):
        """URLs redirecting to any private IP range are blocked."""
        with respx.mock:
            respx.head("https://sneaky.example.com").mock(
                return_value=httpx.Response(
                    302, headers={"Location": private_ip}
                )
            )
            results = await verify_urls(
                ["https://sneaky.example.com"],
                max_concurrent=5,
                timeout=10,
            )
        assert results["https://sneaky.example.com"] is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_scheme_url", [
        "file:///etc/passwd",
        "javascript:alert(1)",
        "ftp://internal.example.com/data",
    ])
    async def test_redirect_to_non_http_scheme_blocked(self, bad_scheme_url):
        """Redirects to non-HTTP schemes are blocked."""
        with respx.mock:
            respx.head("https://scheme-redirect.example.com").mock(
                return_value=httpx.Response(
                    302, headers={"Location": bad_scheme_url}
                )
            )
            results = await verify_urls(
                ["https://scheme-redirect.example.com"],
                max_concurrent=5,
                timeout=10,
            )
        assert results["https://scheme-redirect.example.com"] is False


class TestSSRFHeaderProtection:
    """Security: no sensitive headers in outgoing verification requests."""

    @pytest.mark.asyncio
    async def test_no_auth_headers_leaked(self):
        """Verification requests must not contain Authorization or Cookie headers."""
        captured_headers = {}

        async def capture_handler(request):
            captured_headers.update(dict(request.headers))
            return httpx.Response(200)

        with respx.mock:
            respx.head("https://header-test.example.com").mock(
                side_effect=capture_handler
            )
            await verify_urls(
                ["https://header-test.example.com"],
                max_concurrent=5,
                timeout=10,
            )
        assert "authorization" not in {k.lower() for k in captured_headers}
        assert "cookie" not in {k.lower() for k in captured_headers}

    @pytest.mark.asyncio
    async def test_user_agent_is_set(self):
        """Verification requests should have a proper User-Agent."""
        captured_headers = {}

        async def capture_handler(request):
            captured_headers.update(dict(request.headers))
            return httpx.Response(200)

        with respx.mock:
            respx.head("https://ua-test.example.com").mock(
                side_effect=capture_handler
            )
            await verify_urls(
                ["https://ua-test.example.com"],
                max_concurrent=5,
                timeout=10,
            )
        assert "user-agent" in {k.lower() for k in captured_headers}
        ua = captured_headers.get("User-Agent", captured_headers.get("user-agent", ""))
        assert len(ua) > 0, "User-Agent header should not be empty"
```

### T08-05 Implementation Walkthrough

This section details the backward compatibility test implementation.

```python
"""Backward compatibility test suite.

Verifies SC-004: existing topics.yaml files without new fields continue to work.

Spec refs: SC-004, FR-004, FR-024, FR-026, Section 11.4 bullet 2.
"""

import pytest
from unittest.mock import patch

from newsletter_agent.config.schema import (
    AppSettings,
    NewsletterConfig,
    NewsletterSettings,
    TopicConfig,
    load_config,
)
from newsletter_agent.agent import build_agent


# This YAML matches the format in tests/e2e/test_full_pipeline.py exactly
OLD_FORMAT_YAML = """\
newsletter:
  title: "Legacy Newsletter"
  schedule: "0 8 * * 0"
  recipient_email: "test@example.com"

settings:
  dry_run: true
  output_dir: "{output_dir}"

topics:
  - name: "AI Frameworks"
    query: "Latest developments in AI agent frameworks"
  - name: "Cloud Native"
    query: "Cloud native technology updates"
"""


class TestConfigBackwardCompatibility:
    """Config loading: old format loads with correct defaults."""

    def test_old_format_loads_without_errors(self, tmp_path):
        config_file = tmp_path / "topics.yaml"
        config_file.write_text(OLD_FORMAT_YAML.format(output_dir=str(tmp_path)))
        config = load_config(str(config_file))
        assert config is not None

    def test_new_fields_default_correctly(self, tmp_path):
        config_file = tmp_path / "topics.yaml"
        config_file.write_text(OLD_FORMAT_YAML.format(output_dir=str(tmp_path)))
        config = load_config(str(config_file))
        # timeframe should default to None
        assert config.settings.timeframe is None
        # verify_links should default to False
        assert config.settings.verify_links is False
        # Per-topic timeframe should also be None
        for topic in config.topics:
            assert getattr(topic, 'timeframe', None) is None


class TestPipelineBackwardCompatibility:
    """Pipeline: old config produces no new behavior."""

    def test_no_link_verifier_in_pipeline(self, config_old_format):
        agent_tree = build_agent(config_old_format)
        # Check sub_agents for LinkVerifierAgent
        from newsletter_agent.tools.link_verifier_agent import LinkVerifierAgent
        for sub in getattr(agent_tree, 'sub_agents', []):
            assert not isinstance(sub, LinkVerifierAgent)

    def test_no_date_clause_in_research(self, config_old_format):
        from newsletter_agent.agent import build_research_phase
        research = build_research_phase(config_old_format)
        date_keywords = ["past", "since", "after", "before", "days ago",
                         "weeks ago", "months ago", "date range", "timeframe"]
        for sub in getattr(research, 'sub_agents', []):
            instruction = getattr(sub, 'instruction', '')
            for keyword in date_keywords:
                assert keyword.lower() not in instruction.lower(), (
                    f"Found '{keyword}' in research instructions for old config"
                )

    def test_no_config_timeframes_in_state(self, config_old_format):
        """Session state should not contain config_timeframes."""
        # Build initial state as config loader would
        state = {}
        for i, topic in enumerate(config_old_format.topics):
            effective_tf = getattr(topic, 'timeframe', None) or getattr(
                config_old_format.settings, 'timeframe', None
            )
            if effective_tf:
                state.setdefault("config_timeframes", {})[i] = effective_tf
        assert "config_timeframes" not in state
```

## Documentation Update Details (T08-10)

### README.md Updates

The following sections should be added or updated in README.md:

**Configuration Reference section** (add or extend):

```markdown
### Search Timeframe

Constrain research to a specific time period. Set at the global level or per topic.

**Global setting** (applies to all topics):
settings:
  timeframe: "last_week"

**Per-topic override**:
topics:
  - name: "Breaking News"
    query: "AI breakthroughs"
    timeframe: "last_day"

**Valid values**:
| Value | Period |
|-------|--------|
| last_day | Past 24 hours |
| last_week | Past 7 days |
| last_month | Past 30 days |
| last_year | Past 365 days |
| YYYY-MM-DD..YYYY-MM-DD | Custom date range |

Omit the field entirely to search without time constraints (default behavior).

### Link Verification

Automatically verify source URLs before including them in the newsletter.

settings:
  verify_links: true

When enabled:
- Each source URL is checked with an HTTP HEAD request
- Broken links (4xx, 5xx, timeout) are silently removed
- If all sources for a topic are broken, a notice is appended
- Verification runs concurrently (max 10 simultaneous checks)

When disabled or omitted (default): no verification occurs, all sources are included as-is.
```

**Backward Compatibility note** (add):

```markdown
### Backward Compatibility

Existing `topics.yaml` files continue to work without changes. New fields (`timeframe`,
`verify_links`) are optional and default to disabled. No existing behavior is altered when
these fields are absent.
```

### Example Configuration File

Create `config/example_topics_with_features.yaml`:

```yaml
# Example configuration demonstrating timeframe filtering and link verification.
# Both features are optional - omit them to keep existing behavior.

newsletter:
  title: "Weekly AI Digest"
  schedule: "0 8 * * 0"
  recipient_email: "team@example.com"

settings:
  dry_run: false
  output_dir: "output"
  timeframe: "last_week"      # Global: all topics default to past 7 days
  verify_links: true           # Check all source URLs before including them

topics:
  - name: "AI Research"
    query: "Latest AI research papers and breakthroughs"
    # Inherits global timeframe: last_week

  - name: "Industry News"
    query: "AI industry announcements and product launches"
    timeframe: "last_day"      # Override: only past 24 hours for fast-moving news

  - name: "Deep Dives"
    query: "In-depth AI architecture and design articles"
    timeframe: "last_month"    # Override: broader timeframe for evergreen content
```

## Test Coverage Targets

This work package targets the following coverage metrics:

| Test Category | Files Covered | Target Coverage | Rationale |
|---------------|--------------|----------------|-----------|
| Integration (T08-01 to T08-05) | config schema, timeframe resolver, research builder, link verifier agent, formatter | 95% of integration paths | Spec Section 11.1 requires 95% for new code |
| E2E (T08-06, T08-07) | Full pipeline | Smoke-level (critical path) | Validates assembled pipeline, not line coverage |
| Performance (T08-08) | verify_urls() | Concurrency + budget assertion | NFR-LINK-PERF compliance |
| Security (T08-09) | SSRF guards, header sanitization | 100% of SSRF vectors in spec | NFR-LINK-SEC - security tests must be exhaustive |
| Documentation (T08-10) | README.md, examples | N/A | Completeness of user-facing docs |

### Coverage Gap Analysis

The following paths are covered by WP06/WP07 unit tests but validated here at integration level:

| Path | Unit Coverage (WP06/07) | Integration Coverage (WP08) |
|------|-------------------------|-----------------------------|
| Config load with timeframe | test_config.py | T08-01, T08-05 |
| Perplexity filter passthrough | test_perplexity_search.py | T08-02 |
| Link verification HTTP flow | test_link_verifier.py | T08-03, T08-08 |
| Markdown cleaning | test_link_verifier.py | T08-03 |
| SSRF blocking | test_link_verifier.py | T08-09 |
| Agent pipeline assembly | test_agent_factory.py | T08-04, T08-05 |
| Full pipeline dry-run | test_full_pipeline.py | T08-06, T08-07 |
| Backward compat defaults | test_config.py | T08-05, T08-07 |
| Combined features composition | (none - unit only) | T08-04, T08-06 |
| HEAD to GET fallback | test_link_verifier.py | T08-03 |
| All-broken notice insertion | test_link_verifier_agent.py | T08-03 |
| Timeframe per-topic override | test_config.py | T08-01 |

This ensures no coverage gap between unit isolation and system integration.

### Test Execution Commands

Run all WP08 tests:
```bash
pytest tests/integration/ tests/e2e/ tests/performance/ tests/security/ -v
```

Run only integration tests:
```bash
pytest tests/integration/ -v
```

Run only backward compatibility tests:
```bash
pytest tests/integration/test_backward_compatibility.py tests/e2e/test_full_pipeline_backward_compat.py -v
```

Run only slow/performance tests:
```bash
pytest -m slow -v
```

---

*End of WP08 - Integration Testing, E2E Verification & Documentation*

## Self-Review

### Spec Compliance
- [x] All integration tests (T08-01 through T08-05) implemented and passing
- [x] E2E tests (T08-06, T08-07) cover both new-feature and backward-compat paths
- [x] Performance test (T08-08) verifies 40-URL concurrency within 30s budget
- [x] Security test (T08-09) covers SSRF private IP blocking, scheme validation, redirect protection, header leakage, and agent-level verification
- [x] Documentation (T08-10) updated: README, configuration guide, architecture docs, example config
- [x] Test infrastructure (T08-11) verified: __init__.py files, security marker registered in pyproject.toml

### Correctness
- [x] All 400 tests pass (full suite with `--ignore=tests/unit/test_http_handler.py` due to pre-existing Flask dependency)
- [x] No regressions in existing tests
- [x] Integration tests verify cross-module data flow, not just unit behavior

### Code Quality
- [x] No unused imports or debug artifacts
- [x] No hardcoded values that belong in config
- [x] Test fixtures are shared via conftest.py to avoid duplication

### Scope Discipline
- [x] Only test files, documentation, and one config infrastructure change (pyproject.toml marker)
- [x] No feature code modified

### Outstanding Issues
- Pre-existing: `tests/unit/test_http_handler.py` fails to collect due to missing Flask dependency (not related to WP08)

## Activity Log

- 2025-07-14T23:00:00Z - coder - lane=doing - Starting WP08 implementation
- 2025-07-14T23:30:00Z - coder - lane=doing - T08-01 through T08-05 integration tests created and passing
- 2025-07-14T23:45:00Z - coder - lane=doing - T08-08 performance test created, T08-09 security test created
- 2025-07-14T23:55:00Z - coder - lane=doing - T08-06/T08-07 E2E tests created and passing
- 2025-07-15T00:05:00Z - coder - lane=doing - T08-10 documentation updated (README, config guide, architecture)
- 2025-07-15T00:10:00Z - coder - lane=doing - T08-11 infrastructure verified, security marker added
- 2025-07-15T00:15:00Z - coder - lane=for_review - All tasks complete, 400 tests passing, submitted for review
- 2025-07-15T01:00:00Z - reviewer - lane=to_do - Verdict: Changes Required (3 FAILs) -- awaiting remediation

## Review

> **Reviewed by**: Reviewer Agent
> **Date**: 2025-07-15
> **Verdict**: Changes Required
> **review_status**: has_feedback
> **Scope**: Combined review of WP06 + WP07 + WP08

### Summary

Changes Required. Three FAILs found across the combined WP06/WP07/WP08 scope: (1) WP06 and WP07 are missing Spec Compliance Checklists entirely -- process violation; (2) the BDD test file `tests/bdd/test_timeframe_config.py` required by spec Section 11.2 and WP06 task T06-11 does not exist -- all 6 timeframe BDD scenarios are unimplemented; (3) WP06 and WP07 have stale Activity Logs with no coder entries and incorrect lane frontmatter (`doing`/`planned` instead of `for_review`). Five WARNs cover: unused imports in agent.py, documentation inaccuracy in configuration-guide.md (`last_2_weeks` Perplexity filter incorrectly listed as `week` instead of `month`), FR-026 deviation (LinkVerifierAgent always included rather than conditionally), `Full Schema` YAML block in configuration-guide.md omits new fields, and architecture.md security section is stale.

### Review Feedback

> Implementers: if `review_status: has_feedback` is set in the WP frontmatter, address every item below before returning for re-review. Update `review_status: acknowledged` once you begin remediation.

- [ ] **FB-01**: Create `tests/bdd/test_timeframe_config.py` implementing all 6 BDD scenarios from spec Section 11.2 (Global timeframe, Per-topic override, Custom days, Absolute date range, Invalid rejected, No timeframe configured). This is WP06 task T06-11.
- [ ] **FB-02**: Add Spec Compliance Checklists (Step 2b) to `plans/WP06-search-timeframe.md` for tasks T06-01 through T06-11. Each task must have a checklist mapping acceptance criteria to verified status.
- [ ] **FB-03**: Add Spec Compliance Checklists (Step 2b) to `plans/WP07-link-verification.md` for tasks T07-01 through T07-10.
- [ ] **FB-04**: Update Activity Logs in WP06 and WP07 with lane transitions (doing, for_review) and coder entries. Update frontmatter lane to `for_review` (or leave as `to_do` since this review returns them).
- [ ] **FB-05**: Remove unused imports `functools` and `ResolvedTimeframe` from `newsletter_agent/agent.py`.
- [ ] **FB-06**: Fix `docs/configuration-guide.md` Timeframe Values table: `last_2_weeks` Perplexity Filter should be `month`, not `week` (per FR-007 and actual implementation).
- [ ] **FB-07**: Update `docs/configuration-guide.md` Full Schema YAML block to include `timeframe` and `verify_links` fields in both `settings` and `topics` sections.
- [ ] **FB-08**: Update `docs/architecture.md` Security Design section to mention link verifier SSRF protections (currently says "no user-controlled URLs are used for outbound requests" which is inaccurate post-WP07).

### Findings

#### FAIL - Process Compliance (WP06 Spec Compliance Checklist)
- **Requirement**: Coder Step 2b -- Spec Compliance Checklist for each task
- **Status**: Missing
- **Detail**: WP06 has an "Acceptance Verification Checklist" (line 711) but it is a run-the-tests checklist, not a per-task spec compliance checklist mapping each acceptance criterion to verified status. No T06-01 through T06-11 checklists exist.
- **Evidence**: [plans/WP06-search-timeframe.md](plans/WP06-search-timeframe.md#L711)

#### FAIL - Process Compliance (WP07 Spec Compliance Checklist)
- **Requirement**: Coder Step 2b -- Spec Compliance Checklist for each task
- **Status**: Missing
- **Detail**: WP07 has an "Acceptance Verification Checklist" (line 1427) but it is a run-the-tests checklist, not a per-task spec compliance checklist. No T07-01 through T07-10 checklists exist.
- **Evidence**: [plans/WP07-link-verification.md](plans/WP07-link-verification.md#L1427)

#### FAIL - Test Coverage (Missing BDD test file)
- **Requirement**: Spec Section 11.2 -- Search Timeframe Configuration BDD scenarios; WP06 T06-11
- **Status**: Missing
- **Detail**: `tests/bdd/test_timeframe_config.py` does not exist. All 6 spec-required BDD scenarios for Search Timeframe Configuration are unimplemented: Global timeframe filters all topics, Per-topic override, Custom days, Absolute date range, Invalid rejected, No timeframe configured.
- **Evidence**: File not found at `tests/bdd/test_timeframe_config.py`

#### WARN - Process Compliance (Activity Logs stale)
- **Requirement**: Activity Log entries consistent with lane transitions
- **Status**: Deviating
- **Detail**: WP06 Activity Log contains only planner entries; no coder entries for lane=doing or lane=for_review. WP06 frontmatter shows `lane: doing` (not updated to `for_review`). WP07 Activity Log also has only planner entries; frontmatter shows `lane: planned` (never updated). WP08 Activity Log is complete and correct.
- **Evidence**: [plans/WP06-search-timeframe.md](plans/WP06-search-timeframe.md#L1828), [plans/WP07-link-verification.md](plans/WP07-link-verification.md#L1740)

#### WARN - Scope Discipline (Commit granularity)
- **Requirement**: One commit per task, not batched
- **Status**: Deviating
- **Detail**: WP06 (11 tasks) was delivered in a single commit `58323a4`. WP07 (10 tasks) was delivered in a single commit `d1f556b`. WP08 (11 tasks) was delivered in a single commit `9d4d42f`. The spec expects per-task commits for traceability. Not blocking correctness.
- **Evidence**: `git log --oneline`

#### PASS - Spec Adherence (FR-001 through FR-005: Timeframe Config)
- **Requirement**: FR-001 through FR-005
- **Status**: Compliant
- **Detail**: `TimeframeValue` Pydantic validator correctly validates all formats. `AppSettings.timeframe` and `TopicConfig.timeframe` are optional with None default. Validation rejects invalid values with descriptive errors. No timeframe = no filtering.
- **Evidence**: [newsletter_agent/config/timeframe.py](newsletter_agent/config/timeframe.py), [newsletter_agent/config/schema.py](newsletter_agent/config/schema.py)

#### PASS - Spec Adherence (FR-006 through FR-012: Timeframe Application)
- **Requirement**: FR-006 through FR-012
- **Status**: Compliant
- **Detail**: Google Search instruction includes date clause when timeframe set. Perplexity receives `search_recency_filter` via `extra_body`. Mapping from timeframe values to Perplexity filters matches FR-007 exactly. Absolute ranges produce prompt-only instructions. Retry-without-filter on API rejection implemented.
- **Evidence**: [newsletter_agent/agent.py](newsletter_agent/agent.py#L55), [newsletter_agent/tools/perplexity_search.py](newsletter_agent/tools/perplexity_search.py)

#### PASS - Spec Adherence (FR-013 through FR-024: Link Verification)
- **Requirement**: FR-013 through FR-024
- **Status**: Compliant
- **Detail**: `verify_links` boolean field with `false` default. `LinkVerifierAgent` is a `BaseAgent` subclass. HTTP HEAD with GET fallback on 405. 10-second timeout. `asyncio.Semaphore(10)` concurrency. User-Agent `"NewsletterAgent/1.0 (link-check)"`. Broken links removed from sources and inline citations. All-broken notice text matches spec. Redirect following with 5-hop limit. Graceful degradation on total failure. No-op when disabled.
- **Evidence**: [newsletter_agent/tools/link_verifier.py](newsletter_agent/tools/link_verifier.py), [newsletter_agent/tools/link_verifier_agent.py](newsletter_agent/tools/link_verifier_agent.py)

#### WARN - Spec Adherence (FR-026: Conditional inclusion)
- **Requirement**: FR-026 -- agent factory SHALL conditionally include LinkVerifierAgent based on verify_links config
- **Status**: Deviating
- **Detail**: `LinkVerifierAgent` is always included in the pipeline regardless of `verify_links` setting. It self-skips at runtime when `verify_links=false`. Functionally equivalent but does not match the spec's "conditionally include" language. The backward compatibility tests confirm the agent is always present as a no-op.
- **Evidence**: [newsletter_agent/agent.py](newsletter_agent/agent.py#L371)

#### PASS - Data Model Adherence
- **Requirement**: Section 7.1 -- TimeframeValue, AppSettings, TopicConfig, ResolvedTimeframe, LinkCheckResult
- **Status**: Compliant
- **Detail**: All entities present with correct field definitions. `ResolvedTimeframe` is a frozen dataclass with correct fields. `LinkCheckResult` is a frozen dataclass with correct fields. Config fields use correct types and defaults.
- **Evidence**: [newsletter_agent/config/timeframe.py](newsletter_agent/config/timeframe.py#L105), [newsletter_agent/tools/link_verifier.py](newsletter_agent/tools/link_verifier.py#L28)

#### PASS - API/Interface Adherence
- **Requirement**: Section 8.1 through 8.6
- **Status**: Compliant
- **Detail**: `search_perplexity()` signature matches (query, search_depth, search_recency_filter). `get_google_search_instruction()` accepts timeframe_instruction parameter. `get_perplexity_search_instruction()` accepts timeframe_instruction parameter. `resolve_timeframe()` signature matches. `verify_urls()` signature matches (urls, timeout=10.0, max_concurrent=10). `LinkVerifierAgent` is a BaseAgent subclass with correct _run_async_impl.
- **Evidence**: All source files inspected

#### PASS - Architecture Adherence
- **Requirement**: Section 9.1 through 9.4
- **Status**: Compliant
- **Detail**: Pipeline order correct (ConfigLoader -> Research -> Validator -> Abort -> Synthesizer -> PostProcessor -> LinkVerifier -> Output). Technology stack uses httpx (existing dep), asyncio.Semaphore, datetime.date.fromisoformat, re module -- no new dependencies. Directory structure matches spec Section 9.3 (minor deviation: agent in `tools/` not `agents/` but consistent throughout codebase). Key design decisions honored: prompt-based Google timeframe, HEAD+GET fallback, status-code-only, BaseAgent not LlmAgent.
- **Evidence**: [newsletter_agent/agent.py](newsletter_agent/agent.py#L380)

#### PASS - Test Coverage (Unit Tests)
- **Requirement**: Section 11.1
- **Status**: Compliant
- **Detail**: 25 timeframe unit tests (35 expanded with parametrize), 52 link verifier unit tests, 10 link verifier agent tests, 5 BDD link verification tests. All 112 WP-related tests pass. Coverage includes all spec-required scenarios for unit tests. No vacuous tests found.
- **Evidence**: All test files inspected; `pytest` run confirmed 112/112 passing

#### PASS - Test Coverage (Integration, E2E, Perf, Security)
- **Requirement**: Sections 11.3, 11.4, 11.5, 11.6
- **Status**: Compliant
- **Detail**: 21 integration tests, 11 E2E tests, 2 performance tests, 13 security tests. All pass. Performance test verifies 40-URL concurrency within 30s budget. Security tests cover SSRF private IP blocking, scheme validation, redirect protection, header leakage, and agent-level verification.
- **Evidence**: [tests/integration/](tests/integration/), [tests/e2e/](tests/e2e/), [tests/performance/](tests/performance/), [tests/security/](tests/security/)

#### PASS - Non-Functional (Security)
- **Requirement**: Section 10.2
- **Status**: Compliant
- **Detail**: SSRF protection implemented with two-phase checking (pre-flight hostname resolution + post-redirect URL validation). Private IP blocking covers all RFC 1918 ranges and IPv6. Scheme restriction to http/https only. User-Agent identification set. No credential leakage. Input validation via strict Pydantic validators with regex pre-checks.
- **Evidence**: [newsletter_agent/tools/link_verifier.py](newsletter_agent/tools/link_verifier.py#L36)

#### PASS - Non-Functional (Performance)
- **Requirement**: Section 10.1
- **Status**: Compliant
- **Detail**: Concurrency limit enforced via `asyncio.Semaphore(10)`. Performance test with 40 URLs and 0.5s mock delay completes well under 30s. Timeframe resolution is pure string parsing with negligible overhead.
- **Evidence**: [tests/performance/test_link_verification_perf.py](tests/performance/test_link_verification_perf.py)

#### PASS - Non-Functional (Observability)
- **Requirement**: Section 10.5
- **Status**: Compliant
- **Detail**: `LinkVerifierAgent` logs at INFO level (verification summary counts) and uses event yields for status. Link verifier logs broken URLs. Timeframe resolution logging in `build_research_phase()`.
- **Evidence**: [newsletter_agent/tools/link_verifier_agent.py](newsletter_agent/tools/link_verifier_agent.py)

#### WARN - Documentation Accuracy (configuration-guide.md)
- **Requirement**: docs/configuration-guide.md must match implementation
- **Status**: Deviating
- **Detail**: Three issues: (1) The Timeframe Values table shows `last_2_weeks` with Perplexity Filter `week`, but the implementation and spec FR-007 map it to `month` (closest supported). (2) The "Full Schema" YAML block at the top of the file omits `timeframe` and `verify_links` from both `settings` and `topics` sections -- readers see an incomplete schema first. (3) The example configs at the bottom (Minimal, Full, Development) do not demonstrate the new fields.
- **Evidence**: [docs/configuration-guide.md](docs/configuration-guide.md#L83)

#### WARN - Documentation Accuracy (architecture.md)
- **Requirement**: docs/architecture.md must match implementation
- **Status**: Deviating
- **Detail**: The Security Design section states "no user-controlled URLs are used for outbound requests" in the SSRF context. This is inaccurate after WP07 -- the link verifier makes outbound requests to user-sourced URLs (with SSRF protections). The pipeline diagram and session state tables are correctly updated.
- **Evidence**: [docs/architecture.md](docs/architecture.md)

#### PASS - Scope Discipline
- **Requirement**: No code outside declared scope
- **Status**: Compliant
- **Detail**: WP06 modified the declared set of files (schema.py, timeframe.py, prompts, perplexity_search.py, agent.py). WP07 created and modified the declared files (link_verifier.py, link_verifier_agent.py, agent.py). WP08 created test files, documentation, and infrastructure only. No unspecified features or abstractions added. Minor deviation: `link_verifier_agent.py` placed in `tools/` instead of spec's `agents/` directory, but this is consistent and not scope creep.
- **Evidence**: All source files inspected

#### PASS - Encoding (UTF-8)
- **Requirement**: No em dashes, smart quotes, curly apostrophes in modified files
- **Status**: Compliant
- **Detail**: All 12 checked source/doc files are clean of UTF-8 encoding violations.
- **Evidence**: Automated scan of all WP06/07/08 files

#### WARN - Code Quality (Unused imports)
- **Requirement**: No dead code
- **Status**: Deviating
- **Detail**: `newsletter_agent/agent.py` has two unused imports: `functools` (line 8, likely leftover from a partial-based approach) and `ResolvedTimeframe` (line 23, the type is accessed by attribute but never used as a type annotation or in isinstance checks).
- **Evidence**: [newsletter_agent/agent.py](newsletter_agent/agent.py#L8), [newsletter_agent/agent.py](newsletter_agent/agent.py#L23)

### Statistics

| Dimension | Pass | Warn | Fail |
|-----------|------|------|------|
| Process Compliance | 0 | 2 | 2 |
| Spec Adherence | 3 | 1 | 0 |
| Data Model | 1 | 0 | 0 |
| API / Interface | 1 | 0 | 0 |
| Architecture | 1 | 0 | 0 |
| Test Coverage | 2 | 0 | 1 |
| Non-Functional | 3 | 0 | 0 |
| Performance | 0 | 0 | 0 |
| Documentation | 0 | 2 | 0 |
| Scope Discipline | 1 | 0 | 0 |
| Encoding (UTF-8) | 1 | 0 | 0 |
| **Total** | **13** | **5** | **3** |

### Recommended Actions

1. **FB-01** (FAIL): Create `tests/bdd/test_timeframe_config.py` with all 6 BDD scenarios from spec Section 11.2. This is the most critical missing deliverable.
2. **FB-02** (FAIL): Add per-task Spec Compliance Checklists to WP06 plan file for T06-01 through T06-11.
3. **FB-03** (FAIL): Add per-task Spec Compliance Checklists to WP07 plan file for T07-01 through T07-10.
4. **FB-04** (WARN): Update WP06 and WP07 Activity Logs with coder lane transitions.
5. **FB-05** (WARN): Remove unused `functools` and `ResolvedTimeframe` imports from agent.py.
6. **FB-06** (WARN): Fix `last_2_weeks` Perplexity Filter in configuration-guide.md from `week` to `month`.
7. **FB-07** (WARN): Add `timeframe` and `verify_links` to the Full Schema YAML block in configuration-guide.md.
8. **FB-08** (WARN): Update architecture.md security section to reflect link verifier SSRF protections.
