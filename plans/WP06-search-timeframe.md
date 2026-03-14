---
lane: for_review
---

# WP06 - Search Timeframe Configuration & Research Integration

> **Spec**: `specs/link-verification-timeframe.spec.md`
> **Status**: Complete
> **Priority**: P1
> **Goal**: Operators can set a timeframe in topics.yaml (global or per-topic) to constrain research results to a specific date range, with Perplexity receiving search_recency_filter and Google Search receiving prompt-based date instructions.
> **Independent Test**: Set `settings.timeframe: "last_week"` in topics.yaml, run the pipeline in dry-run mode, and verify (via logs and mocked Perplexity client) that Perplexity receives `search_recency_filter: "week"` and Google Search agent instructions contain "last week".
> **Depends on**: WP01-WP05 (existing completed work packages)
> **Parallelisable**: Yes (independent of WP07)
> **Prompt**: `plans/WP06-search-timeframe.md`

## Objective

This work package adds temporal filtering to the research pipeline. Operators can declare a `timeframe` field in the `settings` section (global default) or on individual topics (override). The system resolves the timeframe into provider-specific parameters: a `search_recency_filter` value for the Perplexity Sonar API and a natural-language date clause injected into Google Search and Perplexity agent prompts. When no timeframe is configured, existing behavior is preserved (no date filtering). All timeframe values are validated at config load time via Pydantic, and invalid values produce descriptive error messages.

## Spec References

- FR-001 through FR-012 (Sections 4.1, 4.2)
- FR-027, FR-028 (Section 4.4 - Pipeline Integration, config loading)
- US-01 (Global timeframe), US-02 (Per-topic override), US-03 (Absolute date range), US-06 (Validation)
- Section 7.1 Data Model: TimeframeValue, AppSettings (modified), TopicConfig (modified), ResolvedTimeframe
- Section 7.2 Session State: config_timeframes
- Section 8.1 (search_perplexity modified), 8.2 (Google instruction modified), 8.3 (Perplexity instruction modified), 8.4 (resolve_timeframe)
- Section 9.4 Decision 1: Prompt-based timeframe for Google Search
- Section 10.2 Security: Input validation for timeframe dates
- Section 11.1 Unit Tests: Timeframe parsing and resolution, Schema validation, Perplexity search additions
- Section 11.2 BDD: Search Timeframe Configuration scenarios

## Tasks

### T06-01 - Implement TimeframeValue Pydantic Validator

- **Description**: Create a custom Pydantic `BeforeValidator` or `Annotated` type for the `timeframe` field that validates all accepted formats: named presets (`last_week`, `last_2_weeks`, `last_month`, `last_year`), custom days (`last_X_days` where X is 1-365), and absolute ranges (`between YYYY-MM-DD and YYYY-MM-DD` where start < end, dates not in future). Invalid values must produce descriptive error messages listing the valid formats. This is implemented directly in `newsletter_agent/config/schema.py`.
- **Spec refs**: FR-003, FR-005, Section 7.1 (TimeframeValue)
- **Parallel**: Yes (can run concurrently with T06-02)
- **Acceptance criteria**:
  - [ ] `"last_week"`, `"last_2_weeks"`, `"last_month"`, `"last_year"` are accepted as valid preset values
  - [ ] `"last_7_days"`, `"last_30_days"`, `"last_365_days"` are accepted as valid custom-days values
  - [ ] `"last_0_days"` is rejected with error message indicating X must be 1-365
  - [ ] `"last_500_days"` is rejected with error message indicating X must be 1-365
  - [ ] `"last_forever"`, `"yesterday"`, `""` are rejected with error listing valid formats
  - [ ] `"between 2025-01-01 and 2025-06-30"` is accepted as a valid absolute range
  - [ ] `"between 2025-06-30 and 2025-01-01"` is rejected because start date >= end date
  - [ ] `"between 2030-01-01 and 2030-06-30"` is rejected because end date is in the future
  - [ ] `"between 2025-13-01 and 2025-06-30"` is rejected because month 13 is invalid
  - [ ] `None` (field omitted) is accepted, meaning no timeframe filtering
- **Test requirements**: unit (test_config.py additions + new test_timeframe.py)
- **Depends on**: none
- **Implementation Guidance**:
  - Official docs: Pydantic v2 custom types - use `Annotated[str | None, BeforeValidator(validate_timeframe)]` pattern
  - Recommended pattern: Define `_PRESET_VALUES`, `_CUSTOM_DAYS_RE = re.compile(r'^last_(\d+)_days$')`, `_ABSOLUTE_RE = re.compile(r'^between (\d{4}-\d{2}-\d{2}) and (\d{4}-\d{2}-\d{2})$')` as module-level constants
  - Known pitfalls: `datetime.date.fromisoformat()` accepts some non-ISO formats in older Python; use strict regex pre-check before parsing. On Python 3.11+, `fromisoformat` handles most ISO 8601 strings correctly
  - Error handling: validator must raise `ValueError` with a message like `"Invalid timeframe '{value}'. Valid formats: 'last_week', 'last_2_weeks', 'last_month', 'last_year', 'last_X_days' (X=1-365), 'between YYYY-MM-DD and YYYY-MM-DD'"`
  - Spec validation rules: Named presets are exact string match; custom days X in [1, 365]; absolute range requires `start < end` and `end <= date.today()`

### T06-02 - Create ResolvedTimeframe Dataclass and resolve_timeframe() Function

- **Description**: Create a new module `newsletter_agent/config/timeframe.py` containing the `ResolvedTimeframe` dataclass and the `resolve_timeframe()` function. The function converts a validated timeframe string into provider-specific parameters: `perplexity_recency_filter` (one of `"day"`, `"week"`, `"month"`, or `None`), `prompt_date_instruction` (natural language clause for agent prompts), and `original_value` (raw string for logging). The mapping from timeframe values to Perplexity filter values must follow the exact rules in FR-007.
- **Spec refs**: FR-007, FR-008, FR-009, Section 7.1 (ResolvedTimeframe), Section 8.4 (resolve_timeframe)
- **Parallel**: Yes (can run concurrently with T06-01)
- **Acceptance criteria**:
  - [ ] `resolve_timeframe("last_week")` returns `ResolvedTimeframe(perplexity_recency_filter="week", prompt_date_instruction="Focus on results from the last week.", original_value="last_week")`
  - [ ] `resolve_timeframe("last_month")` returns filter `"month"` and instruction mentioning "the past month"
  - [ ] `resolve_timeframe("last_2_weeks")` returns filter `"month"` (closest supported) and instruction mentioning "the last 2 weeks"
  - [ ] `resolve_timeframe("last_year")` returns filter `None` (unsupported granularity) and instruction mentioning "the past year"
  - [ ] `resolve_timeframe("last_7_days")` returns filter `"week"` and instruction "Focus on results from the last 7 days."
  - [ ] `resolve_timeframe("last_1_days")` returns filter `"day"` (X <= 1)
  - [ ] `resolve_timeframe("last_30_days")` returns filter `"month"` (8 <= X <= 31)
  - [ ] `resolve_timeframe("last_90_days")` returns filter `None` (X > 31)
  - [ ] `resolve_timeframe("between 2025-01-01 and 2025-06-30")` returns filter `None` and instruction "Only include results published between 2025-01-01 and 2025-06-30."
  - [ ] `resolve_timeframe(None)` returns `ResolvedTimeframe(perplexity_recency_filter=None, prompt_date_instruction=None, original_value=None)`
- **Test requirements**: unit (new test_timeframe.py)
- **Depends on**: none
- **Implementation Guidance**:
  - Recommended pattern: Use `@dataclass(frozen=True)` for `ResolvedTimeframe` since it is immutable after creation
  - Use the same regex patterns from T06-01 to parse the timeframe string (can import or duplicate - keep it simple)
  - Known pitfalls: The Perplexity filter mapping has edge cases - `last_7_days` maps to `"week"` (same as `last_week`), but `last_8_days` maps to `"month"`. Test boundary values carefully
  - The function should never raise - input is pre-validated by Pydantic. If somehow an unexpected value arrives, return all-None fields and log a warning
  - For absolute ranges, the prompt instruction must include the exact dates from config, not computed values

### T06-03 - Add timeframe and verify_links Fields to Pydantic Config Models

- **Description**: Modify `AppSettings` in `newsletter_agent/config/schema.py` to add `timeframe: TimeframeValue | None = None` and `verify_links: bool = False`. Modify `TopicConfig` to add `timeframe: TimeframeValue | None = None`. The `extra="forbid"` config on both models ensures unknown fields are still rejected. This must be fully backward compatible - existing configs without these fields must continue to validate.
- **Spec refs**: FR-001, FR-002, FR-013, Section 7.1 (AppSettings modified, TopicConfig modified)
- **Parallel**: No (depends on T06-01 for TimeframeValue type)
- **Acceptance criteria**:
  - [ ] `AppSettings(dry_run=True, output_dir="output/")` validates without `timeframe` or `verify_links` (backward compatible)
  - [ ] `AppSettings(dry_run=True, output_dir="output/", timeframe="last_week", verify_links=True)` validates successfully
  - [ ] `AppSettings(timeframe="invalid_value")` raises `ValidationError`
  - [ ] `TopicConfig(name="AI", query="test query", timeframe="last_month")` validates successfully
  - [ ] `TopicConfig(name="AI", query="test query")` validates without `timeframe` (backward compatible)
  - [ ] Existing `conftest.py` fixtures `sample_config_data` and `make_config_yaml` still produce valid configs
  - [ ] Full config with `settings.timeframe` + topic-level `timeframe` validates end-to-end
- **Test requirements**: unit (test_config.py additions)
- **Depends on**: T06-01
- **Implementation Guidance**:
  - Official docs: Pydantic v2 `Field(default=None)` with optional types
  - Recommended pattern: Add fields with defaults so existing YAML files remain valid. `timeframe: TimeframeValue | None = None` and `verify_links: bool = False`
  - Known pitfalls: `extra="forbid"` is already set on all models - this is correct and should remain. Adding new optional fields with defaults does not break this setting
  - Spec validation rules: `verify_links` is a simple boolean, no custom validation needed. `timeframe` uses the `TimeframeValue` annotated type from T06-01

### T06-04 - Extend ConfigLoaderAgent to Resolve Timeframes

- **Description**: Modify `ConfigLoaderAgent._run_async_impl()` in `newsletter_agent/agent.py` to resolve timeframes during config loading. After loading the existing config values into session state, the agent must: (1) compute the effective timeframe for each topic (topic-level overrides global), (2) call `resolve_timeframe()` for each, (3) store the list of resolved timeframes in session state as `config_timeframes`, and (4) store `config_verify_links` boolean in session state. This ensures timeframe data is available when `build_research_phase()` constructs research agents.
- **Spec refs**: FR-004, FR-027, FR-028, Section 7.2 (Session State)
- **Parallel**: No (depends on T06-02 and T06-03)
- **Acceptance criteria**:
  - [ ] When `settings.timeframe: "last_week"` and no topic overrides, session state `config_timeframes` is a list of `ResolvedTimeframe` dicts all with `perplexity_recency_filter: "week"`
  - [ ] When topic 0 has `timeframe: "last_month"` and global is `"last_week"`, `config_timeframes[0]` has filter `"month"` while `config_timeframes[1]` has filter `"week"`
  - [ ] When no timeframe is configured anywhere, `config_timeframes` is `None`
  - [ ] `config_verify_links` is set to the value of `settings.verify_links` (default `false`)
  - [ ] Existing session state keys (`config_newsletter_title`, `config_recipient_email`, `config_dry_run`, `config_output_dir`) are still populated correctly
- **Test requirements**: unit (test_agent_factory.py additions)
- **Depends on**: T06-02, T06-03
- **Implementation Guidance**:
  - Recommended pattern: After existing state population, add a block that iterates topics and resolves timeframes. Use `topic.timeframe or config.settings.timeframe` for the merge logic
  - The resolved timeframes should be stored as a list of dicts (serializable to session state), not raw dataclass objects. Use `dataclasses.asdict()` or manual dict conversion
  - Known pitfalls: Session state values must be JSON-serializable (dicts, lists, strings, numbers, booleans, None). Do not store Python objects directly
  - Import `resolve_timeframe` from `newsletter_agent.config.timeframe`

### T06-05 - Extend Google Search Instruction Builder with Timeframe

- **Description**: Modify `get_google_search_instruction()` in `newsletter_agent/prompts/research_google.py` to accept an optional `timeframe_instruction: str | None = None` parameter. When provided, append the instruction as an additional numbered step in both the standard and deep instruction templates. The instruction should be positioned after the existing research steps but before the format instructions.
- **Spec refs**: FR-006, FR-009, FR-011, Section 8.2
- **Parallel**: Yes (can run concurrently with T06-06)
- **Acceptance criteria**:
  - [ ] `get_google_search_instruction("AI", "query", "standard")` returns the existing instruction unchanged (backward compatible)
  - [ ] `get_google_search_instruction("AI", "query", "standard", "Focus on results from the last week.")` returns instruction with an additional numbered step containing the timeframe text
  - [ ] `get_google_search_instruction("AI", "query", "deep", "Only include results published between 2025-01-01 and 2025-06-30.")` includes the date range in the deep instruction
  - [ ] The timeframe instruction is positioned as a numbered step (e.g., step 5 after existing steps 1-4) in the instruction body, not at the very end after the format block
- **Test requirements**: unit (test_research_prompts.py or additions to existing prompt tests)
- **Depends on**: none
- **Implementation Guidance**:
  - Recommended pattern: Add `timeframe_instruction` as the last parameter with `None` default. In the instruction template, conditionally include it: `if timeframe_instruction: steps.append(f"5. {timeframe_instruction}")` before the format block
  - The standard template currently has 4 numbered steps. Add the timeframe as step 5. The deep template has more steps - add it as the next sequential number
  - Known pitfalls: Ensure the numbering of existing steps is not disrupted. If the instruction uses f-string formatting, be careful with the curly braces in the timeframe instruction text

### T06-06 - Extend Perplexity Instruction Builder with Timeframe

- **Description**: Modify `get_perplexity_search_instruction()` in `newsletter_agent/prompts/research_perplexity.py` to accept an optional `timeframe_instruction: str | None = None` parameter. When provided, add the timeframe context to the agent instruction so the LLM is aware of the desired date range. This complements the Perplexity API `search_recency_filter` (which is set separately in T06-07).
- **Spec refs**: FR-009, FR-012, Section 8.3
- **Parallel**: Yes (can run concurrently with T06-05)
- **Acceptance criteria**:
  - [ ] `get_perplexity_search_instruction("AI", "query", "standard")` returns the existing instruction unchanged (backward compatible)
  - [ ] `get_perplexity_search_instruction("AI", "query", "standard", "Focus on results from the last week.")` includes the timeframe context in the instruction
  - [ ] The timeframe instruction does not interfere with the tool-call directive (the LLM must still call the search_perplexity tool)
- **Test requirements**: unit (additions to existing prompt tests or new test file)
- **Depends on**: none
- **Implementation Guidance**:
  - Recommended pattern: Add the timeframe as additional context before the tool-call directive. E.g., "Time constraint: {timeframe_instruction}\n\n" prepended to or inserted inside the existing instruction
  - Known pitfalls: The Perplexity agent instruction explicitly tells the LLM to pass through the tool response without modification. The timeframe instruction should not change this directive - it just adds context about the desired time period

### T06-07 - Extend search_perplexity() with search_recency_filter

- **Description**: Modify `search_perplexity()` in `newsletter_agent/tools/perplexity_search.py` to accept an optional `search_recency_filter: str | None = None` parameter. When not `None`, pass it to the OpenAI client `chat.completions.create()` call via the `extra_body` parameter. If the Perplexity API rejects the parameter (raises an exception), catch the error, log a warning, and retry the call without `search_recency_filter` (graceful degradation).
- **Spec refs**: FR-007, FR-010, Section 8.1, Section 9.5 (Perplexity API modified)
- **Parallel**: No (should be done after T06-05/T06-06 for logical sequencing, but technically independent)
- **Acceptance criteria**:
  - [ ] `search_perplexity("query", "standard")` works identically to current behavior (backward compatible)
  - [ ] `search_perplexity("query", "standard", search_recency_filter="week")` passes `extra_body={"search_recency_filter": "week"}` to `client.chat.completions.create()`
  - [ ] `search_perplexity("query", "standard", search_recency_filter=None)` does not include `extra_body` in the API call
  - [ ] If Perplexity API raises an exception when `search_recency_filter` is set, the function logs a warning and retries the call without `search_recency_filter`
  - [ ] The retry-without-filter path still returns a valid result dict (not an error) if the second call succeeds
  - [ ] The `FunctionTool` wrapper (`perplexity_search_tool`) continues to work - the ADK agent can call the tool with the new parameter
- **Test requirements**: unit (test_perplexity_search.py additions)
- **Depends on**: none
- **Implementation Guidance**:
  - Official docs: OpenAI Python client `extra_body` parameter - passes additional JSON fields in the request body that are not part of the standard schema
  - Recommended pattern: Build `kwargs = {"model": model, "messages": messages}`. If `search_recency_filter` is not None, add `kwargs["extra_body"] = {"search_recency_filter": search_recency_filter}`. Then `client.chat.completions.create(**kwargs)`
  - Known pitfalls: The `FunctionTool` in ADK inspects the function signature to determine what parameters the LLM can pass. Adding `search_recency_filter` to the function signature means the LLM might try to pass it. However, this parameter should be set programmatically by the pipeline, not by the LLM. Consider whether to make it a kwarg that the LLM won't see, or handle it via a wrapper/closure
  - Error handling: Catch `Exception` (broad) on the first call with filter, then retry without. The retry should use the existing error handling (try/except returns error dict)
  - The `perplexity_search_tool = FunctionTool(func=search_perplexity)` line may need adjustment if the new parameter should not be exposed to the LLM. Consider creating a closure or partial for the FunctionTool that binds the filter value

### T06-08 - Wire Timeframe into Research Agent Construction

- **Description**: Modify `build_research_phase()` in `newsletter_agent/agent.py` to read resolved timeframes from the config and pass them to the instruction builders and Perplexity tool. For each topic, the timeframe's `prompt_date_instruction` is passed to `get_google_search_instruction()` and `get_perplexity_search_instruction()`. The `perplexity_recency_filter` is passed to the Perplexity search tool (either via a closure wrapping `search_perplexity` or by extending the agent's instruction to include the filter value).
- **Spec refs**: FR-006, FR-007, FR-011, FR-012, Section 4.4 (Pipeline Integration)
- **Parallel**: No (depends on T06-04, T06-05, T06-06, T06-07)
- **Acceptance criteria**:
  - [ ] When `config_timeframes` is not None, each topic's Google Search agent instruction includes the resolved `prompt_date_instruction`
  - [ ] When `config_timeframes` is not None, each topic's Perplexity agent receives the `perplexity_recency_filter` value
  - [ ] When `config_timeframes` is None (no timeframes configured), agent construction is identical to current behavior
  - [ ] The `build_research_phase()` function signature accepts the timeframe data (either as parameter or reads from config)
  - [ ] Logging at INFO level: `"Timeframe resolved for topic '{name}': {original_value} -> perplexity_filter={filter}, prompt='{instruction}'"`
- **Test requirements**: unit (test_agent_factory.py additions), integration
- **Depends on**: T06-04, T06-05, T06-06, T06-07
- **Implementation Guidance**:
  - Recommended pattern: `build_research_phase(config, resolved_timeframes=None)`. Iterate topics and pass the corresponding timeframe to instruction builders. For Perplexity, create a per-topic closure: `make_perplexity_tool(filter_value)` that returns a `FunctionTool` wrapping a partial of `search_perplexity` with the filter bound
  - Known pitfalls: ADK `FunctionTool` inspects the wrapped function's signature. If using `functools.partial`, the signature changes. Test that ADK can still invoke the tool correctly. An alternative is to not change the function signature but instead embed the filter value in the agent instruction (tell the LLM to pass `search_recency_filter` when calling the tool). This is simpler but relies on the LLM correctly passing the parameter
  - The spec says timeframes are resolved in ConfigLoaderAgent and stored in session state (FR-027). However, `build_research_phase()` runs at pipeline construction time (before any agent executes), so it cannot read session state. The timeframes must be resolved from the config object directly in `build_research_phase()`, or passed as a parameter when building the pipeline. Use the config object approach
  - Observability: Add INFO-level logging per spec Section 10.5

### T06-09 - Unit Tests for Timeframe Parsing and Resolution

- **Description**: Create `tests/unit/test_timeframe.py` with comprehensive unit tests for the TimeframeValue validator and `resolve_timeframe()` function. Cover all valid presets, custom days (boundary values), absolute ranges, invalid inputs, and the Perplexity recency filter mapping.
- **Spec refs**: Section 11.1 (Timeframe parsing and resolution tests)
- **Parallel**: Yes (can run concurrently with T06-10)
- **Acceptance criteria**:
  - [ ] Tests cover all 4 valid presets: `last_week`, `last_2_weeks`, `last_month`, `last_year`
  - [ ] Tests cover custom days: X = 1, 7, 8, 30, 31, 90, 365 (boundary values for filter mapping)
  - [ ] Tests cover valid absolute range with dates in the past
  - [ ] Tests reject: `last_forever`, `last_0_days`, `last_500_days`, `last_-1_days`, `between 2025-13-01 and 2025-06-30`, `between 2025-06-30 and 2025-01-01` (inverted), future dates, empty string
  - [ ] Tests verify `resolve_timeframe()` returns correct `perplexity_recency_filter` for each mapping case in FR-007
  - [ ] Tests verify `resolve_timeframe()` returns correct `prompt_date_instruction` text for relative and absolute timeframes
  - [ ] Tests verify `resolve_timeframe(None)` returns all-None fields
  - [ ] All tests pass
- **Test requirements**: unit
- **Depends on**: T06-01, T06-02
- **Implementation Guidance**:
  - Recommended pattern: Use `pytest.mark.parametrize` for the valid/invalid value matrices. Group tests into classes: `TestTimeframeValidation`, `TestResolveTimeframe`, `TestPerplexityFilterMapping`
  - For future date validation, mock `datetime.date.today()` to a fixed date so tests are deterministic
  - Cover the boundary between "week" and "month" filter mapping (7 days = week, 8 days = month)

### T06-10 - Unit Tests for Schema Additions and Perplexity Filter

- **Description**: Add tests to `tests/unit/test_config.py` for the new `timeframe` and `verify_links` fields on `AppSettings` and `TopicConfig`. Add tests to `tests/unit/test_perplexity_search.py` for the new `search_recency_filter` parameter. Verify backward compatibility of existing fixtures.
- **Spec refs**: Section 11.1 (Schema validation additions, Perplexity search additions)
- **Parallel**: Yes (can run concurrently with T06-09)
- **Acceptance criteria**:
  - [ ] test_config.py: AppSettings accepts `timeframe="last_week"` and `verify_links=True`
  - [ ] test_config.py: AppSettings rejects invalid timeframe values
  - [ ] test_config.py: TopicConfig accepts optional `timeframe` field
  - [ ] test_config.py: Existing config fixtures validate without new fields (backward compatibility)
  - [ ] test_perplexity_search.py: `search_recency_filter="week"` adds `extra_body` to API call
  - [ ] test_perplexity_search.py: `search_recency_filter=None` does not add `extra_body`
  - [ ] test_perplexity_search.py: Perplexity API rejection triggers retry without filter
  - [ ] All tests pass (new and existing)
- **Test requirements**: unit
- **Depends on**: T06-03, T06-07
- **Implementation Guidance**:
  - Use existing `make_topic()` and `make_config()` fixture patterns from the codebase
  - For Perplexity retry test: mock `client.chat.completions.create` to raise on first call (with filter) and succeed on second call (without filter). Use `side_effect` with a list of behaviors
  - Verify that `extra_body` is passed correctly by inspecting the mock's `call_args`

### T06-11 - BDD Tests for Timeframe Configuration

- **Description**: Create `tests/bdd/test_timeframe_config.py` with BDD-style acceptance tests covering the 6 scenarios defined in the spec: global timeframe, per-topic override, custom days, absolute date range, invalid rejection, and no timeframe configured.
- **Spec refs**: Section 11.2 (Search Timeframe Configuration BDD scenarios)
- **Parallel**: No (depends on all implementation tasks)
- **Acceptance criteria**:
  - [ ] Scenario "Global timeframe filters all topics" passes
  - [ ] Scenario "Per-topic timeframe overrides global" passes
  - [ ] Scenario "Custom days timeframe" passes
  - [ ] Scenario "Absolute date range timeframe" passes
  - [ ] Scenario "Invalid timeframe rejected at config load" passes
  - [ ] Scenario "No timeframe configured" passes
  - [ ] Tests use descriptive Given/When/Then naming or comments consistent with existing BDD test patterns
- **Test requirements**: BDD
- **Depends on**: T06-01 through T06-08
- **Implementation Guidance**:
  - Follow the existing BDD pattern in `tests/bdd/test_research_pipeline.py` - pytest functions with Given/When/Then comments, using fixtures for config data and mocked pipeline components
  - These tests should verify the end-to-end config-to-agent-instruction flow without making real API calls
  - Use `make_config_yaml` fixture to create test configs, then call `load_config()` and `build_research_phase()` to verify instructions contain expected timeframe text

## Implementation Notes

### File Changes Summary

| File | Action | Description |
|------|--------|-------------|
| `newsletter_agent/config/schema.py` | Modify | Add `TimeframeValue` validator, add fields to `AppSettings` and `TopicConfig` |
| `newsletter_agent/config/timeframe.py` | Create | `ResolvedTimeframe` dataclass + `resolve_timeframe()` function |
| `newsletter_agent/prompts/research_google.py` | Modify | Add `timeframe_instruction` parameter to `get_google_search_instruction()` |
| `newsletter_agent/prompts/research_perplexity.py` | Modify | Add `timeframe_instruction` parameter to `get_perplexity_search_instruction()` |
| `newsletter_agent/tools/perplexity_search.py` | Modify | Add `search_recency_filter` parameter to `search_perplexity()` |
| `newsletter_agent/agent.py` | Modify | Wire timeframes into `ConfigLoaderAgent` and `build_research_phase()` |
| `tests/unit/test_timeframe.py` | Create | Timeframe validation and resolution tests |
| `tests/unit/test_config.py` | Modify | Schema addition tests |
| `tests/unit/test_perplexity_search.py` | Modify | search_recency_filter tests |
| `tests/bdd/test_timeframe_config.py` | Create | BDD acceptance tests |

### Perplexity search_recency_filter Mapping Table

| Timeframe Value | perplexity_recency_filter | Prompt Instruction |
|----------------|--------------------------|-------------------|
| `last_week` | `"week"` | "Focus on results from the last week." |
| `last_2_weeks` | `"month"` | "Focus on results from the last 2 weeks." |
| `last_month` | `"month"` | "Focus on results from the past month." |
| `last_year` | `None` | "Focus on results from the past year." |
| `last_1_days` | `"day"` | "Focus on results from the last day." |
| `last_7_days` | `"week"` | "Focus on results from the last 7 days." |
| `last_8_days` to `last_31_days` | `"month"` | "Focus on results from the last N days." |
| `last_32_days` to `last_365_days` | `None` | "Focus on results from the last N days." |
| `between X and Y` | `None` | "Only include results published between X and Y." |
| `None` | `None` | `None` (no instruction) |

### Key Design Note: FunctionTool and search_recency_filter

The ADK `FunctionTool` inspects the function signature to determine parameters the LLM can invoke. The `search_recency_filter` parameter should NOT be chosen by the LLM - it must be set programmatically based on config. Two approaches:

1. **Closure approach** (recommended): For each topic with a timeframe, create a closure that binds the filter value and wrap it in a new `FunctionTool`.
2. **Instruction approach**: Keep the function signature but tell the LLM in the instruction to pass the specific filter value.

The closure approach is more reliable as it removes LLM discretion.

## Parallel Opportunities

Tasks marked with [P] can be worked concurrently:

- **[P] T06-01 + T06-02**: TimeframeValue validator and resolve_timeframe() are independent modules
- **[P] T06-05 + T06-06**: Google and Perplexity instruction builders are independent files
- **[P] T06-09 + T06-10**: Unit tests for different subsystems are independent

Sequential dependencies:
- T06-03 depends on T06-01 (needs TimeframeValue type)
- T06-04 depends on T06-02, T06-03 (needs resolution function and schema fields)
- T06-08 depends on T06-04, T06-05, T06-06, T06-07 (wires everything together)
- T06-11 depends on T06-01 through T06-08 (BDD tests the full flow)

## Risks & Mitigations

- **Risk**: ADK FunctionTool may not support closures or partials for dynamic parameter binding.
  - **Mitigation**: Test early in T06-07. If closures don't work, fall back to instruction-based approach (tell LLM to pass the filter value).

- **Risk**: Perplexity API may have changed `search_recency_filter` support since the spec was written.
  - **Mitigation**: FR-007/FR-010 specify graceful degradation - retry without filter on API rejection. The prompt-based instruction provides a fallback.

- **Risk**: Future date validation in timeframe may be flaky in CI if tests run near midnight.
  - **Mitigation**: Mock `datetime.date.today()` in all tests that involve date comparison.

## Detailed Task Walkthroughs

### T06-01 Walkthrough: TimeframeValue Pydantic Validator

The validator should be implemented as a standalone function that is used with Pydantic's `Annotated` and `BeforeValidator` pattern. This keeps the validation logic testable independently of the Pydantic model.

**Module-level constants to define in schema.py:**

```
_TIMEFRAME_PRESETS: set[str] = {"last_week", "last_2_weeks", "last_month", "last_year"}
_CUSTOM_DAYS_PATTERN: re.Pattern = re.compile(r"^last_(\d+)_days$")
_ABSOLUTE_RANGE_PATTERN: re.Pattern = re.compile(
    r"^between (\d{4}-\d{2}-\d{2}) and (\d{4}-\d{2}-\d{2})$"
)
```

**Validator function signature:**

```
def _validate_timeframe(value: str | None) -> str | None:
    if value is None:
        return None
    # 1. Check presets
    # 2. Check custom days pattern
    # 3. Check absolute range pattern
    # 4. Raise ValueError with valid formats list
```

**Error message format:**

The error message when validation fails should be actionable. Example:
```
Invalid timeframe 'last_forever'. Valid formats:
  - Presets: 'last_week', 'last_2_weeks', 'last_month', 'last_year'
  - Custom: 'last_X_days' where X is 1-365 (e.g., 'last_30_days')
  - Range: 'between YYYY-MM-DD and YYYY-MM-DD' (e.g., 'between 2025-01-01 and 2025-06-30')
```

**Edge cases to handle:**

1. Empty string `""` - should be rejected (not treated as None)
2. Whitespace string `"  "` - should be rejected
3. Case sensitivity - `"Last_Week"` should be rejected (exact lowercase match)
4. `"last_01_days"` - should be accepted (leading zero in number is fine, int("01") == 1)
5. `"between 2025-02-29 and 2025-03-01"` - 2025 is not a leap year, so Feb 29 is invalid. `date.fromisoformat()` will raise ValueError, which should be caught and converted to a descriptive error
6. `"between 2025-01-01 and 2025-01-01"` - start == end, should be rejected (start must be strictly less than end)

**Type definition:**

```python
TimeframeValue = Annotated[str | None, BeforeValidator(_validate_timeframe)]
```

This type is then used in `AppSettings` and `TopicConfig` as `timeframe: TimeframeValue = None`.

### T06-02 Walkthrough: ResolvedTimeframe Dataclass

The `ResolvedTimeframe` dataclass is a simple immutable container. It should be in its own module (`newsletter_agent/config/timeframe.py`) to keep config/schema.py focused on Pydantic models.

**Dataclass definition:**

```python
@dataclass(frozen=True)
class ResolvedTimeframe:
    perplexity_recency_filter: str | None  # "day", "week", "month", or None
    prompt_date_instruction: str | None     # Natural language for agent prompts
    original_value: str | None             # Raw config string for logging
```

**resolve_timeframe() implementation logic:**

The function should handle each timeframe format category:

1. **None input** -> Return all-None ResolvedTimeframe
2. **Preset values** -> Lookup table:
   - `last_week` -> filter="week", prompt="Focus on results from the last week."
   - `last_2_weeks` -> filter="month", prompt="Focus on results from the last 2 weeks."
   - `last_month` -> filter="month", prompt="Focus on results from the past month."
   - `last_year` -> filter=None, prompt="Focus on results from the past year."
3. **Custom days** -> Parse X, then:
   - X <= 1 -> filter="day"
   - 2 <= X <= 7 -> filter="week"
   - 8 <= X <= 31 -> filter="month"
   - X > 31 -> filter=None
   - prompt="Focus on results from the last {X} days." (or "last day" if X == 1)
4. **Absolute range** -> Parse start and end dates:
   - filter=None (Perplexity doesn't support exact ranges)
   - prompt="Only include results published between {start} and {end}."

**Boundary value analysis for custom days mapping:**

| X value | Expected filter | Rationale |
|---------|----------------|-----------|
| 1 | "day" | X <= 1 |
| 2 | "week" | 2 <= X <= 7 |
| 7 | "week" | 2 <= X <= 7 |
| 8 | "month" | 8 <= X <= 31 |
| 30 | "month" | 8 <= X <= 31 |
| 31 | "month" | 8 <= X <= 31 |
| 32 | None | X > 31 |
| 90 | None | X > 31 |
| 365 | None | X > 31 |

### T06-04 Walkthrough: ConfigLoaderAgent Extension

The `ConfigLoaderAgent` already populates session state with config values. The extension adds two new state keys.

**Current state keys set by ConfigLoaderAgent:**
- `config_newsletter_title`
- `config_recipient_email`
- `config_dry_run`
- `config_output_dir`

**New state keys to add:**
- `config_verify_links` (bool) - from `config.settings.verify_links`
- `config_timeframes` (list[dict] | None) - resolved timeframes per topic

**Timeframe resolution logic in ConfigLoaderAgent:**

```python
# After existing state population:
if any(t.timeframe for t in config.topics) or config.settings.timeframe:
    resolved_timeframes = []
    for topic in config.topics:
        effective_tf = topic.timeframe or config.settings.timeframe
        resolved = resolve_timeframe(effective_tf)
        resolved_timeframes.append({
            "perplexity_recency_filter": resolved.perplexity_recency_filter,
            "prompt_date_instruction": resolved.prompt_date_instruction,
            "original_value": resolved.original_value,
        })
        logger.info(
            "Timeframe resolved for topic '%s': %s -> perplexity_filter=%s, prompt='%s'",
            topic.name, resolved.original_value,
            resolved.perplexity_recency_filter,
            resolved.prompt_date_instruction,
        )
    state["config_timeframes"] = resolved_timeframes
else:
    state["config_timeframes"] = None
    logger.info("No timeframe configured (searching all time)")

state["config_verify_links"] = config.settings.verify_links
```

**Important design note:** Even though the spec says timeframes are resolved in ConfigLoaderAgent and stored in session state, `build_research_phase()` is called at pipeline construction time (before any agent executes). This means `build_research_phase()` cannot read session state. The timeframes must also be resolved from the config object directly in `build_research_phase()` or passed as a parameter. Both locations need the resolution - ConfigLoaderAgent for observability/logging, and build_research_phase for actual use.

### T06-07 Walkthrough: Perplexity search_recency_filter

The key challenge in this task is that `FunctionTool` in ADK exposes the wrapped function's parameters to the LLM. The `search_recency_filter` parameter should be set by the pipeline configuration, not by the LLM.

**Approach 1: Closure (Recommended)**

Create a factory function that returns a new `search_perplexity` function with the filter bound:

```python
def make_perplexity_search_fn(recency_filter: str | None = None):
    def _search(query: str, search_depth: str = "standard") -> dict[str, Any]:
        return search_perplexity(query, search_depth, search_recency_filter=recency_filter)
    _search.__name__ = "search_perplexity"
    _search.__doc__ = search_perplexity.__doc__
    return _search
```

Then in `build_research_phase()`:

```python
if resolved_tf and resolved_tf.perplexity_recency_filter:
    fn = make_perplexity_search_fn(resolved_tf.perplexity_recency_filter)
    tool = FunctionTool(func=fn)
else:
    tool = perplexity_search_tool  # existing global tool
```

**Approach 2: Instruction-based**

Keep the function signature unchanged and tell the LLM in the instruction to pass the filter:

```
Call search_perplexity with:
- query: "{query}"
- search_depth: "{search_depth}"
- search_recency_filter: "week"
```

This is simpler but relies on the LLM correctly passing the parameter.

**Extra_body usage:**

```python
kwargs = {
    "model": model,
    "messages": messages,
}
if search_recency_filter is not None:
    kwargs["extra_body"] = {"search_recency_filter": search_recency_filter}

response = client.chat.completions.create(**kwargs)
```

**Retry logic for API rejection:**

```python
try:
    response = client.chat.completions.create(**kwargs)
except Exception as filter_err:
    if search_recency_filter is not None:
        logger.warning(
            "Perplexity rejected search_recency_filter='%s': %s. Retrying without filter.",
            search_recency_filter, filter_err,
        )
        kwargs.pop("extra_body", None)
        response = client.chat.completions.create(**kwargs)
    else:
        raise
```

### T06-08 Walkthrough: Wiring Timeframes into Research Phase

This is the integration task that connects all pieces. The `build_research_phase()` function currently takes only a `NewsletterConfig` parameter. It needs to also process timeframe data.

**Modifications to build_research_phase:**

```python
def build_research_phase(config: NewsletterConfig) -> ParallelAgent:
    topic_agents = []
    for idx, topic in enumerate(config.topics):
        # Resolve timeframe for this topic
        effective_tf = topic.timeframe or config.settings.timeframe
        resolved_tf = resolve_timeframe(effective_tf)
        
        timeframe_instruction = resolved_tf.prompt_date_instruction
        
        sub_agents = []
        if "google_search" in topic.sources:
            google_agent = LlmAgent(
                name=f"GoogleSearcher_{idx}",
                model=_RESEARCH_MODEL,
                instruction=get_google_search_instruction(
                    topic.name, topic.query, topic.search_depth,
                    timeframe_instruction=timeframe_instruction,  # NEW
                ),
                tools=[google_search],
                output_key=f"research_{idx}_google",
            )
            sub_agents.append(google_agent)
        
        if "perplexity" in topic.sources:
            # Create per-topic tool with bound filter if needed
            if resolved_tf.perplexity_recency_filter:
                pplx_fn = make_perplexity_search_fn(resolved_tf.perplexity_recency_filter)
                pplx_tool = FunctionTool(func=pplx_fn)
            else:
                pplx_tool = perplexity_search_tool
            
            perplexity_agent = LlmAgent(
                name=f"PerplexitySearcher_{idx}",
                model=_RESEARCH_MODEL,
                instruction=get_perplexity_search_instruction(
                    topic.name, topic.query, topic.search_depth,
                    timeframe_instruction=timeframe_instruction,  # NEW
                ),
                tools=[pplx_tool],
                output_key=f"research_{idx}_perplexity",
            )
            sub_agents.append(perplexity_agent)
        
        if sub_agents:
            topic_pipeline = SequentialAgent(
                name=f"Topic{idx}Research",
                sub_agents=sub_agents,
            )
            topic_agents.append(topic_pipeline)
    
    return ParallelAgent(name="ResearchPhase", sub_agents=topic_agents)
```

### T06-09 Walkthrough: Unit Tests for Timeframe

The test file should be organized into clear test classes with parametrized tests where possible.

**Test class structure:**

```
class TestTimeframeValidation:
    """Tests for the _validate_timeframe validator function."""
    
    @pytest.mark.parametrize("value", ["last_week", "last_2_weeks", "last_month", "last_year"])
    def test_valid_presets(self, value): ...
    
    @pytest.mark.parametrize("days", [1, 7, 30, 90, 365])
    def test_valid_custom_days(self, days): ...
    
    def test_valid_absolute_range(self): ...
    def test_none_is_valid(self): ...
    
    @pytest.mark.parametrize("value,reason", [
        ("last_forever", "not a valid format"),
        ("last_0_days", "X must be 1-365"),
        ("last_500_days", "X must be 1-365"),
        ("between 2025-13-01 and 2025-06-30", "invalid date"),
        ("between 2025-06-30 and 2025-01-01", "start >= end"),
        ("", "empty"),
    ])
    def test_invalid_values(self, value, reason): ...

class TestResolveTimeframe:
    """Tests for resolve_timeframe() function."""
    
    def test_none_returns_all_none(self): ...
    
    @pytest.mark.parametrize("value,expected_filter", [
        ("last_week", "week"),
        ("last_2_weeks", "month"),
        ("last_month", "month"),
        ("last_year", None),
    ])
    def test_preset_perplexity_filter(self, value, expected_filter): ...
    
    @pytest.mark.parametrize("days,expected_filter", [
        (1, "day"), (2, "week"), (7, "week"), (8, "month"),
        (30, "month"), (31, "month"), (32, None), (90, None), (365, None),
    ])
    def test_custom_days_perplexity_filter(self, days, expected_filter): ...
    
    def test_absolute_range_no_perplexity_filter(self): ...
    def test_absolute_range_prompt_includes_dates(self): ...
    
    @pytest.mark.parametrize("value,expected_fragment", [
        ("last_week", "last week"),
        ("last_30_days", "last 30 days"),
        ("last_year", "past year"),
    ])
    def test_prompt_instruction_text(self, value, expected_fragment): ...
```

### T06-11 Walkthrough: BDD Tests for Timeframe

The BDD tests should follow the existing pattern in the codebase. Looking at `tests/bdd/test_research_pipeline.py`, the pattern uses pytest functions with descriptive names and `# Given / # When / # Then` comments.

**Test structure:**

```python
class TestTimeframeConfigBDD:
    """BDD scenarios for Search Timeframe Configuration feature."""

    def test_global_timeframe_filters_all_topics(self, make_config_yaml):
        # Given a topics.yaml with settings.timeframe set to "last_week"
        # And 3 topics with no individual timeframe
        config_data = {
            "newsletter": {...},
            "settings": {"timeframe": "last_week", "dry_run": True},
            "topics": [
                {"name": "Topic1", "query": "query1"},
                {"name": "Topic2", "query": "query2"},
                {"name": "Topic3", "query": "query3"},
            ],
        }
        yaml_path = make_config_yaml(config_data)
        
        # When the config is loaded
        config = load_config(yaml_path)
        
        # Then all 3 topics resolve to perplexity_recency_filter "week"
        for topic in config.topics:
            effective_tf = topic.timeframe or config.settings.timeframe
            resolved = resolve_timeframe(effective_tf)
            assert resolved.perplexity_recency_filter == "week"
            assert "last week" in resolved.prompt_date_instruction.lower()
```

## Rollback Considerations

All changes in this work package are additive (new files, new optional fields, new function parameters with defaults). Rollback is straightforward:

1. Remove `newsletter_agent/config/timeframe.py`
2. Remove `timeframe` and `verify_links` fields from `AppSettings` and `TopicConfig` in schema.py
3. Remove `TimeframeValue` validator from schema.py
4. Revert `search_perplexity()` to 2-parameter signature
5. Revert instruction builders to 3-parameter signatures
6. Revert `build_research_phase()` to current implementation
7. Revert `ConfigLoaderAgent` to current implementation
8. Remove new test files

No data migration is needed. No database changes. No deployment configuration changes.

## Acceptance Verification Checklist

Before marking this WP as complete, verify:

- [ ] `python -m pytest tests/unit/test_timeframe.py -v` - all pass
- [ ] `python -m pytest tests/unit/test_config.py -v` - all pass (including new and existing tests)
- [ ] `python -m pytest tests/unit/test_perplexity_search.py -v` - all pass
- [ ] `python -m pytest tests/bdd/test_timeframe_config.py -v` - all pass
- [ ] `python -m pytest tests/ -v` - full suite passes (no regressions)
- [ ] Existing `config/topics.yaml` (without new fields) still validates
- [ ] A topics.yaml with `settings.timeframe: "last_week"` validates and produces correct resolved timeframes
- [ ] A topics.yaml with per-topic timeframe override resolves correctly

## Configuration Examples

### Example 1: Global Timeframe Only

```yaml
newsletter:
  title: "AI Weekly Briefing"
  recipients:
    - "team@example.com"
settings:
  dry_run: false
  output_dir: "output/"
  timeframe: "last_week"
topics:
  - name: "Machine Learning Advances"
    query: "latest machine learning research breakthroughs"
    sources:
      - perplexity
      - google_search
    search_depth: standard
  - name: "AI in Healthcare"
    query: "artificial intelligence healthcare applications"
    sources:
      - perplexity
    search_depth: standard
```

**Expected behavior:** Both topics inherit `"last_week"` from settings. Perplexity API calls include `search_recency_filter: "week"`. All agent instructions include "Focus on results from the last week."

### Example 2: Per-topic Override

```yaml
newsletter:
  title: "AI Weekly Briefing"
  recipients:
    - "team@example.com"
settings:
  dry_run: false
  output_dir: "output/"
  timeframe: "last_week"
topics:
  - name: "Machine Learning Advances"
    query: "latest machine learning research breakthroughs"
    sources:
      - perplexity
      - google_search
    search_depth: standard
    timeframe: "last_month"
  - name: "AI in Healthcare"
    query: "artificial intelligence healthcare applications"
    sources:
      - perplexity
    search_depth: standard
```

**Expected behavior:** Topic 0 ("Machine Learning Advances") uses `"last_month"` (its own override), so Perplexity gets `search_recency_filter: "month"` and instructions say "Focus on results from the past month." Topic 1 ("AI in Healthcare") inherits `"last_week"` from settings, so Perplexity gets `search_recency_filter: "week"` and instructions say "Focus on results from the last week."

### Example 3: Custom Days

```yaml
settings:
  timeframe: "last_30_days"
topics:
  - name: "Cybersecurity"
    query: "cybersecurity threats 2025"
    sources:
      - perplexity
    search_depth: deep
```

**Expected behavior:** Perplexity gets `search_recency_filter: "month"` (30 is in range 8-31). Instructions say "Focus on results from the last 30 days."

### Example 4: Absolute Date Range

```yaml
settings:
  timeframe: "between 2025-01-01 and 2025-03-31"
topics:
  - name: "Q1 Summary"
    query: "tech industry news Q1 2025"
    sources:
      - perplexity
      - google_search
    search_depth: deep
```

**Expected behavior:** Perplexity gets `search_recency_filter: None` (absolute ranges cannot map to relative filters). Instructions say "Only include results published between 2025-01-01 and 2025-03-31."

### Example 5: No Timeframe (Backward Compatible)

```yaml
newsletter:
  title: "Newsletter"
  recipients:
    - "user@example.com"
settings:
  dry_run: true
  output_dir: "output/"
topics:
  - name: "General AI"
    query: "AI news"
    sources:
      - perplexity
    search_depth: standard
```

**Expected behavior:** No timeframe configured. Perplexity API calls do not include `search_recency_filter`. No timeframe instruction in agent prompts. Behavior identical to current pre-WP06 implementation.

### Example 6: Mixed - Some Topics With, Some Without

```yaml
settings:
  dry_run: true
  output_dir: "output/"
topics:
  - name: "AI Research"
    query: "machine learning papers"
    sources:
      - perplexity
    search_depth: standard
    timeframe: "last_week"
  - name: "Climate Tech"
    query: "climate technology advances"
    sources:
      - google_search
    search_depth: standard
```

**Expected behavior:** Topic 0 has `timeframe: "last_week"`, so it gets the filter and instruction. Topic 1 has no timeframe and no global default, so it searches all time. This is valid - each topic is independent.

## Detailed Error Scenarios

### Error Scenario 1: Invalid Preset Typo

**Input:** `settings.timeframe: "last_Week"` (capital W)

**Expected:** Pydantic `ValidationError` at config load time with message:
```
Invalid timeframe 'last_Week'. Valid formats:
  - Presets: 'last_week', 'last_2_weeks', 'last_month', 'last_year'
  - Custom: 'last_X_days' where X is 1-365 (e.g., 'last_30_days')
  - Range: 'between YYYY-MM-DD and YYYY-MM-DD' (e.g., 'between 2025-01-01 and 2025-06-30')
```

**User action:** Fix the typo in topics.yaml and re-run.

### Error Scenario 2: Days Out of Range

**Input:** `topics[0].timeframe: "last_0_days"`

**Expected:** Pydantic `ValidationError` with message indicating X must be 1-365.

**Input:** `topics[0].timeframe: "last_500_days"`

**Expected:** Same pattern - rejected at validation time.

### Error Scenario 3: Inverted Date Range

**Input:** `settings.timeframe: "between 2025-06-30 and 2025-01-01"`

**Expected:** Pydantic `ValidationError` with message: "Invalid timeframe: start date 2025-06-30 must be before end date 2025-01-01."

### Error Scenario 4: Future End Date

**Input:** `settings.timeframe: "between 2025-01-01 and 2030-12-31"`

**Expected:** Pydantic `ValidationError` with message: "Invalid timeframe: end date 2030-12-31 is in the future."

### Error Scenario 5: Invalid Date Format

**Input:** `settings.timeframe: "between 01/01/2025 and 06/30/2025"`

**Expected:** Rejected by regex - does not match `"between YYYY-MM-DD and YYYY-MM-DD"` pattern.

### Error Scenario 6: Perplexity API Rejection

**Runtime scenario:** The Perplexity API rejects `search_recency_filter: "week"` (e.g., if they change the API).

**Expected behavior:**
1. First API call fails with an exception
2. `search_perplexity()` catches the exception
3. Logs WARNING: "Perplexity rejected search_recency_filter='week': {error}. Retrying without filter."
4. Retries the call without `extra_body`
5. If the retry succeeds, returns the result normally
6. If the retry also fails, returns the standard error dict

## Task Dependency Graph

```
T06-01 ----+
           |
           v
T06-03 ----+
           |
           v
T06-04 ----+
           |
           v
T06-08 ----+-----> T06-11
           ^         ^
           |         |
T06-02 ----+         |
                     |
T06-05 ----+-----> T06-08
           |         ^
T06-06 ----+         |
                     |
T06-07 ----------> T06-08

T06-09 (after T06-01, T06-02)
T06-10 (after T06-03, T06-07)
```

**Critical path:** T06-01 -> T06-03 -> T06-04 -> T06-08 -> T06-11

**Parallel tracks:**
- Track A: T06-01, T06-03, T06-04
- Track B: T06-02 (parallel with T06-01)
- Track C: T06-05, T06-06 (parallel with each other and with Track A)
- Track D: T06-07 (can start anytime, independent until T06-08)
- Track E: T06-09, T06-10 (test writing, parallel with each other, after their dependencies)

## Logging and Observability

Per spec Section 10.5, the following log messages must be emitted:

### INFO-level logs:

1. **Config load - global timeframe:**
   ```
   Global timeframe configured: 'last_week'
   ```

2. **Config load - topic timeframe resolved:**
   ```
   Timeframe resolved for topic 'Machine Learning': last_week -> perplexity_filter=week, prompt='Focus on results from the last week.'
   ```

3. **Config load - no timeframe:**
   ```
   No timeframe configured (searching all time)
   ```

4. **Research phase - Perplexity filter applied:**
   ```
   Perplexity search for topic 'AI' using recency_filter='week'
   ```

### WARNING-level logs:

1. **Perplexity API filter rejected:**
   ```
   Perplexity rejected search_recency_filter='week': {error_details}. Retrying without filter.
   ```

2. **Unexpected timeframe value in resolve_timeframe:**
   ```
   Unexpected timeframe value '{value}' passed to resolve_timeframe(). Returning no filtering.
   ```

### DEBUG-level logs:

1. **Perplexity API request details:**
   ```
   Perplexity API request: model=sonar, extra_body={'search_recency_filter': 'week'}
   ```

2. **Google instruction with timeframe:**
   ```
   Google Search instruction for topic 'AI' includes timeframe: 'Focus on results from the last week.'
   ```

## Security Considerations

Per spec Section 10.2:

1. **Input validation:** All timeframe values are validated at config load time by Pydantic before any processing. No user input reaches the Perplexity API or Google Search without passing validation.

2. **Date parsing:** Use `datetime.date.fromisoformat()` for date parsing, not `strptime` with custom patterns. This avoids format string injection issues.

3. **No shell injection:** Timeframe values are never passed to shell commands. They are used as API parameters (string values) and prompt text (string concatenation into predefined templates).

4. **Regex DoS:** The regex patterns for timeframe validation are simple and bounded. No backtracking-vulnerable patterns. All patterns use anchors (`^` and `$`) and deterministic alternation.

5. **Prompt injection:** The `timeframe_instruction` text is generated by the system from validated config values, not from user-provided free text. The instruction text follows fixed templates ("Focus on results from the last {N} days." or "Only include results published between {start} and {end}.") where N, start, and end are validated values. There is no risk of prompt injection via the timeframe field.

## Backward Compatibility Verification

The following existing behaviors MUST be verified to still work after WP06:

1. **Config without timeframe or verify_links fields loads successfully** - The new fields have defaults (`None` and `False`), so omitting them is valid.

2. **Existing test fixtures continue to work** - `conftest.py` fixtures for `sample_config_data` and `make_config_yaml` do not include the new fields and must still produce valid configs.

3. **Pipeline without timeframe produces identical agents** - When no timeframe is configured, `build_research_phase()` must produce the same agents with the same instructions as before WP06.

4. **Perplexity tool without filter works identically** - `search_perplexity("query", "standard")` (no filter) must behave the same as the current implementation.

5. **All existing tests pass without modification** - No existing test should need changes to pass after WP06 implementation.

## Test Matrix

| Test ID | Test Type | File | Description | Task |
|---------|-----------|------|-------------|------|
| TF-U-01 | Unit | test_timeframe.py | Valid presets accepted | T06-09 |
| TF-U-02 | Unit | test_timeframe.py | Valid custom days accepted | T06-09 |
| TF-U-03 | Unit | test_timeframe.py | Valid absolute range accepted | T06-09 |
| TF-U-04 | Unit | test_timeframe.py | None accepted | T06-09 |
| TF-U-05 | Unit | test_timeframe.py | Invalid preset rejected | T06-09 |
| TF-U-06 | Unit | test_timeframe.py | Days out of range rejected | T06-09 |
| TF-U-07 | Unit | test_timeframe.py | Inverted date range rejected | T06-09 |
| TF-U-08 | Unit | test_timeframe.py | Future date rejected | T06-09 |
| TF-U-09 | Unit | test_timeframe.py | Invalid date format rejected | T06-09 |
| TF-U-10 | Unit | test_timeframe.py | resolve_timeframe preset mapping | T06-09 |
| TF-U-11 | Unit | test_timeframe.py | resolve_timeframe custom days boundary | T06-09 |
| TF-U-12 | Unit | test_timeframe.py | resolve_timeframe absolute range | T06-09 |
| TF-U-13 | Unit | test_timeframe.py | resolve_timeframe None | T06-09 |
| TF-U-14 | Unit | test_timeframe.py | resolve_timeframe prompt text | T06-09 |
| TF-U-15 | Unit | test_config.py | AppSettings with timeframe | T06-10 |
| TF-U-16 | Unit | test_config.py | AppSettings with verify_links | T06-10 |
| TF-U-17 | Unit | test_config.py | AppSettings backward compat | T06-10 |
| TF-U-18 | Unit | test_config.py | TopicConfig with timeframe | T06-10 |
| TF-U-19 | Unit | test_config.py | TopicConfig backward compat | T06-10 |
| TF-U-20 | Unit | test_config.py | Full config with mixed timeframes | T06-10 |
| TF-U-21 | Unit | test_perplexity_search.py | search_recency_filter passed | T06-10 |
| TF-U-22 | Unit | test_perplexity_search.py | No filter when None | T06-10 |
| TF-U-23 | Unit | test_perplexity_search.py | API rejection retry | T06-10 |
| TF-B-01 | BDD | test_timeframe_config.py | Global timeframe all topics | T06-11 |
| TF-B-02 | BDD | test_timeframe_config.py | Per-topic override | T06-11 |
| TF-B-03 | BDD | test_timeframe_config.py | Custom days timeframe | T06-11 |
| TF-B-04 | BDD | test_timeframe_config.py | Absolute date range | T06-11 |
| TF-B-05 | BDD | test_timeframe_config.py | Invalid timeframe rejected | T06-11 |
| TF-B-06 | BDD | test_timeframe_config.py | No timeframe configured | T06-11 |

## Module Import Map

After WP06 implementation, the import graph for timeframe functionality is:

```
newsletter_agent/config/schema.py
  - imports: re, datetime.date
  - defines: _validate_timeframe(), TimeframeValue type
  - used by: config loader, test_config.py

newsletter_agent/config/timeframe.py (NEW)
  - imports: re, datetime.date, dataclasses
  - defines: ResolvedTimeframe, resolve_timeframe()
  - used by: agent.py, test_timeframe.py

newsletter_agent/agent.py
  - imports: resolve_timeframe from config.timeframe
  - imports: make_perplexity_search_fn from tools.perplexity_search (or defines inline)
  - modifies: ConfigLoaderAgent._run_async_impl(), build_research_phase()

newsletter_agent/tools/perplexity_search.py
  - modifies: search_perplexity() signature (adds search_recency_filter)
  - adds: make_perplexity_search_fn() factory function (optional)

newsletter_agent/prompts/research_google.py
  - modifies: get_google_search_instruction() signature (adds timeframe_instruction)

newsletter_agent/prompts/research_perplexity.py
  - modifies: get_perplexity_search_instruction() signature (adds timeframe_instruction)
```

## Estimated File Changes (Lines of Code)

| File | Lines Added | Lines Modified | Lines Removed |
|------|------------|----------------|---------------|
| schema.py | ~35 | 2 | 0 |
| timeframe.py (NEW) | ~70 | 0 | 0 |
| agent.py | ~30 | 5 | 0 |
| perplexity_search.py | ~20 | 3 | 0 |
| research_google.py | ~8 | 2 | 0 |
| research_perplexity.py | ~8 | 2 | 0 |
| test_timeframe.py (NEW) | ~180 | 0 | 0 |
| test_config.py | ~60 | 0 | 0 |
| test_perplexity_search.py | ~45 | 0 | 0 |
| test_timeframe_config.py (NEW) | ~120 | 0 | 0 |
| **Total** | **~576** | **~14** | **0** |

## Detailed Test Case Specifications

### Unit Test Specifications for test_timeframe.py (T06-09)

#### TestTimeframeValidation Class

**test_valid_presets (parametrized)**

For each of `["last_week", "last_2_weeks", "last_month", "last_year"]`:
- Create a Pydantic model with a `TimeframeValue` field
- Pass the preset value
- Assert the model validates without error
- Assert the parsed value matches the input exactly (no transformation)

```python
@pytest.mark.parametrize("value", ["last_week", "last_2_weeks", "last_month", "last_year"])
def test_valid_presets(self, value):
    result = _validate_timeframe(value)
    assert result == value
```

**test_valid_custom_days (parametrized)**

For each of `[1, 2, 7, 8, 30, 31, 90, 180, 365]`:
- Build the string `f"last_{days}_days"`
- Assert `_validate_timeframe()` returns the same string

```python
@pytest.mark.parametrize("days", [1, 2, 7, 8, 30, 31, 90, 180, 365])
def test_valid_custom_days(self, days):
    value = f"last_{days}_days"
    result = _validate_timeframe(value)
    assert result == value
```

**test_valid_absolute_range**

- Use `"between 2025-01-01 and 2025-06-30"` (assuming test runs before 2025-06-30, or mock today)
- Assert validation passes
- Assert the string is returned unchanged

```python
def test_valid_absolute_range(self):
    with patch("newsletter_agent.config.schema.date") as mock_date:
        mock_date.today.return_value = date(2025, 7, 1)
        mock_date.fromisoformat = date.fromisoformat
        result = _validate_timeframe("between 2025-01-01 and 2025-06-30")
        assert result == "between 2025-01-01 and 2025-06-30"
```

**test_none_passes_through**

```python
def test_none_passes_through(self):
    result = _validate_timeframe(None)
    assert result is None
```

**test_invalid_empty_string**

```python
def test_invalid_empty_string(self):
    with pytest.raises(ValueError, match="Invalid timeframe"):
        _validate_timeframe("")
```

**test_invalid_whitespace**

```python
def test_invalid_whitespace(self):
    with pytest.raises(ValueError, match="Invalid timeframe"):
        _validate_timeframe("   ")
```

**test_invalid_case_sensitive**

```python
def test_invalid_case_sensitive(self):
    with pytest.raises(ValueError, match="Invalid timeframe"):
        _validate_timeframe("Last_Week")
```

**test_invalid_days_zero**

```python
def test_invalid_days_zero(self):
    with pytest.raises(ValueError, match="1-365"):
        _validate_timeframe("last_0_days")
```

**test_invalid_days_over_365**

```python
def test_invalid_days_over_365(self):
    with pytest.raises(ValueError, match="1-365"):
        _validate_timeframe("last_500_days")
```

**test_invalid_negative_days**

```python
def test_invalid_negative_days(self):
    # "last_-1_days" should not match the regex at all (no negative numbers)
    with pytest.raises(ValueError, match="Invalid timeframe"):
        _validate_timeframe("last_-1_days")
```

**test_invalid_inverted_range**

```python
def test_invalid_inverted_range(self):
    with pytest.raises(ValueError, match="before end date"):
        _validate_timeframe("between 2025-06-30 and 2025-01-01")
```

**test_invalid_future_dates**

```python
def test_invalid_future_dates(self):
    with patch("newsletter_agent.config.schema.date") as mock_date:
        mock_date.today.return_value = date(2025, 3, 15)
        mock_date.fromisoformat = date.fromisoformat
        with pytest.raises(ValueError, match="future"):
            _validate_timeframe("between 2025-01-01 and 2030-12-31")
```

**test_invalid_impossible_date**

```python
def test_invalid_impossible_date(self):
    # Feb 29 in non-leap year
    with pytest.raises(ValueError, match="Invalid"):
        _validate_timeframe("between 2025-02-29 and 2025-03-01")
```

**test_invalid_arbitrary_string**

```python
@pytest.mark.parametrize("value", [
    "last_forever",
    "yesterday",
    "2025-01-01",
    "this week",
    "recent",
    "last_week ",  # trailing space
    " last_week",  # leading space
])
def test_invalid_arbitrary_strings(self, value):
    with pytest.raises(ValueError, match="Invalid timeframe"):
        _validate_timeframe(value)
```

**test_equal_start_end_range**

```python
def test_equal_start_end_range(self):
    with pytest.raises(ValueError, match="before end date"):
        _validate_timeframe("between 2025-01-01 and 2025-01-01")
```

#### TestResolveTimeframe Class

**test_none_returns_all_none**

```python
def test_none_returns_all_none(self):
    result = resolve_timeframe(None)
    assert result.perplexity_recency_filter is None
    assert result.prompt_date_instruction is None
    assert result.original_value is None
```

**test_preset_perplexity_filters (parametrized)**

```python
@pytest.mark.parametrize("value,expected_filter", [
    ("last_week", "week"),
    ("last_2_weeks", "month"),
    ("last_month", "month"),
    ("last_year", None),
])
def test_preset_perplexity_filters(self, value, expected_filter):
    result = resolve_timeframe(value)
    assert result.perplexity_recency_filter == expected_filter
    assert result.original_value == value
```

**test_custom_days_boundary_filters (parametrized)**

```python
@pytest.mark.parametrize("days,expected_filter", [
    (1, "day"),
    (2, "week"),
    (7, "week"),
    (8, "month"),
    (30, "month"),
    (31, "month"),
    (32, None),
    (90, None),
    (365, None),
])
def test_custom_days_boundary_filters(self, days, expected_filter):
    result = resolve_timeframe(f"last_{days}_days")
    assert result.perplexity_recency_filter == expected_filter
```

**test_absolute_range_perplexity_filter**

```python
def test_absolute_range_perplexity_filter(self):
    result = resolve_timeframe("between 2025-01-01 and 2025-06-30")
    assert result.perplexity_recency_filter is None
```

**test_prompt_instructions_content (parametrized)**

```python
@pytest.mark.parametrize("value,expected_fragment", [
    ("last_week", "last week"),
    ("last_2_weeks", "last 2 weeks"),
    ("last_month", "past month"),
    ("last_year", "past year"),
    ("last_30_days", "last 30 days"),
    ("last_1_days", "last day"),
])
def test_prompt_instructions_content(self, value, expected_fragment):
    result = resolve_timeframe(value)
    assert expected_fragment in result.prompt_date_instruction.lower()
```

**test_absolute_range_prompt_includes_dates**

```python
def test_absolute_range_prompt_includes_dates(self):
    result = resolve_timeframe("between 2025-01-01 and 2025-06-30")
    assert "2025-01-01" in result.prompt_date_instruction
    assert "2025-06-30" in result.prompt_date_instruction
```

**test_resolved_timeframe_is_immutable**

```python
def test_resolved_timeframe_is_immutable(self):
    result = resolve_timeframe("last_week")
    with pytest.raises(FrozenInstanceError):
        result.perplexity_recency_filter = "day"
```

### Unit Test Specifications for test_config.py additions (T06-10)

#### TestAppSettingsTimeframe Class

**test_app_settings_with_valid_timeframe**

```python
def test_app_settings_with_valid_timeframe(self):
    settings = AppSettings(
        dry_run=True,
        output_dir="output/",
        timeframe="last_week",
    )
    assert settings.timeframe == "last_week"
```

**test_app_settings_with_verify_links**

```python
def test_app_settings_with_verify_links(self):
    settings = AppSettings(
        dry_run=True,
        output_dir="output/",
        verify_links=True,
    )
    assert settings.verify_links is True
```

**test_app_settings_verify_links_default_false**

```python
def test_app_settings_verify_links_default_false(self):
    settings = AppSettings(dry_run=True, output_dir="output/")
    assert settings.verify_links is False
```

**test_app_settings_timeframe_default_none**

```python
def test_app_settings_timeframe_default_none(self):
    settings = AppSettings(dry_run=True, output_dir="output/")
    assert settings.timeframe is None
```

**test_app_settings_invalid_timeframe_rejected**

```python
def test_app_settings_invalid_timeframe_rejected(self):
    with pytest.raises(ValidationError):
        AppSettings(dry_run=True, output_dir="output/", timeframe="invalid")
```

**test_app_settings_backward_compatible**

```python
def test_app_settings_backward_compatible(self, sample_config_data):
    """Existing config data without new fields still validates."""
    settings = AppSettings(**sample_config_data["settings"])
    assert settings.dry_run is True
    assert settings.timeframe is None
    assert settings.verify_links is False
```

#### TestTopicConfigTimeframe Class

**test_topic_config_with_timeframe**

```python
def test_topic_config_with_timeframe(self, make_topic):
    topic = make_topic(timeframe="last_month")
    assert topic.timeframe == "last_month"
```

**test_topic_config_timeframe_default_none**

```python
def test_topic_config_timeframe_default_none(self, make_topic):
    topic = make_topic()
    assert topic.timeframe is None
```

**test_topic_config_invalid_timeframe_rejected**

```python
def test_topic_config_invalid_timeframe_rejected(self):
    with pytest.raises(ValidationError):
        TopicConfig(name="Test", query="query", timeframe="bad_value")
```

### Unit Test Specifications for test_perplexity_search.py additions (T06-10)

#### TestSearchRecencyFilter Class

**test_recency_filter_passed_to_api**

```python
@patch("newsletter_agent.tools.perplexity_search.OpenAI")
def test_recency_filter_passed_to_api(self, mock_openai):
    mock_client = MagicMock()
    mock_openai.return_value = mock_client
    mock_client.chat.completions.create.return_value = mock_response("result")
    
    search_perplexity("test query", "standard", search_recency_filter="week")
    
    call_kwargs = mock_client.chat.completions.create.call_args
    assert call_kwargs.kwargs.get("extra_body") == {"search_recency_filter": "week"}
```

**test_no_filter_when_none**

```python
@patch("newsletter_agent.tools.perplexity_search.OpenAI")
def test_no_filter_when_none(self, mock_openai):
    mock_client = MagicMock()
    mock_openai.return_value = mock_client
    mock_client.chat.completions.create.return_value = mock_response("result")
    
    search_perplexity("test query", "standard", search_recency_filter=None)
    
    call_kwargs = mock_client.chat.completions.create.call_args
    assert "extra_body" not in call_kwargs.kwargs
```

**test_api_rejection_retries_without_filter**

```python
@patch("newsletter_agent.tools.perplexity_search.OpenAI")
def test_api_rejection_retries_without_filter(self, mock_openai):
    mock_client = MagicMock()
    mock_openai.return_value = mock_client
    # First call with filter: raises. Second call without: succeeds.
    mock_client.chat.completions.create.side_effect = [
        Exception("Invalid parameter: search_recency_filter"),
        mock_response("result after retry"),
    ]
    
    result = search_perplexity("test query", "standard", search_recency_filter="week")
    
    assert mock_client.chat.completions.create.call_count == 2
    # Second call should not have extra_body
    second_call = mock_client.chat.completions.create.call_args_list[1]
    assert "extra_body" not in second_call.kwargs
    assert "result after retry" in str(result)
```

**test_make_perplexity_search_fn_binds_filter**

```python
def test_make_perplexity_search_fn_binds_filter(self):
    fn = make_perplexity_search_fn("week")
    # Verify the function has the correct name and signature
    assert fn.__name__ == "search_perplexity"
    sig = inspect.signature(fn)
    # Should only expose query and search_depth, not search_recency_filter
    assert "search_recency_filter" not in sig.parameters
    assert "query" in sig.parameters
    assert "search_depth" in sig.parameters
```

### BDD Test Specifications for test_timeframe_config.py (T06-11)

#### Scenario 1: Global timeframe filters all topics

```python
def test_global_timeframe_filters_all_topics(self, make_config_yaml):
    """
    Given a topics.yaml with settings.timeframe set to 'last_week'
    And 3 topics with no individual timeframe
    When the pipeline is built from this config
    Then all 3 topic research agents have instructions containing 'last week'
    And all 3 Perplexity tools use search_recency_filter 'week'
    """
    # Given
    config_data = build_config_data(
        settings={"timeframe": "last_week", "dry_run": True, "output_dir": "out/"},
        topics=[
            {"name": "T1", "query": "q1", "sources": ["perplexity"]},
            {"name": "T2", "query": "q2", "sources": ["perplexity"]},
            {"name": "T3", "query": "q3", "sources": ["perplexity"]},
        ],
    )
    config = load_config_from_dict(config_data)
    
    # When
    research_phase = build_research_phase(config)
    
    # Then - verify instructions contain timeframe
    for agent in research_phase.sub_agents:
        assert "last week" in agent.instruction.lower()
```

#### Scenario 2: Per-topic timeframe overrides global

```python
def test_per_topic_timeframe_overrides_global(self, make_config_yaml):
    """
    Given a topics.yaml with settings.timeframe 'last_week'
    And topic 0 has timeframe 'last_month' override
    And topic 1 has no timeframe override
    When the pipeline is built
    Then topic 0 agent instruction contains 'past month'
    And topic 1 agent instruction contains 'last week'
    """
    # Given
    config_data = build_config_data(
        settings={"timeframe": "last_week", "dry_run": True, "output_dir": "out/"},
        topics=[
            {"name": "T1", "query": "q1", "sources": ["perplexity"], "timeframe": "last_month"},
            {"name": "T2", "query": "q2", "sources": ["perplexity"]},
        ],
    )
    config = load_config_from_dict(config_data)
    
    # When
    research_phase = build_research_phase(config)
    
    # Then
    t1_instruction = research_phase.sub_agents[0].instruction.lower()
    t2_instruction = research_phase.sub_agents[1].instruction.lower()
    assert "past month" in t1_instruction or "last month" in t1_instruction
    assert "last week" in t2_instruction
```

#### Scenario 3: Custom days timeframe

```python
def test_custom_days_timeframe(self, make_config_yaml):
    """
    Given a topics.yaml with settings.timeframe 'last_30_days'
    When the config is loaded and timeframes are resolved
    Then the resolved timeframe has perplexity_recency_filter 'month'
    And the prompt instruction contains '30 days'
    """
    # Given + When
    config_data = build_config_data(
        settings={"timeframe": "last_30_days", "dry_run": True, "output_dir": "out/"},
        topics=[{"name": "T1", "query": "q1", "sources": ["perplexity"]}],
    )
    config = load_config_from_dict(config_data)
    resolved = resolve_timeframe(config.topics[0].timeframe or config.settings.timeframe)
    
    # Then
    assert resolved.perplexity_recency_filter == "month"
    assert "30 days" in resolved.prompt_date_instruction
```

#### Scenario 4: Absolute date range timeframe

```python
def test_absolute_date_range_timeframe(self, make_config_yaml):
    """
    Given a topics.yaml with settings.timeframe 'between 2025-01-01 and 2025-03-31'
    When the config is loaded and timeframes are resolved
    Then perplexity_recency_filter is None
    And prompt instruction contains both dates
    """
    config_data = build_config_data(
        settings={
            "timeframe": "between 2025-01-01 and 2025-03-31",
            "dry_run": True,
            "output_dir": "out/",
        },
        topics=[{"name": "T1", "query": "q1", "sources": ["perplexity"]}],
    )
    config = load_config_from_dict(config_data)
    resolved = resolve_timeframe(config.settings.timeframe)
    
    assert resolved.perplexity_recency_filter is None
    assert "2025-01-01" in resolved.prompt_date_instruction
    assert "2025-03-31" in resolved.prompt_date_instruction
```

#### Scenario 5: Invalid timeframe rejected at config load

```python
def test_invalid_timeframe_rejected_at_config_load(self, tmp_path):
    """
    Given a topics.yaml with settings.timeframe 'last_forever'
    When the config is loaded
    Then a ValidationError is raised with a descriptive message
    """
    config_yaml = tmp_path / "topics.yaml"
    config_yaml.write_text(yaml.dump({
        "newsletter": {"title": "Test", "recipients": ["t@t.com"]},
        "settings": {"dry_run": True, "output_dir": "out/", "timeframe": "last_forever"},
        "topics": [{"name": "T1", "query": "q1", "sources": ["perplexity"]}],
    }))
    
    with pytest.raises(ValidationError, match="Invalid timeframe"):
        load_config(config_yaml)
```

#### Scenario 6: No timeframe configured

```python
def test_no_timeframe_configured(self, make_config_yaml):
    """
    Given a topics.yaml with no timeframe in settings or topics
    When the pipeline is built
    Then agent instructions do not contain any timeframe text
    And Perplexity tool does not use search_recency_filter
    """
    config_data = build_config_data(
        settings={"dry_run": True, "output_dir": "out/"},
        topics=[{"name": "T1", "query": "q1", "sources": ["perplexity"]}],
    )
    config = load_config_from_dict(config_data)
    
    research_phase = build_research_phase(config)
    
    # Verify no timeframe text in instructions
    for agent in research_phase.sub_agents:
        instruction_lower = agent.instruction.lower()
        assert "focus on results from" not in instruction_lower
        assert "only include results published" not in instruction_lower
```

## Perplexity API Reference Notes

The Perplexity Sonar API supports the following `search_recency_filter` values:
- `"day"` - Results from the last 24 hours
- `"week"` - Results from the last 7 days
- `"month"` - Results from the last 30 days

Note: There is no `"year"` filter. For timeframe values that map to periods longer than a month, the code sets `perplexity_recency_filter` to `None` and relies solely on the prompt instruction.

The parameter is passed via `extra_body` in the OpenAI client, not as a standard parameter, because Perplexity uses an OpenAI-compatible API but `search_recency_filter` is a Perplexity-specific extension.

Official Perplexity docs reference: https://docs.perplexity.ai/api-reference/chat-completions

## Google Search (ADK) Timeframe Notes

Google ADK's `google_search` tool does not support date filtering as a parameter. The timeframe is communicated via the agent's instruction prompt. The LLM is told to "Focus on results from the last week" (or similar) and must interpret this when generating search queries.

This means Google Search timeframe filtering is best-effort - the LLM may or may not add date qualifiers to its search queries. This is a known limitation documented in Spec Section 9.4 Decision 1.

To improve compliance, the instruction could suggest the LLM add date operators to queries (e.g., "after:2025-01-01"), but this is beyond the scope of WP06 and would be a future enhancement.

## Implementation Sequence Walkthrough

The recommended implementation sequence for a single developer working through this WP:

### Phase 1: Foundation (T06-01, T06-02) - Can be done in parallel

**Step 1a:** Open `newsletter_agent/config/schema.py`. At the top of the file, add the import for `re` and `datetime.date` if not already present. Define the three regex patterns (`_TIMEFRAME_PRESETS`, `_CUSTOM_DAYS_PATTERN`, `_ABSOLUTE_RANGE_PATTERN`) and the `_validate_timeframe()` function. Then define `TimeframeValue = Annotated[str | None, BeforeValidator(_validate_timeframe)]`. Do not yet add the fields to `AppSettings` or `TopicConfig` - that comes in T06-03.

**Step 1b:** Create `newsletter_agent/config/timeframe.py`. Define `ResolvedTimeframe` as a frozen dataclass. Implement `resolve_timeframe()` with the mapping logic for all timeframe categories.

**Step 2:** Write the tests for Phase 1 (T06-09). Run `pytest tests/unit/test_timeframe.py -v` to verify all validation and resolution tests pass. This gives you confidence in the foundation before wiring it into the config models.

### Phase 2: Schema Integration (T06-03)

**Step 3:** In `newsletter_agent/config/schema.py`, add `timeframe: TimeframeValue = None` to both `AppSettings` and `TopicConfig` models. Add `verify_links: bool = False` to `AppSettings`.

**Step 4:** Run `pytest tests/unit/test_config.py -v` to verify existing tests still pass. Then add the new schema tests (T06-10 config portion).

### Phase 3: Prompt & Tool Changes (T06-05, T06-06, T06-07) - Can be done in parallel

**Step 5a:** Modify `get_google_search_instruction()` to accept and use `timeframe_instruction`.

**Step 5b:** Modify `get_perplexity_search_instruction()` to accept and use `timeframe_instruction`.

**Step 5c:** Modify `search_perplexity()` to accept `search_recency_filter` and add the retry logic. Create the `make_perplexity_search_fn()` factory.

**Step 6:** Add the Perplexity search tests (T06-10 perplexity portion). Run all unit tests.

### Phase 4: Config Loading (T06-04)

**Step 7:** Modify `ConfigLoaderAgent._run_async_impl()` to resolve timeframes and store them in session state along with `config_verify_links`.

### Phase 5: Integration (T06-08)

**Step 8:** Modify `build_research_phase()` to wire timeframes into agent construction. This is the final integration point that connects all pieces.

**Step 9:** Run the full test suite. Then write and run the BDD tests (T06-11).

### Phase 6: Verification

**Step 10:** Run the full test suite: `pytest tests/ -v`. Verify all tests pass, including existing tests (backward compatibility). Check that a topics.yaml without any timeframe fields still works correctly by loading the existing config.

## Edge Case Reference Table

| Edge Case | Input | Expected Behavior | Task |
|-----------|-------|-------------------|------|
| Empty string timeframe | `""` | Rejected by validator | T06-01 |
| Whitespace timeframe | `"  "` | Rejected by validator | T06-01 |
| Case mismatch | `"Last_Week"` | Rejected by validator | T06-01 |
| Zero days | `"last_0_days"` | Rejected (X must be 1-365) | T06-01 |
| 366 days | `"last_366_days"` | Rejected (X must be 1-365) | T06-01 |
| Leading zeros in days | `"last_01_days"` | Accepted (int("01") == 1) | T06-01 |
| Feb 29 in non-leap year | `"between 2025-02-29 and ..."` | Rejected (invalid date) | T06-01 |
| Equal start and end | `"between 2025-01-01 and 2025-01-01"` | Rejected (start must be < end) | T06-01 |
| Future end date | `"between 2025-01-01 and 2030-12-31"` | Rejected (end in future) | T06-01 |
| Single day filter | `"last_1_days"` | filter="day", prompt="last day" | T06-02 |
| 7-day boundary | `"last_7_days"` | filter="week" (2<=X<=7) | T06-02 |
| 8-day boundary | `"last_8_days"` | filter="month" (8<=X<=31) | T06-02 |
| 31-day boundary | `"last_31_days"` | filter="month" (8<=X<=31) | T06-02 |
| 32-day boundary | `"last_32_days"` | filter=None (X>31) | T06-02 |
| Absolute range | `"between X and Y"` | filter=None always | T06-02 |
| No timeframe anywhere | omitted | No filtering, identical to current | T06-08 |
| Global only, no overrides | settings.timeframe set | All topics use global | T06-08 |
| Topic override exists | topic.timeframe set | That topic uses override | T06-08 |
| Perplexity API rejects filter | Runtime error | Retry without filter, log warning | T06-07 |
| FunctionTool with closure | Per-topic tool | ADK can invoke the closure | T06-07 |

## Glossary

| Term | Definition |
|------|-----------|
| TimeframeValue | Pydantic annotated type that validates timeframe strings |
| ResolvedTimeframe | Frozen dataclass that holds the resolved provider-specific parameters |
| search_recency_filter | Perplexity API parameter that filters results by recency |
| prompt_date_instruction | Natural language string injected into agent prompts for date context |
| effective timeframe | The timeframe used for a given topic: topic-level override if set, otherwise global default |
| preset | One of the four named timeframe values: last_week, last_2_weeks, last_month, last_year |
| custom days | A timeframe in the format last_X_days where X is 1-365 |
| absolute range | A timeframe in the format between YYYY-MM-DD and YYYY-MM-DD |
| closure approach | Creating a factory function that binds search_recency_filter and wraps the search function |
| instruction approach | Telling the LLM to pass the filter value via the agent instruction text |
| graceful degradation | When Perplexity rejects the filter, retry without it and rely on prompt-based filtering |

## Cross-references to Other Work Packages

### WP07 - Source Link Verification (Parallel Track)

WP06 and WP07 share the `verify_links` field on `AppSettings`, which is introduced in T06-03 of this work package. WP07 reads this field from session state (`config_verify_links`) to decide whether to run link verification after the research phase. The field definition lives in WP06 because it is part of the schema changes needed for both features.

If WP07 starts before WP06, it will need T06-03 to be completed first (specifically the `verify_links` field on `AppSettings` and the `config_verify_links` session state key from T06-04).

### WP08 - Integration Testing and Backward Compatibility (Depends on Both)

WP08 depends on both WP06 and WP07 being complete. It tests the full pipeline with both features enabled simultaneously. WP08 verifies:
- Timeframe filtering + link verification work together
- The full pipeline with all new features produces a valid newsletter
- Backward compatibility: a config with no new fields produces behavior identical to pre-WP06/WP07

### Relationship to Existing WP01-WP05

WP06 builds on the foundation established by WP01-WP05:
- **WP01** (Project Scaffolding): WP06 follows the project structure established here
- **WP02** (Config & Data Model): WP06 extends the schema defined in WP02
- **WP03** (Research Pipeline): WP06 modifies the research agents built in WP03
- **WP04** (Synthesis & Output): WP06 does not modify synthesis or output - those layers are unaffected
- **WP05** (Testing & Quality): WP06 follows the test patterns established in WP05

## Spec Compliance Checklists (Step 2b)

### T06-01 - TimeframeValue Pydantic Validator
- [x] FR-003: All preset values validated (last_week, last_2_weeks, last_month, last_year)
- [x] FR-005: Absolute range validated (start < end, not future, valid dates)
- [x] Custom days validated (1-365 range enforced)
- [x] Invalid values produce descriptive error with valid format listing
- [x] None accepted (no filtering)

### T06-02 - ResolvedTimeframe + resolve_timeframe()
- [x] FR-007: Perplexity filter mapping correct for all presets and custom days
- [x] FR-008: resolve_timeframe returns correct dataclass for all input types
- [x] FR-009: prompt_date_instruction text correct for relative and absolute
- [x] None input returns all-None fields

### T06-03 - Schema Field Additions
- [x] FR-001: settings.timeframe field added to AppSettings
- [x] FR-002: per-topic timeframe field added to TopicConfig
- [x] FR-013: verify_links boolean field added to AppSettings
- [x] Backward compatible - existing configs without new fields still validate

### T06-04 - ConfigLoaderAgent Timeframe Resolution
- [x] FR-027: ConfigLoaderAgent resolves timeframes during config load
- [x] FR-028: config_timeframes and config_verify_links stored in session state
- [x] FR-004: Topic-level timeframe overrides global

### T06-05 - Google Search Instruction Builder
- [x] FR-006: Timeframe instruction injected into Google Search prompt
- [x] FR-009: Prompt text contains natural-language date clause
- [x] FR-011: Instruction added as numbered step in both standard and deep templates
- [x] Backward compatible when timeframe_instruction is None

### T06-06 - Perplexity Instruction Builder
- [x] FR-009: Timeframe instruction injected into Perplexity prompt
- [x] FR-012: Instruction does not interfere with tool-call directive
- [x] Backward compatible when timeframe_instruction is None

### T06-07 - search_perplexity() with search_recency_filter
- [x] FR-007: search_recency_filter passed via extra_body to Perplexity API
- [x] FR-010: Graceful degradation - retry without filter on API rejection
- [x] Backward compatible when search_recency_filter is None

### T06-08 - Wire Timeframe into Research Agent Construction
- [x] FR-006, FR-011, FR-012: Timeframe passed to both instruction builders
- [x] FR-007: perplexity_recency_filter bound to Perplexity tool per topic
- [x] No-timeframe case identical to previous behavior

### T06-09 - Unit Tests: Timeframe Parsing and Resolution
- [x] All 4 presets tested
- [x] Custom days boundary values tested (1, 7, 8, 30, 31, 90, 365)
- [x] Absolute range tested
- [x] Invalid inputs rejected with correct errors
- [x] resolve_timeframe mapping verified for all cases

### T06-10 - Unit Tests: Schema and Perplexity Filter
- [x] AppSettings accepts/rejects timeframe values correctly
- [x] TopicConfig accepts optional timeframe
- [x] Perplexity extra_body passed when filter set
- [x] Retry-without-filter path tested

### T06-11 - BDD Tests: Timeframe Configuration
- [x] All 6 spec scenarios implemented and passing
- [x] Given/When/Then structure consistent with existing BDD patterns

## Spec Section Coverage Map

| Spec Section | Task(s) | Coverage |
|-------------|---------|----------|
| 4.1 FR-001 (timeframe field) | T06-01, T06-03 | Full |
| 4.1 FR-002 (per-topic timeframe) | T06-03 | Full |
| 4.1 FR-003 (validation) | T06-01, T06-09 | Full |
| 4.1 FR-004 (topic override) | T06-04, T06-08 | Full |
| 4.1 FR-005 (absolute range) | T06-01, T06-02 | Full |
| 4.2 FR-006 (prompt injection) | T06-05, T06-06 | Full |
| 4.2 FR-007 (Perplexity filter) | T06-02, T06-07 | Full |
| 4.2 FR-008 (resolve function) | T06-02 | Full |
| 4.2 FR-009 (prompt text) | T06-02, T06-05, T06-06 | Full |
| 4.2 FR-010 (graceful degradation) | T06-07 | Full |
| 4.2 FR-011 (Google instruction) | T06-05, T06-08 | Full |
| 4.2 FR-012 (Perplexity instruction) | T06-06, T06-08 | Full |
| 4.3 FR-013 (verify_links field) | T06-03 | Full |
| 4.4 FR-027 (ConfigLoader timeframe) | T06-04 | Full |
| 4.4 FR-028 (session state keys) | T06-04 | Full |
| 7.1 Data Model | T06-01, T06-02, T06-03 | Full |
| 7.2 Session State | T06-04 | Full |
| 8.1 search_perplexity | T06-07 | Full |
| 8.2 Google instruction | T06-05 | Full |
| 8.3 Perplexity instruction | T06-06 | Full |
| 8.4 resolve_timeframe | T06-02 | Full |
| 9.4 Decision 1 | T06-05 | Acknowledged |
| 10.2 Security | T06-01 | Full |
| 11.1 Unit Tests | T06-09, T06-10 | Full |
| 11.2 BDD Tests | T06-11 | Full |

## Activity Log

- 2026-03-14T00:00:00Z - planner - lane=planned - Work package created
- 2026-03-14T00:00:00Z - planner - lane=planned - Tasks T06-01 through T06-11 defined with acceptance criteria
- 2026-03-14T00:00:00Z - planner - lane=planned - Detailed walkthroughs, test specifications, and edge case tables added
- 2026-03-14T00:00:00Z - planner - lane=planned - Spec coverage map verified: all FR and test sections covered
- 2026-03-14T00:00:00Z - planner - lane=planned - Cross-references to WP07 and WP08 documented
- 2026-03-14T00:00:00Z - planner - lane=planned - Configuration examples added for all timeframe formats
- 2026-03-14T00:00:00Z - planner - lane=planned - Security considerations and backward compatibility section finalized
- 2026-03-14T00:00:00Z - planner - lane=planned - Implementation sequence walkthrough added for developer guidance
- 2026-03-14T00:00:00Z - planner - lane=planned - Ready for implementation by Coder agent
- 2026-03-15T00:00:00Z - coder - lane=doing - Implementation started (T06-01 through T06-11)
- 2026-03-15T01:00:00Z - coder - lane=for_review - All tasks complete, tests passing, submitted for review
- 2026-03-15T02:00:00Z - reviewer - lane=to_do - Verdict: Changes Required (combined review with WP07+WP08)
- 2026-03-15T03:00:00Z - coder - lane=doing - Addressing reviewer feedback (FB-01, FB-02, FB-04)
- 2026-03-15T04:00:00Z - coder - lane=for_review - All feedback items addressed, BDD test created, spec checklists added, resubmitted for review

---

*End of WP06 - Search Timeframe Configuration & Research Integration*
