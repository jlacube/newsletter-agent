---
lane: for_review
review_status: acknowledged
---

# WP12 - Multi-Round Deep Research Orchestrator

> **Spec**: `specs/autonomous-deep-research.spec.md`
> **Status**: Complete
> **Priority**: P1 (MVP user story US-02)
> **Goal**: Deep-mode topics perform multiple search rounds with varied query angles, accumulating 15+ URLs per provider before combining into the standard research state key
> **Independent Test**: Configure a topic with `search_depth: "deep"` and `max_research_rounds: 3`. Run the pipeline. Verify logs show 3 search rounds per provider with different queries, and the research state key contains sources from multiple rounds.
> **Depends on**: WP11 (needs `max_research_rounds` config field)
> **Parallelisable**: No (modifies `build_research_phase()` in `agent.py`)
> **Prompt**: `plans/WP12-deep-research-orchestrator.md`

## Objective

This work package implements the core multi-round deep research capability: a custom `DeepResearchOrchestrator` (BaseAgent) that generates query variants via an LLM, executes multiple search rounds per provider, tracks URL accumulation, exits early when enough sources are found, and merges all round results into the standard research state key. This is the primary feature enabling higher-quality deep analysis through diverse perspectives.

## Spec References

- FR-MRR-001 through FR-MRR-011 (Section 4.3)
- FR-PIP-003 (Section 4.5)
- FR-BC-001, FR-BC-002, FR-BC-004 (Section 4.6)
- US-02 (Section 5)
- Section 6 Flow B (Deep Multi-Round Research)
- Section 7.2 (Session State - New Keys)
- Section 8.3 (Agent Contracts: QueryExpanderAgent, DeepSearchRound, DeepResearchOrchestrator)
- Section 9.1 (Architecture Diagram)
- Section 9.4 Decision 1 (Custom BaseAgent pattern)
- Section 11.1 (Unit Tests: QueryExpanderAgent, DeepResearchOrchestrator, Pipeline order)
- Section 11.2 (BDD: Multi-Round Deep Research scenarios)

## Tasks

### T12-01 - Create query expansion prompt template
- **Description**: Create `newsletter_agent/prompts/query_expansion.py` with a function that returns the query expansion instruction for the QueryExpanderAgent LlmAgent.
- **Spec refs**: FR-MRR-003, FR-MRR-004, Section 4.3 (QueryExpanderAgent instruction contract)
- **Parallel**: Yes [P] (independent of T12-02)
- **Acceptance criteria**:
  - [ ] Module `newsletter_agent/prompts/query_expansion.py` exists
  - [ ] Function `get_query_expansion_instruction(query: str, topic_name: str, variant_count: int) -> str` returns the prompt template
  - [ ] Prompt instructs LLM to generate exactly `variant_count` alternative search queries exploring different angles (trends, expert opinions, data/statistics, controversies, implications) (FR-MRR-003)
  - [ ] Prompt specifies JSON array output format (FR-MRR-004)
  - [ ] Prompt includes the original query and topic name as context
- **Test requirements**: unit (test prompt contains expected elements)
- **Depends on**: none
- **Implementation Guidance**:
  - Follow existing prompt module pattern in `newsletter_agent/prompts/research_google.py` -- module-level template constant + public function.
  - The prompt template from spec Section 4.3:
    ```
    You are a research query strategist. Given the original research query below,
    generate exactly {N} alternative search queries that explore DIFFERENT angles...
    Original query: {query}
    Topic: {topic_name}
    ...
    Output a JSON array of strings, one per query variant. No other text.
    ```
  - Use `str.format()` for template interpolation, matching existing prompts.

### T12-02 - Create deep search round prompt variants
- **Description**: Add round-specific prompt variant functions or parameters to the existing Google and Perplexity research prompts that can accept a round-specific query.
- **Spec refs**: FR-MRR-009, FR-MRR-010, Section 8.3 (DeepSearchRound contract)
- **Parallel**: Yes [P] (independent of T12-01)
- **Acceptance criteria**:
  - [ ] Google deep round prompt requests at least 8 sources per round (FR-MRR-009)
  - [ ] Perplexity deep round prompt uses `search_depth="deep"` (FR-MRR-010)
  - [ ] Prompts accept a `query` parameter that can differ per round (not hardcoded to topic query)
  - [ ] Existing standard-mode prompts are unchanged (FR-BC-001)
- **Test requirements**: unit (extend `tests/unit/test_google_search_prompts.py`)
- **Depends on**: none
- **Implementation Guidance**:
  - The existing `get_google_search_instruction()` and `get_perplexity_search_instruction()` already accept `query` as a parameter. The deep round LlmAgent just passes the current round's query. No prompt function changes may be needed -- the DeepResearchOrchestrator simply creates LlmAgents with the existing deep prompts, passing the round-specific query.
  - Verify that the existing deep prompt templates work for round-specific queries by reviewing them. If the prompt references the "topic query" by name, it may need adjustment to work with expanded queries.
  - Key files: `newsletter_agent/prompts/research_google.py`, `newsletter_agent/prompts/research_perplexity.py`

### T12-03 - Implement DeepResearchOrchestrator BaseAgent
- **Description**: Create `newsletter_agent/tools/deep_research.py` with the `DeepResearchOrchestrator` class that extends BaseAgent. Implement the constructor, Pydantic fields, and the skeleton of `_run_async_impl`.
- **Spec refs**: FR-MRR-001, Section 8.3 (DeepResearchOrchestrator contract), Section 9.4 Decision 1
- **Parallel**: No (foundation for T12-04 through T12-07)
- **Acceptance criteria**:
  - [ ] `newsletter_agent/tools/deep_research.py` module exists
  - [ ] `DeepResearchOrchestrator` extends `BaseAgent` (FR-MRR-001)
  - [ ] Has `model_config = {"arbitrary_types_allowed": True}` (follows existing pattern)
  - [ ] Constructor fields: `topic_idx: int`, `provider: str`, `query: str`, `topic_name: str`, `max_rounds: int`, `search_depth: str`, `model: str`, `tools: list`
  - [ ] Creates QueryExpanderAgent (LlmAgent) and DeepSearchRound (LlmAgent) sub-agents in constructor
  - [ ] `_run_async_impl(self, ctx)` is defined as async generator
- **Test requirements**: unit (test class instantiation and sub-agent creation)
- **Depends on**: T12-01, T12-02
- **Implementation Guidance**:
  - Official docs: ADK Custom Agents https://google.github.io/adk-docs/agents/custom-agents/
  - Follow existing BaseAgent pattern from `newsletter_agent/tools/link_verifier_agent.py` (most complex existing BaseAgent).
  - Key imports: `from google.adk.agents import BaseAgent, LlmAgent`, `from google.adk.agents.invocation_context import InvocationContext`, `from google.adk.events import Event`
  - Sub-agent creation pattern:
    ```python
    self._query_expander = LlmAgent(
        name=f"QueryExpander_{topic_idx}_{provider}",
        model=model,
        instruction=get_query_expansion_instruction(query, topic_name, max_rounds - 1),
        output_key=f"deep_queries_{topic_idx}_{provider}",
    )
    ```
  - The `sub_agents` property of BaseAgent must list all sub-agents that will be invoked. Set `self.sub_agents = [self._query_expander, self._search_round]` or override accordingly.
  - Known pitfall: ADK requires sub_agents to be declared for event routing. If `run_async(ctx)` is used on a sub-agent, that sub-agent should be in the parent's `sub_agents` list.

### T12-04 - Implement query expansion invocation
- **Description**: In `DeepResearchOrchestrator._run_async_impl`, implement the query expansion step: invoke QueryExpanderAgent, read variants from state, handle JSON parsing with fallback.
- **Spec refs**: FR-MRR-003, FR-MRR-004, FR-MRR-011, Section 4.3 (DeepResearchOrchestrator behavior steps 1-3)
- **Parallel**: No (depends on T12-03)
- **Acceptance criteria**:
  - [ ] Orchestrator invokes QueryExpanderAgent via `async for event in self._query_expander.run_async(ctx)` and yields all events
  - [ ] Reads `deep_queries_{idx}_{provider}` from session state after sub-agent completes
  - [ ] Parses JSON array of query variant strings from state value (FR-MRR-004)
  - [ ] If JSON parsing fails: logs warning and falls back to suffix-based variants (e.g., "{query} trends", "{query} expert analysis", "{query} data statistics") (spec edge case)
  - [ ] Falls back generates exactly `max_rounds - 1` variants (FR-MRR-004)
  - [ ] When `max_rounds == 1`: skips query expansion entirely (no variants needed) (FR-BC-002)
- **Test requirements**: unit (mock LlmAgent, test JSON parsing and fallback)
- **Depends on**: T12-03
- **Implementation Guidance**:
  - Sub-agent invocation pattern (from ADK custom agent docs):
    ```python
    async for event in self._query_expander.run_async(ctx):
        yield event
    variants_raw = ctx.session.state.get(f"deep_queries_{self.topic_idx}_{self.provider}", "[]")
    ```
  - JSON parsing: `json.loads(variants_raw)` -- handle `json.JSONDecodeError`
  - Fallback suffixes: `["trends and developments", "expert analysis and opinions", "data statistics and benchmarks", "implications and predictions"]` -- trim to `max_rounds - 1`
  - When `max_rounds == 1`: set `variants = []` and skip the expansion call entirely.
  - Known pitfall: The LlmAgent output_key writes the raw LLM output as a string. The JSON may be wrapped in markdown code fences. Strip them before parsing: `variants_raw.strip().strip('`').strip('json\n')`

### T12-05 - Implement multi-round search loop
- **Description**: Implement the core round loop in `_run_async_impl`: for each round, set the current query, invoke DeepSearchRound LlmAgent, copy output to round-specific key.
- **Spec refs**: FR-MRR-002, FR-MRR-005, FR-MRR-009, FR-MRR-010, Section 4.3 (behavior steps 4-5)
- **Parallel**: No (depends on T12-04)
- **Acceptance criteria**:
  - [ ] Round 0 uses the original topic query (FR-MRR-002)
  - [ ] Rounds 1+ use query variants from expansion step (FR-MRR-003)
  - [ ] Each round invokes DeepSearchRound LlmAgent via `async for event in self._search_round.run_async(ctx)` and yields all events
  - [ ] After each round, reads `deep_research_latest_{idx}_{provider}` from state (FR-MRR-005)
  - [ ] Copies round output to `research_{idx}_{provider}_round_{round_idx}` state key (FR-MRR-005)
  - [ ] Loop runs up to `max_rounds` times (FR-MRR-001)
  - [ ] Google rounds use `google_search` tool (FR-MRR-009)
  - [ ] Perplexity rounds use `search_perplexity` tool (FR-MRR-010)
- **Test requirements**: unit (mock LlmAgent, verify state key writes per round)
- **Depends on**: T12-04
- **Implementation Guidance**:
  - The DeepSearchRound LlmAgent has a fixed `output_key` (`deep_research_latest_{idx}_{provider}`). The orchestrator reads this key after each invocation.
  - For round-specific queries: the orchestrator needs to update the LlmAgent's instruction before each round. Since LlmAgent instruction is set at construction, create a new LlmAgent per round OR use ADK state variable interpolation in the instruction (e.g., `{deep_query_current_{idx}_{provider}}`).
  - Recommended approach: Use ADK instruction interpolation. Set `ctx.session.state[f"deep_query_current_{self.topic_idx}_{self.provider}"] = current_query` before each round, and have the LlmAgent instruction reference `{deep_query_current_X_Y}`.
  - Alternative: Create a new LlmAgent per round with the specific query baked into the instruction. This avoids state interpolation concerns but creates more agent objects.
  - State write pattern: `ctx.session.state[f"research_{self.topic_idx}_{self.provider}_round_{round_idx}"] = round_output`

### T12-06 - Implement URL tracking and early exit
- **Description**: After each round, extract URLs from the round output, accumulate unique URLs, and exit early if 15+ unique URLs are collected.
- **Spec refs**: FR-MRR-007, Section 4.3 (behavior steps 5d-5f, 5h)
- **Parallel**: No (depends on T12-05)
- **Acceptance criteria**:
  - [ ] Extracts markdown URLs (`[title](url)`) from each round's output using regex
  - [ ] Accumulates unique URLs in `deep_urls_accumulated_{idx}_{provider}` state key
  - [ ] Deduplicates URLs across rounds (same URL from different rounds counted once)
  - [ ] Exits loop early (Python `break`) when 15+ unique URLs accumulated (FR-MRR-007)
  - [ ] Yields progress event after each round: "Round {N}: {X} unique URLs accumulated" (Section 10.5)
  - [ ] Handles empty round output gracefully (no URLs extracted, loop continues)
- **Test requirements**: unit (test URL extraction regex, dedup, early exit threshold)
- **Depends on**: T12-05
- **Implementation Guidance**:
  - URL extraction regex: `r'\[([^\]]*)\]\((https?://[^\)]+)\)'` -- matches `[title](url)` markdown links
  - Accumulation: Use a `set()` for O(1) dedup, convert to list for state storage.
  - Early exit threshold: 15 (hardcoded per spec FR-MRR-007). Could be a class constant `_MIN_URLS_THRESHOLD = 15`.
  - Progress event pattern: `yield Event(author=self.name, content=types.Content(parts=[types.Part(text=f"[DeepResearch] Topic {self.topic_name}/{self.provider} round {round_idx}: {len(new_urls)} new URLs, {len(all_urls)} total accumulated")]))`
  - Logging per Section 10.5: `logger.info(f"[DeepResearch] Topic {self.topic_name}/{self.provider} round {round_idx}: ...")`

### T12-07 - Implement round merging and state cleanup
- **Description**: After the round loop completes, merge all round results into the standard `research_{idx}_{provider}` state key and clean up intermediate keys.
- **Spec refs**: FR-MRR-006, Section 4.3 (behavior steps 6-7)
- **Parallel**: No (depends on T12-06)
- **Acceptance criteria**:
  - [ ] Reads all `research_{idx}_{provider}_round_{N}` keys from state
  - [ ] Concatenates SUMMARY sections from all rounds with round separators (FR-MRR-006)
  - [ ] Deduplicates source URLs across all rounds, keeping first occurrence (FR-MRR-006)
  - [ ] Produces unified output in standard format: `SUMMARY:\n...\n\nSOURCES:\n- [Title](URL)\n...` (FR-MRR-006)
  - [ ] Writes merged output to `research_{idx}_{provider}` state key (standard key, same as single-round mode)
  - [ ] Deletes all intermediate state keys: `deep_queries_*`, `deep_research_latest_*`, `research_*_round_*`, `deep_urls_accumulated_*`, `deep_query_current_*`
  - [ ] If no round outputs exist (all rounds failed): sets `research_{idx}_{provider}` to empty string
- **Test requirements**: unit (test merging logic, dedup, cleanup)
- **Depends on**: T12-06
- **Implementation Guidance**:
  - Merging pattern: Parse each round's output to separate SUMMARY and SOURCES sections. For SUMMARY: join with `\n\n--- Round {N} ---\n\n`. For SOURCES: collect all `[title](url)` pairs, deduplicate by URL, format as markdown list.
  - Use the existing `research_utils.py` parse pattern if applicable, or implement inline.
  - State cleanup: `for key in list(state.keys()): if key.startswith(f"deep_") and key.endswith(f"_{self.topic_idx}_{self.provider}"): del state[key]`
  - Also delete round keys: `research_{idx}_{provider}_round_*`
  - Known pitfall: Modifying dict while iterating -- use `list(state.keys())` to snapshot keys first.

### T12-08 - Update build_research_phase() for conditional deep/standard
- **Description**: Modify `build_research_phase()` in `agent.py` to produce `DeepResearchOrchestrator` agents for deep-mode topics instead of single LlmAgents.
- **Spec refs**: FR-PIP-003, FR-BC-001, FR-BC-002, Section 9.1
- **Parallel**: No (depends on T12-07)
- **Acceptance criteria**:
  - [ ] For topics with `search_depth == "deep"`: creates `DeepResearchOrchestrator` per provider instead of single LlmAgent (FR-PIP-003)
  - [ ] Passes `max_rounds` from `config.settings.max_research_rounds` to orchestrator constructor
  - [ ] For topics with `search_depth == "standard"`: creates single LlmAgent per provider (unchanged behavior) (FR-BC-001)
  - [ ] When `max_research_rounds == 1` and `search_depth == "deep"`: orchestrator runs single round, equivalent to current behavior (FR-BC-002)
  - [ ] Output state key `research_{idx}_{provider}` is produced regardless of mode (FR-BC-004)
  - [ ] All topic SequentialAgents still wrapped in ParallelAgent (unchanged structure)
- **Test requirements**: unit (extend `tests/unit/test_agent_factory.py`)
- **Depends on**: T12-07
- **Implementation Guidance**:
  - File to modify: `newsletter_agent/agent.py`, function `build_research_phase()` (lines 57-115)
  - Current pattern: For each topic, creates LlmAgents for each provider. The conditional logic goes here: if `topic.search_depth == "deep"`, create `DeepResearchOrchestrator` instead.
  - Import: `from newsletter_agent.tools.deep_research import DeepResearchOrchestrator`
  - Construction:
    ```python
    if topic.search_depth == "deep":
        agent = DeepResearchOrchestrator(
            name=f"DeepResearch_{idx}_{provider}",
            topic_idx=idx,
            provider=provider,
            query=topic.query,
            topic_name=topic.name,
            max_rounds=config.settings.max_research_rounds,
            search_depth=topic.search_depth,
            model=_RESEARCH_MODEL,
            tools=[google_search] if provider == "google_search" else [search_perplexity_tool],
        )
    else:
        agent = LlmAgent(...)  # existing code
    ```
  - The SequentialAgent per topic should contain the orchestrator(s) in place of LlmAgents.
  - Known pitfall: The `tools` parameter for Perplexity is a `FunctionTool` wrapper. Check how it's currently constructed in `build_research_phase()`.

### T12-09 - Unit tests for DeepResearchOrchestrator
- **Description**: Write comprehensive unit tests for the orchestrator covering query expansion, round execution, URL tracking, early exit, merging, and error handling.
- **Spec refs**: Section 11.1 (DeepResearchOrchestrator tests), US-02 acceptance scenarios
- **Parallel**: No (depends on T12-08)
- **Acceptance criteria**:
  - [ ] Test orchestrator invokes QueryExpanderAgent for query expansion
  - [ ] Test orchestrator executes correct number of rounds (respects max_rounds)
  - [ ] Test round 0 uses original query, subsequent rounds use expanded variants
  - [ ] Test URL extraction from round output (markdown link regex)
  - [ ] Test URL deduplication across rounds
  - [ ] Test early exit at 15+ URLs (break before max_rounds)
  - [ ] Test graceful handling of empty round output (no crash, loop continues)
  - [ ] Test merges multiple rounds into single output with deduplicated SOURCES
  - [ ] Test cleanup of intermediate state keys after merge
  - [ ] Test handles zero round outputs (sets empty string)
  - [ ] Test fallback query expansion on invalid JSON from LLM
  - [ ] Test max_rounds=1 skips query expansion (FR-BC-002)
  - [ ] All tests pass with >= 80% code coverage for `deep_research.py`
- **Test requirements**: unit (new file `tests/unit/test_deep_research.py`)
- **Depends on**: T12-08
- **Implementation Guidance**:
  - Mock LlmAgent sub-agents: patch `run_async()` on the query expander and search round agents to set state keys directly without actual LLM calls.
  - Create mock InvocationContext with a real session state dict for state read/write testing.
  - Test URL extraction regex with various markdown link formats: `[title](https://example.com)`, `[title](http://example.com/path?q=1)`, etc.
  - Test early exit: Set up mock rounds where round 2 crosses the 15-URL threshold, verify round 3 is not invoked.
  - Follow existing test patterns from `tests/unit/test_link_verifier_agent.py` for BaseAgent testing.

### T12-10 - Unit tests for pipeline structure with deep mode
- **Description**: Extend `tests/unit/test_agent_factory.py` to verify that `build_research_phase()` produces the correct agent tree for deep-mode vs standard-mode topics.
- **Spec refs**: FR-PIP-003, FR-BC-001, Section 11.1 (Pipeline order tests)
- **Parallel**: No (depends on T12-08)
- **Acceptance criteria**:
  - [ ] Test deep-mode topic produces `DeepResearchOrchestrator` (BaseAgent subclass) in research phase
  - [ ] Test standard-mode topic produces single `LlmAgent` in research phase (unchanged)
  - [ ] Test mixed topics: deep and standard together produce correct agent types
  - [ ] Test `max_research_rounds` is passed correctly to orchestrator constructor
  - [ ] All existing agent factory tests continue to pass (regression)
- **Test requirements**: unit (extend `tests/unit/test_agent_factory.py`)
- **Depends on**: T12-08
- **Implementation Guidance**:
  - Follow existing pattern in `test_agent_factory.py`: use `_make_config()` helper, construct agents, assert on types and properties.
  - Create config with `search_depth: "deep"` topic: `TopicConfig(name="AI", query="...", sources=["google_search"], search_depth="deep")`
  - Assert: `isinstance(topic_agent.sub_agents[0], DeepResearchOrchestrator)`
  - For standard mode: `isinstance(topic_agent.sub_agents[0], LlmAgent)`
  - Verify orchestrator's `max_rounds` matches config value.

### T12-11 - BDD tests for multi-round deep research
- **Description**: Write BDD-style acceptance tests for the four multi-round deep research scenarios from the spec.
- **Spec refs**: US-02, Section 11.2 (Feature: Multi-Round Deep Research)
- **Parallel**: No (depends on T12-09)
- **Acceptance criteria**:
  - [ ] BDD scenario: Deep mode executes multiple research rounds -- 3 rounds per provider with different queries, results combined
  - [ ] BDD scenario: Early exit when enough URLs collected -- only 2 rounds when 15+ URLs at round 2
  - [ ] BDD scenario: Standard mode is unaffected -- exactly 1 round, no query expansion
  - [ ] BDD scenario: max_research_rounds of 1 is single-round -- exactly 1 round, no query expansion
  - [ ] Tests follow existing BDD pattern in `tests/bdd/`
- **Test requirements**: BDD (new file `tests/bdd/test_deep_research.py`)
- **Depends on**: T12-09
- **Implementation Guidance**:
  - Follow existing BDD pattern in `tests/bdd/test_research_pipeline.py`.
  - Mock the search tools (google_search, search_perplexity) to return controlled outputs with known URLs.
  - For "multiple rounds" scenario: verify that state key `research_{idx}_{provider}` contains URLs from all 3 rounds.
  - For "early exit": mock round 2 to produce enough URLs to cross 15 threshold, verify round 3 never called.
  - These tests can use the orchestrator directly with a mocked InvocationContext, or run a mini-pipeline.

## Implementation Notes

- The `DeepResearchOrchestrator` follows the ADK custom agent pattern (StoryFlowAgent). It creates LlmAgent sub-agents and invokes them via `async for event in sub_agent.run_async(ctx)`.
- The `google_search` tool is a grounding tool that can only be used via LlmAgent. The orchestrator cannot call it directly -- it must invoke a LlmAgent that has `google_search` in its tools list.
- For Perplexity, the `search_perplexity` function tool can be called directly, but for consistency, the orchestrator uses LlmAgent for both providers.
- The query for each round is injected into the LlmAgent instruction via state variable interpolation: set `deep_query_current_{idx}_{provider}` in state, reference it in the instruction template as `{deep_query_current_X_Y}`.
- All intermediate state keys use the `{idx}_{provider}` suffix to avoid conflicts when multiple orchestrators run in parallel (different topics/providers).

## Parallel Opportunities

- T12-01 (query expansion prompt) and T12-02 (search round prompts) can be worked concurrently [P].
- T12-09 (unit tests) and T12-10 (factory tests) can be worked concurrently [P].
- All other tasks are sequential.

## Risks & Mitigations

- **Risk**: ADK sub-agent invocation via `run_async(ctx)` may not properly propagate state changes from the sub-agent back to the parent context. **Mitigation**: Verify with a minimal test that LlmAgent output_key writes are visible in `ctx.session.state` after `run_async()` completes. Fall back to direct LLM API call if needed.
- **Risk**: Instruction interpolation for round-specific queries may not work as expected with ADK state variables. **Mitigation**: Test interpolation pattern. If it fails, create a new LlmAgent per round with the query baked into the instruction string.
- **Risk**: Running multiple orchestrators in parallel (via ParallelAgent) may cause state key conflicts. **Mitigation**: All state keys include unique `{idx}_{provider}` suffixes. No shared mutable state between orchestrators.
- **Risk**: Query expansion LLM may produce poor quality variants that retrieve irrelevant results. **Mitigation**: Prompt engineering with specific angle requirements. Suffix-based fallback ensures at least basic variants are available.

## Activity Log
- 2026-03-15T00:00:00Z - planner - lane=planned - Work package created
- 2026-03-15T12:00:00Z - coder - lane=doing - Started implementation of WP12
- 2026-03-15T18:00:00Z - coder - lane=for_review - All tasks complete, submitted for review
- 2026-03-15T19:00:00Z - reviewer - lane=to_do - Verdict: Changes Required (1 FAIL) -- awaiting remediation
- 2026-03-15T20:00:00Z - coder - lane=doing - Addressing reviewer feedback (FB-01, FB-02, FB-03)
- 2026-03-15T21:00:00Z - coder - lane=for_review - All FB items resolved, re-submitted for review

## Self-Review (T12-01 through T12-11)

### Spec Compliance
- [x] FR-MRR-001: DeepResearchOrchestrator extends BaseAgent
- [x] FR-MRR-002: Round 0 uses original topic query
- [x] FR-MRR-003: Query expansion generates varied-angle alternatives
- [x] FR-MRR-004: JSON array output format with fallback
- [x] FR-MRR-005: Per-round state keys written
- [x] FR-MRR-006: Round merging with deduplicated sources
- [x] FR-MRR-007: Early exit at 15+ unique URLs
- [x] FR-MRR-009: Google rounds use google_search tool
- [x] FR-MRR-010: Perplexity rounds use search_perplexity tool
- [x] FR-MRR-011: Fallback query expansion on invalid JSON
- [x] FR-PIP-003: build_research_phase conditionally creates orchestrator
- [x] FR-BC-001: Standard-mode topics unchanged (LlmAgent)
- [x] FR-BC-002: max_rounds=1 skips query expansion, single round
- [x] FR-BC-004: Output state key research_N_provider produced regardless of mode

### Correctness
- [x] 524 tests pass (full suite)
- [x] 96.41% code coverage for deep_research.py (target: 80%)
- [x] 100% coverage for query_expansion.py
- [x] All 4 BDD scenarios from spec Section 11.2 implemented and passing

### Code Quality
- [x] No unused imports or dead code
- [x] No hardcoded values except spec-defined thresholds (15 URL threshold)
- [x] No security issues (no direct user input, no injection vectors)
- [x] Logging follows project conventions

### Scope Discipline
- [x] No unasked-for abstractions or optimizations
- [x] Only files required by spec were created/modified

### Encoding
- [x] No em dashes, smart quotes, or curly apostrophes

### Documentation
- [x] architecture.md updated (pipeline tree, state keys, phases, dynamic construction)
- [x] api-reference.md updated (new DeepResearchOrchestrator agent, factory function)
- [x] configuration-guide.md updated (search depth behavior table, multi-round explanation)
- [x] deployment-guide.md updated (timeout guidance, log messages)
- [x] developer-guide.md updated (project structure, agent types, naming, provider guide)
- [x] user-guide.md updated (topic options, configuration rules)

## Review

> **Reviewed by**: Reviewer Agent
> **Date**: 2026-03-15
> **Verdict**: Changes Required
> **review_status**: has_feedback

### Summary
Changes Required. One FAIL: query expansion events are swallowed instead of yielded, violating T12-04 acceptance criteria and the ADK event propagation contract. Two WARNs: sub-agents not created in constructor per T12-03, and user-guide.md omits `max_research_rounds` from the settings documentation.

### Review Feedback

> Implementers: if `review_status: has_feedback` is set in the WP frontmatter, address every item below before returning for re-review. Update `review_status: acknowledged` once you begin remediation.

- [x] **FB-01**: `_expand_queries()` in `newsletter_agent/tools/deep_research.py` (lines 170-183) swallows all events from the QueryExpanderAgent with `async for event in expander.run_async(ctx): pass`. The T12-04 acceptance criteria states: "Orchestrator invokes QueryExpanderAgent via `async for event in self._query_expander.run_async(ctx)` and yields all events". The spec Section 4.3 step 2 also specifies the `async for event in query_expander.run_async(ctx)` invocation pattern. Refactor so that query expansion events are yielded from `_run_async_impl`. Either inline the expansion logic into `_run_async_impl` or convert `_expand_queries` into an async generator that yields events and have the caller yield from it.
- [x] **FB-02**: Add a test in `tests/unit/test_deep_research.py` that verifies query expansion events are yielded (not just search round events). Currently no test checks for expansion event propagation.
- [x] **FB-03**: `docs/user-guide.md` does not document `max_research_rounds` in its settings section or configuration examples. Add it so users know how to configure the number of research rounds.

### Findings

#### FAIL - Spec Adherence: Query Expansion Event Yielding
- **Requirement**: T12-04 acceptance criteria, Spec Section 4.3 step 2
- **Status**: Deviating
- **Detail**: `_expand_queries()` consumes QueryExpanderAgent events with `pass` instead of yielding them. The plan explicitly requires "yields all events". This breaks ADK event propagation for the query expansion sub-agent.
- **Evidence**: `newsletter_agent/tools/deep_research.py` lines 181-183: `async for event in expander.run_async(ctx): pass`

#### WARN - Architecture: Sub-agents Not Created in Constructor
- **Requirement**: T12-03 acceptance criteria ("Creates QueryExpanderAgent and DeepSearchRound sub-agents in constructor")
- **Status**: Deviating
- **Detail**: Sub-agents are created on-the-fly in `_expand_queries()` and `_make_search_agent()` instead of in the constructor. The plan also recommends registering them in the `sub_agents` property. This is a reasonable architectural choice that avoids state interpolation concerns, but it deviates from the plan's letter. Does not block correctness.
- **Evidence**: No `sub_agents` property set; agents created per-invocation in helper methods.

#### WARN - Documentation: user-guide.md Missing max_research_rounds
- **Requirement**: Documentation accuracy (Section 4h)
- **Status**: Partial
- **Detail**: `docs/user-guide.md` references deep research behavior but does not document the `max_research_rounds` setting in its settings section or show it in configuration examples. Users cannot discover this setting from the user guide alone.
- **Evidence**: `docs/user-guide.md` -- no mention of `max_research_rounds` in settings table or YAML examples.

#### PASS - Process Compliance
- **Requirement**: Spec Compliance Checklist, Activity Log, commit per task
- **Status**: Compliant
- **Detail**: Spec Compliance Checklist present with all items checked. Activity Log entries present. Single commit for all tasks (batched, not per-task -- acceptable given single WP scope).

#### PASS - Spec Adherence: Core Orchestrator
- **Requirement**: FR-MRR-001 through FR-MRR-011
- **Status**: Compliant
- **Detail**: DeepResearchOrchestrator extends BaseAgent, implements multi-round search loop, query expansion with fallback, URL tracking, early exit at 15 URLs, round merging with dedup, state cleanup. All FR requirements met except event yielding (separate finding).

#### PASS - Data Model Adherence
- **Requirement**: Section 7.2 (Session State - New Keys)
- **Status**: Compliant
- **Detail**: All intermediate state keys (`deep_queries_`, `deep_research_latest_`, `deep_query_current_`, `research_*_round_*`, `deep_urls_accumulated_`) and final key (`research_{idx}_{provider}`) match spec.

#### PASS - API / Interface Adherence
- **Requirement**: Section 8.3 (Agent Contracts)
- **Status**: Compliant
- **Detail**: DeepResearchOrchestrator contract matches spec. QueryExpanderAgent output_key, DeepSearchRound output_key, and merge behavior all correct.

#### PASS - Architecture Adherence
- **Requirement**: Section 9.1, 9.4 Decision 1
- **Status**: Compliant
- **Detail**: Custom BaseAgent pattern used per Decision 1. Pipeline structure correctly conditionally creates orchestrator for deep-mode topics.

#### PASS - Test Coverage Adherence
- **Requirement**: Section 11.1, 11.2
- **Status**: Compliant
- **Detail**: All 4 BDD scenarios from spec Section 11.2 implemented. Unit tests cover orchestrator invocation, round execution, URL tracking, early exit, merging, cleanup, fallback, and max_rounds=1. 524 tests pass.

#### PASS - Non-Functional Adherence
- **Requirement**: Section 10
- **Status**: Compliant
- **Detail**: No security issues. Logging follows project conventions with `[DeepResearch]` prefix. No user input handling (internal agent). Progress events yielded for round tracking.

#### PASS - Performance
- **Requirement**: Performance review
- **Status**: Compliant
- **Detail**: No N+1 patterns. URL dedup uses set() for O(1). Early exit avoids unnecessary rounds. State cleanup removes intermediate keys.

#### PASS - Documentation: api-reference.md, architecture.md, configuration-guide.md, deployment-guide.md, developer-guide.md
- **Requirement**: Documentation accuracy
- **Status**: Compliant
- **Detail**: All five docs accurately reflect the implementation. Architecture diagram, state key table, agent contracts, config fields, timeout guidance, and project structure all match code.

#### PASS - Success Criteria
- **Requirement**: SC-002, SC-004, SC-005, SC-006
- **Status**: Compliant
- **Detail**: SC-002 (15+ URLs) verified via early exit test. SC-004 (max_rounds respected) verified via unit test. SC-005 (standard unchanged) verified via BDD and unit tests. SC-006 (524 tests pass, exceeding original 437).

#### PASS - Coverage Thresholds
- **Requirement**: >= 80% code, >= 90% branch
- **Status**: Compliant
- **Detail**: deep_research.py: 98% (146/149 stmts, 3 missed in async generator bodies). query_expansion.py: 100%. Total: 97.99%. No `pragma: no cover` exclusions.

#### PASS - Scope Discipline
- **Requirement**: No scope creep
- **Status**: Compliant
- **Detail**: 15 files modified, all within WP12 scope (source, tests, docs, plans). No unspecified features or abstractions.

#### PASS - Encoding (UTF-8)
- **Requirement**: No em dashes, smart quotes, curly apostrophes
- **Status**: Compliant
- **Detail**: All new/modified files use standard ASCII characters only.

### Statistics
| Dimension | Pass | Warn | Fail |
|-----------|------|------|------|
| Process Compliance | 1 | 0 | 0 |
| Spec Adherence | 1 | 0 | 1 |
| Data Model | 1 | 0 | 0 |
| API / Interface | 1 | 0 | 0 |
| Architecture | 0 | 1 | 0 |
| Test Coverage | 1 | 0 | 0 |
| Non-Functional | 1 | 0 | 0 |
| Performance | 1 | 0 | 0 |
| Documentation | 1 | 1 | 0 |
| Success Criteria | 1 | 0 | 0 |
| Coverage Thresholds | 1 | 0 | 0 |
| Scope Discipline | 1 | 0 | 0 |
| Encoding (UTF-8) | 1 | 0 | 0 |

### Recommended Actions
1. **FB-01**: Refactor `_expand_queries()` to yield events from the QueryExpanderAgent instead of swallowing them with `pass`. Move the async for loop into `_run_async_impl` or convert to an async generator pattern.
2. **FB-02**: Add a unit test verifying that query expansion events are included in the yielded event stream from `_run_async_impl`.
3. **FB-03**: Add `max_research_rounds` to `docs/user-guide.md` settings section and include it in at least one YAML configuration example.
