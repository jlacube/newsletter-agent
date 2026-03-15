---
lane: for_review
---

# WP16 - Adaptive Research Orchestrator

> **Spec**: `specs/002-adaptive-deep-research.spec.md`
> **Status**: Complete
> **Priority**: P1
> **Goal**: Replace the fan-out query expansion with an adaptive Plan-Search-Analyze-Decide loop in DeepResearchOrchestrator
> **Independent Test**: Configure a topic with `search_depth: "deep"` and `max_research_rounds: 3`. Run `pytest tests/unit/test_adaptive_research.py -v` and verify all adaptive loop unit tests pass. Inspect that `[AdaptiveResearch]` log entries appear in test output showing planning, per-round analysis, and exit reason.
> **Depends on**: WP15
> **Parallelisable**: No
> **Prompt**: `plans/WP16-adaptive-orchestrator.md`

## Objective

This work package implements the core adaptive research loop that replaces the pre-generated query fan-out in `DeepResearchOrchestrator`. After this WP, deep-mode topics will follow the Plan-Search-Analyze-Decide cycle: a PlanningAgent identifies key aspects and an initial search query, each search round is followed by an AnalysisAgent that evaluates findings and suggests the next query, and the orchestrator exits when saturation is detected or configured limits are reached. This is the MVP user story (US-ADR-01, US-ADR-02).

## Spec References

- FR-ADR-001 through FR-ADR-006 (Adaptive Loop Architecture, Section 4.1)
- FR-ADR-010 through FR-ADR-014 (Planning Phase, Section 4.2)
- FR-ADR-020 through FR-ADR-022 (Search Phase, Section 4.3)
- FR-ADR-030 through FR-ADR-035 (Analysis Phase, Section 4.4)
- FR-ADR-040 through FR-ADR-044 (Exit Criteria, Section 4.5)
- FR-ADR-050 through FR-ADR-055 (State Management, Section 4.6)
- FR-ADR-080 through FR-ADR-085 (Backward Compatibility, Section 4.9)
- Section 6 (User Flows A, B, C)
- Section 7.2-7.5 (Session State keys, Data Contracts)
- Section 8.1 (Agent Contracts)
- Section 9.4 (Design Decisions ADR-1 through ADR-4)
- Section 10.5 (Observability log formats)

## Tasks

### T16-01 - Update orchestrator constructor and remove URL threshold

- **Description**: Modify `DeepResearchOrchestrator.__init__` (or Pydantic field declarations) to accept a new `max_searches` parameter. Remove the `_MIN_URLS_THRESHOLD = 15` constant. Remove the import of `get_query_expansion_instruction` from `query_expansion.py`. Add import of `get_planning_instruction` and `get_analysis_instruction` from `reasoning.py`.
- **Spec refs**: FR-ADR-004, FR-ADR-041, FR-ADR-061, Section 8.1 (DeepResearchOrchestrator contract)
- **Parallel**: No
- **Acceptance criteria**:
  - [ ] `DeepResearchOrchestrator` has a new Pydantic field `max_searches: int = 3` alongside existing `max_rounds`
  - [ ] The class-level constant `_MIN_URLS_THRESHOLD = 15` is removed
  - [ ] Import of `get_query_expansion_instruction` is removed
  - [ ] Imports of `get_planning_instruction` and `get_analysis_instruction` from `newsletter_agent.prompts.reasoning` are added
  - [ ] Existing `DeepResearchOrchestrator(name=..., topic_idx=..., ...)` instantiation still works (the new field has a default)
  - [ ] A new field `min_rounds: int = 2` is added (used by exit criteria in T16-05)
- **Test requirements**: unit (constructor/instantiation tests)
- **Depends on**: WP15 (reasoning.py must exist)
- **Implementation Guidance**:
  - File to modify: `newsletter_agent/tools/deep_research.py`
  - The current class uses Pydantic field declarations (lines ~50-60): `topic_idx: int = 0`, `provider: str = ""`, etc. Add `max_searches: int = 3` and `min_rounds: int = 2` in the same style.
  - Remove line: `from newsletter_agent.prompts.query_expansion import get_query_expansion_instruction`
  - Add: `from newsletter_agent.prompts.reasoning import get_planning_instruction, get_analysis_instruction`
  - Remove: `_MIN_URLS_THRESHOLD = 15`
  - Keep `_FALLBACK_SUFFIXES` list -- it is reused for analysis fallback queries
  - Keep `_MARKDOWN_LINK_RE` and `_BARE_URL_RE` -- they are reused by `_extract_urls`
  - Known pitfall: The existing `_expand_queries` method calls `get_query_expansion_instruction`. Removing the import will break `_expand_queries`. That is intentional -- T16-04 replaces the entire `_run_async_impl` which no longer calls `_expand_queries`.

### T16-02 - Implement PlanningAgent creation and invocation

- **Description**: Add a private method `_run_planning(self, ctx: InvocationContext) -> tuple[str, list[str], list[Event]]` that creates a `PlanningAgent` LlmAgent, invokes it, parses the JSON output, and returns the initial search query and key aspects. Includes full fallback logic for invalid output.
- **Spec refs**: FR-ADR-010 through FR-ADR-014, Section 4.2, Section 7.5 (PlanningOutput schema), Section 8.1 (PlanningAgent contract)
- **Parallel**: Yes (can be developed alongside T16-03)
- **Acceptance criteria**:
  - [ ] Method creates an `LlmAgent` named `AdaptivePlanner_{idx}_{provider}` using `self.model` with no tools
  - [ ] Agent's `output_key` is `adaptive_plan_{idx}_{provider}`
  - [ ] Agent's instruction is generated by `get_planning_instruction(self.query, self.topic_name)`
  - [ ] On valid JSON output: extracts `initial_search_query` (string) and `key_aspects` (list of 3-5 strings)
  - [ ] On valid output with < 3 key_aspects: pads with items from default list `["recent developments", "expert opinions", "data and statistics", "industry implications", "emerging trends"]`
  - [ ] On valid output with > 5 key_aspects: truncates to first 5
  - [ ] On invalid JSON or missing required fields: falls back to `self.query` as initial query and the full default aspects list
  - [ ] Fallback logs warning: `"[AdaptiveResearch] Planning failed for {topic_name}/{provider}, using fallback"`
  - [ ] Returns tuple: `(initial_search_query, key_aspects, events_list)`
- **Test requirements**: unit
- **Depends on**: T16-01 (imports must be in place)
- **Implementation Guidance**:
  - File to modify: `newsletter_agent/tools/deep_research.py`
  - Create the LlmAgent dynamically within the method (same pattern as existing `_make_search_agent`):
    ```python
    planner = LlmAgent(
        name=f"AdaptivePlanner_{self.topic_idx}_{self.provider}",
        model=self.model,
        instruction=get_planning_instruction(self.query, self.topic_name),
        output_key=f"adaptive_plan_{self.topic_idx}_{self.provider}",
    )
    ```
  - Invoke with: `async for event in planner.run_async(ctx): events.append(event)`
  - Read output from state: `raw = state.get(f"adaptive_plan_{self.topic_idx}_{self.provider}", "")`
  - Parse with `json.loads(raw)` in a try/except block
  - Validate required keys: `query_intent`, `key_aspects`, `initial_search_query`, `search_rationale`
  - Validate string fields are non-empty (empty string treated as missing per spec Section 7.5)
  - ADK docs confirm: LlmAgent without `tools` parameter means no tools are available to the agent
  - Known pitfall: The LLM may wrap JSON in markdown code fences. Strip them before parsing (the existing `_parse_variants` method has this logic -- reuse the pattern: strip leading/trailing backticks and "json" language tag)

### T16-03 - Implement AnalysisAgent creation and invocation

- **Description**: Add a private method `_run_analysis(self, ctx, topic_name, query, key_aspects, prior_rounds_summary, latest_results, round_idx, current_query, remaining_searches) -> tuple[dict, list[Event]]` that creates an `AnalysisAgent` LlmAgent, invokes it, parses the JSON output, and returns the analysis result dict. Includes full fallback logic.
- **Spec refs**: FR-ADR-030 through FR-ADR-035, Section 4.4, Section 7.5 (AnalysisOutput schema), Section 8.1 (AnalysisAgent contract)
- **Parallel**: Yes (can be developed alongside T16-02)
- **Acceptance criteria**:
  - [ ] Method creates an `LlmAgent` named `AdaptiveAnalyzer_{idx}_{provider}_r{round_idx}` using `self.model` with no tools
  - [ ] Agent's `output_key` is `adaptive_analysis_{idx}_{provider}`
  - [ ] Agent's instruction is generated by `get_analysis_instruction(...)` with all 8 parameters
  - [ ] On valid JSON: returns dict with keys `findings_summary`, `knowledge_gaps`, `coverage_assessment`, `saturated`, `next_query`, `next_query_rationale`
  - [ ] When `saturated=true` and `next_query` is null: accepted (no error)
  - [ ] When `saturated=false` and `next_query` is missing/empty: triggers fallback, sets `next_query` to fallback suffix query
  - [ ] `knowledge_gaps` list truncated to first 5 items if more than 5 returned
  - [ ] On invalid JSON: falls back with `saturated=false`, `next_query` from next unused suffix in `_FALLBACK_SUFFIXES`, logs warning `"[AdaptiveResearch] Analysis failed for {topic_name}/{provider} round {N}, using fallback query"`
  - [ ] Returns tuple: `(analysis_dict, events_list)`
- **Test requirements**: unit
- **Depends on**: T16-01 (imports must be in place)
- **Implementation Guidance**:
  - File to modify: `newsletter_agent/tools/deep_research.py`
  - Create LlmAgent dynamically:
    ```python
    analyzer = LlmAgent(
        name=f"AdaptiveAnalyzer_{self.topic_idx}_{self.provider}_r{round_idx}",
        model=self.model,
        instruction=get_analysis_instruction(
            topic_name=self.topic_name, query=self.query,
            key_aspects=key_aspects,
            prior_rounds_summary=prior_rounds_summary,
            latest_results=latest_results,
            round_idx=round_idx,
            current_query=current_query,
            remaining_searches=remaining_searches,
        ),
        output_key=f"adaptive_analysis_{self.topic_idx}_{self.provider}",
    )
    ```
  - Read output from state, parse JSON with try/except, strip markdown fences
  - Fallback suffix selection: maintain a counter or use `round_idx % len(_FALLBACK_SUFFIXES)` to cycle through suffixes. The fallback query format is: `f"{self.query} {_FALLBACK_SUFFIXES[suffix_idx]}"`
  - Validate `next_query` presence when `saturated=false`: if missing, apply fallback
  - Known pitfall: The AnalysisAgent output_key is reused across rounds (overwritten each time). This is by design -- only the latest analysis matters.

### T16-04 - Rewrite `_run_async_impl` with adaptive loop

- **Description**: Replace the entire body of `_run_async_impl` with the adaptive Plan-Search-Analyze-Decide loop. Remove `_expand_queries` and `_parse_variants` methods. This is the core orchestration change.
- **Spec refs**: FR-ADR-001 through FR-ADR-006, Section 4.1, Section 6 (Flow A, B, C), Section 8.1 (behavior contract)
- **Parallel**: No (depends on T16-02, T16-03)
- **Acceptance criteria**:
  - [ ] When `max_rounds > 1`: PlanningAgent is invoked first, producing initial query and key aspects
  - [ ] When `max_rounds == 1`: planning is skipped, original query used directly (Flow B, backward compat)
  - [ ] Round 0 uses the initial search query from PlanningAgent (or original query in single-round mode)
  - [ ] Subsequent rounds use `next_query` from AnalysisAgent output
  - [ ] Each search round uses the existing `_make_search_agent` method (unchanged)
  - [ ] After each search round (except single-round mode): AnalysisAgent is invoked
  - [ ] `_expand_queries` method is deleted
  - [ ] `_parse_variants` method is deleted
  - [ ] The `deep_queries_{idx}_{provider}` state key is no longer written (FR-ADR-054)
  - [ ] The `deep_query_current_{idx}_{provider}` state key is no longer written
  - [ ] Standard-mode topics are not affected (this code path only executes for deep-mode, which is already gated in agent.py)
- **Test requirements**: unit
- **Depends on**: T16-02, T16-03
- **Implementation Guidance**:
  - File to modify: `newsletter_agent/tools/deep_research.py`
  - The new `_run_async_impl` structure follows spec Section 8.1 behavior contract:
    ```python
    async def _run_async_impl(self, ctx):
        state = ctx.session.state
        # Phase 0: Planning (skip if max_rounds == 1)
        if self.max_rounds > 1:
            initial_query, key_aspects, plan_events = await self._run_planning(ctx)
            for ev in plan_events: yield ev
            # Log planning output
        else:
            initial_query = self.query
            key_aspects = []

        # Initialize tracking
        accumulated_urls = set()
        round_count = 0
        searches_done = 0
        adaptive_context = {"plan": {...}, "rounds": []}
        used_queries = set()

        for round_idx in range(self.max_rounds):
            # Determine query
            current_query = initial_query if round_idx == 0 else next_query
            # Duplicate query check (T16-06)
            # Search
            # Analysis (skip if max_rounds == 1)
            # Exit criteria check (T16-05)
            # Extract next_query for next round
        # Merge, persist reasoning chain, cleanup
    ```
  - Delete methods: `_expand_queries`, `_parse_variants`
  - The existing `_make_search_agent` method remains unchanged (FR-ADR-020)
  - Known pitfall: The current code sets `state[f"deep_query_current_{idx}_{prov}"]` before each search. Remove this -- the query is now passed directly via instruction. The `_make_search_agent` method takes the query as a parameter and embeds it in the instruction.
  - ADK pattern: Each LlmAgent sub-agent is created fresh per invocation within `_run_async_impl`. This matches the StoryFlowAgent pattern from ADK docs.

### T16-05 - Implement exit criteria and saturation logic

- **Description**: Implement the 4 exit conditions within the adaptive loop, including the configurable `min_rounds` safety minimum for saturation override.
- **Spec refs**: FR-ADR-040 through FR-ADR-044, FR-ADR-064, Section 4.5
- **Parallel**: No (integrates into T16-04's loop)
- **Acceptance criteria**:
  - [ ] Exit condition 1: `saturated == true` AND `round_count >= self.min_rounds` triggers exit with reason `"saturation"`
  - [ ] Exit condition 2: `len(knowledge_gaps) == 0` triggers exit with reason `"full_coverage"`
  - [ ] Exit condition 3: `round_idx + 1 >= self.max_rounds` triggers exit with reason `"max_rounds_reached"`
  - [ ] Exit condition 4: `searches_done >= self.max_searches` triggers exit with reason `"search_budget_exhausted"`
  - [ ] Saturation before `min_rounds`: if `saturated=true` AND `round_count < self.min_rounds`, saturation is overridden and loop continues
  - [ ] Saturation exit logs at INFO: `"[AdaptiveResearch] Topic {name}/{provider}: saturated at round {N} - {coverage_assessment}"`
  - [ ] Max rounds exit logs at WARNING: `"[AdaptiveResearch] Topic {name}/{provider}: reached max rounds ({N}) without saturation. Gaps remaining: [{gaps}]"`
  - [ ] Budget exhaustion logs at INFO: `"[AdaptiveResearch] Topic {name}/{provider}: search budget exhausted ({N}/{max} searches)"`
- **Test requirements**: unit
- **Depends on**: T16-04 (loop structure must exist)
- **Implementation Guidance**:
  - Implement as a block after the AnalysisAgent invocation within the loop:
    ```python
    # Check exit criteria
    exit_reason = None
    if analysis["saturated"] and round_count >= self.min_rounds:
        exit_reason = "saturation"
        logger.info(f"[AdaptiveResearch] Topic {self.topic_name}/{self.provider}: "
                     f"saturated at round {round_idx} - {analysis['coverage_assessment']}")
    elif len(analysis.get("knowledge_gaps", [])) == 0:
        exit_reason = "full_coverage"
    elif searches_done >= self.max_searches:
        exit_reason = "search_budget_exhausted"
        logger.info(...)
    # Next iteration check: if round_idx + 1 >= self.max_rounds, break after finishing
    if exit_reason:
        break
    ```
  - The `max_rounds_reached` reason is checked after the loop (when the for-loop completes without break)
  - Use `self.min_rounds` (from T16-01) instead of hard-coded 2
  - The spec says condition 2 (empty knowledge_gaps) triggers exit regardless of round count -- no minimum round requirement for this condition

### T16-06 - Implement AdaptiveContext and reasoning chain persistence

- **Description**: Implement the `AdaptiveContext` data structure accumulation during the adaptive loop, format the `prior_rounds_summary` for AnalysisAgent prompts, and persist the reasoning chain to a dedicated state key before cleanup.
- **Spec refs**: FR-ADR-050 through FR-ADR-055, Section 4.6, Section 7.2, Section 7.5 (AdaptiveContext contract)
- **Parallel**: No (integrates into T16-04's loop)
- **Acceptance criteria**:
  - [ ] `AdaptiveContext` dict is initialized with `plan` (query_intent + key_aspects) after planning phase
  - [ ] Each completed round appends to `adaptive_context["rounds"]` with: `round_idx`, `query`, `findings_summary`, `knowledge_gaps`, `urls_found`, `coverage_assessment`, `saturated`
  - [ ] `prior_rounds_summary` string is formatted from `adaptive_context["rounds"]` as a human-readable summary for the AnalysisAgent prompt
  - [ ] For round 0: `prior_rounds_summary` is `"No prior research rounds."` (or similar)
  - [ ] For round N>0: summary includes each prior round's query, findings_summary, and knowledge_gaps
  - [ ] Before cleanup: `adaptive_context` is serialized as JSON and written to state key `adaptive_reasoning_chain_{idx}_{provider}`
  - [ ] The `adaptive_reasoning_chain_{idx}_{provider}` key is NOT cleaned up after merge (FR-ADR-055)
  - [ ] After merge: all intermediate keys ARE cleaned up (FR-ADR-053)
- **Test requirements**: unit
- **Depends on**: T16-04, T16-05
- **Implementation Guidance**:
  - Initialize after planning:
    ```python
    adaptive_context = {
        "plan": {"query_intent": plan_intent, "key_aspects": key_aspects},
        "rounds": [],
    }
    ```
  - After each analysis, append:
    ```python
    adaptive_context["rounds"].append({
        "round_idx": round_idx,
        "query": current_query,
        "findings_summary": analysis["findings_summary"],
        "knowledge_gaps": analysis["knowledge_gaps"],
        "urls_found": len(new_urls),
        "coverage_assessment": analysis["coverage_assessment"],
        "saturated": analysis["saturated"],
    })
    ```
  - Format `prior_rounds_summary` helper method:
    ```python
    def _format_prior_rounds(self, rounds: list[dict]) -> str:
        if not rounds:
            return "No prior research rounds."
        lines = []
        for r in rounds:
            lines.append(f"Round {r['round_idx']} (query: \"{r['query']}\"):")
            lines.append(f"  Findings: {r['findings_summary']}")
            gaps = ", ".join(r["knowledge_gaps"]) if r["knowledge_gaps"] else "none"
            lines.append(f"  Remaining gaps: {gaps}")
        return "\n".join(lines)
    ```
  - Persist before cleanup: `state[f"adaptive_reasoning_chain_{idx}_{prov}"] = json.dumps(adaptive_context)`
  - In `_cleanup_state`: add cleanup for `adaptive_plan_*`, `adaptive_analysis_*`, `adaptive_context_*` keys but NOT `adaptive_reasoning_chain_*`

### T16-07 - Implement duplicate query detection

- **Description**: Add logic to detect when the AnalysisAgent suggests a query identical to one already used in a prior round, and append a distinguishing suffix to avoid wasted searches.
- **Spec refs**: FR-ADR-003 (SC-ADR-003), Section 4.1 Edge Cases, Section 10.5 (duplicate query log)
- **Parallel**: No (integrates into T16-04's loop)
- **Acceptance criteria**:
  - [ ] A `set` of used queries is maintained across rounds
  - [ ] Before each search round, the current query is checked against the set
  - [ ] If a duplicate is detected: a suffix from `_FALLBACK_SUFFIXES` is appended (cycling through the list)
  - [ ] A warning is logged: `"[AdaptiveResearch] Topic {name}/{provider} round {N}: duplicate query detected, adding suffix"`
  - [ ] The modified (deduplicated) query is used for the search, not the original duplicate
  - [ ] The modified query is added to the used queries set
- **Test requirements**: unit
- **Depends on**: T16-04
- **Implementation Guidance**:
  - Maintain: `used_queries: set[str] = set()`
  - Before search:
    ```python
    if current_query in used_queries:
        suffix_idx = len(used_queries) % len(_FALLBACK_SUFFIXES)
        current_query = f"{current_query} {_FALLBACK_SUFFIXES[suffix_idx]}"
        logger.warning(f"[AdaptiveResearch] Topic {self.topic_name}/{self.provider} "
                       f"round {round_idx}: duplicate query detected, adding suffix")
    used_queries.add(current_query)
    ```
  - This is a simple mechanism. The suffix list has 4 entries which covers the max 5 rounds scenario.

### T16-08 - Update merge and cleanup for new state keys

- **Description**: Update `_merge_rounds` and `_cleanup_state` to handle the new adaptive state keys. Ensure all intermediate keys are cleaned up while preserving the reasoning chain.
- **Spec refs**: FR-ADR-053, FR-ADR-054, FR-ADR-055, Section 7.2, 7.3
- **Parallel**: No (depends on T16-06)
- **Acceptance criteria**:
  - [ ] `_cleanup_state` deletes: `adaptive_plan_{idx}_{provider}`, `adaptive_analysis_{idx}_{provider}`, `adaptive_context_{idx}_{provider}`, `deep_research_latest_{idx}_{provider}`, `research_{idx}_{provider}_round_{N}` for all N
  - [ ] `_cleanup_state` does NOT delete: `adaptive_reasoning_chain_{idx}_{provider}`, `research_{idx}_{provider}` (final merged output)
  - [ ] `_cleanup_state` no longer deletes: `deep_queries_{idx}_{provider}` (key no longer exists), `deep_query_current_{idx}_{provider}` (key no longer exists)
  - [ ] `_merge_rounds` continues to work correctly: concatenate SUMMARY sections, deduplicate SOURCES URLs
  - [ ] `deep_urls_accumulated_{idx}_{provider}` is still cleaned up (retained for URL tracking within loop, deleted after)
  - [ ] Empty round results (search returned nothing) are handled gracefully in merge
- **Test requirements**: unit
- **Depends on**: T16-06
- **Implementation Guidance**:
  - Modify existing `_cleanup_state` method to add new key patterns:
    ```python
    # New adaptive keys to clean
    for key in [f"adaptive_plan_{idx}_{prov}",
                f"adaptive_analysis_{idx}_{prov}",
                f"adaptive_context_{idx}_{prov}"]:
        state.pop(key, None)
    ```
  - Remove old key cleanup for `deep_queries_*` and `deep_query_current_*`
  - `_merge_rounds` logic should not need changes -- it already reads `research_{idx}_{provider}_round_{N}` and merges them. Verify it handles empty round content gracefully (empty string = skip).
  - Verify: `_split_sections` and `_collect_bare_urls` helper methods remain unchanged

### T16-09 - Update agent.py factory to pass new params

- **Description**: Update the `build_research_phase` function in `newsletter_agent/agent.py` to pass `max_searches` and `min_rounds` from config to `DeepResearchOrchestrator`.
- **Spec refs**: FR-ADR-061, FR-ADR-064, Section 8.1 (DeepResearchOrchestrator constructor)
- **Parallel**: No (depends on T16-01)
- **Acceptance criteria**:
  - [ ] `DeepResearchOrchestrator(...)` call in `agent.py` passes `max_searches=config.settings.max_searches_per_topic`
  - [ ] `DeepResearchOrchestrator(...)` call passes `min_rounds=config.settings.min_research_rounds`
  - [ ] When config omits new fields, defaults flow correctly: `max_searches` = `max_research_rounds`, `min_rounds` = 2
  - [ ] Standard-mode topic construction is unaffected
  - [ ] Perplexity provider construction (if different) also passes the new params
- **Test requirements**: unit (extend test_agent_factory.py)
- **Depends on**: T16-01, WP15 (config fields)
- **Implementation Guidance**:
  - File to modify: `newsletter_agent/agent.py`
  - Find the `DeepResearchOrchestrator(...)` constructor call(s) and add the new keyword arguments
  - There may be multiple calls (one for google, one for perplexity). Add the params to all of them.
  - The config values come from `config.settings.max_searches_per_topic` and `config.settings.min_research_rounds`

### T16-10 - Unit tests for adaptive orchestrator

- **Description**: Create comprehensive unit tests for the adaptive orchestrator in `tests/unit/test_adaptive_research.py`. Cover PlanningAgent, AnalysisAgent, adaptive loop, exit criteria, state management, and merge. This is the primary test file for WP16.
- **Spec refs**: Section 11.1 (all unit test requirements for PlanningAgent, AnalysisAgent, Loop, Prompt)
- **Parallel**: No (depends on T16-01 through T16-08)
- **Acceptance criteria**:
  - [ ] **PlanningAgent tests**: valid JSON output parsed correctly; fallback on invalid JSON; fallback on missing required fields; key_aspects padding (< 3 items); key_aspects truncation (> 5 items); state key `adaptive_plan_{idx}_{provider}` written correctly
  - [ ] **AnalysisAgent tests**: valid JSON output parsed correctly; fallback on invalid JSON; `saturated=true` with `next_query=null` accepted; `saturated=false` with `next_query` missing triggers fallback; empty `knowledge_gaps` accepted; `knowledge_gaps` truncation at 5 items; state key `adaptive_analysis_{idx}_{provider}` written correctly
  - [ ] **Loop tests**: planning invoked for `max_rounds > 1`, skipped for `max_rounds == 1`; round 0 uses planning query; subsequent rounds use analysis `next_query`; analysis invoked after each search (except single-round); `AdaptiveContext` accumulated correctly; `prior_rounds_summary` includes all prior rounds
  - [ ] **Exit criteria tests**: exit on `saturated=true` when `round_count >= min_rounds`; saturation override when `round_count < min_rounds`; exit on empty `knowledge_gaps`; exit on max_rounds; exit on max_searches budget; duplicate query detection
  - [ ] **State/merge tests**: merged output has `SUMMARY:` + `SOURCES:` format; intermediate keys cleaned up; reasoning chain persisted at `adaptive_reasoning_chain_*`; URL deduplication in SOURCES; empty round handled gracefully; single-round mode: no planning, no analysis
  - [ ] All tests use mocked LlmAgent invocations (no real API calls)
  - [ ] Minimum 25 test cases covering the spec Section 11.1 requirements
- **Test requirements**: unit
- **Depends on**: T16-01 through T16-08
- **Implementation Guidance**:
  - Create new file: `tests/unit/test_adaptive_research.py`
  - Mock strategy: mock `LlmAgent.run_async` to avoid real LLM calls. Use `unittest.mock.AsyncMock` or `pytest-asyncio` fixtures with patched agent invocations.
  - The key mocking approach: patch the state dict to simulate LlmAgent writing its output_key:
    ```python
    # Simulate PlanningAgent writing to state
    state[f"adaptive_plan_{idx}_{prov}"] = json.dumps({
        "query_intent": "...",
        "key_aspects": ["a", "b", "c"],
        "initial_search_query": "test query",
        "search_rationale": "..."
    })
    ```
  - For search round mocking: set `state[f"deep_research_latest_{idx}_{prov}"]` to mock search output
  - Mirror test organization from spec Section 11.1: group by PlanningAgent, AnalysisAgent, Loop, State/Merge
  - Follow existing test patterns in `tests/unit/test_deep_research.py` for fixture setup and assertion styles

### T16-11 - Update existing unit tests for API changes

- **Description**: Update `tests/unit/test_deep_research.py` and `tests/unit/test_agent_factory.py` for the orchestrator's changed API (new constructor params, removed methods, changed behavior).
- **Spec refs**: FR-ADR-003, FR-ADR-041, FR-ADR-054, SC-ADR-005 (existing tests pass)
- **Parallel**: No (depends on T16-04 and T16-09)
- **Acceptance criteria**:
  - [ ] `tests/unit/test_deep_research.py` - `TestOrchestratorInstantiation` updated to include `max_searches` and `min_rounds` params
  - [ ] `tests/unit/test_deep_research.py` - `TestParseVariants` tests removed or marked as not applicable (method deleted)
  - [ ] `tests/unit/test_deep_research.py` - URL extraction tests remain unchanged (method is kept)
  - [ ] `tests/unit/test_deep_research.py` - `TestMergeRounds` and `TestCleanupState` updated for new key patterns
  - [ ] `tests/unit/test_agent_factory.py` - deep-mode tests verify `max_searches` param is passed to orchestrator
  - [ ] `tests/unit/test_agent_factory.py` - deep-mode tests verify `min_rounds` param is passed to orchestrator
  - [ ] All existing tests pass: `pytest tests/unit/ -v` exits with code 0
- **Test requirements**: unit (update existing)
- **Depends on**: T16-09, T16-08
- **Implementation Guidance**:
  - File to modify: `tests/unit/test_deep_research.py`
  - File to modify: `tests/unit/test_agent_factory.py`
  - For removed tests (`_parse_variants`): either delete the test class entirely or replace with a comment noting the method was removed per spec 002
  - For constructor tests: add assertions that `orchestrator.max_searches` and `orchestrator.min_rounds` have expected values
  - For factory tests: verify the `DeepResearchOrchestrator` constructor mock receives `max_searches=` and `min_rounds=` kwargs
  - For cleanup tests: update the expected set of keys to be cleaned/preserved

## Implementation Notes

- **Primary file**: `newsletter_agent/tools/deep_research.py` -- this is where most changes happen (orchestrator rewrite)
- **Secondary files**: `newsletter_agent/agent.py` (factory), existing test files
- **New test file**: `tests/unit/test_adaptive_research.py`
- **Deleted code**: `_expand_queries` method, `_parse_variants` method, `_MIN_URLS_THRESHOLD` constant, `import get_query_expansion_instruction`
- **Preserved code**: `_make_search_agent`, `_extract_urls`, `_merge_rounds`, `_split_sections`, `_collect_bare_urls`, `_FALLBACK_SUFFIXES`, `_MARKDOWN_LINK_RE`, `_BARE_URL_RE`
- **Test approach**: All tests use mocked LlmAgent invocations. No real API calls in unit tests.
- **Test commands**:
  - New tests: `pytest tests/unit/test_adaptive_research.py -v`
  - Updated tests: `pytest tests/unit/test_deep_research.py tests/unit/test_agent_factory.py -v`
  - Full suite: `pytest tests/unit/ -v`

## Parallel Opportunities

- T16-02 (PlanningAgent) and T16-03 (AnalysisAgent) can be developed in parallel
- T16-07 (duplicate detection) is conceptually independent but integrates into T16-04's loop
- T16-09 (factory update) can be done as soon as T16-01 is complete

## Risks & Mitigations

- **Risk**: Dynamically creating LlmAgent sub-agents within `_run_async_impl` may have ADK framework side effects (agent tree registration, lifecycle). **Mitigation**: The existing code already creates agents dynamically (`_make_search_agent`), and ADK docs confirm this pattern via the StoryFlowAgent example. No framework registration is needed for dynamically created agents.
- **Risk**: Removing `_expand_queries` and `_parse_variants` breaks all existing unit tests that reference these methods. **Mitigation**: T16-11 explicitly updates those tests. The old test class for `_parse_variants` is deleted.
- **Risk**: State key collisions if multiple orchestrators run in parallel for the same topic. **Mitigation**: Keys include `{idx}_{provider}` suffix which is unique per orchestrator instance. Cross-topic parallelism is preserved via `ParallelAgent` in the parent pipeline.

## Activity Log

- 2026-03-15T00:00:00Z - planner - lane=planned - Work package created
- 2025-07-24T00:00:00Z - coder - lane=doing - Started WP16 implementation
- 2025-07-24T01:00:00Z - coder - lane=doing - T16-01 through T16-09: Implemented adaptive orchestrator, planning/analysis agents, exit criteria, state management, factory update
- 2025-07-24T02:00:00Z - coder - lane=doing - T16-10: Created test_adaptive_research.py with 40 test cases
- 2025-07-24T02:30:00Z - coder - lane=doing - T16-11: Updated test_deep_research.py and test_agent_factory.py for API changes
- 2025-07-24T03:00:00Z - coder - lane=doing - All 537 unit tests passing, documentation updated
- 2025-07-24T04:00:00Z - coder - lane=for_review - All tasks complete, submitted for review

## Self-Review

### Spec Compliance
- [x] FR-ADR-001 through FR-ADR-006: Adaptive loop architecture implemented
- [x] FR-ADR-010 through FR-ADR-014: PlanningAgent with fallback logic
- [x] FR-ADR-020 through FR-ADR-022: Search phase using existing _make_search_agent
- [x] FR-ADR-030 through FR-ADR-035: AnalysisAgent with fallback logic
- [x] FR-ADR-040 through FR-ADR-044: Exit criteria (saturation, full_coverage, max_rounds, budget)
- [x] FR-ADR-050 through FR-ADR-055: State management and reasoning chain persistence
- [x] FR-ADR-080 through FR-ADR-085: Backward compatibility (single-round mode)

### Correctness
- [x] All 537 unit tests pass
- [x] 109 tests specific to WP16 files all pass
- [x] deep_research.py coverage: 94% statement, well above 80% threshold
- [x] agent.py factory lines touched by WP16 are fully covered

### Code Quality
- [x] No unused imports or dead code
- [x] No hardcoded values; all limits from config or constants
- [x] No security issues (no user input without validation)
- [x] Logic is self-documenting with clear method names

### Scope Discipline
- [x] Only changed files specified in the WP
- [x] No unasked-for abstractions added

### Documentation
- [x] docs/architecture.md updated for adaptive loop
- [x] docs/api-reference.md updated with new params and behavior
- [x] docs/configuration-guide.md updated with new config fields
- [x] docs/developer-guide.md updated with new file listing
