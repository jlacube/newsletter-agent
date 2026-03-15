---
lane: doing
---

# WP13 - Deep Research Source Refinement

> **Spec**: `specs/autonomous-deep-research.spec.md`
> **Status**: Complete
> **Priority**: P1 (MVP user story US-04)
> **Goal**: After multi-round research and link verification, an LLM-based refiner selects the 5-10 most relevant sources per provider per deep-mode topic, removing noise from the large URL pool
> **Independent Test**: Configure a deep-mode topic. Run the pipeline. Verify that after refinement, each topic-provider has between 5 and 10 sources (visible in refinement log: "Refined topic X/Y: 20 -> 8 sources").
> **Depends on**: WP12 (multi-round research produces the large source pool that needs refinement)
> **Parallelisable**: No (modifies `build_pipeline()` in `agent.py`; depends on WP12 state key output)
> **Prompt**: `plans/WP13-source-refinement.md`

## Objective

This work package implements the source refinement step: a `DeepResearchRefinerAgent` (BaseAgent) that evaluates all verified sources for deep-mode topics and selects the 5-10 most relevant per provider using LLM-based relevance scoring. This prevents synthesis from being overwhelmed by the large URL pool produced by multi-round research, ensuring the newsletter cites only high-quality, diverse sources.

## Spec References

- FR-REF-001 through FR-REF-007 (Section 4.4)
- FR-PIP-001, FR-PIP-002 (Section 4.5)
- US-04 (Section 5)
- Section 6 Flow C (Source Refinement)
- Section 8.3 (Agent Contract: DeepResearchRefinerAgent)
- Section 9.1 (Architecture Diagram - DeepResearchRefiner position)
- Section 11.1 (Unit Tests: DeepResearchRefinerAgent, Pipeline order)
- Section 11.2 (BDD: Deep Research Source Refinement scenarios)

## Tasks

### T13-01 - Create refinement prompt template
- **Description**: Create `newsletter_agent/prompts/refinement.py` with a function that returns the source refinement instruction for the LLM evaluation call.
- **Spec refs**: FR-REF-003, Section 4.4 (Refinement LLM prompt contract)
- **Parallel**: Yes [P] (independent of T13-02)
- **Acceptance criteria**:
  - [ ] Module `newsletter_agent/prompts/refinement.py` exists
  - [ ] Function `get_refinement_instruction(topic_name: str, target_count: int, research_text: str, source_list: str) -> str` returns the prompt
  - [ ] Prompt instructs LLM to evaluate sources by: topical relevance, source diversity, recency, information density (in that order) (FR-REF-003)
  - [ ] Prompt specifies JSON output format: `{"selected_urls": [...], "rationale": "..."}` (Section 4.4)
  - [ ] Prompt instructs selection of between 5 and 10 sources (FR-REF-005)
  - [ ] Prompt includes the full research text and current source list as context
- **Test requirements**: unit (test prompt contains expected elements)
- **Depends on**: none
- **Implementation Guidance**:
  - Follow existing prompt module pattern in `newsletter_agent/prompts/research_google.py`.
  - The prompt template is defined in spec Section 4.4 "Refinement LLM prompt contract":
    ```
    You are a research source curator. Given the following research text and sources
    for the topic "{topic_name}", select the {target_count} most relevant and diverse sources.
    ...
    Return a JSON object with:
    - "selected_urls": list of the {target_count} most relevant URLs (strings)
    - "rationale": one-sentence explanation of selection strategy
    ```
  - Use `str.format()` for interpolation.

### T13-02 - Create DeepResearchRefinerAgent BaseAgent
- **Description**: Create `newsletter_agent/tools/deep_research_refiner.py` with the `DeepResearchRefinerAgent` class extending BaseAgent. Implement constructor, Pydantic fields, and the skeleton of `_run_async_impl`.
- **Spec refs**: FR-REF-001, FR-REF-006, Section 8.3 (DeepResearchRefinerAgent contract)
- **Parallel**: Yes [P] (independent of T13-01)
- **Acceptance criteria**:
  - [ ] Module `newsletter_agent/tools/deep_research_refiner.py` exists
  - [ ] `DeepResearchRefinerAgent` extends `BaseAgent` (FR-REF-001)
  - [ ] Has `model_config = {"arbitrary_types_allowed": True}` (follows existing pattern)
  - [ ] Constructor fields: `topic_count: int`, `providers: list`, `topic_configs: list` (Section 8.3)
  - [ ] `_run_async_impl(self, ctx)` is defined as async generator
  - [ ] Iterates over topics and providers, checks `search_depth == "deep"` for each (FR-REF-006)
  - [ ] Skips standard-mode topics with no modification (FR-REF-006)
- **Test requirements**: unit (test class instantiation, no-op for standard topics)
- **Depends on**: none
- **Implementation Guidance**:
  - Follow existing BaseAgent pattern from `newsletter_agent/tools/link_verifier_agent.py`.
  - Key imports: `from google.adk.agents import BaseAgent`, `from google.adk.agents.invocation_context import InvocationContext`, `from google.adk.events import Event`
  - The agent does NOT use LlmAgent as a sub-agent. Instead, it calls the Gemini API directly using `google.genai` for the refinement evaluation. This avoids the overhead of creating dynamic LlmAgents.
  - Alternative approach: Use `google.genai.Client().aio.models.generate_content()` for the LLM call, which is a direct API call without ADK agent overhead.
  - If using direct API call: `from google import genai; client = genai.Client(); response = await client.aio.models.generate_content(model="gemini-2.5-flash", contents=prompt)`

### T13-03 - Implement source extraction and count check
- **Description**: Implement the logic to extract source URLs from `research_{idx}_{provider}` state keys and determine if refinement is needed (count > 10) or should be skipped (count <= 10 or count < 5).
- **Spec refs**: FR-REF-002, FR-REF-005, Section 6 Flow C (steps 2a-2d)
- **Parallel**: No (depends on T13-02)
- **Acceptance criteria**:
  - [ ] Extracts all markdown URLs from `research_{idx}_{provider}` state value
  - [ ] If source count <= 10: skips refinement for this topic-provider (no LLM call) (Section 8.3 no-op condition)
  - [ ] If source count < 5: keeps all sources without filtering (FR-REF-005)
  - [ ] If source count > 10: proceeds to LLM refinement (FR-REF-002)
  - [ ] Logs source count before refinement decision (FR-REF-007)
- **Test requirements**: unit (test count thresholds and skip logic)
- **Depends on**: T13-02
- **Implementation Guidance**:
  - Reuse the URL extraction regex from WP12 (T12-06): `r'\[([^\]]*)\]\((https?://[^\)]+)\)'`
  - Or factor it into a shared utility if both WP12 and WP13 need it. Consider adding to `newsletter_agent/tools/research_utils.py`.
  - Decision tree: `count > 10 -> refine`, `5 <= count <= 10 -> skip (already in range)`, `count < 5 -> skip (keep all)`
  - Log pattern: `logger.info(f"[Refinement] Topic {topic_name}/{provider}: {count} sources, {'refining' if count > 10 else 'skipping'}")`

### T13-04 - Implement LLM-based source evaluation
- **Description**: When refinement is needed (> 10 sources), call the LLM with the refinement prompt, parse the JSON response to get selected URLs, and handle all error cases.
- **Spec refs**: FR-REF-003, FR-REF-005, Section 4.4 (Error behavior)
- **Parallel**: No (depends on T13-03)
- **Acceptance criteria**:
  - [ ] Calls LLM (gemini-2.5-flash) with refinement prompt containing research text and source list (FR-REF-003)
  - [ ] Parses JSON response to extract `selected_urls` list
  - [ ] Validates selection: clamps to [5, 10] range if LLM selects outside bounds (FR-REF-005, spec error behavior)
  - [ ] If LLM call fails (API error): keeps all sources, logs warning (spec error behavior)
  - [ ] If LLM returns invalid JSON: keeps all sources, logs warning (spec error behavior)
  - [ ] If LLM returns empty selection: keeps all sources, logs warning
  - [ ] Target count: `min(10, source_count)` passed to prompt (aim for best 10 or fewer)
- **Test requirements**: unit (mock LLM call, test JSON parsing, error handling)
- **Depends on**: T13-03, T13-01
- **Implementation Guidance**:
  - LLM call option A (direct API): `from google import genai; client = genai.Client(); response = await client.aio.models.generate_content(model="gemini-2.5-flash", contents=prompt)`
  - LLM call option B (ADK LlmAgent sub-agent): Create a temporary LlmAgent, invoke via `run_async(ctx)`, read output from state. More ADK-idiomatic but heavier.
  - Recommended: Option A (direct API call) as the refiner is a data processing step, not a conversational agent.
  - JSON parsing: `json.loads(response.text)` -- handle `json.JSONDecodeError`, handle missing `selected_urls` key.
  - Clamping: If `len(selected_urls) < 5`: keep all original sources (don't use LLM selection). If `len(selected_urls) > 10`: take first 10.
  - Known pitfall: LLM may return URLs not in the original list. Filter `selected_urls` to only include URLs that actually exist in the source list.

### T13-05 - Implement in-place state update
- **Description**: After selecting the best sources, update `research_{idx}_{provider}` state key in-place: remove references to non-selected sources from both the text and SOURCES section.
- **Spec refs**: FR-REF-004, Section 6 Flow C (steps 2f-2g)
- **Parallel**: No (depends on T13-04)
- **Acceptance criteria**:
  - [ ] Updates `research_{idx}_{provider}` state key in-place (FR-REF-004)
  - [ ] Removes non-selected source references from the SOURCES section
  - [ ] Preserves all SUMMARY text (does not modify analysis content)
  - [ ] After update, research text has exactly the selected number of sources in SOURCES section
  - [ ] Logs before/after source counts: "Refined topic {name}/{provider}: {before} -> {after} sources" (FR-REF-007)
- **Test requirements**: unit (test state update with known input/output)
- **Depends on**: T13-04
- **Implementation Guidance**:
  - Parse research text into SUMMARY and SOURCES sections (split on `\nSOURCES:\n` or similar delimiter).
  - Filter SOURCES lines: keep only lines whose URL is in `selected_urls` set.
  - Reassemble: `f"SUMMARY:\n{summary_text}\n\nSOURCES:\n{filtered_sources}"`
  - Write back to state: `ctx.session.state[key] = updated_text`
  - Edge case: Some research text may not have a clean SUMMARY/SOURCES split. Handle gracefully -- if no SOURCES section found, skip refinement for this entry.

### T13-06 - Add DeepResearchRefinerAgent to pipeline
- **Description**: Modify `build_pipeline()` in `agent.py` to insert `DeepResearchRefinerAgent` between LinkVerifier and Synthesizer.
- **Spec refs**: FR-PIP-001, FR-PIP-002, Section 9.1
- **Parallel**: No (depends on T13-05)
- **Acceptance criteria**:
  - [ ] Pipeline order is: ConfigLoader, ResearchPhase, ResearchValidator, PipelineAbortCheck, LinkVerifier, **DeepResearchRefiner**, Synthesizer, SynthesisPostProcessor, OutputPhase (FR-PIP-001)
  - [ ] DeepResearchRefinerAgent is at position [5] in pipeline sub_agents list (after LinkVerifier at [4]) (FR-PIP-002)
  - [ ] Refiner receives `topic_count`, `providers`, `topic_configs` from config
  - [ ] All existing pipeline agents remain in correct order
- **Test requirements**: unit (extend `tests/unit/test_agent_factory.py`)
- **Depends on**: T13-05
- **Implementation Guidance**:
  - File to modify: `newsletter_agent/agent.py`, function `build_pipeline()` (lines 329-413)
  - Import: `from newsletter_agent.tools.deep_research_refiner import DeepResearchRefinerAgent`
  - Construction:
    ```python
    refiner = DeepResearchRefinerAgent(
        name="DeepResearchRefiner",
        topic_count=len(config.topics),
        providers=[...],  # Collect unique providers across all topics
        topic_configs=config.topics,
    )
    ```
  - Insert in sub_agents list between LinkVerifier and Synthesizer.
  - The refiner is always added to the pipeline (even if no deep topics exist). For standard-only configs, it's a no-op.

### T13-07 - Unit tests for DeepResearchRefinerAgent
- **Description**: Write comprehensive unit tests for the refiner covering all modes, error handling, and edge cases.
- **Spec refs**: Section 11.1 (DeepResearchRefinerAgent tests)
- **Parallel**: No (depends on T13-06)
- **Acceptance criteria**:
  - [ ] Test no-op for standard-mode topics (no LLM call, state unchanged)
  - [ ] Test selects 5-10 sources when pool > 10 (mock LLM returns valid selection)
  - [ ] Test keeps all sources when pool < 5 (no LLM call)
  - [ ] Test keeps all sources when pool is 5-10 (no LLM call, already in range)
  - [ ] Test keeps all sources on LLM failure (API error)
  - [ ] Test keeps all sources on invalid JSON from LLM
  - [ ] Test keeps all sources when LLM returns empty selection
  - [ ] Test clamping: LLM selects > 10 URLs -- only first 10 kept
  - [ ] Test clamping: LLM selects < 5 URLs -- all original sources kept
  - [ ] Test state key updated in-place (before/after comparison)
  - [ ] Test log output for source counts (before -> after)
  - [ ] Test multiple topics: one deep, one standard -- only deep topic refined
  - [ ] All tests pass with >= 80% code coverage for `deep_research_refiner.py`
- **Test requirements**: unit (new file `tests/unit/test_deep_research_refiner.py`)
- **Depends on**: T13-06
- **Implementation Guidance**:
  - Mock the LLM call (whether direct API or LlmAgent). For direct API: `@patch("google.genai.Client")` or similar.
  - Create mock InvocationContext with session state containing known research text with 20 sources.
  - For no-op tests: set `topic.search_depth = "standard"`, verify state unchanged.
  - For error tests: mock LLM to raise exception or return malformed JSON, verify state unchanged and warning logged.
  - Use `caplog` fixture to verify log messages.

### T13-08 - BDD tests for source refinement
- **Description**: Write BDD-style acceptance tests for the four source refinement scenarios from the spec.
- **Spec refs**: US-04, Section 11.2 (Feature: Deep Research Source Refinement)
- **Parallel**: No (depends on T13-07)
- **Acceptance criteria**:
  - [ ] BDD scenario: Sources refined to 5-10 per provider -- deep topic with 20 sources refined to 5-10
  - [ ] BDD scenario: Few sources kept without filtering -- deep topic with 3 sources, all kept
  - [ ] BDD scenario: Refinement no-op for standard mode -- standard topic sources unchanged
  - [ ] BDD scenario: Graceful degradation on LLM failure -- all sources kept, warning logged
  - [ ] Tests follow existing BDD pattern in `tests/bdd/`
- **Test requirements**: BDD (new file `tests/bdd/test_source_refinement.py`)
- **Depends on**: T13-07
- **Implementation Guidance**:
  - Follow existing BDD pattern in `tests/bdd/`.
  - For "refined to 5-10" scenario: set up state with 20 mock sources, mock LLM to return 8 selected, verify final count is 8.
  - For "few sources" scenario: set up state with 3 sources, verify no LLM call made (use mock assertion), verify all 3 kept.
  - For "standard mode" scenario: set up standard-mode topic config, verify refiner is no-op.
  - For "LLM failure" scenario: mock LLM to raise exception, verify all sources kept and warning in caplog.

## Implementation Notes

- The refiner uses a direct LLM API call (not an LlmAgent sub-agent) because it's a data processing step, not a conversational agent. This is simpler and avoids creating dynamic LlmAgents.
- The URL extraction regex should be consistent between WP12 (DeepResearchOrchestrator URL tracking) and WP13 (refiner source extraction). Consider extracting to a shared utility in `research_utils.py`.
- The refiner always runs in the pipeline (even for standard-only configs) but is a no-op for standard topics. This simplifies pipeline construction.
- The SOURCES section format in research text uses markdown links: `- [Title](URL)`. The refiner filters these lines based on URL matching.

## Parallel Opportunities

- T13-01 (prompt template) and T13-02 (agent skeleton) can be worked concurrently [P].
- All other tasks are sequential.

## Risks & Mitigations

- **Risk**: LLM refinement may select sources that are not the most relevant (LLM judgment). **Mitigation**: Prompt engineering with explicit evaluation criteria in priority order. Users can review output quality and adjust prompt.
- **Risk**: Research text format may not have clean SUMMARY/SOURCES split in all cases. **Mitigation**: T13-05 handles this edge case -- if no SOURCES section found, skip refinement for that entry.
- **Risk**: Direct LLM API call may require different authentication than ADK's built-in agent calls. **Mitigation**: Use `google.genai.Client()` which reads the same `GOOGLE_API_KEY` env var as ADK. Test in CI.

## Activity Log
- 2026-03-15T00:00:00Z - planner - lane=planned - Work package created
- 2026-03-15T12:00:00Z - coder - lane=doing - Starting WP13 implementation. Baseline: 477 tests passing.
- 2026-03-15T13:00:00Z - coder - lane=doing - All 8 tasks complete. 523 tests passing (477 + 37 unit + 9 BDD). Coverage: 94.68% (95% code, 92% branch).

## Self-Review

### Spec Compliance Checklist

- [x] FR-REF-001: DeepResearchRefinerAgent added to pipeline between LinkVerifier and Synthesizer (position [5])
- [x] FR-REF-002: Evaluates verified source URLs in research_{idx}_{provider} for deep-mode topics, selects 5-10 per provider
- [x] FR-REF-003: LLM-based evaluation using gemini-2.5-flash with criteria: topical relevance, diversity, recency, information density
- [x] FR-REF-004: Updates research_{idx}_{provider} state keys in-place, removing non-selected sources
- [x] FR-REF-005: After refinement, 5-10 sources per deep-mode topic-provider. < 5 verified sources kept without filtering. Clamping enforced.
- [x] FR-REF-006: Standard-mode topics are no-op (pass through without modification)
- [x] FR-REF-007: Logs before/after source counts for each topic-provider
- [x] FR-PIP-001: Pipeline order: ConfigLoader, ResearchPhase, ResearchValidator, PipelineAbortCheck, LinkVerifier, DeepResearchRefiner, Synthesizer, SynthesisPostProcessor, OutputPhase
- [x] FR-PIP-002: DeepResearchRefinerAgent at position [5] after LinkVerifier and before Synthesizer

### Review Checklist

- [x] All acceptance criteria from the spec are met
- [x] All 523 tests pass (477 existing + 37 unit + 9 BDD)
- [x] Edge cases handled: < 5 sources, 5-10 sources, > 10 sources, LLM failure, invalid JSON, empty selection, URLs not in source list
- [x] Error paths: API failure keeps all sources, invalid JSON keeps all sources, empty selection keeps all sources
- [x] No unused code, dead imports, or debug artifacts
- [x] No hardcoded values in config (model name is a module constant)
- [x] No security issues (no user-controlled input in prompts, no injection risk)
- [x] No em dashes, smart quotes, or curly apostrophes
- [x] Implementation does not exceed spec scope
- [x] Coverage: 94.68% overall (95% code, 92% branch) -- exceeds 80% code / 90% branch thresholds
- [x] Documentation updated: architecture.md, api-reference.md, developer-guide.md, user-guide.md

### Outstanding Issues

None.
