# Grounding Metadata Extraction -- Specification

> **Source brief**: Addendum to `specs/002-adaptive-deep-research.spec.md`
> **Feature branch**: `004-grounding-metadata-extraction`
> **Status**: Draft
> **Version**: 1.0

---

## 1. Overview

The newsletter agent's Google search pipeline currently relies on regex-parsing the LLM's text output to extract source URLs and titles - a fundamentally fragile approach because the model formats grounding citations inconsistently across rounds, topics, and model versions. The Gemini API already returns structured `groundingMetadata` on every grounded response, including typed `groundingChunks` (URI + title pairs) and `groundingSupports` (text-segment-to-source mappings). This specification defines how to intercept, persist, and use that structured metadata as the authoritative source of truth for Google search results, eliminating dependence on LLM text formatting for source preservation.

---

## 2. Goals & Success Criteria

- **SC-001**: 100% of Google search grounding sources are captured from structured API metadata, not from LLM text parsing.
- **SC-002**: Zero synthetic/placeholder Google URLs (e.g. `google.com/search?q=`) appear in final newsletter HTML.
- **SC-003**: Source count per topic increases by at least 20% compared to current regex-only extraction (measured across a 5-run average with identical config).
- **SC-004**: Perplexity provider continues to work unchanged via existing text-based extraction (no regression).
- **SC-005**: End-to-end pipeline latency does not increase by more than 5% (metadata extraction is in-memory, no additional network calls).

---

## 3. Users & Roles

- **Pipeline Operator**: Runs the newsletter agent. Benefits from more reliable source attribution and fewer empty sections. No configuration changes required - this is a transparent improvement.
- **Developer**: Maintains the codebase. Needs clear separation between metadata-based extraction (Google) and text-based extraction (Perplexity) paths.

---

## 4. Functional Requirements

### 4.1 Grounding Metadata Capture

- **FR-GME-001**: The system SHALL capture `groundingMetadata` from every Google search round's `LlmResponse` by registering an `after_model_callback` on the search `LlmAgent` that extracts and persists the metadata to session state before the round completes.
- **FR-GME-002**: The system SHALL extract `groundingChunks` from the captured metadata, producing a list of `{uri: str, title: str}` pairs per round.
- **FR-GME-003**: The system SHALL extract `groundingSupports` from the captured metadata, producing a list of `{segment_text: str, start_index: int, end_index: int, chunk_indices: list[int]}` per round.
- **FR-GME-004**: The system SHALL extract `webSearchQueries` from the captured metadata, producing a list of query strings per round.
- **FR-GME-005**: If `groundingMetadata` is absent or empty for a Google search round (model decided no search was needed, or API version difference), the system SHALL fall back to the existing regex-based URL extraction from the LLM text output for that round. This fallback SHALL be logged at WARNING level.
- **FR-GME-006**: The system SHALL NOT modify how Perplexity provider results are processed. Text-based extraction remains the sole mechanism for Perplexity.

### 4.2 Grounding Metadata Persistence

- **FR-GME-010**: The system SHALL persist extracted grounding sources per round in session state under key `grounding_sources_{idx}_{provider}_round_{round_idx}` as a JSON-serializable list of `{"uri": str, "title": str}` dicts.
- **FR-GME-011**: The system SHALL persist extracted grounding supports per round in session state under key `grounding_supports_{idx}_{provider}_round_{round_idx}` as a JSON-serializable list of `{"segment_text": str, "start_index": int, "end_index": int, "chunk_indices": list[int]}` dicts.
- **FR-GME-012**: The system SHALL persist extracted web search queries per round in session state under key `grounding_queries_{idx}_{provider}_round_{round_idx}` as a JSON-serializable list of strings.
- **FR-GME-013**: Intermediate state keys from FR-GME-010 through FR-GME-012 SHALL be cleaned up during the existing `_cleanup_state` method, following the same lifecycle as other round-specific keys.

### 4.3 Source Merging (Authoritative Path)

- **FR-GME-020**: When merging round results for Google provider, the system SHALL use grounding chunks (from FR-GME-010 state) as the authoritative source list, NOT regex-extracted URLs from LLM text.
- **FR-GME-021**: The merged SOURCES section SHALL be built by iterating grounding chunks across all rounds, deduplicating by URI (first occurrence wins for title), and formatting as `- [title](uri)` markdown links.
- **FR-GME-022**: If grounding chunks are empty for all rounds (complete fallback scenario), the system SHALL fall back to the existing `_merge_rounds` text-based logic for that topic. This SHALL be logged at WARNING level with the message: "No grounding metadata available for topic {name}/google, falling back to text extraction".
- **FR-GME-023**: The system SHALL resolve Google grounding redirect URIs (`vertexaisearch.cloud.google.com/grounding-api-redirect/...`) by preserving them as-is (matching existing link verifier behavior in FR-LV-003). These URIs are valid and resolve to the actual article when clicked.

### 4.4 URL Tracking Integration

- **FR-GME-030**: The `accumulated_urls` set used for saturation detection SHALL be populated from grounding chunk URIs (for Google provider) rather than from regex extraction of LLM text.
- **FR-GME-031**: The `deep_urls_accumulated_{idx}_{provider}` state key SHALL include all URIs from grounding chunks across all rounds.
- **FR-GME-032**: URL counts logged during each round SHALL reflect grounding chunk counts, not regex extraction counts.

### 4.5 Link Verification Integration

- **FR-GME-040**: Per-round link verification SHALL verify URLs from grounding chunks (for Google provider) instead of regex-extracted URLs.
- **FR-GME-041**: When a URL from grounding chunks is verified as broken, the system SHALL:
  1. Remove the entry from the grounding sources state for that round.
  2. Remove the corresponding plain-text references from the LLM text output (existing behavior).
- **FR-GME-042**: Google grounding redirect URIs SHALL continue to be auto-approved during verification (existing `_is_google_grounding_redirect` logic).

### 4.6 Adaptive Context Integration

- **FR-GME-050**: Each round entry in `adaptive_context["rounds"]` SHALL include a new field `grounding_source_count` (int) recording the number of unique sources from grounding chunks for that round.
- **FR-GME-051**: The AnalysisAgent's input context SHALL include the grounding source count to improve saturation assessment accuracy.

### Implementation Contract: Grounding Metadata Extraction

**Dataclass**: `GroundingResult`

```
@dataclasses.dataclass
class GroundingResult:
    sources: list[dict[str, str]]       # [{"uri": "...", "title": "..."}]
    supports: list[dict[str, Any]]      # [{"segment_text": "...", "start_index": int, "end_index": int, "chunk_indices": [...]}]
    queries: list[str]                  # ["query 1", "query 2"]
    has_metadata: bool                  # True if grounding metadata was found
```

**Callback**: `_grounding_capture_callback(callback_context: CallbackContext, llm_response: LlmResponse) -> None`

Registered as `after_model_callback` on the Google search `LlmAgent`. This callback:
1. Checks `llm_response.grounding_metadata` for presence.
2. If present, serializes the grounding chunks, supports, and queries into a JSON-serializable dict.
3. Writes the serialized data to session state under key `_grounding_raw_{idx}_{prov}_round_{round_idx}`.
4. Returns `None` (does not modify the LLM response).

**Function**: `_parse_grounding_from_state(state: dict, idx: int, prov: str, round_idx: int) -> GroundingResult`

**Input**:
- `state`: Session state dict.
- `idx`, `prov`, `round_idx`: Identifiers for the round.

**Output**: `GroundingResult` dataclass.

**Behavior**:
1. Read `_grounding_raw_{idx}_{prov}_round_{round_idx}` from state.
2. If present and non-empty:
   - Extract `grounding_chunks[].web.uri` and `grounding_chunks[].web.title` into `sources`.
   - Extract `grounding_supports[]` with segment text, indices, and chunk index references into `supports`.
   - Extract `web_search_queries[]` into `queries`.
   - Set `has_metadata = True`.
3. If the state key is absent or empty, return empty lists with `has_metadata = False`.

**Error behavior**: Never raises. Returns empty `GroundingResult(has_metadata=False)` on any exception, logged at WARNING.

**Function**: `_merge_rounds_with_grounding(state: dict, round_count: int) -> str`

**Input**:
- `state`: Session state dict containing round outputs and grounding source keys.
- `round_count`: Number of rounds completed.

**Output**: Merged markdown string with SUMMARY and SOURCES sections.

**Behavior**:
1. Check for grounding source keys (`grounding_sources_{idx}_{prov}_round_{r}`) for each round.
2. If at least one round has grounding sources:
   - Build SOURCES from grounding sources, deduplicating by URI (first title wins).
   - Build SUMMARY from text output (same as existing `_merge_rounds`).
   - Return merged result.
3. If no grounding sources exist for any round, delegate to existing `_merge_rounds` (text-based fallback).

**Error behavior**: Falls back to `_merge_rounds` on any exception, logged at WARNING.

---

## 5. User Stories

### US-01 -- Reliable Google Source Capture (Priority: P1) MVP

**As a** pipeline operator, **I want** Google search sources captured directly from the API's structured metadata, **so that** newsletter sections always have accurate, complete source attribution regardless of how the LLM formats its text output.

**Why P1**: This is the core problem - LLM text formatting is unpredictable and causes empty source sections, placeholder URLs, and lost citations. Fixing this eliminates the root cause.

**Independent Test**: Run the pipeline with a topic using `google_search` provider. Verify that the merged SOURCES section contains URLs matching `groundingChunks` from the API response, not regex-parsed from LLM text.

**Acceptance Scenarios**:
1. **Given** a topic configured with `google_search` provider, **When** the search agent completes a round and the API returns `groundingMetadata` with 5 grounding chunks, **Then** the system captures all 5 source URIs and titles from the structured metadata and stores them in `grounding_sources_{idx}_google_round_{r}` state key.
2. **Given** a completed multi-round Google search, **When** rounds are merged, **Then** the SOURCES section is built from grounding chunks across all rounds, deduplicated by URI.
3. **Given** a Google search round where the model did not trigger a search (no grounding metadata), **When** the round completes, **Then** the system falls back to regex extraction and logs a WARNING.

### US-02 -- Perplexity Unaffected (Priority: P1) MVP

**As a** pipeline operator, **I want** Perplexity search results to continue working exactly as they do today, **so that** the metadata extraction change does not break the non-Google search path.

**Why P1**: Regression prevention. Perplexity does not return grounding metadata, so the text-based extraction must remain the sole mechanism.

**Independent Test**: Run the pipeline with a topic using `perplexity` provider. Verify output is identical to the pre-change baseline.

**Acceptance Scenarios**:
1. **Given** a topic configured with `perplexity` provider, **When** the search completes, **Then** source extraction uses regex-based text parsing (no attempt to read grounding metadata).
2. **Given** a topic with both `google_search` and `perplexity` providers, **When** results are merged per-provider, **Then** Google uses grounding metadata and Perplexity uses text parsing, independently.

### US-03 -- Grounding-Aware Link Verification (Priority: P2)

**As a** pipeline operator, **I want** per-round link verification to verify grounding chunk URLs instead of regex-extracted URLs, **so that** verification targets the actual API-sourced links rather than whatever the LLM happened to format.

**Why P2**: Improves verification accuracy but not strictly required for source capture.

**Independent Test**: Run a round with link verification enabled. Verify that the URLs sent to `verify_urls` match the grounding chunk URIs, not the regex-extracted set.

**Acceptance Scenarios**:
1. **Given** link verification is enabled and a Google search round returns grounding chunks, **When** verification runs, **Then** it verifies grounding chunk URIs (not regex-extracted URLs).
2. **Given** a grounding chunk URI is verified as broken, **When** cleanup runs, **Then** the URI is removed from the grounding sources state AND from the LLM text output.

### US-04 -- Grounding Metadata Observability (Priority: P2)

**As a** developer, **I want** grounding metadata extraction to be logged with clear metrics, **so that** I can diagnose source capture issues without guessing.

**Why P2**: Debugging aid. Not required for correctness but essential for maintenance.

**Independent Test**: Run a topic with Google search and check logs for grounding metadata counts, fallback warnings, and round-level source tracking.

**Acceptance Scenarios**:
1. **Given** a Google search round with grounding metadata, **When** extraction completes, **Then** the system logs at INFO level: grounding chunk count, support segment count, and query count.
2. **Given** a Google search round without grounding metadata, **When** fallback triggers, **Then** the system logs at WARNING level with the specific reason.

### Edge Cases

- What happens when grounding metadata contains duplicate URIs across chunks within a single round? Deduplicate by URI; first title wins.
- What happens when a grounding chunk has a URI but no title? Use the URI as the title.
- What happens when grounding metadata is partially present (chunks but no supports)? Extract whatever is available; missing fields default to empty lists.
- What happens when `webSearchQueries` is empty but chunks exist? Valid - the model may have used cached results. Extract chunks normally.
- What happens when an event has grounding metadata on a partial (streaming) response? Ignore partial responses; only process events where `turn_complete` is True or the event is the final response.

---

## 6. User Flows

### Flow 1: Google Search Round with Grounding Metadata (Happy Path)

1. `DeepResearchOrchestrator` creates search agent via `_make_search_agent(round_idx, query)` with `_grounding_capture_callback` registered as `after_model_callback`.
2. Search agent executes via `search_agent.run_async(ctx)`.
3. During execution, the LLM calls `google_search` tool and receives grounded response.
4. ADK's flow attaches `grounding_metadata` to `LlmResponse`.
5. `_grounding_capture_callback` fires, serializes grounding metadata, writes to `_grounding_raw_{idx}_{prov}_round_{r}` state key.
6. Events yielded to orchestrator as before (unchanged).
7. After the search agent completes, `_parse_grounding_from_state(state, idx, prov, round_idx)` reads the captured metadata.
8. Grounding data found: `has_metadata = True`.
9. Sources extracted from `groundingChunks` and stored in `grounding_sources_{idx}_{prov}_round_{r}`.
10. Supports and queries stored in their respective state keys.
11. `accumulated_urls` populated from grounding chunk URIs.
12. Per-round link verification runs against grounding chunk URIs.
13. Broken URIs removed from grounding sources state and LLM text.
14. Round entry added to `adaptive_context` with `grounding_source_count`.
15. At merge time, `_merge_rounds_with_grounding` builds SOURCES from grounding sources state.

### Flow 2: Google Search Round without Grounding Metadata (Fallback)

1. Steps 1-3 same as Flow 1.
2. `_grounding_capture_callback` fires but `llm_response.grounding_metadata` is None. Nothing is written to state.
3. After the search agent completes, `_parse_grounding_from_state` returns `has_metadata = False`.
4. System logs WARNING: "No grounding metadata for topic {name}/google round {r}, falling back to text extraction".
4. Existing regex-based URL extraction runs on LLM text output.
5. No grounding source state key is written for this round.
6. `accumulated_urls` populated from regex-extracted URLs.
7. Per-round link verification runs against regex-extracted URLs.
8. At merge time, if no grounding sources exist for any round, `_merge_rounds` (existing text-based) is used.

### Flow 3: Perplexity Search Round (Unchanged)

1. `DeepResearchOrchestrator` creates search agent for Perplexity.
2. Search agent executes normally.
3. No grounding metadata extraction is attempted (provider != "google").
4. Existing text-based extraction and merge logic applies unchanged.

### Flow 4: Mixed Provider Topic

1. Google provider runs with grounding metadata extraction (Flow 1 or 2).
2. Perplexity provider runs with text extraction (Flow 3).
3. Per-provider merge produces separate `research_{idx}_{prov}` state entries.
4. Synthesis reads both state entries and combines them (existing behavior, unchanged).

---

## 7. Data Model

### GroundingResult (New Dataclass)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `sources` | `list[dict[str, str]]` | Yes | List of `{"uri": str, "title": str}` from `groundingChunks`. Empty list if no metadata. |
| `supports` | `list[dict[str, Any]]` | Yes | List of `{"segment_text": str, "start_index": int, "end_index": int, "chunk_indices": list[int]}` from `groundingSupports`. Empty list if none. |
| `queries` | `list[str]` | Yes | List of search query strings from `webSearchQueries`. Empty list if none. |
| `has_metadata` | `bool` | Yes | `True` if grounding metadata was found in any event. `False` otherwise. |

**Validation rules**:
- `sources[].uri` must be a non-empty string starting with `https://`.
- `sources[].title` must be a non-empty string; defaults to the URI if the API returns an empty title.
- `supports[].start_index` and `end_index` must be non-negative integers with `end_index > start_index`.
- `supports[].chunk_indices` must be a list of non-negative integers, each < `len(sources)`.
- `queries` entries must be non-empty strings.

### Session State Keys (New)

| Key Pattern | Type | Lifecycle | Description |
|-------------|------|-----------|-------------|
| `_grounding_raw_{idx}_{prov}_round_{r}` | `dict` | Written by callback, read by orchestrator, cleaned up in `_cleanup_state` | Raw serialized grounding metadata captured by the after_model_callback. |
| `grounding_sources_{idx}_{prov}_round_{r}` | `list[dict]` | Created per round, cleaned up in `_cleanup_state` | Processed grounding chunk sources for one round. |
| `grounding_supports_{idx}_{prov}_round_{r}` | `list[dict]` | Created per round, cleaned up in `_cleanup_state` | Processed grounding support segments for one round. |
| `grounding_queries_{idx}_{prov}_round_{r}` | `list[str]` | Created per round, cleaned up in `_cleanup_state` | Search queries executed by the model for one round. |

### Adaptive Context Extension

The `adaptive_context["rounds"][n]` dict gains one new field:

| Field | Type | Description |
|-------|------|-------------|
| `grounding_source_count` | `int` | Number of unique sources from grounding metadata for this round. `0` if fallback was used. |

---

## 8. API / Interface Design

No external API changes. This specification modifies internal interfaces within `DeepResearchOrchestrator`.

### Internal Method Changes

#### `_run_async_impl` (Modified)

The search agent gains an `after_model_callback` that captures grounding metadata into session state. After the search agent completes, the orchestrator reads the captured metadata. The event yielding loop remains unchanged:

```
# Before (current):
async for event in search_agent.run_async(ctx):
    yield event

# After (new) - event loop unchanged, metadata captured via callback:
async for event in search_agent.run_async(ctx):
    yield event

if self.provider == "google":
    grounding = self._parse_grounding_from_state(state, idx, prov, round_idx)
    # ... persist processed grounding data, populate accumulated_urls
```

#### `_grounding_capture_callback` (New Module-Level Function)

```python
def _grounding_capture_callback(callback_context: CallbackContext, llm_response: LlmResponse) -> None:
```

Registered as `after_model_callback` on Google search LlmAgents. Captures `llm_response.grounding_metadata` to session state.

**Returns**: `None` (never modifies the response).

**Raises**: Never. Silently logs WARNING on any internal error.

#### `_parse_grounding_from_state` (New Method)

```python
def _parse_grounding_from_state(self, state: dict, idx: int, prov: str, round_idx: int) -> GroundingResult:
```

**Parameters**:
- `state: dict` - Session state.
- `idx: int` - Topic index.
- `prov: str` - Provider name.
- `round_idx: int` - Round index.

**Returns**: `GroundingResult` dataclass.

**Raises**: Never. Returns empty result on any internal error.

#### `_merge_rounds_with_grounding` (New Method)

```python
def _merge_rounds_with_grounding(self, state: dict, round_count: int) -> str:
```

**Parameters**:
- `state: dict` - Session state.
- `round_count: int` - Number of completed rounds.

**Returns**: Merged markdown string with SUMMARY and SOURCES sections. Falls back to `_merge_rounds` if no grounding data exists.

---

## 9. Architecture

### 9.1 System Design

The change is scoped to `DeepResearchOrchestrator` in `newsletter_agent/tools/deep_research.py`. No new modules are created. The metadata extraction is a post-processing step inserted into the existing adaptive loop, between the search agent execution and the round output processing.

```
Search Agent executes (with after_model_callback registered)
    |
    v
LLM calls google_search, gets grounded response
    |
    v
[NEW] after_model_callback captures grounding_metadata to state key
    |
    v
Events yielded (existing, unchanged)
    |
    v
[NEW] _parse_grounding_from_state reads captured metadata
    |
    v
[NEW] Persist processed grounding sources/supports/queries to state
    |
    v
Read round text output from state (existing)
    |
    v
Link verification (existing, but now uses grounding URIs for Google)
    |
    v
URL tracking / adaptive context (existing, but uses grounding counts)
    |
    v
Analysis phase (existing)
    |
    v
Merge rounds (modified to prefer grounding sources)
```

### 9.2 Technology Stack

No new dependencies. All required types are already available:

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Grounding metadata types | `google.genai.types.GroundingMetadata` | Already in `google-genai` SDK, used by ADK |
| Event inspection | `google.adk.events.Event` | Already imported in `deep_research.py` |
| Data class | `dataclasses.dataclass` | Standard library, lightweight |

### 9.3 Directory & Module Structure

No new files. Changes are confined to:

| File | Change |
|------|--------|
| `newsletter_agent/tools/deep_research.py` | Add `GroundingResult` dataclass, `_extract_grounding_metadata` static method, `_merge_rounds_with_grounding` method, modify `_run_async_impl` loop |
| `tests/unit/test_deep_research.py` | Add tests for grounding metadata extraction, merge with grounding, fallback scenarios |

### 9.4 Key Design Decisions

#### Decision 1: after_model_callback vs. Event Inspection vs. State Key Reading

- **Decision**: Register an `after_model_callback` on the Google search `LlmAgent` to capture `LlmResponse.grounding_metadata` and write it to a known session state key.
- **Rationale**: The `after_model_callback` is a documented ADK API that receives the `LlmResponse` object directly, with guaranteed access to `grounding_metadata`. This avoids depending on (a) whether `Event` exposes `grounding_metadata` (undocumented), or (b) internal ADK state key naming conventions (`temp:_adk_grounding_metadata`).
- **Alternatives considered**:
  - Event inspection: `Event` wraps `types.Content`, not the full `LlmResponse`. Whether grounding metadata is accessible from events is not documented and may vary by ADK version. Rejected for reliability concerns.
  - `temp:_adk_grounding_metadata` state key: Internal ADK implementation detail. Could break on ADK upgrades without notice. Rejected for fragility.
- **Consequences**: The search agent construction in `_make_search_agent` gains an `after_model_callback` parameter. This is a small, localized change.

#### Decision 2: Grounding Sources as Authoritative (Not Supplementary)

- **Decision**: Grounding chunk sources replace regex-extracted sources as the primary source of truth for Google provider.
- **Rationale**: The whole point of this change is to stop depending on LLM text formatting. Using grounding metadata as merely supplementary would not solve the problem - the regex path would still be the primary path and would still fail when the LLM formats sources inconsistently.
- **Alternatives considered**:
  - Supplementary approach (union of grounding + regex): Does not solve the core problem. Regex extraction still produces garbage URLs. Rejected.
  - Pure grounding, no fallback: Too risky if grounding metadata is occasionally absent. Rejected.
- **Consequences**: If grounding metadata is absent (rare), the fallback to regex extraction provides a safety net but with known limitations.

#### Decision 3: Inline GroundingResult Dataclass, Not Separate Module

- **Decision**: Define `GroundingResult` as a simple `dataclass` within `deep_research.py`.
- **Rationale**: Single-use data structure, only consumed within the same module. Creating a separate module would be over-engineering.
- **Alternatives considered**:
  - Separate `grounding.py` module: Unnecessary abstraction for one dataclass and one function. Rejected.
  - TypedDict: Less self-documenting than dataclass. Rejected.
- **Consequences**: If grounding metadata is needed elsewhere in the future, the dataclass can be extracted to a shared module at that time.

### 9.5 External Integrations

No new external integrations. The grounding metadata is already returned by the Gemini API as part of every grounded response. The ADK surfaces it through the event/response model.

**Gemini Grounding API**:
- **Purpose**: Source attribution and citation for search-grounded responses.
- **Authentication**: Same as existing Gemini API auth (API key or service account).
- **Key data used**: `groundingChunks`, `groundingSupports`, `webSearchQueries` from `GenerateContentResponse.candidates[].grounding_metadata`.
- **Failure handling**: If metadata is absent, fall back to text extraction. No retries needed since the metadata is part of the existing API response.

---

## 10. Non-Functional Requirements

### 10.1 Performance

- **NFR-001**: Grounding metadata extraction SHALL complete in < 1ms per round (in-memory iteration, no I/O).
- **NFR-002**: Total pipeline latency increase SHALL be < 5% end-to-end. The only new work is event list construction and metadata field access.
- **NFR-003**: Memory overhead from event list collection SHALL be < 10MB per round (events are short-lived and garbage collected after extraction).

### 10.2 Security

- **OWASP consideration**: URIs from grounding metadata come from Google's API, not from user input. They are not subject to injection attacks. However:
  - **CWE-918 (SSRF)**: Grounding URIs are verified through the existing link verifier which has SSRF protection for private IPs. No change needed.
  - **CWE-79 (XSS)**: URIs and titles are used in markdown output, then rendered to HTML by the FormatterAgent. The existing HTML escaping in the Jinja2 template applies. No change needed.

### 10.3 Scalability & Availability

No change. Grounding metadata extraction is a local in-memory operation with no network calls.

### 10.4 Accessibility

Not applicable. This change affects backend data processing only.

### 10.5 Observability

- **LOG-001**: Log at INFO after each Google search round: `"[Grounding] Topic {name}/google round {r}: {n} chunks, {s} supports, {q} queries"`.
- **LOG-002**: Log at WARNING on fallback: `"[Grounding] Topic {name}/google round {r}: no grounding metadata, falling back to text extraction"`.
- **LOG-003**: Log at INFO at merge time: `"[Grounding] Topic {name}/google: merged {n} unique sources from grounding metadata across {r} rounds"`.
- **LOG-004**: Log at WARNING if grounding chunks contain a URI with empty title: `"[Grounding] Topic {name}/google round {r}: chunk {i} has empty title, using URI"`.

---

## 11. Test Requirements

### 11.1 Unit Tests

**Module**: `newsletter_agent/tools/deep_research.py`
**Minimum coverage**: 80% code, 90% branch for new/modified methods.

Tests required:

1. `test_grounding_capture_callback_with_metadata` - Callback serializes grounding metadata to state when present on LlmResponse.
2. `test_grounding_capture_callback_no_metadata` - Callback does nothing when grounding_metadata is None.
3. `test_grounding_capture_callback_exception_safety` - Callback never raises on malformed data.
4. `test_parse_grounding_from_state_happy_path` - State with full grounding data returns complete `GroundingResult`.
5. `test_parse_grounding_from_state_no_data` - Missing state key returns `has_metadata=False`.
6. `test_parse_grounding_from_state_partial_metadata` - Chunks present but no supports returns chunks with empty supports.
7. `test_parse_grounding_from_state_duplicate_uris` - Duplicate URIs across chunks are deduplicated (first title wins).
8. `test_parse_grounding_from_state_empty_title` - Chunk with empty title uses URI as title.
8. `test_merge_rounds_with_grounding_happy_path` - Grounding sources from 3 rounds merge into deduplicated SOURCES section.
9. `test_merge_rounds_with_grounding_fallback` - No grounding sources delegates to text-based `_merge_rounds`.
10. `test_merge_rounds_with_grounding_mixed` - Some rounds have grounding, some do not; grounding rounds contribute to SOURCES section, text fallback supplements.
11. `test_accumulated_urls_from_grounding` - Google provider populates `accumulated_urls` from grounding chunks, not regex.
12. `test_link_verification_uses_grounding_urls` - Verification targets grounding chunk URIs for Google provider.
13. `test_broken_url_removed_from_grounding_sources` - Broken grounding URL is removed from grounding sources state.
14. `test_adaptive_context_includes_grounding_count` - Round entry contains `grounding_source_count`.
15. `test_perplexity_unchanged` - Perplexity provider does not attempt grounding metadata extraction.

### 11.2 BDD / Acceptance Tests

```gherkin
Feature: Grounding Metadata Extraction

  Scenario: Google search round captures grounding metadata
    Given a topic configured with google_search provider
    And the Gemini API returns groundingMetadata with 5 groundingChunks
    When the search round completes
    Then the system extracts 5 source URIs from grounding metadata
    And stores them in the grounding_sources state key
    And logs the grounding chunk count at INFO level

  Scenario: Google search round without grounding metadata falls back
    Given a topic configured with google_search provider
    And the Gemini API returns a response without groundingMetadata
    When the search round completes
    Then the system falls back to regex-based URL extraction
    And logs a WARNING about missing grounding metadata

  Scenario: Multi-round merge uses grounding sources
    Given a Google topic that completed 3 research rounds
    And rounds 1 and 2 had grounding metadata with 4 and 3 sources respectively
    And round 3 had no grounding metadata
    When rounds are merged
    Then the SOURCES section contains deduplicated sources from grounding metadata of rounds 1 and 2
    And any regex-extracted sources from round 3 are included as supplementary

  Scenario: Perplexity provider is unaffected
    Given a topic configured with perplexity provider
    When the search round completes
    Then no grounding metadata extraction is attempted
    And source extraction uses the existing regex-based approach

  Scenario: Broken grounding URL is cleaned up
    Given a Google search round with grounding metadata containing 5 sources
    And link verification determines 2 of those URLs are broken
    When cleanup runs
    Then the grounding sources state contains only 3 sources
    And the broken URLs are removed from the LLM text output
```

### 11.3 Integration Tests

- **IT-001**: End-to-end pipeline run with Google search produces SOURCES from grounding metadata (verify by checking state keys after research phase).
- **IT-002**: Pipeline run with both Google and Perplexity providers produces correct sources for each (Google from metadata, Perplexity from text).
- **IT-003**: Pipeline run with link verification enabled correctly verifies grounding chunk URLs and removes broken ones.

**Mocking strategy**: Mock `LlmAgent.run_async` to yield events with pre-built `grounding_metadata`. Do NOT mock the Gemini API directly - the ADK mediates access.

### 11.4 End-to-End Tests

- **E2E-001**: Full pipeline run with real API calls. Compare source counts with pre-change baseline. Expect >= 20% improvement (SC-003).
- **E2E-002**: Full pipeline run produces final HTML with zero synthetic/placeholder Google URLs (SC-002).

### 11.5 Performance Tests

- **PT-001**: Measure `_extract_grounding_metadata` execution time across 100 iterations with realistic event payloads. Must be < 1ms average.
- **PT-002**: Compare end-to-end pipeline latency before and after. Must be < 5% increase (SC-005).

### 11.6 Security Tests

- **ST-001**: Verify that grounding URIs pass through the existing SSRF protection in the link verifier (no private IP URIs accepted).
- **ST-002**: Verify that grounding titles with HTML entities are properly escaped in the final newsletter output.

---

## 12. Constraints & Assumptions

### Constraints

- **C-001**: Must work with `google-adk >= 1.x` (current project dependency). The `LlmResponse.grounding_metadata` field must be present.
- **C-002**: Must not break existing Perplexity provider path.
- **C-003**: Must not require configuration changes - the improvement is transparent to operators.
- **C-004**: Python 3.11+ (existing project constraint).

### Assumptions

- **A-001**: The Gemini API returns `groundingMetadata` on responses from `google_search` tool calls. Verified via API documentation (https://ai.google.dev/gemini-api/docs/google-search, consulted 2026-03-22).
- **A-002**: ADK's `Event` objects yielded by `LlmAgent.run_async()` contain the `LlmResponse` with `grounding_metadata` populated when the Gemini API returns it. Verified via ADK source code inspection (`LlmResponse.grounding_metadata` field exists, `base_llm_flow.py` has `_maybe_add_grounding_metadata` method).
- **A-003**: The `types.GroundingMetadata` class from `google.genai.types` has `grounding_chunks`, `grounding_supports`, and `web_search_queries` attributes. Verified via Gemini API documentation.
- **A-004**: Grounding metadata is available on the final (non-partial) event from a search round. Streaming partial events may not contain complete metadata.

---

## 13. Out of Scope

- **OS-001**: Rendering grounding supports as inline citations in the newsletter HTML. The supports data is persisted for future use but this spec does not define how to render inline citations. This could be a follow-up feature.
- **OS-002**: Using `webSearchQueries` to improve the adaptive planning loop. The queries are persisted for observability but not fed back into the PlanningAgent or AnalysisAgent.
- **OS-003**: Resolving Google grounding redirect URLs to their final destination URLs. The existing behavior (preserve redirect URLs as-is) is maintained.
- **OS-004**: Changes to the synthesis or formatting pipeline. Source data flows into synthesis via the same `research_{idx}_{prov}` state key format.
- **OS-005**: Changes to the Perplexity provider path.

---

## 14. Open Questions

| # | Question | Impact if Unresolved | Owner |
|---|----------|---------------------|-------|
| OQ-1 | Does `after_model_callback` receive `grounding_metadata` populated on `LlmResponse` when the Google search tool is used? ADK source shows `_maybe_add_grounding_metadata` runs during post-processing, but callback ordering needs verification. | If the callback fires before metadata is attached, the callback will see `None`. Mitigation: implementation SHALL verify this during the first integration test and fall back to reading `temp:_adk_grounding_metadata` from state if needed. | Developer (verify during implementation) |

---

## 15. Glossary

- **Grounding**: The process of connecting LLM responses to real-world sources via Google Search.
- **Grounding chunk**: A single source reference from the Gemini API's `groundingMetadata`, containing a `uri` and `title`.
- **Grounding support**: A mapping from a specific text segment in the LLM response to one or more grounding chunks, enabling inline citation.
- **Grounding redirect**: A URL of the form `https://vertexaisearch.cloud.google.com/grounding-api-redirect/...` that redirects to the actual source article.
- **Fallback extraction**: The existing regex-based URL extraction from LLM text output, used when grounding metadata is unavailable.
- **Adaptive loop**: The Plan-Search-Analyze-Decide cycle in `DeepResearchOrchestrator` (specified in 002-adaptive-deep-research.spec.md).

---

## 16. Traceability Matrix

| FR ID | Requirement Summary | User Story | Acceptance Scenario | Test Type | Test Section Ref |
|-------|-------------------|------------|--------------------|-----------|----|
| FR-GME-001 | Capture groundingMetadata from events | US-01 | Scenario 1 | unit, BDD | 11.1 (#1), 11.2 |
| FR-GME-002 | Extract groundingChunks as source list | US-01 | Scenario 1 | unit | 11.1 (#1, #6, #7) |
| FR-GME-003 | Extract groundingSupports | US-01 | Scenario 1 | unit | 11.1 (#1, #3) |
| FR-GME-004 | Extract webSearchQueries | US-04 | Scenario 1 | unit | 11.1 (#1) |
| FR-GME-005 | Fallback to regex on missing metadata | US-01 | Scenario 3 | unit, BDD | 11.1 (#2, #5), 11.2 |
| FR-GME-006 | Perplexity unchanged | US-02 | Scenario 1, 2 | unit, BDD | 11.1 (#15), 11.2 |
| FR-GME-010 | Persist grounding sources per round | US-01 | Scenario 1 | unit | 11.1 (#1) |
| FR-GME-011 | Persist grounding supports per round | US-01 | Scenario 1 | unit | 11.1 (#1, #3) |
| FR-GME-012 | Persist web search queries per round | US-04 | Scenario 1 | unit | 11.1 (#1) |
| FR-GME-013 | Cleanup intermediate state keys | US-01 | Scenario 1 | unit | 11.1 (#8) |
| FR-GME-020 | Grounding chunks as authoritative source | US-01 | Scenario 2 | unit, BDD | 11.1 (#8), 11.2 |
| FR-GME-021 | Merged SOURCES from grounding chunks | US-01 | Scenario 2 | unit, BDD | 11.1 (#8, #10), 11.2 |
| FR-GME-022 | Full fallback when no grounding data | US-01 | Scenario 3 | unit, BDD | 11.1 (#9), 11.2 |
| FR-GME-023 | Preserve grounding redirect URIs | US-03 | Scenario 5 | unit | 11.1 (#12) |
| FR-GME-030 | accumulated_urls from grounding chunks | US-01 | Scenario 1 | unit | 11.1 (#11) |
| FR-GME-031 | deep_urls state from grounding chunks | US-01 | Scenario 1 | unit | 11.1 (#11) |
| FR-GME-032 | Log counts from grounding data | US-04 | Scenario 1 | unit | 11.1 (#1) |
| FR-GME-040 | Verify grounding chunk URLs | US-03 | Scenario 1 | unit, BDD | 11.1 (#12), 11.2 |
| FR-GME-041 | Remove broken grounding URLs | US-03 | Scenario 2 | unit, BDD | 11.1 (#13), 11.2 |
| FR-GME-042 | Auto-approve grounding redirects | US-03 | Scenario 1 | unit | 11.1 (#12) |
| FR-GME-050 | grounding_source_count in adaptive context | US-04 | Scenario 1 | unit | 11.1 (#14) |
| FR-GME-051 | Analysis input includes grounding count | US-04 | Scenario 1 | unit | 11.1 (#14) |

**Validation**: Every FR maps to at least one US. Every US maps to at least one acceptance scenario. Every acceptance scenario maps to at least one test.

---

## 17. Technical References

### Architecture & Patterns
- Google Gemini API - Grounding with Google Search documentation, https://ai.google.dev/gemini-api/docs/google-search, consulted 2026-03-22. Covers `groundingMetadata` response structure, `groundingChunks`, `groundingSupports`, and inline citation patterns.

### Technology Stack
- Google ADK Python - `LlmResponse` model, https://github.com/google/adk-python/blob/main/src/google/adk/models/llm_response.py, consulted 2026-03-22. Confirms `grounding_metadata: Optional[types.GroundingMetadata]` field.
- Google ADK Python - `base_llm_flow.py`, https://github.com/google/adk-python/blob/main/src/google/adk/flows/llm_flows/base_llm_flow.py, consulted 2026-03-22. Confirms `_maybe_add_grounding_metadata` method that propagates metadata from `temp:_adk_grounding_metadata` state to `LlmResponse`.
- Google ADK Python - `google_search_tool.py`, https://github.com/google/adk-python/blob/main/src/google/adk/tools/google_search_tool.py, consulted 2026-03-22. Confirms `google_search` is a built-in model tool, not a function-call tool.
- Google ADK Python - `Event` model, https://github.com/google/adk-python/blob/main/src/google/adk/events/event.py, consulted 2026-03-22. Confirms event structure with content and actions.

### Security
- OWASP Top 10 2021 - A10:2021 Server-Side Request Forgery, applied to grounding URI verification. Existing SSRF protections in `link_verifier.py` cover this surface.

---

## 18. Version History

| Version | Date | Author | Summary of Changes |
|---------|------|--------|--------------------|
| 1.0 | 2026-03-22 | Spec Architect | Initial specification. Self-review corrections: (1) Changed extraction mechanism from event inspection to after_model_callback for reliability - Event objects may not expose grounding_metadata directly, while the callback receives LlmResponse with guaranteed access. (2) Added _grounding_raw state key for callback-to-orchestrator data passing. (3) Updated user flows and architecture diagram to reflect callback approach. (4) Added edge case for streaming/partial events. (5) Added explicit fallback logging message format. (6) Added mixed-round merge test case (#10). (7) Clarified that grounding redirect URIs are preserved as-is per existing link verifier behavior. (8) Replaced "should" with "SHALL" throughout Section 4. (9) Added validation rules for GroundingResult fields. (10) Consolidated OQ-1 and OQ-2 into a single OQ about callback timing vs grounding metadata attachment ordering. |
