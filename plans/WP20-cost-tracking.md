---
lane: to_do
review_status: has_feedback
---

# WP20 - Cost Tracking & LLM Instrumentation

> **Spec**: `specs/003-observability-cost-tracing.spec.md`
> **Status**: Not Started
> **Priority**: P1
> **Goal**: Every direct `genai.Client()` LLM call records token counts on OTel spans and accumulates USD cost in a CostTracker; ConfigLoaderAgent initializes pricing
> **Independent Test**: Run the pipeline with 1 topic in dry_run mode. After completion, inspect logs for `pipeline_cost_summary` with `total_cost_usd > 0` and `call_count >= 1`. Verify spans named `llm.generate:gemini-2.5-pro` contain `gen_ai.usage.input_tokens > 0`.
> **Depends on**: WP19
> **Parallelisable**: No
> **Prompt**: `plans/WP20-cost-tracking.md`

## Objective

Implement the cost tracking infrastructure (`cost_tracker.py`) and the LLM call instrumentation helper (`traced_generate()` in `telemetry.py`). Modify the two direct `genai.Client()` call sites (`per_topic_synthesizer.py`, `deep_research_refiner.py`) to use `traced_generate()`, and wire CostTracker initialization into the ConfigLoaderAgent. After this WP, every synthesis and refinement LLM call records token counts as span attributes and accumulates cost in the global CostTracker.

## Spec References

- FR-301 through FR-304 (Token Tracking & Extraction)
- FR-401 through FR-406 (Cost Calculation)
- FR-208 (ConfigLoaderAgent initializes CostTracker)
- Section 4.4 Implementation Contract (cost_tracker.py)
- Section 4.3 Implementation Contract (traced_generate in telemetry.py)
- Section 7.1b, 7.4, 7.5, 7.6 (Data Model: ModelPricing, LlmCallRecord, CostSummary, ModelCostDetail)
- Section 8.2 (cost_tracker.py public interface)
- Section 8.1 (traced_generate interface)
- Section 9.4 Decisions 2, 3, 5
- SC-001, SC-002
- US-01, US-02, US-06, US-07

## Tasks

### T20-01 - Create cost_tracker.py with data model classes

- **Description**: Create `newsletter_agent/cost_tracker.py` with `ModelPricing`, `LlmCallRecord`, `CostSummary`, and `ModelCostDetail` dataclasses per Section 7.1b, 7.4, 7.5, 7.6.
- **Spec refs**: Section 7.1b, 7.4, 7.5, 7.6
- **Parallel**: No (foundation for other tasks)
- **Acceptance criteria**:
  - [ ] `ModelPricing` is a `@dataclass(frozen=True)` with `input_per_million: float` and `output_per_million: float`, both `>= 0.0`
  - [ ] `LlmCallRecord` is a `@dataclass(frozen=True)` with all 13 fields per Section 7.4: model, agent_name, phase, topic_name, topic_index, prompt_tokens, completion_tokens, thinking_tokens, total_tokens, input_cost_usd, output_cost_usd, total_cost_usd, timestamp
  - [ ] `CostSummary` is a `@dataclass` with fields per Section 7.5: total_input_tokens, total_output_tokens, total_thinking_tokens, total_cost_usd, call_count, per_model, per_topic, per_phase
  - [ ] `ModelCostDetail` is a `@dataclass` with fields per Section 7.6: input_tokens, output_tokens, thinking_tokens, cost_usd, call_count
  - [ ] `phase` field on `LlmCallRecord` accepts `"research"`, `"synthesis"`, `"refinement"`, `"unknown"`
- **Test requirements**: unit (T20-08)
- **Depends on**: none
- **Implementation Guidance**:
  - Use stdlib `dataclasses` only - no Pydantic for internal data structures (spec Section 9.4 Decision 3: pure Python, no external deps)
  - `frozen=True` on `ModelPricing` and `LlmCallRecord` ensures immutability
  - `timestamp` format: `datetime.now(timezone.utc).isoformat()` -- generated at record creation time
  - All numeric fields should be non-negative by convention (enforced by CostTracker logic, not dataclass validators)

### T20-02 - Implement CostTracker class

- **Description**: Implement the `CostTracker` class with `record_llm_call()` and `get_summary()` methods per the implementation contract in Section 4.4.
- **Spec refs**: FR-401, FR-402, FR-403, FR-404, FR-405, FR-406, Section 4.4 contract
- **Parallel**: No (depends on T20-01)
- **Acceptance criteria**:
  - [ ] `__init__` accepts `pricing: dict[str, ModelPricing]` and `cost_budget_usd: float | None = None`
  - [ ] Internal state: `_calls: list[LlmCallRecord]`, `_lock: threading.Lock`, `_total_cost: float = 0.0`
  - [ ] `record_llm_call()` is thread-safe using `threading.Lock` (FR-405)
  - [ ] Cost formula: `input_cost = prompt_tokens * input_per_million / 1_000_000`; `output_cost = (completion_tokens + thinking_tokens) * output_per_million / 1_000_000` (FR-401, Decision 5)
  - [ ] Unknown model: logs WARNING with model name, uses zero pricing (`input_per_million=0.0, output_per_million=0.0`) (FR-404)
  - [ ] Budget exceeded: when `cost_budget_usd` is set and `_total_cost > cost_budget_usd`, logs WARNING `"Cost budget exceeded: ${accumulated:.4f} > ${budget:.4f} USD"` (FR-406)
  - [ ] Budget None: no warning regardless of cost (FR-406)
  - [ ] `get_summary()` is thread-safe, aggregates all `_calls` into `CostSummary` with correct per_model, per_topic, per_phase breakdowns
  - [ ] `get_calls()` returns shallow copy of `_calls`
  - [ ] Returns the created `LlmCallRecord` from `record_llm_call()`
- **Test requirements**: unit (T20-08)
- **Depends on**: T20-01
- **Implementation Guidance**:
  - Cost formula from spec Section 4.4:
    ```python
    input_cost = prompt_tokens * pricing.input_per_million / 1_000_000
    output_cost = (completion_tokens + thinking_tokens) * pricing.output_per_million / 1_000_000
    total_cost = input_cost + output_cost
    ```
  - Thread safety: acquire `_lock` in both `record_llm_call()` and `get_summary()`. Use `with self._lock:` context manager.
  - `get_summary()` aggregation: iterate `_calls`, group by model/topic/phase, sum tokens and costs
  - `per_topic` key: use `topic_name` if not None, else `"unknown"`
  - Logging: `logger = logging.getLogger("newsletter_agent.cost_tracker")`
  - Known pitfall: floating-point accumulation. For cost summaries in the $0.01-$1.00 range, float precision is sufficient. No need for `Decimal`.

### T20-03 - Implement module-level init, get, reset functions

- **Description**: Implement `init_cost_tracker()`, `get_cost_tracker()`, and `reset_cost_tracker()` module-level functions in `cost_tracker.py`.
- **Spec refs**: Section 8.2 (public interface), US-07 Scenario 2 (no-op when disabled)
- **Parallel**: No (depends on T20-02)
- **Acceptance criteria**:
  - [ ] `init_cost_tracker(pricing, cost_budget_usd)` creates and stores a module-level `CostTracker` instance
  - [ ] `get_cost_tracker()` returns the active `CostTracker` if initialized
  - [ ] `get_cost_tracker()` returns a no-op `CostTracker` instance (with empty pricing dict or equivalent) when not initialized -- never raises (spec Section 8.2)
  - [ ] `reset_cost_tracker()` sets the module-level tracker to `None` (for test teardown)
  - [ ] No-op tracker silently discards all `record_llm_call()` calls and returns a zero `CostSummary` from `get_summary()`
- **Test requirements**: unit (T20-08, T20-10)
- **Depends on**: T20-02
- **Implementation Guidance**:
  - Module-level pattern matches OTel's own `trace.get_tracer_provider()` approach (Section 9.4 Decision 3)
  - No-op behavior: either create a `CostTracker` with empty pricing dict and handle gracefully, or create a `_NoOpCostTracker` subclass that overrides methods. The simplest approach is to have the default be a `CostTracker({})` which will log warnings on every call -- better to create a sentinel that silently no-ops:
    ```python
    class _NoOpCostTracker:
        def record_llm_call(self, **kwargs) -> LlmCallRecord:
            return LlmCallRecord(model="", agent_name="", phase="unknown", ...)
        def get_summary(self) -> CostSummary:
            return CostSummary(total_input_tokens=0, ...)
        def get_calls(self) -> list[LlmCallRecord]:
            return []
    ```
    Or simply: `_tracker: CostTracker | None = None` and `get_cost_tracker()` returns `_tracker or _NoOpCostTracker()`.

### T20-04 - Implement traced_generate() in telemetry.py

- **Description**: Add the `traced_generate()` async function to `telemetry.py` that wraps `genai.Client().aio.models.generate_content()` with OTel span creation, token extraction, and cost recording.
- **Spec refs**: FR-303, FR-301, FR-402, Section 4.3 contract, Section 8.1
- **Parallel**: No (depends on T20-03 for get_cost_tracker, and WP19 T19-02 for get_tracer)
- **Acceptance criteria**:
  - [ ] Function signature matches spec Section 8.1: `async def traced_generate(model, contents, config, *, agent_name, topic_name, topic_index, phase) -> GenerateContentResponse`
  - [ ] Creates a child span named `"llm.generate:{model}"` under current context
  - [ ] Creates `genai.Client()` internally and calls `await client.aio.models.generate_content(model=model, contents=contents, config=config)`
  - [ ] Extracts token counts from `response.usage_metadata` using `getattr(usage_metadata, field, 0)` pattern (Assumption A1 mitigation)
  - [ ] Sets span attributes per FR-301: `gen_ai.system`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.usage.thinking_tokens`, `gen_ai.usage.total_tokens`
  - [ ] Sets cost attributes per FR-402: `newsletter.cost.input_usd`, `newsletter.cost.output_usd`, `newsletter.cost.total_usd`
  - [ ] Sets context attributes: `newsletter.agent.name`, `newsletter.phase`, and optionally `newsletter.topic.name`, `newsletter.topic.index`
  - [ ] Calls `get_cost_tracker().record_llm_call(...)` with extracted data
  - [ ] If `usage_metadata` is None: logs WARNING `"usage_metadata missing"`, all token counts default to 0 (FR-303 error)
  - [ ] If individual `usage_metadata` field is None: that field defaults to 0
  - [ ] On API exception: sets span status to ERROR, records exception on span, re-raises
  - [ ] When `is_enabled() == False`: calls LLM directly without span creation or cost tracking (User Flow 6.3)
  - [ ] Returns the original `GenerateContentResponse` unchanged
- **Test requirements**: unit (T20-09)
- **Depends on**: T20-03, WP19 T19-02
- **Implementation Guidance**:
  - Official docs for genai: https://ai.google.dev/gemini-api/docs/tokens?lang=python
  - OTel semantic conventions for GenAI: https://opentelemetry.io/docs/specs/semconv/gen-ai/
  - Key pattern:
    ```python
    async def traced_generate(model, contents, config=None, *, agent_name, topic_name=None, topic_index=None, phase):
        if not is_enabled():
            client = genai.Client()
            return await client.aio.models.generate_content(model=model, contents=contents, config=config)
        
        tracer = get_tracer("newsletter_agent.telemetry")
        with tracer.start_as_current_span(f"llm.generate:{model}") as span:
            span.set_attribute("gen_ai.system", "google_genai")
            span.set_attribute("gen_ai.request.model", model)
            # ... set context attributes ...
            try:
                client = genai.Client()
                response = await client.aio.models.generate_content(model=model, contents=contents, config=config)
                # Extract usage_metadata ...
                # Record cost ...
                return response
            except Exception as e:
                span.set_status(StatusCode.ERROR, str(e))
                span.record_exception(e)
                raise
    ```
  - Known pitfall: `tracer.start_as_current_span()` is a context manager that auto-ends the span. Use this pattern for clean span lifecycle.
  - Known pitfall: `genai.Client()` reads `GOOGLE_API_KEY` from env. The function creates a new client each call (matching existing pattern in the codebase).
  - For the unknown pricing model case: `traced_generate` does not need to handle this -- it passes model name to `record_llm_call()` which handles the fallback.

### T20-05 - Modify per_topic_synthesizer.py to use traced_generate()

- **Description**: Replace the direct `genai.Client().aio.models.generate_content()` call in `per_topic_synthesizer.py` with `traced_generate()`.
- **Spec refs**: FR-302 (call site 1: per_topic_synthesizer.py, model gemini-2.5-pro)
- **Parallel**: Yes (independent of T20-06)
- **Acceptance criteria**:
  - [ ] The `_synthesize_topic()` function (or equivalent) uses `from newsletter_agent.telemetry import traced_generate` instead of creating `genai.Client()` directly
  - [ ] The call passes `model="gemini-2.5-pro"` (or the configured model), `agent_name="PerTopicSynthesizer"`, `phase="synthesis"`, `topic_name`, and `topic_index`
  - [ ] The response is used identically to before (no behavioral change)
  - [ ] Existing functionality and error handling preserved
- **Test requirements**: unit (existing tests updated to mock `traced_generate` instead of `genai.Client`)
- **Depends on**: T20-04
- **Implementation Guidance**:
  - Current code pattern (from codebase grep):
    ```python
    client = genai.Client()
    response = await client.aio.models.generate_content(model=..., contents=..., config=...)
    ```
  - Replace with:
    ```python
    from newsletter_agent.telemetry import traced_generate
    response = await traced_generate(model=..., contents=..., config=..., agent_name="PerTopicSynthesizer", phase="synthesis", topic_name=topic_name, topic_index=topic_idx)
    ```
  - Known pitfall: The function needs access to `topic_name` and `topic_index`. Check the function signature and local variables to determine how to pass these. They may come from the iteration context in the synthesizer.
  - Update existing unit test mocks to patch `newsletter_agent.telemetry.traced_generate` instead of `genai.Client`.

### T20-06 - Modify deep_research_refiner.py to use traced_generate()

- **Description**: Replace the direct `genai.Client().aio.models.generate_content()` call in `deep_research_refiner.py` with `traced_generate()`.
- **Spec refs**: FR-302 (call site 2: deep_research_refiner.py, model gemini-2.5-flash)
- **Parallel**: Yes (independent of T20-05)
- **Acceptance criteria**:
  - [ ] The `_call_refinement_llm()` function (or equivalent) uses `traced_generate()` instead of creating `genai.Client()` directly
  - [ ] The call passes `model="gemini-2.5-flash"` (or the configured model), `agent_name="DeepResearchRefiner"`, `phase="refinement"`, `topic_name`, and `topic_index`
  - [ ] The response is used identically to before
  - [ ] Existing functionality and error handling preserved
- **Test requirements**: unit (existing tests updated to mock `traced_generate` instead of `genai.Client`)
- **Depends on**: T20-04
- **Implementation Guidance**:
  - Same pattern as T20-05. Check `deep_research_refiner.py` line ~170 for the call site.
  - The refiner processes multiple topics, so `topic_name` and `topic_index` should be available from the iteration context.
  - Update existing unit test mocks: `@patch("newsletter_agent.tools.deep_research_refiner.traced_generate")` instead of `@patch("newsletter_agent.tools.deep_research_refiner.genai.Client")`.
  - Also update E2E test at `tests/e2e/test_deep_mode_pipeline.py` line ~252 which patches `genai.Client`.

### T20-07 - Modify ConfigLoaderAgent to initialize CostTracker

- **Description**: Add CostTracker initialization to the ConfigLoaderAgent after config parsing, converting `ModelPricingConfig` Pydantic instances to `ModelPricing` frozen dataclass instances.
- **Spec refs**: FR-208
- **Parallel**: No (depends on T20-03 and WP19 T19-03)
- **Acceptance criteria**:
  - [ ] After `ConfigLoaderAgent` parses the config, it calls `init_cost_tracker()` with pricing from `settings.pricing`
  - [ ] Pydantic `ModelPricingConfig` instances are converted to `ModelPricing` frozen dataclass instances before passing to `init_cost_tracker()`
  - [ ] `cost_budget_usd` from `settings.pricing.cost_budget_usd` is passed through
  - [ ] When `OTEL_ENABLED=false`, ConfigLoaderAgent skips CostTracker initialization (the no-op fallback in `get_cost_tracker()` handles subsequent calls)
  - [ ] Existing ConfigLoaderAgent behavior is unchanged
- **Test requirements**: unit, integration (T20-08)
- **Depends on**: T20-03, WP19 T19-03
- **Implementation Guidance**:
  - The ConfigLoaderAgent is in `newsletter_agent/agent.py`. Find where it parses config and add:
    ```python
    from newsletter_agent.telemetry import is_enabled
    from newsletter_agent.cost_tracker import init_cost_tracker, ModelPricing
    
    if is_enabled():
        pricing = {
            name: ModelPricing(
                input_per_million=pc.input_per_million,
                output_per_million=pc.output_per_million,
            )
            for name, pc in settings.pricing.models.items()
        }
        init_cost_tracker(pricing, settings.pricing.cost_budget_usd)
    ```
  - Known pitfall: The ConfigLoaderAgent runs early in the pipeline (first agent). CostTracker must be initialized before any LLM calls happen. This is guaranteed because synthesis and refinement run after research.

### T20-08 - Unit tests for CostTracker

- **Description**: Create `tests/test_cost_tracker.py` with comprehensive unit tests per Section 11.1.
- **Spec refs**: Section 11.1 (test_cost_tracker.py requirements), FR-401, FR-404, FR-405, FR-406
- **Parallel**: Yes (can be started once T20-03 is done)
- **Acceptance criteria**:
  - [ ] Test: `record_llm_call()` calculates correct cost for known model (FR-401). Given gemini-2.5-pro pricing (1.25/10.00) and 10000 prompt + 2000 completion + 500 thinking tokens: `input_cost = 0.0125`, `output_cost = 0.025`, `total_cost = 0.0375`
  - [ ] Test: `record_llm_call()` uses zero cost for unknown model and logs WARNING (FR-404)
  - [ ] Test: `get_summary()` aggregates per_model, per_topic, per_phase correctly with multiple calls
  - [ ] Test: `record_llm_call()` is thread-safe -- concurrent calls from 10 threads produce correct total (FR-405)
  - [ ] Test: Cost budget exceeded triggers WARNING log (FR-406)
  - [ ] Test: Cost budget None means no warning regardless of cost
  - [ ] Test: `get_cost_tracker()` returns no-op when not initialized
  - [ ] Test: `reset_cost_tracker()` clears global state
  - [ ] Test: No-op tracker returns zero `CostSummary`
  - [ ] Test: `get_calls()` returns a list matching all recorded calls
  - [ ] Minimum 80% code, 90% branch coverage for `cost_tracker.py`
- **Test requirements**: unit (pytest)
- **Depends on**: T20-03
- **Implementation Guidance**:
  - Thread safety test pattern:
    ```python
    import threading
    tracker = CostTracker(pricing={...})
    threads = [threading.Thread(target=tracker.record_llm_call, kwargs={...}) for _ in range(10)]
    for t in threads: t.start()
    for t in threads: t.join()
    summary = tracker.get_summary()
    assert summary.call_count == 10
    ```
  - Use `caplog` fixture to assert WARNING log messages
  - Use `reset_cost_tracker()` in test teardown fixture
  - Budget exceeded test: create tracker with `cost_budget_usd=0.01`, record a call that costs $0.02, assert WARNING in caplog

### T20-09 - Unit tests for traced_generate()

- **Description**: Add traced_generate tests to `tests/test_telemetry.py` (extending from WP19's T19-07).
- **Spec refs**: Section 11.1 (test_telemetry.py requirements for traced_generate), FR-303
- **Parallel**: No (depends on T20-04)
- **Acceptance criteria**:
  - [ ] Test: `traced_generate()` creates a span named `"llm.generate:{model}"` with correct attributes (mock genai.Client)
  - [ ] Test: `traced_generate()` extracts usage_metadata and sets gen_ai.usage.* span attributes
  - [ ] Test: `traced_generate()` handles missing `usage_metadata` (None) -- tokens default to 0, WARNING logged
  - [ ] Test: `traced_generate()` handles individual missing usage_metadata fields -- that field defaults to 0
  - [ ] Test: `traced_generate()` records cost in CostTracker via `record_llm_call()`
  - [ ] Test: `traced_generate()` re-raises API exceptions after recording on span (span status = ERROR)
  - [ ] Test: `traced_generate()` when `is_enabled() == False` still calls LLM and returns response (no span)
  - [ ] Test: `traced_generate()` sets `newsletter.cost.pricing_missing: true` when model not in pricing config
  - [ ] All tests use mocked genai.Client -- no real API calls
- **Test requirements**: unit (pytest, pytest-asyncio)
- **Depends on**: T20-04
- **Implementation Guidance**:
  - Use `InMemorySpanExporter` to capture and assert spans:
    ```python
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    exporter = InMemorySpanExporter()
    # ... configure TracerProvider with SimpleSpanProcessor(exporter) ...
    # ... call traced_generate() ...
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "llm.generate:gemini-2.5-pro"
    ```
  - Mock genai.Client:
    ```python
    mock_response = MagicMock()
    mock_response.usage_metadata.prompt_token_count = 1000
    mock_response.usage_metadata.candidates_token_count = 500
    mock_response.usage_metadata.thoughts_token_count = 200
    mock_response.usage_metadata.total_token_count = 1700
    with patch("newsletter_agent.telemetry.genai.Client") as mock_client:
        mock_client.return_value.aio.models.generate_content = AsyncMock(return_value=mock_response)
        result = await traced_generate(model="gemini-2.5-pro", contents="test", agent_name="test", phase="synthesis")
    ```
  - Each test needs cost_tracker initialized for cost recording. Use `init_cost_tracker()` in setup and `reset_cost_tracker()` in teardown.

### T20-10 - Unit tests for no-op CostTracker behavior when disabled

- **Description**: Test that when telemetry is disabled or CostTracker is not initialized, the system behaves correctly without errors.
- **Spec refs**: US-07 Scenario 2, Section 8.2
- **Parallel**: Yes (depends on T20-03)
- **Acceptance criteria**:
  - [ ] Test: When `init_cost_tracker()` has not been called, `get_cost_tracker()` returns a no-op instance
  - [ ] Test: No-op tracker's `record_llm_call()` does not raise and returns a valid (zeroed) `LlmCallRecord`
  - [ ] Test: No-op tracker's `get_summary()` returns a `CostSummary` with all zeros
  - [ ] Test: No-op tracker's `get_calls()` returns an empty list
  - [ ] Test: After `reset_cost_tracker()`, `get_cost_tracker()` returns no-op
- **Test requirements**: unit (pytest)
- **Depends on**: T20-03
- **Implementation Guidance**:
  - Ensure `reset_cost_tracker()` is called before each test in this group
  - Verify no warnings are logged by no-op operations (they should be truly silent)

## Implementation Notes

- **Execution order**: T20-01 -> T20-02 -> T20-03 -> T20-04 -> T20-05 + T20-06 (parallel) + T20-07 -> T20-08 + T20-09 + T20-10 (parallel)
- **Key files created**: `newsletter_agent/cost_tracker.py`, `tests/test_cost_tracker.py`
- **Key files modified**: `newsletter_agent/telemetry.py` (add traced_generate), `newsletter_agent/tools/per_topic_synthesizer.py`, `newsletter_agent/tools/deep_research_refiner.py`, `newsletter_agent/agent.py` (ConfigLoaderAgent)
- **Test files modified**: `tests/test_telemetry.py` (add traced_generate tests), existing unit tests for synthesizer and refiner (update mocks)
- **Existing test updates**: Tests that mock `genai.Client` in synthesizer/refiner must be updated to mock `traced_generate` instead. This includes `tests/e2e/test_deep_mode_pipeline.py`.

## Parallel Opportunities

- T20-05 (synthesizer mod) and T20-06 (refiner mod) are independent call-site changes [P]
- T20-08 (cost tracker tests), T20-09 (traced_generate tests), and T20-10 (no-op tests) are independent test tasks [P]

## Risks & Mitigations

- **Risk**: `usage_metadata` field names differ from spec assumptions (A1). **Mitigation**: Use `getattr(usage_metadata, field, 0)` with WARNING log. Verify with one real API call.
- **Risk**: Mocking genai.Client in tests is fragile. **Mitigation**: Use `unittest.mock.AsyncMock` for async generate_content. Keep mock setup in shared fixtures.
- **Risk**: Thread-safety test is flaky. **Mitigation**: Use sufficient iterations (10+ threads) and verify exact counts rather than ranges.
- **Risk**: `thoughts_token_count` may be included in `candidates_token_count` (OQ-1 in spec). **Mitigation**: Implementer must verify with one real API call. If so, adjust formula to avoid double-counting.

## Activity Log

- 2025-07-18T00:00:00Z - planner - lane=planned - Work package created
- 2026-03-21T12:00:00Z - reviewer - lane=to_do - Verdict: Changes Required (3 FAILs) -- awaiting remediation

## Review

> **Reviewed by**: Reviewer Agent
> **Date**: 2026-03-21
> **Verdict**: Changes Required
> **review_status**: has_feedback

### Summary

Changes Required. Three FAIL findings block approval: (1) missing `newsletter.cost.pricing_missing` span attribute required by FR-404, (2) `CostSummary.per_topic` and `per_phase` deviate from spec data types, and (3) Spec Compliance Checklist (Step 2b) was not completed and no commits exist for WP20. Documentation does not mention `cost_tracker.py`, `traced_generate()`, or `CostTracker` in architecture, API reference, or developer guide. All functional tests pass with 99.6% coverage.

### Review Feedback

> Implementers: if `review_status: has_feedback` is set in the WP frontmatter, address every item below before returning for re-review. Update `review_status: acknowledged` once you begin remediation.

- [ ] **FB-01**: `traced_generate()` in [telemetry.py](newsletter_agent/telemetry.py) does not set `newsletter.cost.pricing_missing: true` span attribute when the model is not in the pricing config (FR-404). The `CostTracker.record_llm_call()` correctly warns and zero-prices, but the return value is not checked by `traced_generate()` to detect unknown-model cases. Add logic: if the model is not in the tracker's pricing dict, set `span.set_attribute("newsletter.cost.pricing_missing", True)`. Add a test for this case.
- [ ] **FB-02**: `CostSummary.per_topic` is typed `dict[str, ModelCostDetail]` but spec Section 7.5 defines it as `dict[str, float]` (topic_name -> cost_usd). Same for `per_phase`. Either align with the spec contract (use `dict[str, float]`) or document the deviation as a deliberate enhancement. Current tests and aggregation code use `ModelCostDetail` consistently, so if keeping `ModelCostDetail`, update the spec or add a clear comment.
- [ ] **FB-03**: No Spec Compliance Checklist (Step 2b) exists in the WP file for any task. No Activity Log entries exist for coder lane transitions. No git commits exist for any WP20 task. Add the Spec Compliance Checklist per task, update the activity log, and commit per task.
- [ ] **FB-04**: Documentation files do not mention `cost_tracker.py`, `traced_generate()`, or `CostTracker`. Update [architecture.md](docs/architecture.md) (add cost tracking subsection under Telemetry), [api-reference.md](docs/api-reference.md) (add cost_tracker.py public API), and [developer-guide.md](docs/developer-guide.md) (add `cost_tracker.py` to project structure listing).

### Findings

#### FAIL - Process Compliance
- **Requirement**: Step 2b Spec Compliance Checklist
- **Status**: Missing
- **Detail**: No Spec Compliance Checklist exists for any of T20-01 through T20-10. No Activity Log entries from coder. No git commits for WP20 implementation — all changes are uncommitted in working tree.
- **Evidence**: `plans/WP20-cost-tracking.md` Activity Log has only the planner entry. `git log` shows no WP20 commits.

#### PASS - Spec Adherence (FR-401: Cost calculation formula)
- **Requirement**: FR-401
- **Status**: Compliant
- **Detail**: Cost formula exactly matches spec: `input_cost = prompt_tokens * input_per_million / 1_000_000; output_cost = (completion_tokens + thinking_tokens) * output_per_million / 1_000_000`.
- **Evidence**: [cost_tracker.py](newsletter_agent/cost_tracker.py#L113-L118), verified by `test_correct_cost_for_known_model` with exact values ($0.0125, $0.025, $0.0375).

#### PASS - Spec Adherence (FR-402: Cost span attributes)
- **Requirement**: FR-402
- **Status**: Compliant
- **Detail**: `traced_generate()` sets `newsletter.cost.input_usd`, `newsletter.cost.output_usd`, `newsletter.cost.total_usd` on span.
- **Evidence**: [telemetry.py](newsletter_agent/telemetry.py#L228-L230), verified by `test_sets_cost_attributes`.

#### PASS - Spec Adherence (FR-403: Default pricing)
- **Requirement**: FR-403
- **Status**: Compliant
- **Detail**: `PricingConfig` in schema.py provides default pricing matching spec: Flash 0.30/2.50, Pro 1.25/10.00.
- **Evidence**: `newsletter_agent/config/schema.py` PricingConfig default_factory.

#### FAIL - Spec Adherence (FR-404: pricing_missing attribute)
- **Requirement**: FR-404
- **Status**: Partial
- **Detail**: Unknown model gets zero pricing and WARNING log (compliant), but span attribute `newsletter.cost.pricing_missing: true` is never set. Spec says "The span SHALL include attribute `newsletter.cost.pricing_missing: true`". No test exists for this span attribute.
- **Evidence**: `traced_generate()` in [telemetry.py](newsletter_agent/telemetry.py#L215-L230) does not set this attribute. `grep` for `pricing_missing` returns zero matches in implementation and test files.

#### PASS - Spec Adherence (FR-405: Thread safety)
- **Requirement**: FR-405
- **Status**: Compliant
- **Detail**: `CostTracker` uses `threading.Lock` in `record_llm_call()` and `get_summary()`. Thread safety verified by 10-thread concurrent test.
- **Evidence**: [cost_tracker.py](newsletter_agent/cost_tracker.py#L137-L149), `test_concurrent_calls_produce_correct_count`, `test_concurrent_cost_accumulation`.

#### PASS - Spec Adherence (FR-406: Budget warning)
- **Requirement**: FR-406
- **Status**: Compliant
- **Detail**: Budget exceeded logs WARNING with correct format. Budget None produces no warning.
- **Evidence**: [cost_tracker.py](newsletter_agent/cost_tracker.py#L141-L148), `test_budget_exceeded_logs_warning`, `test_budget_none_no_warning`.

#### PASS - Spec Adherence (FR-301: Token extraction)
- **Requirement**: FR-301
- **Status**: Compliant
- **Detail**: `traced_generate()` extracts `prompt_token_count`, `candidates_token_count`, `thoughts_token_count` from `usage_metadata` using `getattr(..., 0) or 0` pattern. Sets all `gen_ai.usage.*` span attributes.
- **Evidence**: [telemetry.py](newsletter_agent/telemetry.py#L199-L213), `test_sets_span_attributes`.

#### PASS - Spec Adherence (FR-303: Missing usage_metadata)
- **Requirement**: FR-303
- **Status**: Compliant
- **Detail**: When `usage_metadata` is None, logs WARNING, tokens default to 0. Individual None fields also default to 0.
- **Evidence**: `test_missing_usage_metadata`, `test_individual_missing_fields_default_to_zero`.

#### PASS - Spec Adherence (FR-302: Call site instrumentation)
- **Requirement**: FR-302
- **Status**: Compliant
- **Detail**: Both `per_topic_synthesizer.py` and `deep_research_refiner.py` use `traced_generate()` instead of direct `genai.Client()` calls. Agent names and phases match spec.
- **Evidence**: [per_topic_synthesizer.py](newsletter_agent/tools/per_topic_synthesizer.py#L168-L178), [deep_research_refiner.py](newsletter_agent/tools/deep_research_refiner.py#L171-L180).

#### PASS - Spec Adherence (FR-208: ConfigLoaderAgent CostTracker init)
- **Requirement**: FR-208
- **Status**: Compliant
- **Detail**: ConfigLoaderAgent calls `init_cost_tracker()` with pricing converted from Pydantic `ModelPricingConfig` to frozen dataclass `ModelPricing`, passing `cost_budget_usd`. Skips when `is_enabled()` is False.
- **Evidence**: [agent.py](newsletter_agent/agent.py#L200-L212).

#### WARN - Spec Adherence (Section 8.2: get_cost_tracker behavior)
- **Requirement**: Section 8.2 / Section 4.4 contract
- **Status**: Deviating (deliberate)
- **Detail**: Spec contract says `get_cost_tracker()` "Raises RuntimeError if not initialized". Implementation returns a `_NoOpCostTracker` instance instead, which is documented in the WP plan (T20-03) as the preferred approach aligning with US-07 Scenario 2. This is a deliberate improvement over the spec.
- **Evidence**: [cost_tracker.py](newsletter_agent/cost_tracker.py#L253-L255), WP plan T20-03 acceptance criteria.

#### FAIL - Data Model Adherence (Section 7.5: CostSummary types)
- **Requirement**: Section 7.5
- **Status**: Deviating
- **Detail**: `CostSummary.per_topic` is `dict[str, ModelCostDetail]` but spec says `dict[str, float]` (topic_name -> cost_usd). Same for `per_phase`: implementation is `dict[str, ModelCostDetail]`, spec says `dict[str, float]`. This provides more data than the spec requires but breaks the defined contract.
- **Evidence**: [cost_tracker.py](newsletter_agent/cost_tracker.py#L72-L73) vs spec Section 7.5.

#### PASS - API / Interface Adherence (Section 8.1: traced_generate)
- **Requirement**: Section 8.1
- **Status**: Compliant
- **Detail**: Function signature matches spec: `async def traced_generate(model, contents, config=None, *, agent_name, topic_name=None, topic_index=None, phase)`. Returns response unchanged. Handles errors correctly.
- **Evidence**: [telemetry.py](newsletter_agent/telemetry.py#L151-L162).

#### WARN - API / Interface Adherence (Section 4.4: record_llm_call signature)
- **Requirement**: Section 4.4 contract
- **Status**: Deviating (minor)
- **Detail**: Spec contract shows `record_llm_call(self, model, prompt_tokens, completion_tokens, thinking_tokens, agent_name, phase, ...)` with positional parameters. Implementation uses keyword-only (`*,`). Functionally equivalent and arguably safer, but deviates from the contract.
- **Evidence**: [cost_tracker.py](newsletter_agent/cost_tracker.py#L101-L110).

#### PASS - Architecture Adherence
- **Requirement**: Section 9.4 Decisions 2, 3, 5
- **Status**: Compliant
- **Detail**: Uses stdlib `dataclasses` for internal structures (Decision 3). Module-level init/get/reset pattern matches OTel approach (Decision 3). Cost formula includes thinking tokens at output rate (Decision 5). `genai.Client()` created inside `traced_generate()` matching existing pattern (Decision 2).
- **Evidence**: [cost_tracker.py](newsletter_agent/cost_tracker.py), [telemetry.py](newsletter_agent/telemetry.py#L191).

#### PASS - Test Coverage Adherence
- **Requirement**: Section 11.1, T20-08, T20-09, T20-10
- **Status**: Compliant
- **Detail**: All required tests implemented: cost calculation (FR-401), unknown model (FR-404), summary aggregation, thread safety (FR-405), budget warnings (FR-406), traced_generate span attributes, missing usage_metadata (FR-303), API exceptions, disabled mode, no-op tracker. All 62 tests pass.
- **Evidence**: `pytest` output shows 62 passed. Coverage: `cost_tracker.py` 100%, `telemetry.py` 99%.

#### PASS - Non-Functional: Security
- **Requirement**: Section 10
- **Status**: Compliant
- **Detail**: No secrets in code. No SQL injection, XSS, or CSRF vectors. API key read from environment by `genai.Client()` internally, not exposed. No user input handling in cost tracking code.

#### PASS - Performance
- **Requirement**: Section 10
- **Status**: Compliant
- **Detail**: No N+1 patterns, no unbounded fetching. `threading.Lock` scope is minimal (only around list append and cost accumulation). No synchronous blocking in async path except the lock (acceptable for in-memory list operations).

#### WARN - Documentation Accuracy
- **Requirement**: docs/ accuracy
- **Status**: Partial
- **Detail**: The configuration guide correctly documents the `pricing` section. However, `cost_tracker.py` is not listed in the developer guide project structure, `traced_generate()` is not mentioned in architecture or API reference docs, and the architecture telemetry section only describes init/shutdown/get_tracer/is_enabled but omits `traced_generate()` and cost tracking.
- **Evidence**: `grep` for `cost_tracker` and `traced_generate` in `docs/` returns zero matches.

#### PASS - Success Criteria (SC-001)
- **Requirement**: SC-001
- **Status**: Verifiable
- **Detail**: SC-001 requires that every `genai.Client()` call records token counts as span attributes and accumulates in cost tracker. Unit tests `test_sets_span_attributes` and `test_records_cost_in_tracker` verify this with mock LLM calls.
- **Evidence**: Tests in [test_telemetry.py](tests/unit/test_telemetry.py#L307-L370).

#### PASS - Coverage Thresholds
- **Requirement**: 80% code, 90% branch
- **Status**: Compliant
- **Detail**: `cost_tracker.py` has 100% statement and 100% branch coverage. `telemetry.py` has 99% coverage with 1 partial branch (line 91->90, an innocuous edge).
- **Evidence**: `pytest --cov` output: 99.6% total, 100%/99%.

#### PASS - Scope Discipline
- **Requirement**: No scope creep
- **Status**: Compliant
- **Detail**: WP20 files match the plan exactly: `cost_tracker.py` (new), `telemetry.py` (traced_generate added), `per_topic_synthesizer.py` (call site), `deep_research_refiner.py` (call site), `agent.py` (ConfigLoaderAgent init), corresponding test files. No unspecified features or abstractions added. The `_NoOpCostTracker` is specified in the WP plan T20-03.

#### PASS - Encoding (UTF-8)
- **Requirement**: No em dashes, smart quotes, curly apostrophes
- **Status**: Compliant
- **Detail**: All WP20-created/modified files checked for UTF-8 violations. None found.
- **Evidence**: PowerShell regex check on 4 core implementation/test files returned all OK.

### Statistics
| Dimension | Pass | Warn | Fail |
|-----------|------|------|------|
| Process Compliance | 0 | 0 | 1 |
| Spec Adherence | 8 | 1 | 1 |
| Data Model | 0 | 0 | 1 |
| API / Interface | 1 | 1 | 0 |
| Architecture | 1 | 0 | 0 |
| Test Coverage | 1 | 0 | 0 |
| Non-Functional | 1 | 0 | 0 |
| Performance | 1 | 0 | 0 |
| Documentation | 0 | 1 | 0 |
| Success Criteria | 1 | 0 | 0 |
| Coverage Thresholds | 1 | 0 | 0 |
| Scope Discipline | 1 | 0 | 0 |
| Encoding (UTF-8) | 1 | 0 | 0 |

### Recommended Actions

1. **(FB-01)** Add `newsletter.cost.pricing_missing: true` span attribute in `traced_generate()` when the model is not in the CostTracker's pricing config. Add a corresponding test. This requires either exposing pricing info from the tracker or checking pricing before calling `record_llm_call()`.
2. **(FB-02)** Align `CostSummary.per_topic` and `per_phase` types with spec Section 7.5 (`dict[str, float]`), or document the deviation in the WP plan as a deliberate enhancement and add a comment in code.
3. **(FB-03)** Add Spec Compliance Checklists for all tasks (T20-01 through T20-10), update the Activity Log with coder lane transitions, and commit WP20 changes with per-task granularity.
4. **(FB-04)** Update documentation: add `cost_tracker.py` to developer guide project structure, add cost tracking subsection to architecture.md telemetry section, add `cost_tracker.py` and `traced_generate()` public API to api-reference.md.
