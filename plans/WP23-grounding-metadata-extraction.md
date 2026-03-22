---
lane: planned
---

# WP23 - Grounding Metadata Extraction

> **Spec**: `specs/004-grounding-metadata-extraction.spec.md`
> **Status**: Not Started
> **Priority**: P1 (MVP - core source reliability fix)
> **Goal**: Capture Google search sources from structured API grounding metadata instead of fragile LLM text parsing, eliminating empty source sections and placeholder URLs.
> **Independent Test**: Run the pipeline with a Google search topic. Verify the merged SOURCES section contains URLs from `groundingChunks` API metadata, not regex-parsed from LLM text. Confirm Perplexity topics are unchanged.
> **Depends on**: none (all prerequisites - WP12 DeepResearchOrchestrator, WP07 link verification - are complete)
> **Parallelisable**: No (single production file, sequential task chain)
> **Prompt**: `plans/WP23-grounding-metadata-extraction.md`

## Objective

Replace the regex-based source URL extraction from Google search rounds with structured `groundingMetadata` captured directly from the Gemini API response. The `after_model_callback` on search LlmAgents intercepts `LlmResponse.grounding_metadata`, persists `groundingChunks` (URI + title pairs) to session state, and a new merge method uses these as the authoritative source list. Existing regex extraction is preserved as a fallback when metadata is absent, and the Perplexity provider path is completely unchanged. This is the single most impactful reliability improvement for the newsletter pipeline - it eliminates the root cause of empty/weak source sections.

## Spec References

- FR-GME-001 through FR-GME-051 (Sections 4.1-4.6)
- Section 5 (User Stories US-01 through US-04, edge cases)
- Section 6 (User Flows 1-4)
- Section 7 (Data Model: GroundingResult, session state keys, adaptive context extension)
- Section 8 (Interface Design: callback, parse, merge method contracts)
- Section 9.4 (Design Decisions 1-3)
- Section 10.5 (Observability: LOG-001 through LOG-004)
- Section 11 (All test requirements)
- Section 14 (OQ-1: callback timing verification)

## Tasks

### T23-01 - ADK Callback Verification Spike

- **Description**: Resolve OQ-1 from the spec: verify that `after_model_callback` on an `LlmAgent` using `google_search` tool receives `LlmResponse` with `grounding_metadata` populated. Write a minimal integration test that creates an LlmAgent with `google_search` and an `after_model_callback`, executes a real search query, and inspects whether `llm_response.grounding_metadata` is non-None. If the callback fires BEFORE ADK's `_maybe_add_grounding_metadata` attaches the metadata, document the finding and implement the fallback: read `temp:_adk_grounding_metadata` from session state instead. Record the decision for subsequent tasks.
- **Spec refs**: Section 14 OQ-1, Section 9.4 Decision 1, FR-GME-001
- **Parallel**: No
- **Acceptance criteria**:
  - [ ] A test script or integration test executes a real Google search via ADK with `after_model_callback` registered
  - [ ] The test captures and logs whether `llm_response.grounding_metadata` is populated (non-None) in the callback
  - [ ] If `grounding_metadata` is None in the callback, the test checks `session.state.get("temp:_adk_grounding_metadata")` as fallback
  - [ ] A decision record is written as a comment in the test file documenting which mechanism works and will be used in T23-02 through T23-05
- **Test requirements**: integration (real API call, can be skipped in CI via marker)
- **Depends on**: none
- **Implementation Guidance**:
  - Official docs: ADK `after_model_callback` - https://github.com/google/adk-python/blob/main/src/google/adk/agents/llm_agent.py (callback signature: `Callable[[CallbackContext, LlmResponse], Optional[LlmResponse]]`)
  - ADK grounding flow: `_maybe_add_grounding_metadata` in https://github.com/google/adk-python/blob/main/src/google/adk/flows/llm_flows/base_llm_flow.py
  - LlmResponse model: `grounding_metadata: Optional[types.GroundingMetadata]` field confirmed in https://github.com/google/adk-python/blob/main/src/google/adk/models/llm_response.py
  - Known pitfall: The ADK's `_maybe_add_grounding_metadata` runs in the post-processing flow. If `after_model_callback` fires BEFORE that method, the metadata will be None on `LlmResponse`. In that case, read `ctx.session.state.get("temp:_adk_grounding_metadata")` which is where ADK stores raw grounding data before attaching it
  - Test location: `tests/integration/test_grounding_spike.py` with `@pytest.mark.integration` marker
  - Existing pattern: see `tests/integration/` for API-calling test conventions in this project

### T23-02 - GroundingResult Dataclass and Capture Callback

- **Description**: Implement the `GroundingResult` dataclass and the `_grounding_capture_callback` module-level function in `deep_research.py`. The callback is registered as `after_model_callback` on Google search LlmAgents (registration happens in T23-04). The callback reads `grounding_metadata` from `LlmResponse` (or session state fallback per T23-01 findings), serializes it to a JSON-friendly dict, and writes it to session state under `_grounding_raw_{idx}_{prov}_round_{round_idx}`. The callback MUST never raise - all exceptions are caught and logged at WARNING.
- **Spec refs**: FR-GME-001, FR-GME-002, FR-GME-003, FR-GME-004, Section 7 (GroundingResult), Section 8 (callback contract)
- **Parallel**: No
- **Acceptance criteria**:
  - [ ] `GroundingResult` dataclass defined with fields: `sources: list[dict[str, str]]`, `supports: list[dict[str, Any]]`, `queries: list[str]`, `has_metadata: bool`
  - [ ] `_grounding_capture_callback` accepts `(callback_context, llm_response)` and returns `None`
  - [ ] When `llm_response.grounding_metadata` is present: serialized grounding chunks (uri + title), supports, and queries are written to `_grounding_raw_{idx}_{prov}_round_{round_idx}` state key
  - [ ] When `grounding_metadata` is None: callback does nothing (no state write)
  - [ ] On any exception: callback logs WARNING and returns None (never raises)
  - [ ] New imports added: `import dataclasses` and `from typing import Any`; ADK callback types imported conditionally
- **Test requirements**: unit
  - `test_grounding_capture_callback_with_metadata` - callback serializes metadata to state
  - `test_grounding_capture_callback_no_metadata` - callback is no-op when metadata is None
  - `test_grounding_capture_callback_exception_safety` - callback never raises on malformed input
- **Depends on**: T23-01 (determines callback vs state-key mechanism)
- **Implementation Guidance**:
  - Official docs: Gemini grounding metadata structure - https://ai.google.dev/gemini-api/docs/google-search#understanding_the_grounding_response
  - `types.GroundingMetadata` attributes: `grounding_chunks` (list of `GroundingChunk` with `.web.uri` and `.web.title`), `grounding_supports` (list of `GroundingSupport` with `.segment.text`, `.segment.start_index`, `.segment.end_index`, `.grounding_chunk_indices`), `web_search_queries` (list of str)
  - Callback signature must match ADK's `AfterModelCallback` type: `Callable[[CallbackContext, LlmResponse], Optional[LlmResponse]]`. Return `None` to not modify the response.
  - The callback needs access to `idx`, `prov`, and `round_idx` to construct the state key. Use a closure or functools.partial to bind these values when registering the callback in T23-04.
  - Validation rules from spec Section 7: `sources[].uri` must start with `https://`; empty titles default to URI; empty `web_search_queries` is valid
  - Known pitfall: `grounding_chunks` may contain entries where `.web` is None (non-web grounding). Filter these out.
  - Mock pattern for tests: Create a mock `LlmResponse` with `grounding_metadata` set to a mock `types.GroundingMetadata`. Use `unittest.mock.MagicMock` for the ADK types.

### T23-03 - Parse Grounding from State

- **Description**: Implement `_parse_grounding_from_state` method on `DeepResearchOrchestrator`. This reads the raw grounding data written by the callback (from `_grounding_raw_{idx}_{prov}_round_{round_idx}` state key), processes it into a `GroundingResult`, and handles all edge cases: duplicate URIs (deduplicate, first title wins), empty titles (use URI), partial metadata (missing supports/queries default to empty lists), and missing state key (return `has_metadata=False`). Must never raise.
- **Spec refs**: FR-GME-002, FR-GME-003, FR-GME-004, FR-GME-005, Section 7 (validation rules), Section 8 (`_parse_grounding_from_state` contract)
- **Parallel**: Yes (can be developed in parallel with T23-04 if callback is done) [P]
- **Acceptance criteria**:
  - [ ] Method reads `_grounding_raw_{idx}_{prov}_round_{round_idx}` from `state` dict
  - [ ] When present: extracts `sources` (uri + title pairs), `supports`, `queries` into `GroundingResult(has_metadata=True)`
  - [ ] Duplicate URIs within a single round are deduplicated; first title occurrence wins
  - [ ] Chunks with empty or missing `title` use the URI as the title
  - [ ] Missing `grounding_supports` or `web_search_queries` in raw data defaults to empty lists (partial metadata OK)
  - [ ] When state key is absent or empty: returns `GroundingResult(has_metadata=False)` with empty lists
  - [ ] On any exception: logs WARNING, returns empty `GroundingResult(has_metadata=False)`
- **Test requirements**: unit
  - `test_parse_grounding_from_state_happy_path` - full metadata returns complete GroundingResult
  - `test_parse_grounding_from_state_no_data` - missing key returns has_metadata=False
  - `test_parse_grounding_from_state_partial_metadata` - chunks but no supports
  - `test_parse_grounding_from_state_duplicate_uris` - deduplication (first title wins)
  - `test_parse_grounding_from_state_empty_title` - empty title uses URI
- **Depends on**: T23-02 (GroundingResult dataclass must exist)
- **Implementation Guidance**:
  - The raw data in state is a Python dict (serialized by the callback in T23-02). Structure: `{"grounding_chunks": [{"web": {"uri": "...", "title": "..."}}], "grounding_supports": [...], "web_search_queries": [...]}`
  - Deduplication: use an `OrderedDict` or `dict` (Python 3.7+ insertion order) keyed by URI to track first-seen title
  - Validation: skip chunks where `uri` is empty or doesn't start with `https://`
  - Known pitfall: `grounding_supports[].segment` may have `text` that references the model's response text. This is informational - store it but don't validate against the model output.
  - Test pattern: directly call `orch._parse_grounding_from_state(state, 0, "google", 0)` with crafted state dicts. No async needed.

### T23-04 - Register Callback on Google Search Agent

- **Description**: Modify `_make_search_agent` to register `_grounding_capture_callback` as `after_model_callback` on Google search LlmAgents only. Perplexity agents must NOT have this callback. The callback must be bound with the correct `idx`, `prov`, and `round_idx` values via closure or `functools.partial`.
- **Spec refs**: FR-GME-001, FR-GME-006, Section 8 (`_make_search_agent` modification), Section 9.4 Decision 1
- **Parallel**: Yes (can be developed in parallel with T23-03) [P]
- **Acceptance criteria**:
  - [ ] `_make_search_agent` creates LlmAgent with `after_model_callback` when `self.provider == "google"`
  - [ ] The callback is NOT registered for Perplexity provider agents (FR-GME-006)
  - [ ] The callback closure/partial correctly binds `self.topic_idx`, `self.provider`, and `round_idx` so the state key is unique per round
  - [ ] Existing LlmAgent parameters (name, model, instruction, tools, output_key) are unchanged
- **Test requirements**: unit
  - Verify Google agent has `after_model_callback` set
  - Verify Perplexity agent does NOT have `after_model_callback`
  - Existing `_make_search_agent` tests continue to pass
- **Depends on**: T23-02 (callback function must exist)
- **Implementation Guidance**:
  - ADK `LlmAgent` accepts `after_model_callback` parameter: https://github.com/google/adk-python/blob/main/src/google/adk/agents/llm_agent.py
  - Use a closure to capture round-specific values:
    ```python
    def _make_callback(idx, prov, round_idx):
        def _cb(callback_context, llm_response):
            return _grounding_capture_callback(callback_context, llm_response, idx, prov, round_idx)
        return _cb
    ```
  - Or use `functools.partial` if the callback signature allows extra args
  - Known pitfall: lambda closures in loops can capture the loop variable by reference, not value. Use default argument binding: `lambda ctx, resp, _r=round_idx: ...`
  - Test pattern: call `orch._make_search_agent(round_idx=0, query="test")`, inspect the returned LlmAgent's `after_model_callback` attribute

### T23-05 - Orchestrator Loop Integration

- **Description**: Modify `_run_async_impl` to integrate grounding metadata into the main adaptive loop. After each Google search round completes, call `_parse_grounding_from_state` to read captured metadata. If `has_metadata` is True: persist processed sources/supports/queries to their respective state keys, populate `accumulated_urls` from grounding chunk URIs, and add `grounding_source_count` to the round's adaptive context entry. If `has_metadata` is False (fallback): use existing regex-based `_extract_urls` for `accumulated_urls` (current behavior), set `grounding_source_count = 0`, and log WARNING. Perplexity provider continues to use existing `_extract_urls` exclusively.
- **Spec refs**: FR-GME-005, FR-GME-010, FR-GME-011, FR-GME-012, FR-GME-030, FR-GME-031, FR-GME-032, FR-GME-050, FR-GME-051, Section 6 Flows 1-3
- **Parallel**: No
- **Acceptance criteria**:
  - [ ] After each Google round, `_parse_grounding_from_state` is called
  - [ ] When grounding metadata present: `grounding_sources_{idx}_{prov}_round_{r}`, `grounding_supports_{idx}_{prov}_round_{r}`, `grounding_queries_{idx}_{prov}_round_{r}` written to state (FR-GME-010/011/012)
  - [ ] When grounding metadata present: `accumulated_urls` populated from grounding chunk URIs, not regex extraction (FR-GME-030)
  - [ ] When grounding metadata absent: existing `_extract_urls` used for `accumulated_urls` (FR-GME-005 fallback)
  - [ ] When grounding metadata absent: WARNING logged with message: "No grounding metadata for topic {name}/google round {r}, falling back to text extraction" (FR-GME-005)
  - [ ] Each round entry in `adaptive_context["rounds"]` includes `grounding_source_count` field (FR-GME-050)
  - [ ] Perplexity provider rounds do NOT call `_parse_grounding_from_state` (FR-GME-006)
  - [ ] URL count logs reflect grounding chunk counts for Google (FR-GME-032)
  - [ ] `deep_urls_accumulated_{idx}_{provider}` state key includes grounding URIs (FR-GME-031)
- **Test requirements**: unit
  - `test_accumulated_urls_from_grounding` - Google round populates accumulated_urls from grounding chunks
  - `test_adaptive_context_includes_grounding_count` - round has grounding_source_count field
  - `test_perplexity_unchanged` - Perplexity round uses regex extraction, no grounding attempt
- **Depends on**: T23-03, T23-04
- **Implementation Guidance**:
  - Insert grounding extraction AFTER `async for event in search_agent.run_async(ctx): yield event` and BEFORE the existing `round_key` state write
  - Conditional on provider: `if self.provider == "google":` guards the grounding extraction block
  - The existing `new_urls = self._extract_urls(round_output)` becomes the fallback path: only executed for Google if `grounding.has_metadata is False`, always executed for Perplexity
  - `grounding_source_count` is `len(grounding.sources)` when metadata present, `0` when fallback
  - Add it to the `adaptive_context["rounds"].append({...})` dict alongside existing fields
  - Known pitfall: the existing `accumulated_urls.update(new_urls)` line must be replaced with conditional logic, not duplicated. Ensure only ONE path populates accumulated_urls per round.
  - Test pattern: use the existing `_make_orchestrator` helper + mock search agent pattern from `test_deep_research.py`. Set up mock state with `_grounding_raw` key to simulate callback having fired.

### T23-06 - Grounding-Aware Link Verification

- **Description**: Modify the per-round link verification block in `_run_async_impl` to verify grounding chunk URIs for Google provider instead of regex-extracted URLs. When a grounding URL is verified as broken, remove it from the `grounding_sources` state AND from the LLM text output (existing cleanup). For Perplexity and fallback scenarios, existing regex-based verification continues unchanged.
- **Spec refs**: FR-GME-040, FR-GME-041, FR-GME-042, Section 5 US-03
- **Parallel**: No
- **Acceptance criteria**:
  - [ ] When link verification enabled AND Google provider has grounding metadata: `verify_urls` receives grounding chunk URIs (FR-GME-040)
  - [ ] Broken grounding URIs are removed from `grounding_sources_{idx}_{prov}_round_{r}` state (FR-GME-041 step 1)
  - [ ] Broken grounding URIs are also removed from LLM text output via existing `clean_broken_links_from_markdown` and `_remove_broken_source_lines` (FR-GME-041 step 2)
  - [ ] Google grounding redirect URIs (`vertexaisearch.cloud.google.com/grounding-api-redirect/...`) continue to be auto-approved (FR-GME-042)
  - [ ] When Google provider has NO grounding metadata (fallback): verification uses regex-extracted URLs (existing behavior)
  - [ ] Perplexity rounds: verification unchanged (uses regex-extracted URLs)
- **Test requirements**: unit
  - `test_link_verification_uses_grounding_urls` - Google round sends grounding URIs to verify_urls
  - `test_broken_url_removed_from_grounding_sources` - broken grounding URL removed from state + text
- **Depends on**: T23-05 (grounding data must be in state before verification runs)
- **Implementation Guidance**:
  - The existing verification block starts with `if state.get("config_verify_links", False) and round_output:`. Add a sub-condition: if grounding metadata present, use grounding URIs; else use regex extraction
  - For removal from grounding sources state: read `grounding_sources_{idx}_{prov}_round_{r}`, filter out broken URIs, write back
  - The existing `clean_broken_links_from_markdown` and `_remove_broken_source_lines` operate on text - they continue to clean the LLM text output WITH the same broken URL set
  - `_is_google_grounding_redirect` in link_verifier.py already auto-approves grounding redirects - no change needed there
  - Known pitfall: grounding chunk URIs may include grounding redirect URLs. These will be auto-approved by the verifier. Do NOT filter them out before verification.
  - Test pattern: mock `verify_urls` to return specific broken/valid results, check that grounding_sources state is correctly filtered

### T23-07 - Grounding-Aware Round Merge

- **Description**: Implement `_merge_rounds_with_grounding` method and wire it into the orchestrator. For Google provider, this replaces the call to `_merge_rounds` at the end of `_run_async_impl`. When at least one round has grounding sources in state, the SOURCES section is built from grounding chunks (deduplicated by URI, first title wins). When no rounds have grounding data, falls back to existing `_merge_rounds`. SUMMARY section always comes from LLM text output (same as existing merge).
- **Spec refs**: FR-GME-020, FR-GME-021, FR-GME-022, FR-GME-023, Section 8 (`_merge_rounds_with_grounding` contract)
- **Parallel**: No
- **Acceptance criteria**:
  - [ ] `_merge_rounds_with_grounding` builds SOURCES from grounding sources state keys across all rounds (FR-GME-020/021)
  - [ ] Sources deduplicated by URI across rounds; first occurrence's title wins (FR-GME-021)
  - [ ] Sources formatted as `- [title](uri)` markdown links (FR-GME-021)
  - [ ] SUMMARY section built from LLM text output using existing `_split_sections` logic
  - [ ] When no grounding sources exist for any round: falls back to `_merge_rounds` (FR-GME-022)
  - [ ] Fallback logged at WARNING: "No grounding metadata available for topic {name}/google, falling back to text extraction" (FR-GME-022)
  - [ ] Google grounding redirect URIs preserved as-is in SOURCES (FR-GME-023)
  - [ ] Orchestrator calls `_merge_rounds_with_grounding` instead of `_merge_rounds` for Google provider
  - [ ] Perplexity provider continues to use existing `_merge_rounds`
- **Test requirements**: unit
  - `test_merge_rounds_with_grounding_happy_path` - 3 rounds with grounding produce deduplicated SOURCES
  - `test_merge_rounds_with_grounding_fallback` - no grounding data delegates to `_merge_rounds`
  - `test_merge_rounds_with_grounding_mixed` - some rounds with grounding, some without
- **Depends on**: T23-05 (grounding sources must be in state)
- **Implementation Guidance**:
  - Method signature: `def _merge_rounds_with_grounding(self, state: dict, round_count: int) -> str:`
  - Iterate rounds 0..round_count-1, check for `grounding_sources_{idx}_{prov}_round_{r}` state key
  - Collect sources into `seen_urls: dict[str, str]` (uri -> title) for deduplication (same pattern as existing `_merge_rounds`)
  - Build summary from round text output using existing `_split_sections` (reuse, don't duplicate)
  - Return format: `"SUMMARY:\n{summary}\n\nSOURCES:\n{sources_lines}"`
  - Wire in: replace `merged = self._merge_rounds(state, round_count)` with conditional: if `self.provider == "google"` use `_merge_rounds_with_grounding`, else use `_merge_rounds`
  - Known pitfall: ensure the SUMMARY is still built from ALL rounds' text output, not just rounds with grounding data. Grounding only replaces SOURCES extraction.
  - Test pattern: set up state with `grounding_sources_*` and `research_*_round_*` keys, call `_merge_rounds_with_grounding`, verify output format

### T23-08 - State Cleanup Extension

- **Description**: Update `_cleanup_state` to delete the new grounding-related intermediate state keys after merge completes. Keys to clean: `_grounding_raw_{idx}_{prov}_round_{r}`, `grounding_sources_{idx}_{prov}_round_{r}`, `grounding_supports_{idx}_{prov}_round_{r}`, `grounding_queries_{idx}_{prov}_round_{r}` for all rounds.
- **Spec refs**: FR-GME-013
- **Parallel**: Yes (can be developed in parallel with T23-07) [P]
- **Acceptance criteria**:
  - [ ] `_cleanup_state` deletes `_grounding_raw_{idx}_{prov}_round_{r}` for r in 0..round_count-1
  - [ ] `_cleanup_state` deletes `grounding_sources_{idx}_{prov}_round_{r}` for r in 0..round_count-1
  - [ ] `_cleanup_state` deletes `grounding_supports_{idx}_{prov}_round_{r}` for r in 0..round_count-1
  - [ ] `_cleanup_state` deletes `grounding_queries_{idx}_{prov}_round_{r}` for r in 0..round_count-1
  - [ ] Existing cleanup of `research_*_round_*`, `adaptive_plan`, `adaptive_analysis`, etc. is unchanged
  - [ ] Keys that don't exist are silently skipped (no KeyError)
- **Test requirements**: unit - extend existing `TestCleanupState` class
- **Depends on**: T23-02 (state key naming convention established)
- **Implementation Guidance**:
  - Current `_cleanup_state` method (deep_research.py lines ~512-530) uses `state.pop(key, None)` pattern for safe deletion
  - Add 4 new cleanup loops (one per key pattern) in the same method, after the existing `research_{idx}_{prov}_round_{r}` cleanup loop
  - Follow the existing pattern: `state.pop(f"_grounding_raw_{idx}_{prov}_round_{r}", None)` in a `for r in range(round_count)` loop
  - Test pattern: extend the existing `TestCleanupState` class in `test_deep_research.py`. Set grounding keys in state, call cleanup, verify they're removed.

### T23-09 - Observability Logging

- **Description**: Add structured logging throughout the grounding extraction flow as specified in Section 10.5. Four log messages: INFO after each Google round extraction (chunk/support/query counts), WARNING on fallback, INFO at merge time (total unique sources), WARNING on empty titles. Verify Perplexity provider does NOT trigger any grounding-related log messages.
- **Spec refs**: Section 10.5 (LOG-001 through LOG-004), FR-GME-005, FR-GME-032, US-04
- **Parallel**: Yes (can be done alongside T23-07/T23-08 since it's additive logging) [P]
- **Acceptance criteria**:
  - [ ] LOG-001: After successful grounding extraction, logs at INFO: `"[Grounding] Topic {name}/google round {r}: {n} chunks, {s} supports, {q} queries"` (Section 10.5)
  - [ ] LOG-002: On fallback, logs at WARNING: `"[Grounding] Topic {name}/google round {r}: no grounding metadata, falling back to text extraction"` (Section 10.5)
  - [ ] LOG-003: At merge time, logs at INFO: `"[Grounding] Topic {name}/google: merged {n} unique sources from grounding metadata across {r} rounds"` (Section 10.5)
  - [ ] LOG-004: On empty title, logs at WARNING: `"[Grounding] Topic {name}/google round {r}: chunk {i} has empty title, using URI"` (Section 10.5)
  - [ ] Perplexity provider rounds produce zero `[Grounding]` log messages
- **Test requirements**: unit - verify log messages with `caplog` fixture
- **Depends on**: T23-05, T23-07 (logging sites are in the orchestrator loop and merge method)
- **Implementation Guidance**:
  - Use the existing `logger = logging.getLogger(__name__)` in deep_research.py
  - Follow the existing log format convention: `"[AdaptiveResearch] ..."` but use `"[Grounding] ..."` prefix for grounding-specific messages
  - LOG-001 and LOG-002 go in the orchestrator loop (T23-05 code), after `_parse_grounding_from_state`
  - LOG-003 goes in `_merge_rounds_with_grounding` (T23-07 code), after deduplication
  - LOG-004 goes in `_parse_grounding_from_state` (T23-03 code), during chunk processing
  - Test pattern: use `caplog` pytest fixture to capture log output, assert on message content and level

### T23-10 - Acceptance & Integration Tests

- **Description**: Write BDD acceptance tests for the 5 scenarios from spec Section 11.2, integration tests IT-001 through IT-003, and validate the full pipeline with an E2E run. Ensure 80% code coverage and 90% branch coverage on new/modified methods. Run the complete test suite to confirm zero regressions.
- **Spec refs**: Section 11.2 (BDD scenarios), Section 11.3 (IT-001 through IT-003), Section 11.4 (E2E), SC-002, SC-004
- **Parallel**: No
- **Acceptance criteria**:
  - [ ] BDD scenario: "Google search round captures grounding metadata" passes
  - [ ] BDD scenario: "Google search round without grounding metadata falls back" passes
  - [ ] BDD scenario: "Multi-round merge uses grounding sources" passes
  - [ ] BDD scenario: "Perplexity provider is unaffected" passes
  - [ ] BDD scenario: "Broken grounding URL is cleaned up" passes
  - [ ] IT-001: Pipeline run with Google search produces SOURCES from grounding metadata (mocked)
  - [ ] IT-002: Mixed provider pipeline produces correct per-provider sources (mocked)
  - [ ] IT-003: Link verification correctly handles grounding chunk URLs (mocked)
  - [ ] New/modified methods in deep_research.py: >= 80% code coverage, >= 90% branch coverage
  - [ ] Full test suite passes with zero regressions (all existing tests still pass)
  - [ ] E2E pipeline run (manual or CI) produces newsletter with zero synthetic/placeholder Google URLs (SC-002)
- **Test requirements**: BDD, integration, E2E
- **Depends on**: T23-01 through T23-09 (all implementation must be complete)
- **Implementation Guidance**:
  - BDD tests go in `tests/bdd/` following existing project structure
  - Integration tests go in `tests/integration/` following existing conventions
  - Mocking strategy from spec: mock `LlmAgent.run_async` to yield events, set up session state with pre-built grounding data. Do NOT mock the Gemini API directly.
  - For the orchestrator integration test, use the existing mock pattern from `test_deep_research.py`: `patch.object(orch, "_make_search_agent")` returning a mock agent, with state pre-populated
  - Coverage check: `pytest --cov=newsletter_agent/tools/deep_research --cov-branch --cov-report=term-missing`
  - E2E validation: run `python -m newsletter_agent` with a topic using google_search, inspect output HTML and logs
  - Known pitfall: BDD tests need realistic grounding metadata fixtures. Create a `conftest.py` fixture or helper that builds `types.GroundingMetadata`-like mock objects with the correct nested structure.

## Implementation Notes

### Import Changes

`deep_research.py` needs these new imports:
```python
import dataclasses
from typing import Any
# Conditional/lazy for ADK callback types:
from google.adk.agents.callback_context import CallbackContext  # or equivalent
from google.adk.models.llm_response import LlmResponse
```

### State Key Naming Convention

All new state keys follow the existing pattern `{prefix}_{idx}_{prov}_round_{r}`:
- `_grounding_raw_{idx}_{prov}_round_{r}` - raw callback data (underscore prefix = internal)
- `grounding_sources_{idx}_{prov}_round_{r}` - processed sources
- `grounding_supports_{idx}_{prov}_round_{r}` - processed supports
- `grounding_queries_{idx}_{prov}_round_{r}` - executed queries

### Callback Closure Pattern

The callback needs round-specific context. Recommended approach:
```python
def _make_grounding_callback(idx: int, prov: str, round_idx: int):
    def _callback(callback_context, llm_response):
        # ... capture grounding_metadata to state
        state = callback_context.state
        key = f"_grounding_raw_{idx}_{prov}_round_{round_idx}"
        # ... serialize and write
    return _callback
```

### Backward Compatibility

- The `_merge_rounds` method is NOT removed. It becomes the fallback for:
  1. Perplexity provider (always)
  2. Google provider when no grounding metadata exists (rare)
- The `_extract_urls` method is NOT removed. It remains used for:
  1. Perplexity provider URL tracking
  2. Google provider fallback URL tracking (when no grounding metadata)
  3. Existing text cleanup flows (markdown link removal for broken URLs)

## Parallel Opportunities

- [P] T23-03 and T23-04 can run concurrently after T23-02 completes
- [P] T23-08 can run concurrently with T23-07 (cleanup is independent of merge logic)
- [P] T23-09 can run concurrently with T23-07/T23-08 (additive logging, no structural changes)

## Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|-----------|-----------|
| `after_model_callback` fires before grounding metadata is attached (OQ-1) | High - callback sees None, no metadata captured | Medium | T23-01 spike verifies this first. Fallback: read `temp:_adk_grounding_metadata` from session state instead. Spec Section 14 documents this mitigation. |
| Google ADK upgrade changes grounding metadata structure | Medium - parse fails silently, falls back to regex | Low | `_parse_grounding_from_state` wraps all access in try/except. Fallback to `_merge_rounds` preserves existing behavior. LOG-002 warns on fallback. |
| Grounding chunks contain non-HTTPS URIs | Low - validation rejects them | Low | `_parse_grounding_from_state` skips chunks without `https://` prefix (spec Section 7 validation rules). |
| Perplexity path regression | High - breaks non-Google topics | Low | T23-05 has explicit test: `test_perplexity_unchanged`. All existing Perplexity tests continue to run. |
| Performance degradation from event collection | Very Low - in-memory only | Very Low | Event list is not collected (callback handles capture). NFR-001 specifies < 1ms extraction time. |

## Activity Log

- 2026-03-22T00:00:00Z - planner - lane=planned - Work package created
