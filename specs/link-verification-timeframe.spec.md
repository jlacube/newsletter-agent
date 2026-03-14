# Link Verification & Search Timeframe - Specification

> **Source brief**: User request (inline) - see Version History
> **Feature branch**: `link-verification-timeframe`
> **Status**: Draft
> **Version**: 1.0

---

## 1. Overview

This specification defines two enhancements to the Newsletter Agent system:

1. **Source Link Verification**: An automated post-synthesis pipeline stage that validates all source URLs collected during research are reachable and working (HTTP 2xx). Broken links are silently removed from the newsletter before formatting. Verification is configurable via `verify_links` in settings.

2. **Search Timeframe Filtering**: A new `timeframe` configuration option in `topics.yaml` that constrains research results to a specific date range. Supports relative presets (`last_week`, `last_month`), relative custom (`last_X_days`), and absolute date ranges (`between YYYY-MM-DD and YYYY-MM-DD`). Configurable globally with per-topic override.

Both features extend the existing Newsletter Agent pipeline without breaking backward compatibility. All existing fields and behaviors remain unchanged when the new fields are omitted.

---

## 2. Goals & Success Criteria

- **SC-001**: Zero broken links (HTTP 4xx/5xx, DNS failure, connection timeout) appear in the final newsletter HTML when `verify_links` is enabled.
- **SC-002**: Link verification for a typical newsletter (up to 40 source URLs) completes within 30 seconds using concurrent HTTP HEAD requests.
- **SC-003**: Research results are temporally constrained when a `timeframe` is configured - Perplexity API receives `search_recency_filter` parameter and Google Search agent instructions include explicit date constraints.
- **SC-004**: The system is fully backward compatible - existing `topics.yaml` files without `timeframe` or `verify_links` fields continue to work with no changes.
- **SC-005**: When all source links for a topic section are broken, the section is retained with a notice ("Sources could not be verified for this topic") instead of being silently removed.

---

## 3. Users & Roles

- **Operator**: Same role as the base spec. Configures `verify_links` and `timeframe` settings in `topics.yaml`. No new roles introduced.

---

## 4. Functional Requirements

### 4.1 Search Timeframe Configuration

- **FR-001**: The `settings` section of `topics.yaml` SHALL support an optional `timeframe` field that defines the default search date range for all topics.
- **FR-002**: Each topic entry SHALL support an optional `timeframe` field that overrides the global default for that specific topic.
- **FR-003**: The `timeframe` field SHALL accept the following formats:
  - Relative presets: `"last_week"`, `"last_2_weeks"`, `"last_month"`, `"last_year"`
  - Relative custom: `"last_X_days"` where X is a positive integer 1-365 (e.g., `"last_30_days"`, `"last_7_days"`)
  - Absolute range: `"between YYYY-MM-DD and YYYY-MM-DD"` where start date < end date, and both dates are valid ISO 8601 dates not in the future
- **FR-004**: If no `timeframe` is specified at either level, the system SHALL NOT apply any date filtering (current behavior, searches all time).
- **FR-005**: The Pydantic config validator SHALL reject invalid timeframe values with a descriptive error message specifying the expected formats.

**Implementation Contract - Timeframe Configuration**:
- Input: `settings.timeframe` (optional str), `topics[].timeframe` (optional str)
- Output: Resolved `TimeframeConfig` per topic: `{google_date_restrict: str | None, perplexity_recency_filter: str | None, prompt_date_instruction: str}`
- Error: `ConfigValidationError` with details on invalid format, future dates, or start >= end in absolute ranges

### 4.2 Timeframe Application to Search Providers

- **FR-006**: When a timeframe is configured, the Google Search agent instruction prompt SHALL include an explicit date context clause, e.g., "Focus your search on content published {timeframe description}. Prioritize results from this time period."
- **FR-007**: When a timeframe is configured, the Perplexity Sonar API call SHALL include the `search_recency_filter` parameter in the request body via the OpenAI client `extra_body` mechanism. The mapping SHALL be:
  - `"last_week"` or `"last_7_days"` -> `search_recency_filter: "week"`
  - `"last_month"` or `"last_30_days"` -> `search_recency_filter: "month"`
  - `"last_X_days"` where X <= 1 -> `search_recency_filter: "day"`
  - `"last_X_days"` where 2 <= X <= 7 -> `search_recency_filter: "week"`
  - `"last_X_days"` where 8 <= X <= 31 -> `search_recency_filter: "month"`
  - `"last_X_days"` where X > 31 -> no filter (Perplexity only supports day/week/month)
  - `"last_2_weeks"` -> `search_recency_filter: "month"` (closest supported value)
  - `"last_year"` -> no Perplexity recency filter (unsupported granularity); rely on prompt instruction
  - Absolute ranges -> no Perplexity recency filter; rely on prompt instruction that includes the exact date range
- **FR-008**: For absolute date ranges, both Google Search and Perplexity agents SHALL receive an instruction clause: "Only include results published between {start_date} and {end_date}."
- **FR-009**: For relative timeframes, the prompt instruction SHALL use natural language, e.g., "Focus on results from the last 7 days" or "Focus on results from the past month."
- **FR-010**: The Perplexity `search_perplexity()` function signature SHALL be extended with an optional `search_recency_filter` parameter: `search_perplexity(query: str, search_depth: str = "standard", search_recency_filter: str | None = None) -> dict`.
- **FR-011**: The Google Search agent instruction builder SHALL be extended: `get_google_search_instruction(topic_name: str, query: str, search_depth: str, timeframe_instruction: str | None = None) -> str`.
- **FR-012**: The Perplexity agent instruction builder SHALL be extended: `get_perplexity_instruction(topic_name: str, query: str, search_depth: str, timeframe_instruction: str | None = None) -> str`.

**Implementation Contract - Timeframe Application**:
- Input: Resolved `TimeframeConfig` per topic from FR-005
- Output: Modified agent instructions (str) and Perplexity API `extra_body` parameter
- Error: If Perplexity API rejects `search_recency_filter`, the system SHALL log a warning and retry without the filter (graceful degradation)

### 4.3 Link Verification

- **FR-013**: The `settings` section of `topics.yaml` SHALL support an optional `verify_links` field (boolean, default: `false`).
- **FR-014**: When `verify_links` is `true`, the pipeline SHALL execute a link verification stage after synthesis post-processing and before HTML formatting.
- **FR-015**: The link verification stage SHALL be implemented as a `BaseAgent` subclass named `LinkVerifierAgent` that reads synthesis results from session state, verifies all source URLs, and writes cleaned results back to session state.
- **FR-016**: For each source URL, the verifier SHALL send an HTTP HEAD request with a 10-second timeout. If HEAD is not supported (405 Method Not Allowed), it SHALL fall back to an HTTP GET request with a 10-second timeout and `stream=True` (to avoid downloading full content).
- **FR-017**: A source URL SHALL be considered valid if the HTTP response status code is in the range 200-399 (success or redirect). Status codes 400+ (client error, server error), connection timeouts, DNS resolution failures, and SSL/TLS errors SHALL mark the URL as broken.
- **FR-018**: The verifier SHALL use `httpx.AsyncClient` for concurrent HTTP requests with a concurrency limit of 10 simultaneous requests (via `asyncio.Semaphore`).
- **FR-019**: The verifier SHALL set a `User-Agent` header that identifies the bot: `"NewsletterAgent/1.0 (link-check)"`.
- **FR-020**: Broken links SHALL be removed silently from:
  - The `sources` list in each `synthesis_{topic_index}` state entry
  - Inline markdown citations `[Title](broken_url)` in `body_markdown` - replaced with just the title text (no link)
- **FR-021**: If ALL source links for a topic section are removed by verification, the section SHALL be retained but a notice SHALL be appended to `body_markdown`: "\n\n*Note: Sources for this topic could not be verified and have been omitted.*"
- **FR-022**: The verifier SHALL follow HTTP redirects (up to 5 hops) and verify the final destination URL.
- **FR-023**: The verifier SHALL log at INFO level the count of verified vs. broken links per topic, and at DEBUG level the specific broken URLs with their failure reason (status code, timeout, DNS error).
- **FR-024**: When `verify_links` is `false` (default), the `LinkVerifierAgent` SHALL be a no-op passthrough - it reads state and writes it back unchanged, adding zero latency.

**Implementation Contract - Link Verification**:
- Input: Session state keys `synthesis_{topic_index}` containing `body_markdown` (str) and `sources` (list[dict])
- Output: Updated session state keys `synthesis_{topic_index}` with broken links removed from both `sources` and inline citations in `body_markdown`
- Error: If the entire verification stage fails (e.g., network unavailable), the system SHALL log a warning and proceed to formatting with unverified links (graceful degradation, not pipeline failure)
- Error: Individual URL check failures are expected and handled per FR-017 - they do not propagate

### 4.4 Pipeline Integration

- **FR-025**: The `LinkVerifierAgent` SHALL be inserted into the root `SequentialAgent` pipeline between `SynthesisPostProcessorAgent` and the `OutputPhase` agent.
- **FR-026**: The agent factory (`build_agent()`) SHALL conditionally include `LinkVerifierAgent` based on the `verify_links` config setting.
- **FR-027**: The `timeframe` resolution logic SHALL be executed during config loading (in `ConfigLoaderAgent`) so that resolved timeframe data is available in session state for research agent construction.
- **FR-028**: The session state SHALL include a key `config_timeframes` containing a list of resolved timeframe configs (one per topic, in topic order), or `None` if no timeframes are configured.

**Implementation Contract - Pipeline Integration**:
- Input: `NewsletterConfig` with optional `verify_links` and `timeframe` fields
- Output: Modified pipeline agent tree with conditional `LinkVerifierAgent`; modified research agents with timeframe-aware instructions
- Error: If new config fields are absent, pipeline behaves identically to current behavior (backward compatible)

---

## 5. User Stories

### US-01 - Configure search timeframe globally (Priority: P1) MVP

**As an** Operator, **I want** to set a default search timeframe in my topics.yaml settings, **so that** all research results are focused on a specific time period (e.g., last week's news).

**Why P1**: Core value - a newsletter about "last week's developments" needs temporal filtering to avoid stale results.

**Independent Test**: Set `settings.timeframe: "last_week"` in topics.yaml. Run the pipeline. Verify the Perplexity API call includes `search_recency_filter: "week"` and the Google Search agent instruction includes "Focus your search on content published in the last week."

**Acceptance Scenarios**:
1. **Given** `settings.timeframe: "last_week"`, **When** the pipeline runs, **Then** both search providers receive timeframe-constrained queries and results reflect the past 7 days.
2. **Given** `settings.timeframe: "last_month"`, **When** the pipeline runs, **Then** Perplexity receives `search_recency_filter: "month"` and Google Search instruction mentions "the past month".
3. **Given** no `timeframe` field in settings or topics, **When** the pipeline runs, **Then** search behavior is unchanged from the current implementation (no date filtering).

---

### US-02 - Override timeframe per topic (Priority: P2)

**As an** Operator, **I want** to set a different timeframe for specific topics, **so that** some topics search recent news (last week) while others search a broader range (last year).

**Why P2**: Adds granularity on top of the global default - useful but not essential for MVP.

**Independent Test**: Set global `settings.timeframe: "last_week"` and one topic with `timeframe: "last_year"`. Verify the overridden topic uses the per-topic timeframe while others use the global.

**Acceptance Scenarios**:
1. **Given** global timeframe `"last_week"` and topic A with `timeframe: "last_month"`, **When** the pipeline runs, **Then** topic A uses "last_month" and all other topics use "last_week".
2. **Given** global timeframe `"last_week"` and topic B with `timeframe: "last_30_days"`, **When** the pipeline runs, **Then** topic B's Perplexity call uses `search_recency_filter: "month"` and its prompt says "last 30 days".

---

### US-03 - Use absolute date range for research (Priority: P2)

**As an** Operator, **I want** to specify an exact date range like "between 2025-01-01 and 2025-06-30", **so that** I can generate a newsletter covering a specific historical period.

**Why P2**: Niche use case (retrospective newsletters) but adds flexibility.

**Independent Test**: Set topic timeframe to `"between 2025-01-01 and 2025-06-30"`. Verify both search agents receive explicit date range instructions.

**Acceptance Scenarios**:
1. **Given** topic with `timeframe: "between 2025-01-01 and 2025-06-30"`, **When** the pipeline runs, **Then** agent prompts include "Only include results published between 2025-01-01 and 2025-06-30."
2. **Given** topic with `timeframe: "between 2025-12-01 and 2025-01-01"` (start > end), **When** config is loaded, **Then** validation fails with "Start date must be before end date."
3. **Given** topic with `timeframe: "between 2030-01-01 and 2030-06-30"` (future dates), **When** config is loaded, **Then** validation fails with "Dates must not be in the future."

---

### US-04 - Verify source links automatically (Priority: P1) MVP

**As an** Operator, **I want** all source links in the newsletter to be verified as working before the newsletter is sent, **so that** recipients never encounter broken links.

**Why P1**: Broken links damage newsletter credibility. This is a quality gate.

**Independent Test**: Enable `settings.verify_links: true`. Mock one source URL to return 404. Run the pipeline. Verify the broken link is absent from the final HTML and the working links remain.

**Acceptance Scenarios**:
1. **Given** `verify_links: true` and all source URLs return 200, **When** the pipeline runs, **Then** all sources appear in the final newsletter unchanged.
2. **Given** `verify_links: true` and 2 out of 5 source URLs return 404, **When** the pipeline runs, **Then** only the 3 working sources appear in the newsletter.
3. **Given** `verify_links: true` and a source URL times out after 10 seconds, **When** the pipeline runs, **Then** the timed-out URL is removed from the newsletter.
4. **Given** `verify_links: false` (default), **When** the pipeline runs, **Then** no HTTP verification requests are made and all sources are included as-is.

---

### US-05 - Handle all sources broken for a topic (Priority: P1) MVP

**As an** Operator, **I want** the newsletter to show a notice when all sources for a topic are broken, **so that** I know the topic's research citations could not be verified.

**Why P1**: Edge case of US-04 that must be handled to avoid confusing empty source lists.

**Independent Test**: Enable `verify_links: true`. Mock all source URLs for one topic to return 404. Verify the topic section includes the notice text.

**Acceptance Scenarios**:
1. **Given** `verify_links: true` and all 4 source URLs for "AI Frameworks" return 404, **When** the pipeline runs, **Then** the "AI Frameworks" section body includes "*Note: Sources for this topic could not be verified and have been omitted.*" and its sources list is empty.
2. **Given** `verify_links: true` and only 1 of 4 sources is broken, **When** the pipeline runs, **Then** no notice is shown and 3 sources appear.

---

### US-06 - Validate timeframe configuration (Priority: P1) MVP

**As an** Operator, **I want** the system to reject invalid timeframe values immediately at startup, **so that** I get clear feedback instead of silent misconfiguration.

**Why P1**: Config validation is a quality gate that prevents wasted pipeline runs.

**Independent Test**: Set `settings.timeframe: "last_forever"` (invalid). Verify config validation fails with a descriptive error.

**Acceptance Scenarios**:
1. **Given** `settings.timeframe: "last_forever"`, **When** config is loaded, **Then** validation fails with a message listing valid formats.
2. **Given** `settings.timeframe: "last_0_days"`, **When** config is loaded, **Then** validation fails (X must be 1-365).
3. **Given** `settings.timeframe: "last_500_days"`, **When** config is loaded, **Then** validation fails (X must be 1-365).
4. **Given** `topics[0].timeframe: "between 2025-13-01 and 2025-06-30"`, **When** config is loaded, **Then** validation fails (invalid date).

---

### Edge Cases

- What happens when the network is completely down during link verification? Pipeline proceeds with unverified links (graceful degradation).
- What happens when a URL returns a redirect chain longer than 5 hops? Treated as broken (redirect limit exceeded).
- What happens when `search_recency_filter` is rejected by the Perplexity API? Retried without the filter; warning logged.
- What happens when the same source URL appears in multiple topics? Each topic verifies independently; verification results are not shared across topics.
- What happens when a URL returns 200 but with an empty body or error page? Treated as valid (status-code-based verification only; content analysis is out of scope).

---

## 6. User Flows

### 6.1 Timeframe Configuration Flow

1. Operator edits `config/topics.yaml` and adds `timeframe` field to `settings` and/or individual topics.
2. System loads config at pipeline start via `ConfigLoaderAgent`.
3. Config validator parses `timeframe` field and resolves it into a `TimeframeConfig` dataclass per topic.
4. For each topic, resolver merges: topic-level timeframe (if present) overrides global timeframe; absence of both means no date filtering.
5. Resolved timeframes are stored in session state as `config_timeframes` (list, one entry per topic).
6. During research agent construction, timeframe data is read from state and injected into:
   - Google Search agent instruction (natural language date clause)
   - Perplexity tool call parameters (`search_recency_filter` via `extra_body`)
7. Research agents execute with date-constrained queries.
8. **Error path**: If timeframe format is invalid, config validation fails at step 3 with descriptive error. Pipeline does not start.

### 6.2 Link Verification Flow

1. Pipeline reaches `LinkVerifierAgent` (after `SynthesisPostProcessorAgent`, before `OutputPhase`).
2. Agent reads `config_verify_links` from session state. If `false`, exits immediately (no-op).
3. Agent collects all unique source URLs from `synthesis_{topic_index}` entries in session state.
4. Agent creates an `httpx.AsyncClient` with 10-second timeout and redirect following (max 5).
5. Agent verifies all URLs concurrently (up to 10 at a time via `asyncio.Semaphore`).
6. For each URL, sends HTTP HEAD. If 405, falls back to GET with `stream=True`.
7. URLs with status 200-399 are marked valid. All others are marked broken.
8. For each topic's synthesis result:
   a. Remove broken URLs from the `sources` list.
   b. In `body_markdown`, replace `[Title](broken_url)` with just `Title` (unlinked text).
   c. If all sources are removed, append the notice to `body_markdown`.
9. Updated synthesis results are written back to session state.
10. Logs: INFO-level summary ("Verified 35/40 links, removed 5 broken"), DEBUG-level per-broken-URL detail.
11. Pipeline continues to `OutputPhase` with cleaned data.
12. **Error path**: If `httpx.AsyncClient` cannot be created (e.g., event loop issue), log warning and skip verification. Pipeline proceeds with unverified links.

---

## 7. Data Model

### 7.1 New/Modified Pydantic Models

#### TimeframeValue (New - Annotated str type)

Custom Pydantic type with a validator. Accepts:
- `None` (field omitted)
- `"last_week"` | `"last_2_weeks"` | `"last_month"` | `"last_year"` (named presets)
- `"last_X_days"` where X is an integer 1-365
- `"between YYYY-MM-DD and YYYY-MM-DD"` where start < end, dates not in future

| Field | Type | Constraints |
|-------|------|-------------|
| (value) | `str` | Must match one of the accepted patterns above |

Validation rules:
- Named presets: exact match against allowed set
- `last_X_days`: regex `^last_(\d+)_days$`, X in range [1, 365]
- `between` range: regex `^between (\d{4}-\d{2}-\d{2}) and (\d{4}-\d{2}-\d{2})$`, both dates parseable as ISO 8601, start < end, end <= today

#### AppSettings (Modified)

Add two optional fields:

| Field | Type | Default | Constraints |
|-------|------|---------|-------------|
| `timeframe` | `TimeframeValue \| None` | `None` | See TimeframeValue validation |
| `verify_links` | `bool` | `false` | - |

#### TopicConfig (Modified)

Add one optional field:

| Field | Type | Default | Constraints |
|-------|------|---------|-------------|
| `timeframe` | `TimeframeValue \| None` | `None` | See TimeframeValue validation; overrides `settings.timeframe` when present |

#### ResolvedTimeframe (New - Internal dataclass, not in YAML)

Computed during config loading for each topic:

| Field | Type | Description |
|-------|------|-------------|
| `perplexity_recency_filter` | `str \| None` | One of: `"day"`, `"week"`, `"month"`, or `None` |
| `prompt_date_instruction` | `str \| None` | Natural language clause for agent prompts, e.g., "Focus on results from the last 7 days" |
| `original_value` | `str \| None` | Raw timeframe string from config for logging/debugging |

#### LinkCheckResult (New - Internal dataclass, not in YAML)

| Field | Type | Description |
|-------|------|-------------|
| `url` | `str` | The URL that was checked |
| `status` | `str` | One of: `"valid"`, `"broken"` |
| `http_status` | `int \| None` | HTTP status code if a response was received |
| `error` | `str \| None` | Error description if check failed (e.g., "timeout", "dns_error", "ssl_error", "redirect_limit") |

### 7.2 Session State Changes

New keys added to session state:

| Key | Type | Set By | Read By |
|-----|------|--------|---------|
| `config_verify_links` | `bool` | `ConfigLoaderAgent` | `LinkVerifierAgent` |
| `config_timeframes` | `list[dict] \| None` | `ConfigLoaderAgent` | `build_research_phase()` |

---

## 8. API / Interface Design

### 8.1 Modified Function: `search_perplexity()`

```
search_perplexity(
    query: str,
    search_depth: str = "standard",
    search_recency_filter: str | None = None
) -> dict[str, Any]
```

- **New parameter**: `search_recency_filter` - optional string, one of `"day"`, `"week"`, `"month"`, or `None`
- **Behavior**: When not `None`, passes `{"search_recency_filter": value}` via `extra_body` to the OpenAI client `chat.completions.create()` call
- **Error**: If Perplexity rejects the parameter, catch the `APIError`, log a warning, and retry the call without `search_recency_filter`
- **Return**: Unchanged - `{text: str, sources: list[dict], provider: "perplexity"}`

### 8.2 Modified Function: `get_google_search_instruction()`

```
get_google_search_instruction(
    topic_name: str,
    query: str,
    search_depth: str,
    timeframe_instruction: str | None = None
) -> str
```

- **New parameter**: `timeframe_instruction` - optional natural language string inserted into the agent prompt
- **Behavior**: When not `None`, appends the instruction as an additional numbered step in the prompt, e.g., "5. Focus your search on content published in the last 7 days."
- **Return**: Instruction string with date context (or without, if `None`)

### 8.3 Modified Function: `get_perplexity_instruction()`

```
get_perplexity_instruction(
    topic_name: str,
    query: str,
    search_depth: str,
    timeframe_instruction: str | None = None
) -> str
```

- Same behavior as 8.2 for prompt augmentation

### 8.4 New Function: `resolve_timeframe()`

```
resolve_timeframe(
    timeframe_value: str | None
) -> ResolvedTimeframe
```

- **Purpose**: Converts a raw timeframe string into provider-specific parameters
- **Input**: Raw timeframe string from config (or `None`)
- **Output**: `ResolvedTimeframe` dataclass
- **Error**: Should not raise - input is pre-validated by Pydantic

### 8.5 New Function: `verify_urls()`

```
async verify_urls(
    urls: list[str],
    timeout: float = 10.0,
    max_concurrent: int = 10
) -> dict[str, LinkCheckResult]
```

- **Purpose**: Concurrently verify a list of URLs via HTTP HEAD (fallback to GET)
- **Input**: List of URL strings, timeout per request, concurrency limit
- **Output**: Dict mapping each URL to its `LinkCheckResult`
- **Error**: Never raises - individual URL failures are captured in `LinkCheckResult.error`

### 8.6 New Agent: `LinkVerifierAgent`

```
class LinkVerifierAgent(BaseAgent):
    """Post-synthesis agent that verifies source URLs and removes broken links."""
```

- **run_async_impl()**: Reads synthesis state, calls `verify_urls()`, cleans results, writes back
- **Session state read**: `config_verify_links`, `config_topic_count`, `synthesis_{i}` for each topic
- **Session state write**: Updated `synthesis_{i}` entries with broken links removed
- **No-op when**: `config_verify_links` is `False`

---

## 9. Architecture

### 9.1 System Design

The two features integrate into the existing pipeline as follows:

**Timeframe** affects the early pipeline stages:
- `ConfigLoaderAgent` resolves timeframes during config loading
- `build_research_phase()` reads resolved timeframes and passes them to agent instruction builders and Perplexity tool parameters

**Link Verification** adds a new pipeline stage:

```
ConfigLoader -> ResearchPhase -> ResearchValidator -> PipelineAbortCheck
  -> Synthesizer -> SynthesisPostProcessor -> [LinkVerifier] -> OutputPhase
```

The `LinkVerifierAgent` is conditionally included based on `verify_links` config.

### 9.2 Technology Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| HTTP Client (link verification) | `httpx` (already a dependency) | Async support, timeout control, redirect following, already in requirements.txt |
| Concurrency (link verification) | `asyncio.Semaphore` | Standard library, lightweight, no new dependency |
| Date parsing (timeframe) | `datetime.date.fromisoformat()` | Standard library, Python 3.7+, no new dependency |
| Regex (timeframe parsing) | `re` module | Standard library |

No new dependencies are required. `httpx` is already in `requirements.txt` for E2E tests.

### 9.3 Directory & Module Structure

New and modified files:

```
newsletter_agent/
  config/
    schema.py              # Modified: add timeframe/verify_links fields, TimeframeValue validator
    timeframe.py           # New: resolve_timeframe() function and ResolvedTimeframe dataclass
  tools/
    link_verifier.py       # New: verify_urls() function and LinkCheckResult dataclass
    perplexity_search.py   # Modified: add search_recency_filter parameter
  agents/
    link_verifier_agent.py # New: LinkVerifierAgent BaseAgent subclass
  prompts/
    research_google.py     # Modified: accept timeframe_instruction parameter
    research_perplexity.py # Modified: accept timeframe_instruction parameter
  agent.py                 # Modified: wire timeframe into research, conditionally add LinkVerifierAgent
tests/
  unit/
    test_timeframe.py      # New: unit tests for timeframe parsing and resolution
    test_link_verifier.py  # New: unit tests for URL verification
    test_link_verifier_agent.py  # New: unit tests for LinkVerifierAgent
    test_schema.py         # Modified: add timeframe validation tests
    test_perplexity_search.py  # Modified: add search_recency_filter tests
  bdd/
    test_timeframe_config.py  # New: BDD tests for timeframe configuration
    test_link_verification.py # New: BDD tests for link verification pipeline
```

### 9.4 Key Design Decisions

**Decision 1: Prompt-based timeframe for Google Search (no API parameter)**
- **Rationale**: ADK's built-in `google_search` tool uses Gemini's internal grounding tool (`types.GoogleSearch()`), which does not expose `dateRestrict` or any date filtering parameter. The only mechanism available is prompt engineering.
- **Alternatives considered**: (a) Replace ADK google_search with Custom Search JSON API - rejected because it would require a Programmable Search Engine ID, breaks the ADK pattern, and adds API key management complexity. (b) Append date operator to query string (e.g., `"after:2025-03-01"`) - may work for some queries but is unreliable and not documented for Gemini grounding.
- **Consequences**: Google Search timeframe filtering is best-effort via prompt instruction. Perplexity's `search_recency_filter` provides the reliable date constraint.

**Decision 2: HTTP HEAD with GET fallback for link verification**
- **Rationale**: HEAD is faster (no body download) and sufficient for checking link liveness. Some servers block HEAD requests (405), so GET fallback with `stream=True` avoids downloading full content while still getting a status code.
- **Alternatives considered**: (a) GET only - slower, downloads unnecessary content. (b) HEAD only - would miss servers that block HEAD. (c) DNS-only check - too weak, doesn't catch 404s.
- **Consequences**: Two HTTP requests in worst case (HEAD then GET) for servers that block HEAD. Acceptable given the 10-second timeout per request.

**Decision 3: Status-code-only verification (no content analysis)**
- **Rationale**: Determining if a 200-response page is a "soft 404" (error page returning 200) requires content analysis, which is complex, slow, and error-prone. Status-code verification catches the vast majority of broken links.
- **Alternatives considered**: Content-based detection (check for "404", "not found" in response body) - rejected due to false positives and complexity.
- **Consequences**: Some "soft 404" pages will pass verification. Acceptable trade-off for simplicity.

**Decision 4: LinkVerifierAgent as BaseAgent (not LlmAgent)**
- **Rationale**: Link verification is deterministic HTTP checking - no LLM needed. Using BaseAgent avoids unnecessary Gemini API calls and keeps costs down.
- **Alternatives considered**: LlmAgent that decides which links to keep - rejected because verification is mechanical, not judgmental.
- **Consequences**: No API cost for link verification stage.

### 9.5 External Integrations

**Perplexity API (Modified)**
- Purpose: Research with date filtering
- Authentication: API key (unchanged)
- Key operations: `chat.completions.create()` with `extra_body={"search_recency_filter": "week"}`
- Failure handling: If `search_recency_filter` is rejected, retry without it and log warning

**Target URLs (New - link verification)**
- Purpose: Verify source URL liveness
- Authentication: None (public URLs)
- Key operations: HTTP HEAD / GET requests
- Failure handling: Per-URL timeout (10s), concurrency limit (10), individual failures are captured not propagated

---

## 10. Non-Functional Requirements

### 10.1 Performance

- Link verification for up to 40 URLs SHALL complete within 30 seconds (10 concurrent with 10s timeout).
- Timeframe resolution adds negligible overhead (string parsing only).
- Total pipeline time increase with link verification enabled: maximum 30 seconds over the base pipeline time.

### 10.2 Security

- **HTTP requests (link verification)**: The verifier SHALL NOT follow redirects to non-HTTP(S) schemes (e.g., `javascript:`, `file:`, `ftp:`). Only `http://` and `https://` final URLs are accepted. This prevents SSRF via redirect chains.
- **SSRF mitigation**: The verifier SHALL NOT make requests to private/internal IP ranges (127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, ::1, fc00::/7). URLs resolving to these ranges SHALL be treated as broken.
- **User-Agent identification**: All verification requests include `User-Agent: NewsletterAgent/1.0 (link-check)` to allow target servers to identify and rate-limit the bot.
- **No credential leakage**: The verifier SHALL NOT send cookies, auth headers, or cached credentials to target URLs.
- **Input validation**: Timeframe dates are validated against injection (strict ISO 8601 format, no embedded commands or special characters).

### 10.3 Scalability & Availability

- Concurrency limit (10) prevents overwhelming target servers or exhausting local file descriptors.
- Timeframe feature has no scalability impact (static config parsing).

### 10.4 Accessibility

No UI changes. Newsletter HTML output format is unchanged.

### 10.5 Observability

- **Link verification logging**:
  - INFO: `"Link verification: {valid_count}/{total_count} URLs verified, {broken_count} removed"`
  - INFO: `"Link verification skipped (verify_links=false)"`
  - DEBUG: `"Broken link removed: {url} - reason: {error}"`
  - WARNING: `"Link verification failed entirely, proceeding with unverified links: {error}"`
- **Timeframe logging**:
  - INFO: `"Timeframe resolved for topic '{name}': {original_value} -> perplexity_filter={filter}, prompt='{instruction}'"`
  - INFO: `"No timeframe configured (searching all time)"`

---

## 11. Test Requirements

### 11.1 Unit Tests

**Timeframe parsing and resolution** (`test_timeframe.py`):
- Parse each valid preset: `last_week`, `last_2_weeks`, `last_month`, `last_year`
- Parse `last_X_days` for X = 1, 7, 30, 90, 365
- Parse absolute range with valid dates
- Reject invalid formats: `last_forever`, `last_0_days`, `last_500_days`, `between 2025-13-01 and 2025-06-30`, `between 2025-06-30 and 2025-01-01` (inverted), future dates
- Verify `resolve_timeframe()` returns correct `perplexity_recency_filter` for each mapping
- Verify `resolve_timeframe()` returns correct `prompt_date_instruction` text
- Verify `resolve_timeframe(None)` returns all-None fields

**Link verification** (`test_link_verifier.py`):
- URL returning 200 -> valid
- URL returning 301 -> valid (redirect followed)
- URL returning 404 -> broken
- URL returning 500 -> broken
- URL timeout -> broken with error "timeout"
- URL DNS failure -> broken with error "dns_error"
- URL SSL error -> broken with error "ssl_error"
- HEAD returns 405, GET returns 200 -> valid (fallback)
- Redirect chain > 5 hops -> broken
- Private IP URL -> broken (SSRF protection)
- Concurrency: 20 URLs with limit 10 -> max 10 concurrent
- Empty URL list -> empty result dict

**LinkVerifierAgent** (`test_link_verifier_agent.py`):
- `verify_links=false` -> no HTTP requests made, state unchanged
- `verify_links=true`, all links valid -> state unchanged
- `verify_links=true`, 2 broken links -> removed from sources and body_markdown
- `verify_links=true`, all links broken for a topic -> notice appended
- Inline citation `[Title](broken_url)` replaced with `Title`
- Verification failure (network down) -> state unchanged, warning logged

**Schema validation** (`test_schema.py` - additions):
- `AppSettings` with valid `timeframe` values accepted
- `AppSettings` with invalid `timeframe` values rejected
- `AppSettings` with `verify_links: true/false` accepted
- `TopicConfig` with valid `timeframe` override accepted
- `TopicConfig` with invalid `timeframe` rejected
- Backward compatibility: config without new fields validates successfully

**Perplexity search** (`test_perplexity_search.py` - additions):
- `search_recency_filter="week"` passes in `extra_body`
- `search_recency_filter=None` -> no `extra_body` added
- Perplexity rejects `search_recency_filter` -> retries without it

Minimum unit test coverage for new code: 95%

### 11.2 BDD / Acceptance Tests

```gherkin
Feature: Search Timeframe Configuration

  Scenario: Global timeframe filters all topics
    Given a topics.yaml with settings.timeframe set to "last_week"
    And 3 topics with no individual timeframe
    When the config is loaded
    Then all 3 topics resolve to perplexity_recency_filter "week"
    And all 3 topics have prompt instruction containing "last week"

  Scenario: Per-topic timeframe overrides global
    Given a topics.yaml with settings.timeframe set to "last_week"
    And topic "AI" has timeframe "last_month"
    When the config is loaded
    Then topic "AI" resolves to perplexity_recency_filter "month"
    And other topics resolve to perplexity_recency_filter "week"

  Scenario: Custom days timeframe
    Given a topics.yaml with topic timeframe "last_30_days"
    When the config is loaded
    Then the topic resolves to perplexity_recency_filter "month"
    And prompt instruction contains "last 30 days"

  Scenario: Absolute date range timeframe
    Given a topics.yaml with topic timeframe "between 2025-01-01 and 2025-06-30"
    When the config is loaded
    Then the topic resolves to perplexity_recency_filter None
    And prompt instruction contains "between 2025-01-01 and 2025-06-30"

  Scenario: Invalid timeframe rejected at config load
    Given a topics.yaml with settings.timeframe set to "last_forever"
    When the config is loaded
    Then a ConfigValidationError is raised
    And the error message lists valid timeframe formats

  Scenario: No timeframe configured
    Given a topics.yaml with no timeframe fields
    When the config is loaded
    Then all topics resolve to perplexity_recency_filter None
    And no date instructions are added to prompts
```

```gherkin
Feature: Source Link Verification

  Scenario: All links valid
    Given verify_links is true
    And synthesis results contain 5 source URLs all returning 200
    When the LinkVerifierAgent runs
    Then all 5 sources remain in the synthesis results
    And body_markdown inline citations are unchanged

  Scenario: Some links broken
    Given verify_links is true
    And synthesis results contain 5 source URLs
    And 2 URLs return 404
    When the LinkVerifierAgent runs
    Then only 3 sources remain in the synthesis results
    And broken URL inline citations are replaced with unlinked text

  Scenario: All links broken for a topic
    Given verify_links is true
    And topic "AI" has 3 source URLs all returning 404
    When the LinkVerifierAgent runs
    Then topic "AI" sources list is empty
    And topic "AI" body_markdown contains the verification notice

  Scenario: Link verification disabled
    Given verify_links is false
    When the LinkVerifierAgent runs
    Then no HTTP requests are made
    And synthesis results are unchanged

  Scenario: Link verification network failure
    Given verify_links is true
    And the HTTP client cannot connect to any server
    When the LinkVerifierAgent runs
    Then synthesis results are unchanged
    And a warning is logged
```

### 11.3 Integration Tests

- **Config + Research integration**: Load a config with `timeframe: "last_week"`, verify that the research agent instructions generated by `build_research_phase()` include the date clause.
- **Config + Perplexity integration**: Mock the Perplexity API endpoint, verify that `search_recency_filter` is present in the request body when timeframe is set.
- **Synthesis + LinkVerifier integration**: Generate synthesis state with mock data, run `LinkVerifierAgent` against a mock HTTP server, verify the cleaned state is passed to the formatter correctly.
- External dependencies to mock: All HTTP servers (Perplexity API, target URLs)
- Data setup: Pytest fixtures providing pre-populated session state

### 11.4 End-to-End Tests

- **E2E with timeframe**: Full pipeline dry-run with `timeframe: "last_week"` and `verify_links: true`. Verify the output HTML contains no broken link markup and topics reference recent content.
- **E2E backward compatibility**: Full pipeline dry-run with an existing `topics.yaml` (no new fields). Verify output is identical to current behavior.
- Target environment: Local (dry-run mode)

### 11.5 Performance Tests

- **Link verification throughput**: Verify 40 URLs checked within 30 seconds using mock HTTP server with artificial 2-second delay per response.
- **Concurrency enforcement**: Verify no more than 10 simultaneous connections using a connection counter in the mock server.

### 11.6 Security Tests

- **SSRF prevention**: Attempt to verify a URL that redirects to `http://127.0.0.1/admin` - must be marked broken.
- **Private IP blocking**: Verify URLs resolving to 10.0.0.1, 172.16.0.1, 192.168.1.1, ::1 are rejected.
- **Scheme restriction**: Verify redirects to `file:///etc/passwd` or `javascript:alert(1)` are rejected.
- **No credential leakage**: Verify outgoing verification requests contain no `Authorization` or `Cookie` headers.

---

## 12. Constraints & Assumptions

### Constraints

- **ADK google_search tool**: Does not expose date filtering API parameters. Timeframe for Google Search is prompt-engineered only (best-effort, not guaranteed).
- **Perplexity search_recency_filter**: Only supports `"day"`, `"week"`, `"month"` granularity. Finer or coarser granularity (hours, years) is not available via API.
- **Perplexity absolute date ranges**: Not supported by the API. Absolute ranges for Perplexity rely on prompt instructions only.
- **Link verification is status-code based**: "Soft 404" pages (200 status with error content) will pass verification.
- **No new Python dependencies**: Both features use only existing dependencies (`httpx`, `re`, `datetime`).

### Assumptions

- The Perplexity Sonar API (OpenAI-compatible chat completions endpoint) continues to support the `search_recency_filter` parameter via `extra_body`. If Perplexity deprecates or changes this, the graceful degradation (retry without filter) ensures the pipeline continues.
- Target servers for link verification respond to HTTP HEAD or GET within 10 seconds for valid URLs.
- The existing `httpx` version in requirements.txt supports async operations and `stream=True`.

---

## 13. Out of Scope

- **Content-based broken link detection**: Detecting "soft 404" pages that return HTTP 200 but display error content. Out of scope for v1 - pure status-code-based verification only.
- **Link caching/persistence**: No caching of verification results between pipeline runs. Each run verifies all links fresh.
- **Google Custom Search API integration**: Replacing ADK's built-in google_search with the Custom Search JSON API (which supports `dateRestrict`) is not in scope. Would require Programmable Search Engine setup and API key management.
- **Wayback Machine fallback**: Replacing broken links with archived versions is not in this version.
- **Per-topic verify_links toggle**: Verification is all-or-nothing at the settings level. Per-topic control is not supported.
- **Rate limiting for verification**: No built-in rate limiting beyond the concurrency cap. Target servers that rate-limit will cause verification failures (treated as broken) for affected URLs.

---

## 14. Open Questions

| # | Question | Impact if Unresolved | Owner |
|---|----------|---------------------|-------|
| 1 | Does the current Perplexity API version still support `search_recency_filter` via `extra_body`? Their docs restructured recently. | Graceful degradation handles this - feature works via prompt instructions only if API parameter is rejected. Low risk. | Operator (test during implementation) |
| 2 | Should the link verifier respect `robots.txt`? | Some sites block crawlers via robots.txt. Not checking could cause the bot to be blocked. However, HEAD requests for link checking are generally considered acceptable. Low risk for v1. | Deferred to v2 if needed |

---

## 15. Glossary

- **Timeframe**: A date range constraint applied to search queries to limit results to a specific time period.
- **search_recency_filter**: A Perplexity API parameter that filters search results by recency. Accepts `"day"`, `"week"`, or `"month"`.
- **dateRestrict**: A Google Custom Search JSON API parameter for date filtering (not available in ADK's built-in google_search tool).
- **Soft 404**: A web page that returns HTTP 200 status but displays error/not-found content. Not detected by status-code-based verification.
- **SSRF**: Server-Side Request Forgery - an attack where a server is tricked into making requests to internal/private resources.
- **LinkVerifierAgent**: The new BaseAgent subclass that performs post-synthesis link verification.
- **ResolvedTimeframe**: Internal dataclass containing provider-specific timeframe parameters derived from the user's timeframe config string.

---

## 16. Traceability Matrix

| FR ID | Requirement Summary | User Story | Acceptance Scenario | Test Type | Test Section Ref |
|-------|-------------------|------------|--------------------|-----------|--------------------|
| FR-001 | Global timeframe in settings | US-01 | US-01 Sc.1, Sc.3 | unit, BDD | 11.1, 11.2 |
| FR-002 | Per-topic timeframe override | US-02 | US-02 Sc.1, Sc.2 | unit, BDD | 11.1, 11.2 |
| FR-003 | Timeframe format validation (presets, custom, absolute) | US-01, US-03, US-06 | US-03 Sc.1, US-06 Sc.1-4 | unit, BDD | 11.1, 11.2 |
| FR-004 | No timeframe = no filtering | US-01 | US-01 Sc.3 | unit, BDD | 11.1, 11.2 |
| FR-005 | Pydantic validation rejects invalid timeframes | US-06 | US-06 Sc.1-4 | unit, BDD | 11.1, 11.2 |
| FR-006 | Google Search prompt includes date clause | US-01 | US-01 Sc.1, Sc.2 | unit, integration | 11.1, 11.3 |
| FR-007 | Perplexity search_recency_filter mapping | US-01, US-02 | US-01 Sc.1, Sc.2 | unit, integration | 11.1, 11.3 |
| FR-008 | Absolute range prompt instruction | US-03 | US-03 Sc.1 | unit, BDD | 11.1, 11.2 |
| FR-009 | Relative timeframe prompt instruction | US-01, US-02 | US-01 Sc.1, US-02 Sc.2 | unit | 11.1 |
| FR-010 | search_perplexity() extended signature | US-01 | US-01 Sc.1 | unit | 11.1 |
| FR-011 | Google instruction builder extended | US-01 | US-01 Sc.1 | unit | 11.1 |
| FR-012 | Perplexity instruction builder extended | US-01 | US-01 Sc.1 | unit | 11.1 |
| FR-013 | verify_links config field | US-04 | US-04 Sc.4 | unit | 11.1 |
| FR-014 | LinkVerifier stage placement in pipeline | US-04 | US-04 Sc.1-3 | integration | 11.3 |
| FR-015 | LinkVerifierAgent as BaseAgent | US-04 | US-04 Sc.1-3 | unit | 11.1 |
| FR-016 | HEAD with GET fallback | US-04 | US-04 Sc.1 | unit | 11.1 |
| FR-017 | 200-399 valid, 400+ broken | US-04 | US-04 Sc.1, Sc.2, Sc.3 | unit | 11.1 |
| FR-018 | Concurrent verification (max 10) | US-04 | US-04 Sc.1 | unit, performance | 11.1, 11.5 |
| FR-019 | User-Agent header | US-04 | (implicit) | security | 11.6 |
| FR-020 | Silent removal of broken links | US-04 | US-04 Sc.2 | unit, BDD | 11.1, 11.2 |
| FR-021 | All-broken notice | US-05 | US-05 Sc.1, Sc.2 | unit, BDD | 11.1, 11.2 |
| FR-022 | Redirect following (max 5) | US-04 | (implicit) | unit | 11.1 |
| FR-023 | Verification logging | US-04 | (implicit) | unit | 11.1 |
| FR-024 | No-op when disabled | US-04 | US-04 Sc.4 | unit, BDD | 11.1, 11.2 |
| FR-025 | Pipeline stage placement | US-04 | US-04 Sc.1 | integration | 11.3 |
| FR-026 | Conditional inclusion in agent factory | US-04 | US-04 Sc.4 | unit | 11.1 |
| FR-027 | Timeframe resolved during config loading | US-01 | US-01 Sc.1 | integration | 11.3 |
| FR-028 | config_timeframes session state key | US-01, US-02 | US-01 Sc.1, US-02 Sc.1 | unit, integration | 11.1, 11.3 |

**Validation**: Every FR maps to at least one US. Every US maps to at least one acceptance scenario. Every acceptance scenario maps to at least one test type. Matrix is complete.

---

## 17. Technical References

### Architecture & Patterns
- Google ADK documentation - Agent pipeline patterns, SequentialAgent, BaseAgent subclassing
- Existing Newsletter Agent spec (specs/newsletter-agent.spec.md) - base architecture and pipeline design

### Technology Stack
- httpx documentation - async client, timeout configuration, redirect handling, stream mode
- Python asyncio - Semaphore for concurrency limiting
- Pydantic v2 - field validators, custom types, model validators

### Security
- OWASP SSRF Prevention Cheat Sheet - private IP range blocking, scheme validation
- CWE-918: Server-Side Request Forgery - mitigated via IP range and scheme checks

### Standards & Specifications
- Google Custom Search JSON API reference - `dateRestrict` parameter format: `d[number]`, `w[number]`, `m[number]`, `y[number]`
- Perplexity Sonar API - `search_recency_filter` parameter values: `"day"`, `"week"`, `"month"` (via OpenAI-compatible chat completions endpoint `extra_body`)
- ISO 8601 date format - used for absolute date range parsing
- RFC 9110 HTTP Semantics - HEAD method behavior, status code semantics

---

## 18. Version History

| Version | Date | Author | Summary of Changes |
|---------|------|--------|--------------------|
| 1.0 | 2026-03-14 | Spec Architect | Initial specification for link verification and search timeframe features |
