---
lane: planned
---

# WP15 - Config Fields & Prompt Templates

> **Spec**: `specs/002-adaptive-deep-research.spec.md`
> **Status**: Not Started
> **Priority**: P0
> **Goal**: Add the new config fields and prompt templates that the adaptive orchestrator depends on
> **Independent Test**: Run `pytest tests/unit/test_config.py tests/unit/test_reasoning_prompts.py -v` and verify all new config field and prompt template tests pass
> **Depends on**: none
> **Parallelisable**: No (foundation WP)
> **Prompt**: `plans/WP15-config-and-prompts.md`

## Objective

This work package adds the foundational building blocks that WP16 (the orchestrator rewrite) depends on: two new config fields (`max_searches_per_topic`, `min_research_rounds`) with cross-field validation, the new `reasoning.py` prompt module with planning and analysis instruction functions, and deprecation of the old `query_expansion.py` module. All changes are independently testable without modifying the orchestrator.

## Spec References

- FR-ADR-060 through FR-ADR-065 (Configuration Changes, Section 4.7)
- FR-ADR-070 through FR-ADR-072 (Prompt Templates, Section 4.8)
- Section 7.1 (Config Schema Changes)
- Section 8.2 (Config Schema Extension)
- Section 11.1 (Unit Test requirements for config and prompt templates)

## Tasks

### T15-01 - Add `max_searches_per_topic` and `min_research_rounds` to AppSettings

- **Description**: Add two new optional fields to the `AppSettings` Pydantic model in `newsletter_agent/config/schema.py`. Add a `model_validator` that resolves the dynamic default for `max_searches_per_topic` and validates the cross-field constraint `min_research_rounds <= max_research_rounds`.
- **Spec refs**: FR-ADR-060, FR-ADR-061, FR-ADR-064, FR-ADR-065, Section 7.1, Section 8.2
- **Parallel**: No
- **Acceptance criteria**:
  - [ ] `AppSettings` has field `max_searches_per_topic: int | None = Field(default=None, ge=1, le=15)` that accepts `None` and integers 1-15
  - [ ] `AppSettings` has field `min_research_rounds: int = Field(default=2, ge=1, le=3)` that accepts integers 1-3
  - [ ] A `model_validator(mode="after")` named `resolve_adaptive_defaults` replaces the unset `max_searches_per_topic` with the value of `max_research_rounds`
  - [ ] The same validator raises `ValueError` when `min_research_rounds > max_research_rounds` with the message: `"min_research_rounds ({val}) must be <= max_research_rounds ({val})"`
  - [ ] Existing `AppSettings` instantiation without new fields continues to work (backward compat): `AppSettings()` yields `max_research_rounds=3`, `max_searches_per_topic=3`, `min_research_rounds=2`
  - [ ] `ConfigDict(extra="forbid")` still rejects unknown fields
- **Test requirements**: unit
- **Depends on**: none
- **Implementation Guidance**:
  - Official docs: Pydantic v2 model_validator - https://docs.pydantic.dev/latest/concepts/validators/#model-validators
  - File to modify: `newsletter_agent/config/schema.py`
  - The existing `AppSettings` class at line ~151 has `model_config = ConfigDict(extra="forbid")` and a single field `max_research_rounds`. Add the two new fields after it.
  - The validator function name in the spec is `resolve_adaptive_defaults`. Use `@model_validator(mode="after")` decorator.
  - The `max_searches_per_topic` field uses `None` as the sentinel for "not set" so the validator can distinguish between "user explicitly set 3" and "user didn't set, default to max_research_rounds".
  - Implementation contract from spec:
    ```python
    max_searches_per_topic: int | None = Field(default=None, ge=1, le=15)
    min_research_rounds: int = Field(default=2, ge=1, le=3)

    @model_validator(mode="after")
    def resolve_adaptive_defaults(self) -> AppSettings:
        if self.max_searches_per_topic is None:
            self.max_searches_per_topic = self.max_research_rounds
        if self.min_research_rounds > self.max_research_rounds:
            raise ValueError(
                f"min_research_rounds ({self.min_research_rounds}) must be "
                f"<= max_research_rounds ({self.max_research_rounds})"
            )
        return self
    ```
  - Known pitfall: Pydantic v2 `Field(ge=1, le=15)` with `default=None` requires the type hint to be `int | None` (or `Optional[int]`), not just `int`. Otherwise Pydantic will reject `None` at validation time before the model_validator runs.

### T15-02 - Unit tests for new config fields

- **Description**: Extend the existing `tests/unit/test_config.py` with test cases covering the new `max_searches_per_topic` and `min_research_rounds` fields, including valid values, defaults, boundary values, and error cases.
- **Spec refs**: FR-ADR-061, FR-ADR-064, FR-ADR-065, Section 11.1 (Config field tests)
- **Parallel**: No (depends on T15-01)
- **Acceptance criteria**:
  - [ ] Test `max_searches_per_topic` defaults to `max_research_rounds` value when omitted from config
  - [ ] Test `max_searches_per_topic` accepts boundary values: 1, 5, 10, 15
  - [ ] Test `max_searches_per_topic` rejects 0 (below minimum) with Pydantic validation error
  - [ ] Test `max_searches_per_topic` rejects 16 (above maximum) with Pydantic validation error
  - [ ] Test `max_searches_per_topic` rejects non-integer values (e.g., "abc")
  - [ ] Test `min_research_rounds` defaults to 2 when omitted
  - [ ] Test `min_research_rounds` accepts boundary values: 1, 2, 3
  - [ ] Test `min_research_rounds` rejects 0 and 4 (out of range)
  - [ ] Test cross-field: `min_research_rounds=3, max_research_rounds=2` raises `ValueError` with descriptive message
  - [ ] Test cross-field: `min_research_rounds=1, max_research_rounds=1` succeeds (edge case)
  - [ ] Test backward compat: existing config YAML without new fields loads successfully
  - [ ] All existing config tests continue to pass unchanged
- **Test requirements**: unit
- **Depends on**: T15-01
- **Implementation Guidance**:
  - File to modify: `tests/unit/test_config.py`
  - Follow the existing test patterns in the file (they use `AppSettings(**kwargs)` directly and `load_config()` with fixture YAML)
  - For validation error tests, use `pytest.raises(ValidationError)` (from Pydantic) or `pytest.raises(ValueError)` depending on how the validator raises
  - The model_validator raises `ValueError` which Pydantic wraps into `ValidationError` -- test for `ValidationError` at the outer layer when constructing via Pydantic, or `ValueError` if testing the validator method directly
  - Group new tests in a dedicated class: `TestAdaptiveConfigFields`

### T15-03 - Create `reasoning.py` with `get_planning_instruction`

- **Description**: Create the new prompt module `newsletter_agent/prompts/reasoning.py` with the `get_planning_instruction` function that generates the PlanningAgent's instruction prompt.
- **Spec refs**: FR-ADR-070, Section 4.2 (PlanningAgent instruction contract)
- **Parallel**: Yes (independent of T15-01/T15-02)
- **Acceptance criteria**:
  - [ ] File `newsletter_agent/prompts/reasoning.py` exists with function `get_planning_instruction(query: str, topic_name: str) -> str`
  - [ ] Returned string contains the exact prompt structure from the spec: topic name, query, JSON output instructions with the 4 required fields (`query_intent`, `key_aspects`, `initial_search_query`, `search_rationale`)
  - [ ] Returned string contains `{topic_name}` and `{query}` parameter values interpolated (not as template placeholders)
  - [ ] Function is importable: `from newsletter_agent.prompts.reasoning import get_planning_instruction`
- **Test requirements**: unit
- **Depends on**: none
- **Implementation Guidance**:
  - Create new file: `newsletter_agent/prompts/reasoning.py`
  - The exact prompt template is in spec Section 4.2 "PlanningAgent instruction contract"
  - Use Python f-string or `.format()` for parameter interpolation
  - The prompt asks the LLM to output ONLY a JSON object with exactly 4 fields
  - Pattern: follow the same style as `newsletter_agent/prompts/query_expansion.py` (a single function returning a formatted instruction string)
  - Ensure the prompt includes: (1) role definition, (2) topic/query context, (3) numbered task steps, (4) JSON schema description, (5) "Output ONLY the JSON object" constraint

### T15-04 - Add `get_analysis_instruction` to `reasoning.py`

- **Description**: Add the `get_analysis_instruction` function to `newsletter_agent/prompts/reasoning.py`. This function generates the AnalysisAgent's instruction prompt with 8 parameters for full research context.
- **Spec refs**: FR-ADR-070, Section 4.4 (AnalysisAgent instruction contract)
- **Parallel**: No (depends on T15-03 for file existence)
- **Acceptance criteria**:
  - [ ] Function signature: `get_analysis_instruction(topic_name: str, query: str, key_aspects: list[str], prior_rounds_summary: str, latest_results: str, round_idx: int, current_query: str, remaining_searches: int) -> str`
  - [ ] Returned string contains all 8 parameter values interpolated into the prompt
  - [ ] `key_aspects` list is formatted as a bulleted list (one aspect per line with "- " prefix)
  - [ ] Returned string contains the exact JSON output schema: `findings_summary`, `knowledge_gaps`, `coverage_assessment`, `saturated`, `next_query`, `next_query_rationale`
  - [ ] Returned string contains the saturation guidelines section from the spec
  - [ ] Returned string ends with "Output ONLY the JSON object. No other text."
  - [ ] Function is importable: `from newsletter_agent.prompts.reasoning import get_analysis_instruction`
- **Test requirements**: unit
- **Depends on**: T15-03
- **Implementation Guidance**:
  - File to modify: `newsletter_agent/prompts/reasoning.py`
  - The exact prompt template is in spec Section 4.4 "AnalysisAgent instruction contract"
  - `key_aspects` formatting: join the list with newline-prefixed bullets: `"\n".join(f"- {a}" for a in key_aspects)`
  - `prior_rounds_summary` is a pre-formatted string (the orchestrator in WP16 will format it before calling this function)
  - Include the saturation guidelines verbatim from the spec (3 bullet points for true, 3 for false)
  - The `remaining_searches` parameter gives the LLM awareness of budget constraints to inform its saturation decision

### T15-05 - Deprecate `query_expansion.py`

- **Description**: Add a module-level deprecation comment to `newsletter_agent/prompts/query_expansion.py`. The function remains importable but is no longer called by the orchestrator.
- **Spec refs**: FR-ADR-071
- **Parallel**: Yes (independent of other tasks)
- **Acceptance criteria**:
  - [ ] `newsletter_agent/prompts/query_expansion.py` has a module-level docstring or comment clearly stating it is deprecated and superseded by `reasoning.py`
  - [ ] `get_query_expansion_instruction` function remains importable and functional (no code changes to the function body)
  - [ ] No other files are modified in this task
- **Test requirements**: none (existing tests validate the function still works)
- **Depends on**: none
- **Implementation Guidance**:
  - File to modify: `newsletter_agent/prompts/query_expansion.py`
  - Add a deprecation notice at the top of the module docstring, e.g.: `"DEPRECATED: This module is superseded by newsletter_agent.prompts.reasoning. The adaptive research loop (spec 002) generates queries per-round via the AnalysisAgent instead of upfront expansion. This module is retained for backward compatibility."`
  - Do NOT delete the file or the function -- it must remain importable per FR-ADR-071
  - Do NOT add Python `warnings.warn()` calls -- a comment/docstring is sufficient per spec

### T15-06 - Unit tests for prompt template functions

- **Description**: Create `tests/unit/test_reasoning_prompts.py` with unit tests for both `get_planning_instruction` and `get_analysis_instruction`.
- **Spec refs**: Section 11.1 (Prompt templates tests)
- **Parallel**: No (depends on T15-03, T15-04)
- **Acceptance criteria**:
  - [ ] Test `get_planning_instruction` returns a string containing the provided `query` and `topic_name` values
  - [ ] Test `get_planning_instruction` returns a string containing all 4 required JSON field names: `query_intent`, `key_aspects`, `initial_search_query`, `search_rationale`
  - [ ] Test `get_analysis_instruction` returns a string containing all 8 parameter values
  - [ ] Test `get_analysis_instruction` formats `key_aspects` as a bulleted list (each aspect on its own line prefixed with "- ")
  - [ ] Test `get_analysis_instruction` formats `prior_rounds_summary` correctly for 0 prior rounds (empty or "No prior rounds" text)
  - [ ] Test `get_analysis_instruction` formats `prior_rounds_summary` correctly for 1 prior round (contains round data)
  - [ ] Test `get_analysis_instruction` formats `prior_rounds_summary` correctly for 3 prior rounds (multi-round context)
  - [ ] Test `get_analysis_instruction` returns a string containing all 6 required JSON field names: `findings_summary`, `knowledge_gaps`, `coverage_assessment`, `saturated`, `next_query`, `next_query_rationale`
- **Test requirements**: unit
- **Depends on**: T15-03, T15-04
- **Implementation Guidance**:
  - Create new file: `tests/unit/test_reasoning_prompts.py`
  - Follow existing test patterns in `tests/unit/` (pytest style, no class needed unless grouping helps)
  - Test that interpolated values appear in the returned string using `assert "expected_value" in result`
  - For the bullet list test: pass `["aspect1", "aspect2", "aspect3"]` and verify `"- aspect1\n- aspect2\n- aspect3"` appears in the output
  - For the prior_rounds_summary tests: pass pre-formatted strings (the orchestrator formats these, not the prompt function) and verify they appear in the output

### T15-07 - Coverage verification for WP15

- **Description**: Run the full test suite and verify that the new config and prompt code meets coverage thresholds.
- **Spec refs**: Section 11.1 (minimum coverage: 80% code, 90% branch)
- **Parallel**: No (depends on all prior tasks)
- **Acceptance criteria**:
  - [ ] `pytest tests/unit/test_config.py tests/unit/test_reasoning_prompts.py --cov=newsletter_agent/config/schema --cov=newsletter_agent/prompts/reasoning --cov-report=term-missing` shows >= 80% line coverage and >= 90% branch coverage for both modules
  - [ ] All existing tests continue to pass: `pytest tests/ -v` exits with code 0
  - [ ] No regressions in any test file
- **Test requirements**: coverage check
- **Depends on**: T15-01 through T15-06
- **Implementation Guidance**:
  - Run: `pytest tests/unit/test_config.py tests/unit/test_reasoning_prompts.py --cov=newsletter_agent/config --cov=newsletter_agent/prompts/reasoning --cov-branch --cov-report=term-missing -v`
  - If coverage is below threshold, add targeted tests for uncovered branches
  - Then run full suite: `pytest tests/ -v` to confirm no regressions
  - The project's pytest config in `pyproject.toml` already sets `fail_under = 80` for overall coverage

## Implementation Notes

- **File changes**: 2 modified (`schema.py`, `query_expansion.py`), 2 new (`reasoning.py`, `test_reasoning_prompts.py`), 1 extended (`test_config.py`)
- **No orchestrator changes**: This WP only creates the pieces that WP16 will consume. The orchestrator is NOT modified here.
- **Backward compatibility**: All existing config YAML files work unchanged. The new fields have sensible defaults.
- **Test commands**:
  - Unit tests only: `pytest tests/unit/test_config.py tests/unit/test_reasoning_prompts.py -v`
  - Full suite: `pytest tests/ -v`

## Parallel Opportunities

- T15-03 (planning prompt) and T15-05 (deprecation) can run in parallel with T15-01/T15-02 (config)
- T15-04 depends on T15-03 (same file)
- T15-06 depends on T15-03 and T15-04

## Risks & Mitigations

- **Risk**: Pydantic v2 `Field(default=None)` with `int | None` type might cause issues with `ge`/`le` constraints when value is None. **Mitigation**: The `ge=1, le=15` constraints only apply when the value is not None. Pydantic v2 handles `Optional[int]` with `Field(ge=...)` correctly -- the constraint is skipped for None values.
- **Risk**: Existing tests that construct `AppSettings` without the new fields might break if the validator runs before defaults resolve. **Mitigation**: The validator runs `mode="after"` so all defaults are populated first. `max_searches_per_topic=None` is the default and the validator resolves it.

## Activity Log

- 2026-03-15T00:00:00Z - planner - lane=planned - Work package created
