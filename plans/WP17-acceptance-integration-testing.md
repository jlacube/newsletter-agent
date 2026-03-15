---
lane: planned
---

# WP17 - Acceptance & Integration Testing

> **Spec**: `specs/002-adaptive-deep-research.spec.md`
> **Status**: Not Started
> **Priority**: P1
> **Goal**: Validate the adaptive research loop via BDD scenarios, integration tests, and backward compatibility verification
> **Independent Test**: Run `pytest tests/bdd/ tests/integration/ -v` and verify all acceptance and integration tests pass including the new adaptive research scenarios
> **Depends on**: WP16
> **Parallelisable**: No
> **Prompt**: `plans/WP17-acceptance-integration-testing.md`

## Objective

This work package validates the adaptive deep research implementation through BDD acceptance tests matching the spec's 10 Gherkin scenarios, integration tests verifying the full Plan-Search-Analyze-Decide flow with mocked search tools, and backward compatibility checks ensuring standard-mode and single-round-mode topics remain unaffected. This WP completes the MVP scope.

## Spec References

- Section 11.2 (BDD / Acceptance Tests - 10 Gherkin scenarios)
- Section 11.3 (Integration Tests - 5 integration scenarios)
- Section 11.4 (End-to-End Tests)
- FR-ADR-080 through FR-ADR-085 (Backward Compatibility)
- SC-ADR-001 through SC-ADR-006 (Success Criteria)
- US-ADR-01 through US-ADR-05 (User Stories)

## Tasks

### T17-01 - Update existing BDD tests for adaptive behavior

- **Description**: Update `tests/bdd/test_deep_research.py` to reflect the changed orchestrator behavior. Existing scenarios for "deep mode executes multiple rounds" and "early exit" need their mocking strategy updated since the orchestrator no longer uses query expansion and no longer exits on URL count.
- **Spec refs**: FR-ADR-001, FR-ADR-003, FR-ADR-041, SC-ADR-005, BDD Scenario 1
- **Parallel**: No
- **Acceptance criteria**:
  - [ ] Existing "Deep mode executes multiple rounds" scenario updated: mocks PlanningAgent and AnalysisAgent instead of QueryExpanderAgent
  - [ ] Existing "Early exit" scenario updated: no longer tests 15-URL threshold (removed per FR-ADR-041), instead tests saturation-based exit
  - [ ] Existing "Standard mode unaffected" scenario continues to pass unchanged
  - [ ] Existing "max_research_rounds=1 is single-round" scenario continues to pass (may need minor mock updates)
  - [ ] All updated BDD tests pass: `pytest tests/bdd/test_deep_research.py -v` exits with code 0
- **Test requirements**: BDD
- **Depends on**: WP16 (orchestrator complete)
- **Implementation Guidance**:
  - File to modify: `tests/bdd/test_deep_research.py`
  - The existing tests mock the `QueryExpanderAgent` behavior -- replace this with mocking the PlanningAgent (writing to `adaptive_plan_{idx}_{provider}` state key) and AnalysisAgent (writing to `adaptive_analysis_{idx}_{provider}`)
  - The "early exit" test currently checks for `accumulated_urls >= 15`. Replace with mocking the AnalysisAgent to return `saturated: true` after round 2
  - Keep the same Given/When/Then structure; update the internal mock wiring
  - Known pitfall: The mocking for AnalysisAgent needs to return different results per round (round 0: not saturated with gaps; round 1: not saturated with fewer gaps; round 2: saturated). Use `side_effect` to cycle through responses.

### T17-02 - Add BDD scenarios: saturation and early exit paths

- **Description**: Implement BDD test scenarios for saturation detection, round 0 saturation override, empty knowledge gaps exit, and search budget exhaustion. These correspond to spec BDD Scenarios 2, 3, 4, 5.
- **Spec refs**: Section 11.2 (Scenarios 2-5), FR-ADR-040, FR-ADR-042, FR-ADR-062
- **Parallel**: Yes (independent of T17-03, T17-04)
- **Acceptance criteria**:
  - [ ] **Scenario 2 - Saturation detection triggers early exit**: Given deep mode with max_research_rounds=5, when AnalysisAgent reports saturated after round 2, then only 3 rounds execute (0,1,2) and log contains saturation exit message
  - [ ] **Scenario 3 - Round 0 saturation is overridden**: Given deep mode with max_research_rounds=3, when AnalysisAgent reports saturated on round 0, then at least `min_research_rounds` rounds execute
  - [ ] **Scenario 4 - Empty knowledge gaps triggers early exit**: Given deep mode with max_research_rounds=5, when AnalysisAgent reports empty knowledge_gaps after round 1, then only 2 rounds execute and log contains coverage exit message
  - [ ] **Scenario 5 - Search budget exhaustion stops loop**: Given deep mode with max_research_rounds=5 and max_searches_per_topic=2, then only 2 search rounds execute and log contains budget exhaustion message
  - [ ] All scenarios use mocked LLM responses (no real API calls)
  - [ ] All scenarios verify log output contains expected `[AdaptiveResearch]` messages
- **Test requirements**: BDD
- **Depends on**: T17-01 (shared fixtures/helpers)
- **Implementation Guidance**:
  - File to extend: `tests/bdd/test_deep_research.py` (or create `tests/bdd/test_adaptive_research.py` if the file grows too large)
  - Use pytest parameterize or separate test functions for each scenario
  - For log verification: use `caplog` pytest fixture to capture log messages and assert on them
  - For Scenario 3 (round 0 override): mock AnalysisAgent to return `saturated: true` on round 0, verify at least 2 rounds of search occur
  - For Scenario 5 (budget): construct orchestrator with `max_searches=2, max_rounds=5`, verify only 2 search agent invocations happened
  - Gherkin scenarios from spec Section 11.2 should be used as test names/docstrings

### T17-03 - Add BDD scenarios: single-round, standard mode, fallbacks

- **Description**: Implement BDD test scenarios for single-round mode, standard mode unaffected, planning failure fallback, analysis failure fallback, and reasoning chain logging. Corresponds to spec BDD Scenarios 6, 7, 8, 9, 10.
- **Spec refs**: Section 11.2 (Scenarios 6-10), FR-ADR-063, FR-ADR-080, FR-ADR-013, FR-ADR-033
- **Parallel**: Yes (independent of T17-02)
- **Acceptance criteria**:
  - [ ] **Scenario 6 - Single round mode**: Given max_research_rounds=1, then exactly 1 search round executes, no planning or analysis agents invoked
  - [ ] **Scenario 7 - Standard mode unaffected**: Given search_depth="standard" with max_research_rounds=3, then exactly 1 search round per provider, no adaptive planning or analysis
  - [ ] **Scenario 8 - Planning failure fallback**: Given PlanningAgent returns invalid JSON, then original topic query is used for round 0, default key_aspects used, warning logged
  - [ ] **Scenario 9 - Analysis failure fallback**: Given AnalysisAgent returns invalid JSON on round 1, then fallback suffix-based query used for round 2, warning logged, loop continues
  - [ ] **Scenario 10 - Reasoning chain logged**: Given max_research_rounds=3, then INFO logs contain planning output, each round's analysis summary and gaps, completion message with exit reason
  - [ ] All scenarios verify correct log messages using `caplog` fixture
- **Test requirements**: BDD
- **Depends on**: T17-01 (shared fixtures/helpers)
- **Implementation Guidance**:
  - File to extend: same as T17-02
  - For Scenario 7 (standard mode): this test validates that standard-mode code path in `agent.py` creates an `LlmAgent` (not `DeepResearchOrchestrator`). This test may already exist -- verify and update if needed.
  - For Scenario 8 (planning failure): mock the PlanningAgent's output_key to contain invalid JSON (e.g., `"not json"`), verify the orchestrator continues with `self.query` and default aspects
  - For Scenario 9 (analysis failure): mock AnalysisAgent to return invalid JSON on a specific round, verify fallback query contains a suffix from `_FALLBACK_SUFFIXES`
  - For Scenario 10 (reasoning chain): use `caplog` at INFO level, search for `[AdaptiveResearch]` prefix in captured messages
  - Pattern for mocking per-round responses: create a side_effect function that returns different state values based on invocation count

### T17-04 - Integration tests: full adaptive flow with mocked tools

- **Description**: Create integration tests that exercise the full adaptive orchestrator flow end-to-end with mocked search tools but real orchestrator logic. Test the complete Plan-Search-Analyze-Decide cycle across multiple rounds.
- **Spec refs**: Section 11.3 (Integration Tests), FR-ADR-001, FR-ADR-082, FR-ADR-083
- **Parallel**: No (depends on T17-01 for test infrastructure patterns)
- **Acceptance criteria**:
  - [ ] Test adaptive research with mocked Google Search tool: planning -> search -> analysis -> next query flow across 3 rounds, final output in SUMMARY+SOURCES format
  - [ ] Test adaptive research with mocked Perplexity tool: same flow verification for Perplexity provider
  - [ ] Test pipeline with mixed topics (standard + deep): standard topics use LlmAgent, deep topics use adaptive orchestrator, both produce valid output
  - [ ] Test `max_searches_per_topic < max_research_rounds`: search budget is binding, loop exits early
  - [ ] Test saturation path: mock AnalysisAgent to return `saturated: true` on round 2, verify only 3 rounds execute
  - [ ] Each test verifies the final `research_{idx}_{provider}` state key contains valid SUMMARY + SOURCES format
- **Test requirements**: integration
- **Depends on**: T17-01
- **Implementation Guidance**:
  - File to create or modify: `tests/integration/test_adaptive_research_integration.py`
  - Integration tests should use a more realistic setup than unit tests: real `InvocationContext`, real state dict, mocked LlmAgent.run_async
  - Mock the search tool responses with realistic SUMMARY + SOURCES output containing multiple URLs
  - For mixed topic tests: build the full research phase using `build_research_phase(config)` and verify the agent tree
  - Follow patterns from existing `tests/integration/test_deep_research_integration.py`
  - Use `pytest.mark.integration` marker

### T17-05 - Update backward compatibility tests

- **Description**: Update existing backward compatibility tests in `tests/integration/` to ensure they still pass with the new adaptive orchestrator. These tests verify that the external contract (state key format, pipeline position, config schema) is unchanged.
- **Spec refs**: FR-ADR-080 through FR-ADR-085, SC-ADR-005
- **Parallel**: No (depends on T17-04 for integration test patterns)
- **Acceptance criteria**:
  - [ ] `tests/integration/test_backward_compatibility.py` passes - existing config YAML loads correctly
  - [ ] `tests/integration/test_backward_compat_deep.py` passes - deep mode output format unchanged (SUMMARY + SOURCES)
  - [ ] Test: config without `max_searches_per_topic` or `min_research_rounds` loads and runs successfully
  - [ ] Test: `max_research_rounds=1` with deep mode produces single-round output identical to previous behavior
  - [ ] Test: standard-mode topics produce identical output format
  - [ ] All backward compat tests pass: `pytest tests/integration/test_backward_compat*.py -v` exits with code 0
- **Test requirements**: integration
- **Depends on**: T17-04
- **Implementation Guidance**:
  - Files to verify/modify: `tests/integration/test_backward_compatibility.py`, `tests/integration/test_backward_compat_deep.py`
  - These tests may need mock updates (removing references to QueryExpanderAgent, adding PlanningAgent/AnalysisAgent mocks)
  - The key assertion is that `research_{idx}_{provider}` contains `SUMMARY:` and `SOURCES:` sections -- this must remain unchanged
  - If existing tests reference internal methods like `_expand_queries`, update or remove those references
  - Check `tests/integration/test_combined_features.py` for any multi-topic tests that may need updates

### T17-06 - End-to-end test with dry_run mode

- **Description**: Create or update an E2E test that runs the full pipeline with `dry_run: true` and deep-mode topics, verifying that adaptive research log entries appear and HTML output contains multi-round research.
- **Spec refs**: Section 11.4 (E2E Tests), SC-ADR-004
- **Parallel**: No (depends on T17-04)
- **Acceptance criteria**:
  - [ ] Test runs full pipeline with `dry_run: true`, at least one deep-mode topic
  - [ ] Log output contains `[AdaptiveResearch]` entries for: planning, per-round analysis, completion
  - [ ] HTML output file is produced (or would be produced in non-dry-run mode)
  - [ ] Test completes within reasonable time (mocked tools, so < 30 seconds)
- **Test requirements**: E2E
- **Depends on**: T17-04
- **Implementation Guidance**:
  - File: `tests/e2e/test_adaptive_e2e.py` (create new or extend existing)
  - This test may use partially mocked search tools (to avoid real API calls) while exercising the full pipeline wiring
  - Use `caplog` or log capture to verify `[AdaptiveResearch]` messages
  - Use `pytest.mark.e2e` marker
  - If the existing E2E directory is empty/placeholder, create a simple test that at minimum validates the pipeline builds correctly with adaptive orchestrators

### T17-07 - Coverage threshold verification

- **Description**: Run the full test suite with coverage measurement and verify that the adaptive research code meets the required thresholds.
- **Spec refs**: Section 11.1 (minimum coverage: 80% code, 90% branch)
- **Parallel**: No (final task)
- **Acceptance criteria**:
  - [ ] `pytest tests/ --cov=newsletter_agent --cov-branch --cov-report=term-missing` shows >= 80% line coverage for `newsletter_agent/tools/deep_research.py`
  - [ ] Branch coverage for `deep_research.py` >= 90%
  - [ ] Coverage for `newsletter_agent/prompts/reasoning.py` >= 80% line, >= 90% branch
  - [ ] Coverage for `newsletter_agent/config/schema.py` >= 80% line, >= 90% branch
  - [ ] Full test suite passes: `pytest tests/ -v` exits with code 0
  - [ ] No regressions in any existing test
- **Test requirements**: coverage verification
- **Depends on**: T17-01 through T17-06
- **Implementation Guidance**:
  - Run: `pytest tests/ --cov=newsletter_agent --cov-branch --cov-report=term-missing -v`
  - Focus coverage analysis on: `deep_research.py`, `reasoning.py`, `schema.py`
  - If coverage is below threshold for specific modules, identify uncovered branches and add targeted tests
  - The project's `pyproject.toml` already has `fail_under = 80` for overall coverage
  - For 90% branch coverage, pay special attention to: all fallback paths, all exit conditions, empty/edge-case inputs

## Implementation Notes

- **Mock strategy summary**: All BDD and integration tests mock LlmAgent invocations. The approach is:
  1. Patch `LlmAgent.run_async` or use state injection to simulate agent outputs
  2. PlanningAgent writes JSON to `adaptive_plan_{idx}_{provider}` state key
  3. Search agents write SUMMARY+SOURCES to `deep_research_latest_{idx}_{provider}`
  4. AnalysisAgent writes JSON to `adaptive_analysis_{idx}_{provider}` state key
  5. Test verifies orchestrator's decision logic, merging, and state management

- **Log verification**: Use `caplog` fixture:
  ```python
  def test_saturation_logged(caplog):
      with caplog.at_level(logging.INFO):
          # ... run orchestrator ...
      assert any("[AdaptiveResearch]" in m and "saturated" in m for m in caplog.messages)
  ```

- **Test commands**:
  - BDD: `pytest tests/bdd/ -v`
  - Integration: `pytest tests/integration/ -v`
  - E2E: `pytest tests/e2e/ -v`
  - All: `pytest tests/ -v --cov=newsletter_agent --cov-branch`

## Parallel Opportunities

- T17-02 (saturation/exit BDD) and T17-03 (single-round/fallback BDD) can be developed in parallel
- T17-06 (E2E) is independent of specific BDD/integration tasks once the orchestrator works

## Risks & Mitigations

- **Risk**: BDD tests become brittle if they depend on exact mock call counts (e.g., "PlanningAgent invoked exactly once"). **Mitigation**: Prefer asserting on state outcomes (what state keys exist, what values they contain) over invocation counts. Use call counts only where the spec explicitly requires a specific number of invocations.
- **Risk**: Integration tests with mocked search tools may not catch real-world issues (e.g., actual Google Search grounding returning unexpected formats). **Mitigation**: Use realistic mock responses that include actual SUMMARY+SOURCES formatting, multiple URLs, and edge cases (empty results, single URL). The scope of these tests is orchestration logic, not search tool behavior.
- **Risk**: Existing BDD tests in `test_deep_research.py` may have deeply embedded assumptions about QueryExpanderAgent that require extensive rewriting. **Mitigation**: T17-01 explicitly handles this update. If the rewrite is too extensive, considered creating `test_adaptive_deep_research.py` as a separate file alongside (not replacing) the existing tests.

## Activity Log

- 2026-03-15T00:00:00Z - planner - lane=planned - Work package created
