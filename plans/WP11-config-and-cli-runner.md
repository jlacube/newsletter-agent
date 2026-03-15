---
lane: for_review
---

# WP11 - Config Extension & Autonomous CLI Runner

> **Spec**: `specs/autonomous-deep-research.spec.md`
> **Status**: Complete
> **Priority**: P0 (config field) / P1 (CLI runner = US-01)
> **Goal**: Add `max_research_rounds` config field and a `python -m newsletter_agent` CLI entry point that runs the full pipeline without interactive input
> **Independent Test**: Run `python -m newsletter_agent` with `dry_run: true` in config. Verify it completes without prompting, produces HTML in `output/`, and exits with code 0.
> **Depends on**: none
> **Parallelisable**: Yes (independent of WP12/WP13)
> **Prompt**: `plans/WP11-config-and-cli-runner.md`

## Objective

This work package delivers two foundational changes: (1) the `max_research_rounds` config field required by multi-round deep research (WP12), and (2) the autonomous CLI runner that enables scheduled, non-interactive pipeline execution. The config field is P0 foundation; the CLI runner is a P1 user story (US-01) that can be independently demonstrated.

## Spec References

- FR-CLI-001 through FR-CLI-006 (Section 4.1)
- FR-CFG-001 through FR-CFG-004 (Section 4.2)
- US-01 (Section 5)
- Section 8.1 (CLI Entry Point)
- Section 8.2 (Config Schema Extension)
- Section 9.3 (Directory & Module Structure)
- Section 10.5 (Observability - CLI logging)
- Section 11.1 (Unit Tests - CLI runner, Config field)
- Section 11.2 (BDD - Autonomous CLI Execution scenarios)

## Tasks

### T11-01 - Add max_research_rounds config field
- **Description**: Add `max_research_rounds: int` field to `AppSettings` in `newsletter_agent/config/schema.py` with default 3, range 1-5.
- **Spec refs**: FR-CFG-001, FR-CFG-002, FR-CFG-003, FR-CFG-004, Section 7.1, Section 8.2
- **Parallel**: Yes (independent of T11-03 through T11-07)
- **Acceptance criteria**:
  - [ ] `AppSettings` has a `max_research_rounds` field of type `int` with default value 3 (FR-CFG-002)
  - [ ] Values 1 through 5 are accepted without error (FR-CFG-001)
  - [ ] Value 0 raises `ValidationError` with message containing "greater than or equal to 1" (FR-CFG-003)
  - [ ] Value 6 raises `ValidationError` with message containing "less than or equal to 5" (FR-CFG-003)
  - [ ] Non-integer values raise `ValidationError` (FR-CFG-003)
  - [ ] Omitting `max_research_rounds` from YAML uses default 3 (FR-CFG-002)
- **Test requirements**: unit (extend `tests/unit/test_config.py`)
- **Depends on**: none
- **Implementation Guidance**:
  - Official docs: Pydantic Field validators https://docs.pydantic.dev/latest/concepts/fields/
  - Recommended pattern: Follow existing `AppSettings` field pattern in `config/schema.py`. Use `Field(default=3, ge=1, le=5)`.
  - File to modify: `newsletter_agent/config/schema.py` -- add field to `AppSettings` class (around line 60-80 where other settings fields are defined)
  - Known pitfalls: The spec says `SettingsConfig` but the actual class is `AppSettings`. Use `AppSettings`.
  - Spec validation rules: `max_research_rounds: int, default=3, ge=1, le=5`
  - Error handling: Pydantic handles validation automatically; no custom validator needed

### T11-02 - Unit tests for max_research_rounds config
- **Description**: Add unit tests for the new config field covering valid values, boundary conditions, and default behavior.
- **Spec refs**: FR-CFG-001, FR-CFG-002, FR-CFG-003, Section 11.1
- **Parallel**: No (depends on T11-01)
- **Acceptance criteria**:
  - [ ] Test `max_research_rounds` default is 3 when omitted
  - [ ] Test accepts values 1, 2, 3, 4, 5
  - [ ] Test rejects value 0 with appropriate ValidationError
  - [ ] Test rejects value 6 with appropriate ValidationError
  - [ ] Test rejects non-integer (e.g., "abc") with appropriate ValidationError
  - [ ] All new tests pass
- **Test requirements**: unit (in `tests/unit/test_config.py`)
- **Depends on**: T11-01
- **Implementation Guidance**:
  - Existing test patterns: See `tests/unit/test_config.py` for existing config validation tests. Follow the same parametrize patterns.
  - Add a new test class `TestMaxResearchRounds` or extend existing `TestAppSettings` class.
  - Use `pytest.raises(ValidationError)` for invalid values.
  - Test via `AppSettings(max_research_rounds=...)` direct construction.

### T11-03 - Create __main__.py CLI entry point module
- **Description**: Create `newsletter_agent/__main__.py` that enables `python -m newsletter_agent` execution. Import the `main()` function and call it.
- **Spec refs**: FR-CLI-001, Section 8.1, Section 9.3
- **Parallel**: Yes (independent of T11-01)
- **Acceptance criteria**:
  - [ ] `newsletter_agent/__main__.py` module exists and is importable (FR-CLI-001)
  - [ ] Running `python -m newsletter_agent` invokes the main function (FR-CLI-001)
  - [ ] Module follows Python `__main__.py` conventions: `if __name__ == "__main__": main()`
- **Test requirements**: unit (test module exists and is importable)
- **Depends on**: none
- **Implementation Guidance**:
  - Official docs: Python `__main__.py` convention https://docs.python.org/3/library/__main__.html
  - Pattern: Thin entry point that imports and calls `main()` from a runner module. The actual logic goes in a separate function for testability.
  - File to create: `newsletter_agent/__main__.py`
  - Structure: Import `main` from a runner function (defined in T11-04), call `asyncio.run()` around it.

### T11-04 - Implement CLI runner main() function
- **Description**: Implement the `main()` async function that creates an ADK `Runner` with `InMemorySessionService`, sends `"Generate newsletter"` trigger message, consumes all events, and handles exit codes.
- **Spec refs**: FR-CLI-002, FR-CLI-003, FR-CLI-004, FR-CLI-005, Section 4.1 Implementation Contract, Section 8.1
- **Parallel**: No (depends on T11-03)
- **Acceptance criteria**:
  - [ ] Uses ADK `Runner` with `InMemorySessionService` for programmatic execution (FR-CLI-002)
  - [ ] Sends `"Generate newsletter"` as the trigger message without requiring interactive input (FR-CLI-002)
  - [ ] Logs pipeline progress events to stdout using existing logging configuration (FR-CLI-003)
  - [ ] Returns exit code 0 on successful completion (FR-CLI-004)
  - [ ] Returns exit code 1 on any unhandled exception or pipeline abort (FR-CLI-004)
  - [ ] Prints JSON summary to stdout with: `status`, `newsletter_date`, `topics_processed`, `email_sent`, `output_file` (FR-CLI-005)
  - [ ] On failure, prints JSON summary with `status: "error"` and `message` field (FR-CLI-005)
- **Test requirements**: unit (mock Runner and pipeline)
- **Depends on**: T11-03
- **Implementation Guidance**:
  - Official docs: ADK Runner API https://google.github.io/adk-docs/runtime/runner/
  - Existing pattern: Copy from `newsletter_agent/http_handler.py` lines 25-65 which already implement programmatic execution via Runner. The CLI version is nearly identical but adds exit codes and summary output.
  - Key imports: `from google.adk.runners import Runner`, `from google.adk.sessions import InMemorySessionService`, `from google.genai import types`
  - Runner invocation pattern:
    ```python
    runner = Runner(agent=root_agent, app_name="newsletter_agent", session_service=session_service)
    session = await session_service.create_session(app_name="newsletter_agent", user_id="cli")
    content = types.Content(role="user", parts=[types.Part(text="Generate newsletter")])
    async for event in runner.run_async(session_id=session.id, user_id="cli", new_message=content):
        # Log events
    ```
  - Exit code handling: Wrap in try/except, catch all exceptions, return 1 on failure
  - JSON summary: Read `newsletter_date`, `topics_processed` from session state after pipeline completes. Use `json.dumps()` to print.
  - Known pitfalls: `root_agent` is created at module import time in `agent.py`. Import it directly: `from newsletter_agent.agent import root_agent`. This triggers config loading -- ensure env vars are set.
  - Logging: Use `logging.getLogger(__name__)` and the existing `logging_config.setup_logging()` if available. Log `"[CLI] Pipeline starting..."` and `"[CLI] Pipeline completed in {seconds}s"` per Section 10.5.

### T11-05 - Preserve existing entry points
- **Description**: Verify that `http_handler.py` and `adk run`/`adk web` entry points remain functional after adding `__main__.py`.
- **Spec refs**: FR-CLI-006, FR-BC-003
- **Parallel**: No (depends on T11-04)
- **Acceptance criteria**:
  - [ ] `http_handler.py` still works (import succeeds, endpoint callable) (FR-CLI-006)
  - [ ] `adk run` / `adk web` still discover `root_agent` from `newsletter_agent/__init__.py` (FR-CLI-006)
  - [ ] No changes to `newsletter_agent/__init__.py` that break ADK discovery (FR-BC-003)
- **Test requirements**: unit (import tests), integration (extend existing `tests/unit/test_http_handler.py`)
- **Depends on**: T11-04
- **Implementation Guidance**:
  - The key risk is that adding `__main__.py` might cause import side effects. Verify that `import newsletter_agent` still works (triggers ADK discovery via `__init__.py` which imports `agent`).
  - Check `newsletter_agent/__init__.py` -- it currently does `from newsletter_agent import agent`. The `__main__.py` should NOT be auto-imported.
  - Add a simple test: `import newsletter_agent; assert hasattr(newsletter_agent.agent, 'root_agent')`.

### T11-06 - Unit tests for CLI runner
- **Description**: Write unit tests for the CLI runner's `main()` function covering success, failure, and output format.
- **Spec refs**: FR-CLI-002, FR-CLI-004, FR-CLI-005, Section 11.1
- **Parallel**: No (depends on T11-04)
- **Acceptance criteria**:
  - [ ] Test `main()` creates Runner and sends trigger message (mock Runner)
  - [ ] Test exit code 0 on successful pipeline completion
  - [ ] Test exit code 1 on pipeline exception
  - [ ] Test JSON summary output format on success (contains `status`, `newsletter_date`, `topics_processed`, `email_sent`, `output_file`)
  - [ ] Test JSON summary output format on failure (contains `status: "error"`, `message`)
  - [ ] Test that `__main__.py` module is importable
  - [ ] All tests pass with >= 80% code coverage for `__main__.py`
- **Test requirements**: unit (new file `tests/unit/test_cli_runner.py`)
- **Depends on**: T11-04
- **Implementation Guidance**:
  - Mock `Runner` and `InMemorySessionService` using `unittest.mock.patch` or `pytest-mock`.
  - Mock `runner.run_async()` to yield a sequence of mock events, then verify `main()` returns 0.
  - Mock `runner.run_async()` to raise `RuntimeError`, then verify `main()` returns 1.
  - Capture stdout using `capsys` fixture to verify JSON summary output.
  - Test file: `tests/unit/test_cli_runner.py`

### T11-07 - BDD tests for CLI execution
- **Description**: Write BDD-style acceptance tests for the three CLI scenarios from the spec.
- **Spec refs**: US-01, Section 11.2 (Feature: Autonomous CLI Execution)
- **Parallel**: No (depends on T11-06)
- **Acceptance criteria**:
  - [ ] BDD scenario: Successful pipeline run via CLI -- pipeline runs to completion, HTML saved, JSON summary printed, exit code 0
  - [ ] BDD scenario: CLI handles config error -- config error logged, exit code 1
  - [ ] BDD scenario: CLI handles pipeline failure -- pipeline error logged, exit code 1
  - [ ] Tests follow existing BDD pattern in `tests/bdd/`
- **Test requirements**: BDD (new file `tests/bdd/test_cli_execution.py`)
- **Depends on**: T11-06
- **Implementation Guidance**:
  - Follow existing BDD pattern in `tests/bdd/test_research_pipeline.py` -- Given/When/Then comments with pytest functions.
  - For the "successful run" scenario: use mocked search tools, `dry_run: true` config, verify HTML file is created in output dir.
  - For "config error": create config with missing required field, verify exit code 1.
  - For "pipeline failure": mock all search tools to fail, verify exit code 1.
  - Use `subprocess.run(["python", "-m", "newsletter_agent"], ...)` for true CLI testing, or test the `main()` function directly with mocked dependencies.

### T11-08 - Configure coverage thresholds for new modules
- **Description**: Ensure pytest-cov is configured to enforce 80% code / 90% branch coverage for the new `__main__.py` and updated `config/schema.py`.
- **Spec refs**: Section 11.1 (minimum coverage: 80% code, 90% branch)
- **Parallel**: No (depends on T11-06)
- **Acceptance criteria**:
  - [ ] `pytest --cov=newsletter_agent --cov-branch` reports >= 80% code coverage for `__main__.py`
  - [ ] `pytest --cov=newsletter_agent --cov-branch` reports >= 90% branch coverage for `__main__.py`
  - [ ] Coverage configuration in `pyproject.toml` includes the new module paths
- **Test requirements**: none (coverage verification)
- **Depends on**: T11-06
- **Implementation Guidance**:
  - Check existing `pyproject.toml` for `[tool.pytest.ini_options]` and `[tool.coverage]` sections.
  - Existing pattern: `pytest-cov>=5.0` is already in requirements. The project likely has coverage configured.
  - If needed, add `--cov-fail-under=80` to pytest config for enforcement.

## Implementation Notes

- The CLI runner closely follows `http_handler.py` (lines 25-65). The main difference: no Flask, no HTTP response -- instead, exit codes and JSON summary to stdout.
- The `root_agent` is created at import time in `agent.py`. The CLI runner imports it, creates a Runner, and runs it. This means config loading happens at import time -- ensure environment variables (API keys) are set before running.
- The `main()` function should be `async` and called via `asyncio.run(main())` in `__main__.py`.
- JSON summary should be a single line printed with `print(json.dumps(summary))` for easy machine parsing.

## Parallel Opportunities

- T11-01 (config field) and T11-03 (create __main__.py) can be worked concurrently [P].
- T11-02 (config tests) depends on T11-01 only.
- T11-04 through T11-08 are sequential (each builds on the previous).

## Risks & Mitigations

- **Risk**: `root_agent` import triggers config loading, which may fail if `topics.yaml` is missing. **Mitigation**: CLI runner should catch `ConfigValidationError` at import time and exit with code 1 and appropriate error message.
- **Risk**: `asyncio.run()` may conflict with existing event loop in some environments. **Mitigation**: This is standard Python 3.11+ usage; no known issues. Test in CI.

## Activity Log
- 2026-03-15T00:00:00Z - planner - lane=planned - Work package created
- 2026-03-15T10:30:00Z - coder - lane=doing - Started implementation of WP11
- 2026-03-15T10:55:00Z - coder - lane=for_review - All tasks complete, submitted for review

## Self-Review

### Spec Compliance
- [x] FR-CFG-001: max_research_rounds field accepts values 1-5
- [x] FR-CFG-002: default value is 3
- [x] FR-CFG-003: values outside 1-5 raise ValidationError
- [x] FR-CFG-004: field present in AppSettings, available via config loader
- [x] FR-CLI-001: __main__.py module exists, python -m newsletter_agent works
- [x] FR-CLI-002: Uses ADK Runner with InMemorySessionService, sends "Generate newsletter"
- [x] FR-CLI-003: Logs pipeline progress using setup_logging()
- [x] FR-CLI-004: Exit code 0 on success, 1 on failure
- [x] FR-CLI-005: Prints JSON summary with status, newsletter_date, topics_processed, email_sent, output_file
- [x] FR-CLI-006: Existing http_handler.py and adk entry points unchanged

### Correctness
- [x] All 464 tests pass (excluding pre-existing Flask import failure)
- [x] 12 new config tests cover default, valid range (1-5), rejections (0, 6, -1, "abc"), YAML loading
- [x] 14 CLI runner unit tests cover success/failure paths, JSON output, exit codes, run_pipeline
- [x] 7 BDD tests cover all 3 spec scenarios (success, config error, pipeline failure)

### Code Quality
- [x] No unused code or debug artifacts
- [x] No hardcoded values - config-driven
- [x] No security issues - no secrets, no injection vectors
- [x] Clean, well-documented code following existing patterns

### Scope Discipline
- [x] Only config/schema.py modified, __main__.py created, tests created, docs updated
- [x] No unasked-for abstractions

### Coverage
- [x] __main__.py: 90% code coverage (lines 50-51 event logging branch are the only miss)
- [x] config/schema.py: 89% (misses are in pre-existing email validation code)
- [x] Total: 89.36% - exceeds 80% threshold

### Documentation
- [x] api-reference.md: Added CLI entry point section, updated AppSettings table
- [x] architecture.md: No changes needed (pipeline structure unchanged)
- [x] configuration-guide.md: Added max_research_rounds to settings table
- [x] deployment-guide.md: Added Autonomous CLI Runner section
- [x] developer-guide.md: Added __main__.py to project structure
- [x] user-guide.md: Added CLI runner instructions
