---
lane: planned
---

# WP14 - Integration Testing & Backward Compatibility

> **Spec**: `specs/autonomous-deep-research.spec.md`
> **Status**: Not Started
> **Priority**: P1 (quality assurance for MVP)
> **Goal**: Verify all features work together end-to-end: mixed standard/deep topics, CLI runner with full pipeline, backward compatibility, and performance within bounds
> **Independent Test**: Run the full test suite (`pytest tests/`) and verify all tests pass, including new integration/E2E/BDD tests, with no regressions in the existing 437+ tests.
> **Depends on**: WP11, WP12, WP13
> **Parallelisable**: No (requires all features implemented)
> **Prompt**: `plans/WP14-integration-testing.md`

## Objective

This work package verifies that all three features (CLI runner, multi-round deep research, source refinement) work correctly together and do not break existing functionality. It covers integration tests with mocked external services, E2E tests with subprocess execution, backward compatibility verification, performance benchmarks, and security checks.

## Spec References

- FR-BC-001 through FR-BC-004 (Section 4.6)
- US-01 through US-04 (Section 5)
- Section 11.3 (Integration Tests)
- Section 11.4 (End-to-End Tests)
- Section 11.5 (Performance Tests)
- Section 11.6 (Security Tests)
- SC-001 through SC-006 (Section 2)

## Tasks

### T14-01 - Integration test: multi-round research with mocked tools
- **Description**: Write an integration test that runs the full research phase with deep-mode topics using mocked Google Search and Perplexity tools, verifying that multiple rounds produce accumulated results in correct state keys.
- **Spec refs**: FR-MRR-001 through FR-MRR-011, Section 11.3
- **Parallel**: Yes [P] (independent of T14-02)
- **Acceptance criteria**:
  - [ ] Test creates a config with `search_depth: "deep"` and `max_research_rounds: 3`
  - [ ] Mocks `google_search` and `search_perplexity` tools to return controlled outputs with known URLs
  - [ ] Runs the research phase (ParallelAgent containing DeepResearchOrchestrator)
  - [ ] Verifies `research_{idx}_{provider}` state keys contain URLs from all 3 rounds
  - [ ] Verifies intermediate state keys are cleaned up (no `deep_*` or `round_*` keys remain)
  - [ ] Verifies standard research format (SUMMARY + SOURCES sections)
- **Test requirements**: integration (extend or add to `tests/integration/`)
- **Depends on**: none (assumes WP12 implemented)
- **Implementation Guidance**:
  - Follow existing integration test pattern in `tests/integration/conftest.py`.
  - Create a mocked tool that returns different URLs per invocation (simulating different round results).
  - Use `InMemorySessionService` to create a session, build the research phase agent, and run it via `Runner`.
  - Verify state by inspecting `session.state` after pipeline completes.
  - Check for state key cleanup: `assert not any(k.startswith("deep_") for k in state.keys())`

### T14-02 - Integration test: mixed standard and deep topics
- **Description**: Write an integration test with a config containing both standard-mode and deep-mode topics, verifying that standard topics are unaffected while deep topics get multi-round research.
- **Spec refs**: FR-BC-001, FR-BC-004, Section 11.3
- **Parallel**: Yes [P] (independent of T14-01)
- **Acceptance criteria**:
  - [ ] Config has 2+ topics: at least one standard, at least one deep
  - [ ] Standard topic produces single `research_{idx}_{provider}` key (no round keys, no deep keys)
  - [ ] Deep topic produces `research_{idx}_{provider}` key with multi-round results
  - [ ] Standard topic output format is identical to pre-change behavior (FR-BC-001)
  - [ ] All state keys consumed by downstream agents maintain current format (FR-BC-004)
- **Test requirements**: integration
- **Depends on**: none (assumes WP12 implemented)
- **Implementation Guidance**:
  - Create config with 2 topics: `TopicConfig(search_depth="standard")` and `TopicConfig(search_depth="deep")`.
  - Run research phase with mocked tools.
  - For the standard topic: assert output matches the format produced by a single LlmAgent (snapshot comparison).
  - For the deep topic: assert output contains SOURCES from multiple rounds.

### T14-03 - Integration test: CLI runner end-to-end with mocks
- **Description**: Write an integration test that runs the CLI `main()` function with mocked search tools, verifying complete pipeline execution including research, refinement, and output.
- **Spec refs**: FR-CLI-002, FR-CLI-004, FR-CLI-005, Section 11.3
- **Parallel**: Yes [P] (independent of T14-01, T14-02)
- **Acceptance criteria**:
  - [ ] Calls `main()` function (not subprocess) with mocked search tools and `dry_run: true`
  - [ ] Pipeline runs to completion (config -> research -> validate -> verify -> refine -> synthesize -> output)
  - [ ] Returns exit code 0
  - [ ] JSON summary output contains all required fields: `status`, `newsletter_date`, `topics_processed`, `email_sent`, `output_file`
  - [ ] HTML output file exists at the path specified in summary
- **Test requirements**: integration
- **Depends on**: none (assumes WP11, WP12, WP13 implemented)
- **Implementation Guidance**:
  - Mock the search tools and synthesis model to return controlled outputs.
  - Use `tmp_path` fixture for output directory.
  - Set `dry_run: true` in config to avoid email sending.
  - Capture stdout to parse JSON summary.
  - Check that HTML file exists and contains expected content markers.

### T14-04 - E2E test: full pipeline with deep-mode topics (dry_run)
- **Description**: Write an E2E test that runs the full pipeline with real agent construction but mocked external APIs, verifying HTML output contains sources from multiple research rounds.
- **Spec refs**: Section 11.4, SC-002, SC-003
- **Parallel**: No (depends on T14-01 through T14-03 for confidence)
- **Acceptance criteria**:
  - [ ] Test builds the complete pipeline with `build_pipeline()` using a deep-mode config
  - [ ] Runs via ADK Runner with mocked search tools
  - [ ] Verifies deep-mode topics collected at least 15 unique source URLs across rounds (SC-002, before verification)
  - [ ] If refinement ran: verifies 5-10 curated sources remain per deep-mode topic-provider (SC-003)
  - [ ] HTML output file is generated in `output/` directory
  - [ ] Test runs in under 60 seconds (no real API calls)
- **Test requirements**: E2E (extend `tests/e2e/`)
- **Depends on**: T14-01, T14-02, T14-03
- **Implementation Guidance**:
  - Follow existing E2E test pattern in `tests/e2e/test_full_pipeline.py`.
  - Use mocked tools that return realistic multi-URL outputs per search round.
  - For SC-002 verification: inspect intermediate state (or log output) to confirm URL accumulation.
  - For SC-003 verification: inspect final `research_{idx}_{provider}` state key and count SOURCES entries.
  - Use `@pytest.mark.e2e` marker.

### T14-05 - E2E test: CLI subprocess execution
- **Description**: Write an E2E test that runs `python -m newsletter_agent` as a subprocess and verifies exit code and output.
- **Spec refs**: FR-CLI-001, FR-CLI-004, SC-001, Section 11.4
- **Parallel**: No (depends on T14-04)
- **Acceptance criteria**:
  - [ ] Runs `subprocess.run(["python", "-m", "newsletter_agent"])` in a clean environment
  - [ ] With valid config and `dry_run: true`: exit code 0 (SC-001)
  - [ ] Stdout contains JSON summary line with `status: "success"`
  - [ ] HTML output file exists at path in summary
  - [ ] With invalid config: exit code 1, error message in output
- **Test requirements**: E2E
- **Depends on**: T14-04
- **Implementation Guidance**:
  - Use `subprocess.run()` with `capture_output=True`, `text=True`, `timeout=120`.
  - Set up environment: create temp `config/topics.yaml` with `dry_run: true`, set required env vars.
  - For the valid config test: mock external APIs via environment variable flags or test fixtures.
  - For the invalid config test: create intentionally malformed YAML.
  - Known pitfall: subprocess tests are slow and environment-dependent. Consider marking as `@pytest.mark.slow` or `@pytest.mark.e2e`.
  - Alternative: If real API keys are not available in CI, mock at the tool level by patching imports. This may require the subprocess to load a test config that uses mocked tools.

### T14-06 - Backward compatibility: standard mode unchanged
- **Description**: Verify that standard-mode topics produce identical results and behavior to pre-change baseline (SC-005).
- **Spec refs**: FR-BC-001, SC-005, SC-006
- **Parallel**: Yes [P] (independent of T14-04, T14-05)
- **Acceptance criteria**:
  - [ ] Standard-mode topic with `max_research_rounds: 3` performs exactly 1 search round per provider (no loop, no expansion) (FR-BC-001)
  - [ ] Standard-mode output format matches pre-change format exactly (FR-BC-004)
  - [ ] All existing 437+ tests continue to pass (SC-006)
  - [ ] No new state keys are created for standard-mode topics (no `deep_*` keys)
- **Test requirements**: integration, regression
- **Depends on**: none (assumes WP12 implemented)
- **Implementation Guidance**:
  - Run the existing test suite: `pytest tests/ -x --tb=short` and verify all pass.
  - Add a specific regression test: create a standard-mode config, run research phase, snapshot the output, compare against known baseline.
  - Check state keys: `assert not any(k.startswith("deep_") for k in state.keys())` for standard topics.

### T14-07 - Backward compatibility: max_research_rounds=1
- **Description**: Verify that deep-mode topics with `max_research_rounds: 1` behave identically to current single-round deep research.
- **Spec refs**: FR-BC-002, US-02 Scenario 4
- **Parallel**: Yes [P] (independent of T14-06)
- **Acceptance criteria**:
  - [ ] Deep-mode topic with `max_research_rounds: 1` performs exactly 1 search round per provider
  - [ ] No query expansion occurs (no `deep_queries_*` state key created)
  - [ ] Output format matches single-round deep research format
  - [ ] No intermediate round keys created (no `research_*_round_*` keys)
- **Test requirements**: integration
- **Depends on**: none (assumes WP12 implemented)
- **Implementation Guidance**:
  - Create config with `search_depth: "deep"`, `max_research_rounds: 1`.
  - Run research phase with mocked tools.
  - Verify single round executed (mock tool called exactly once per provider).
  - Verify no expansion: `assert f"deep_queries_0_google" not in state`.
  - Verify output matches single-round format.

### T14-08 - Performance benchmark for deep research
- **Description**: Benchmark deep-mode research time with mocked tools to establish baseline and verify total pipeline time stays within bounds.
- **Spec refs**: Section 10.1, Section 11.5
- **Parallel**: No (depends on T14-04)
- **Acceptance criteria**:
  - [ ] Measure per-round latency with mocked tools (fast, < 1s per round with mocks)
  - [ ] Measure total pipeline time with 3 deep-mode topics (should stay under 60s with mocks)
  - [ ] Document baseline timing for future comparison
  - [ ] Performance test does not fail CI (advisory only)
- **Test requirements**: performance (extend `tests/performance/`)
- **Depends on**: T14-04
- **Implementation Guidance**:
  - Follow existing performance test pattern in `tests/performance/test_pipeline_timing.py`.
  - Use `time.perf_counter()` or `pytest-benchmark` if available.
  - Mark with `@pytest.mark.performance`.
  - This is an advisory test -- it establishes baselines, not strict pass/fail thresholds.

### T14-09 - Security verification
- **Description**: Verify that the new features do not introduce security vulnerabilities: CLI does not accept arbitrary arguments, query expansion does not leak system instructions, existing SSRF protections work.
- **Spec refs**: Section 10.2, Section 11.6
- **Parallel**: Yes [P] (independent of T14-08)
- **Acceptance criteria**:
  - [ ] CLI runner does not accept command-line arguments that could be used for injection
  - [ ] Query expansion prompt does not leak system instructions (prompt does not contain sensitive info)
  - [ ] Existing SSRF prevention tests continue to pass
  - [ ] No new external attack surface introduced
- **Test requirements**: security (extend `tests/security/`)
- **Depends on**: none (assumes WP11 implemented)
- **Implementation Guidance**:
  - For CLI argument safety: verify `__main__.py` does not use `sys.argv` or `argparse`. The spec explicitly states "no command-line arguments".
  - For prompt safety: verify query expansion and refinement prompts do not include API keys, file paths, or other sensitive information.
  - Run existing security tests: `pytest tests/security/ -v` and verify they pass.
  - Add a simple test: attempt to pass arguments to `python -m newsletter_agent --malicious` and verify they are ignored or cause clean error.

### T14-10 - Verify existing entry points remain functional
- **Description**: Confirm that `adk run`, `adk web`, and HTTP handler continue to work with the updated pipeline.
- **Spec refs**: FR-BC-003, FR-CLI-006
- **Parallel**: Yes [P] (independent of T14-09)
- **Acceptance criteria**:
  - [ ] `from newsletter_agent.agent import root_agent` succeeds (ADK discovery) (FR-BC-003)
  - [ ] `root_agent` is a SequentialAgent with correct sub-agent count (FR-BC-003)
  - [ ] HTTP handler can be imported and endpoint is callable (FR-CLI-006)
  - [ ] No import errors or side effects from new modules
- **Test requirements**: integration (extend existing handler tests)
- **Depends on**: none
- **Implementation Guidance**:
  - Extend `tests/unit/test_http_handler.py` to verify import still works.
  - Add a test: `from newsletter_agent.agent import root_agent; assert root_agent.name == "NewsletterPipeline"`
  - Verify sub_agent count matches expected (now with DeepResearchRefiner added).
  - Run existing handler tests to confirm no regression.

## Implementation Notes

- This WP focuses entirely on testing -- no new production code is written. All production code comes from WP11, WP12, WP13.
- Integration tests use ADK Runner with InMemorySessionService and mocked tools. They construct real agent trees and run them.
- E2E tests use subprocess execution for the CLI and full pipeline runs for agent-based tests.
- Backward compatibility tests are critical -- they verify SC-005 and SC-006 (existing behavior unchanged, existing tests pass).
- Performance tests are advisory only. Real latency depends on API response times which cannot be tested with mocks.

## Parallel Opportunities

- T14-01 (multi-round integration), T14-02 (mixed topics), T14-03 (CLI integration) can be worked concurrently [P].
- T14-06 (standard mode compat), T14-07 (max_rounds=1 compat), T14-09 (security), T14-10 (entry points) can be worked concurrently [P].
- T14-04 and T14-05 are sequential (E2E depends on integration confidence).

## Risks & Mitigations

- **Risk**: E2E subprocess tests may be flaky in CI due to environment setup (missing API keys, config files). **Mitigation**: Use environment-independent mocking strategy. Mark flaky tests with `@pytest.mark.skipif` when API keys are absent.
- **Risk**: Existing tests may break due to import side effects from new modules. **Mitigation**: T14-10 catches this early. New modules should not have side effects at import time.
- **Risk**: Performance benchmarks may be meaningless with mocked tools (too fast). **Mitigation**: Document that these are baseline measurements. Real performance testing requires API keys and is done manually.

## Activity Log
- 2026-03-15T00:00:00Z - planner - lane=planned - Work package created
