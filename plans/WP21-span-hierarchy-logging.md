---
lane: planned
---

# WP21 - Agent Span Hierarchy & Log Correlation

> **Spec**: `specs/003-observability-cost-tracing.spec.md`
> **Status**: Not Started
> **Priority**: P1
> **Goal**: Every agent execution creates an OTel span with correct parent-child hierarchy; logs include trace_id/span_id; cost summary is logged and recorded as span event on pipeline completion
> **Independent Test**: Run the pipeline with 1 topic. Verify ConsoleSpanExporter output shows spans with parent-child relationships: `NewsletterPipeline` > `ResearchPhase` > `Topic0Research`. Verify log lines contain `trace=` with a 32-char hex value.
> **Depends on**: WP19, WP20
> **Parallelisable**: No
> **Prompt**: `plans/WP21-span-hierarchy-logging.md`

## Objective

Modify `timing.py` to create OTel spans in the existing ADK `before_agent_callback`/`after_agent_callback`, producing a structured span hierarchy that mirrors the agent execution tree. Add root agent and topic-scoped span attributes. Log the cost summary at pipeline completion and record it as a span event. Add `TraceContextFilter` to `logging_config.py` so every log line includes trace_id and span_id for correlation.

## Spec References

- FR-201 through FR-208 (Span Hierarchy & Agent Instrumentation)
- FR-304 (LlmAgent tokens_available attribute)
- FR-501 through FR-504 (Cost Summary & Reporting)
- FR-701 through FR-704 (Logging Integration)
- Section 4.2 Implementation Contract (modified timing.py)
- Section 4.5 (Cost Summary format)
- Section 8.3 (timing.py callback signatures)
- Section 8.4 (TraceContextFilter)
- Section 7.7 (OTel Span Attributes Schema)
- SC-003, SC-005
- US-03, US-04

## Tasks

### T21-01 - Modify before_agent_callback to create OTel spans

- **Description**: Enhance `before_agent_callback` in `newsletter_agent/timing.py` to create an OTel span for each agent execution, attach it to the context, and store the span reference for later retrieval.
- **Spec refs**: FR-201, FR-204, Section 4.2 contract (before_agent_callback new behavior)
- **Parallel**: No (foundation for other timing tasks)
- **Acceptance criteria**:
  - [ ] `before_agent_callback` creates an OTel span with `name=callback_context.agent_name` using `get_tracer("newsletter_agent.timing")` (FR-201)
  - [ ] Span has attributes `newsletter.agent.name` (str) and `newsletter.invocation_id` (str) (FR-201)
  - [ ] The span is attached to the OTel context via `context.attach(trace.set_span_in_context(span))` (FR-202)
  - [ ] The (span, token) tuple is stored in `_active_spans[key]` dict, keyed by `"{invocation_id}:{agent_name}"` (FR-204)
  - [ ] When `is_enabled() == False`, span creation is skipped entirely -- only existing timing behavior runs
  - [ ] Existing behavior preserved: start time recording, pipeline_start_time in state, log messages (FR-207)
  - [ ] Module-level `_active_spans: dict[str, tuple[Span, Token]]` added alongside existing `_phase_starts`
- **Test requirements**: unit (T21-09)
- **Depends on**: WP19 (get_tracer, is_enabled), none within WP21
- **Implementation Guidance**:
  - Key imports to add to timing.py:
    ```python
    from opentelemetry import context, trace
    from newsletter_agent.telemetry import get_tracer, is_enabled
    ```
  - Pattern for span creation and context attachment:
    ```python
    tracer = get_tracer("newsletter_agent.timing")
    span = tracer.start_span(name=callback_context.agent_name)
    span.set_attribute("newsletter.agent.name", callback_context.agent_name)
    span.set_attribute("newsletter.invocation_id", callback_context.invocation_id)
    token = context.attach(trace.set_span_in_context(span))
    _active_spans[key] = (span, token)
    ```
  - Use `tracer.start_span()` (not `start_as_current_span`) because we need manual control over span lifecycle across two callbacks.
  - Known pitfall: `context.attach()` returns a token that MUST be passed to `context.detach()` in after_callback. Store it alongside the span.
  - Known pitfall: Python 3.11+ copies context to new asyncio tasks automatically, enabling correct parent-child spans in ParallelAgent (Assumption A3).

### T21-02 - Modify after_agent_callback to end spans and detach context

- **Description**: Enhance `after_agent_callback` to end the OTel span, set duration, and detach the context token.
- **Spec refs**: FR-203, FR-204, Section 4.2 contract (after_agent_callback new behavior)
- **Parallel**: No (depends on T21-01)
- **Acceptance criteria**:
  - [ ] `after_agent_callback` pops `(span, token)` from `_active_spans[key]` (FR-204)
  - [ ] Sets `newsletter.duration_seconds` float attribute on the span (FR-203)
  - [ ] Calls `span.end()` to close the span
  - [ ] Calls `context.detach(token)` to restore parent context (FR-202)
  - [ ] If key not found in `_active_spans` (span not found): logs WARNING, skips span operations (FR-204 error)
  - [ ] Existing behavior preserved: timing calculation, logging, metadata setting (FR-207)
  - [ ] When `is_enabled() == False`, span operations are skipped
- **Test requirements**: unit (T21-09)
- **Depends on**: T21-01
- **Implementation Guidance**:
  - Pattern:
    ```python
    if is_enabled():
        span_data = _active_spans.pop(key, None)
        if span_data is not None:
            span, token = span_data
            span.set_attribute("newsletter.duration_seconds", elapsed)
            span.end()
            context.detach(token)
        else:
            logger.warning("Span not found for key %s", key)
    ```
  - The `elapsed` time is already computed from `_phase_starts` -- reuse the same value
  - Known pitfall: Always call `context.detach()` even if span operations fail. Use try/finally if needed.

### T21-03 - Implement root agent span attributes

- **Description**: When the agent is the root `NewsletterPipeline`, set additional span attributes.
- **Spec refs**: FR-205, Section 7.7 (Root Agent Span Attributes)
- **Parallel**: Yes (independent of T21-04, T21-05)
- **Acceptance criteria**:
  - [ ] Root agent span has `newsletter.topic_count` (int) from `state["config_topic_count"]` or equivalent
  - [ ] Root agent span has `newsletter.dry_run` (bool) from `state["config_dry_run"]` or equivalent
  - [ ] Root agent span has `newsletter.pipeline_start_time` (str, ISO 8601)
  - [ ] Attributes are set in `before_agent_callback` when `agent_name == _ROOT_AGENT_NAME`
  - [ ] If state keys are not yet populated (ConfigLoader hasn't run), attributes are omitted gracefully
- **Test requirements**: unit (T21-09)
- **Depends on**: T21-01
- **Implementation Guidance**:
  - Check how the existing codebase stores topic count and dry_run in session state. These may be set by ConfigLoaderAgent.
  - State key names to check: `config_topic_count`, `config_dry_run`, or derive from `state` dict
  - If topic count isn't in state at root agent start (ConfigLoader runs as first child), set it in after_callback instead, or use a sentinel.
  - `pipeline_start_time`: use `datetime.now(timezone.utc).isoformat()` (already computed for `state["pipeline_start_time"]`)
  - Known pitfall: Root agent's before_callback fires before ConfigLoader runs, so dependent state values may not exist yet. Consider setting `topic_count` and `dry_run` in after_callback (when they are available) instead of before_callback. Check timing.

### T21-04 - Implement topic-scoped agent span attributes

- **Description**: For agents whose name contains a topic index, parse and set topic-related span attributes.
- **Spec refs**: FR-206, Section 7.7 (Topic-Scoped Agent Span Attributes)
- **Parallel**: Yes (independent of T21-03, T21-05)
- **Acceptance criteria**:
  - [ ] Agent name is parsed with regex `r'_(\d+)(?:_|$)'` to extract topic index (FR-206)
  - [ ] If match found: sets `newsletter.topic.index` (int) on span
  - [ ] If match found and topic names are available in state: sets `newsletter.topic.name` (str)
  - [ ] If no regex match: attributes are omitted (no error)
  - [ ] Regex correctly matches: `GoogleSearcher_0`, `DeepResearch_2_google`, `Topic3Research`
- **Test requirements**: unit (T21-09)
- **Depends on**: T21-01
- **Implementation Guidance**:
  - Regex: `re.search(r'_(\d+)(?:_|$)', agent_name)`. First captured group is the index.
  - Topic name lookup: check `state` for a list of topic names. The config stores topics in state, likely accessible via `state["config_topics"]` or similar. Parse index as `int(match.group(1))` and index into the topics list.
  - Known pitfall: Topic index may be out of range if the regex matches something unexpected. Guard with `try/except IndexError` or bounds check.
  - Set attributes in `before_agent_callback` alongside the base attributes.

### T21-05 - Add gen_ai.tokens_available attribute for LlmAgent spans

- **Description**: For agents that are LlmAgent-based (where token tracking is not available in P1), set a marker attribute.
- **Spec refs**: FR-304, Section 7.7 (LlmAgent Span Attributes)
- **Parallel**: Yes (independent of T21-03, T21-04)
- **Acceptance criteria**:
  - [ ] Spans for LlmAgent-based agents include `gen_ai.tokens_available: false`
  - [ ] LlmAgent-based agents include: `GoogleSearcher_*`, `PerplexitySearcher_*`, `AdaptivePlanner_*`, `DeepSearchRound_*`, `AdaptiveAnalyzer_*`
  - [ ] Non-LlmAgent agents (BaseAgent subclasses) do NOT get this attribute
  - [ ] Detection is by agent name pattern (not introspection)
- **Test requirements**: unit (T21-09)
- **Depends on**: T21-01
- **Implementation Guidance**:
  - Use a set of known LlmAgent name prefixes:
    ```python
    _LLMAGENT_PREFIXES = {"GoogleSearcher", "PerplexitySearcher", "AdaptivePlanner", "DeepSearchRound", "AdaptiveAnalyzer"}
    ```
  - Check if `agent_name` starts with any prefix: `any(agent_name.startswith(p) for p in _LLMAGENT_PREFIXES)`
  - Set in `before_agent_callback`:
    ```python
    if any(agent_name.startswith(p) for p in _LLMAGENT_PREFIXES):
        span.set_attribute("gen_ai.tokens_available", False)
    ```
  - This is an informational attribute for trace viewers to know that token data is absent due to P1 limitations.

### T21-06 - Implement cost summary logging and span events at pipeline end

- **Description**: At pipeline completion (root agent's after_callback), log the structured cost summary and record it as a span event.
- **Spec refs**: FR-501, FR-502, FR-503, FR-504, Section 4.5
- **Parallel**: No (depends on T21-02, WP20 CostTracker)
- **Acceptance criteria**:
  - [ ] When root agent completes and telemetry is enabled: calls `get_cost_tracker().get_summary()` to get the cost data
  - [ ] Logs cost summary at INFO level as structured JSON with `"event": "pipeline_cost_summary"` and all fields from FR-501 (total_cost_usd, total_input_tokens, total_output_tokens, total_thinking_tokens, call_count, per_model, per_topic, per_phase)
  - [ ] Records span event named `"cost_summary"` on the root span with attributes: `total_cost_usd`, `total_input_tokens`, `total_output_tokens`, `call_count` (FR-502)
  - [ ] Sets `state["run_cost_usd"]` (float) in session state (FR-503)
  - [ ] Sets `state["cost_summary"]` (dict) in session state with full CostSummary as dict (FR-504)
  - [ ] When telemetry is disabled or CostTracker returns zero summary: still logs (with zeros) but does not error
  - [ ] Cost summary logging does not prevent span from being ended
- **Test requirements**: unit (T21-09), integration (WP22)
- **Depends on**: T21-02, WP20 T20-03 (get_cost_tracker)
- **Implementation Guidance**:
  - In `after_agent_callback`, after duration calculation for root agent:
    ```python
    if is_enabled() and agent_name == _ROOT_AGENT_NAME:
        from newsletter_agent.cost_tracker import get_cost_tracker
        summary = get_cost_tracker().get_summary()
        cost_dict = {
            "event": "pipeline_cost_summary",
            "total_cost_usd": summary.total_cost_usd,
            "total_input_tokens": summary.total_input_tokens,
            # ... etc ...
        }
        logger.info(json.dumps(cost_dict))
        span.add_event("cost_summary", attributes={
            "total_cost_usd": summary.total_cost_usd,
            "total_input_tokens": summary.total_input_tokens,
            "total_output_tokens": summary.total_output_tokens,
            "call_count": summary.call_count,
        })
        callback_context.state["run_cost_usd"] = summary.total_cost_usd
        callback_context.state["cost_summary"] = asdict(summary)  # or manual dict conversion
    ```
  - `per_model` dict needs simplification for JSON: convert `ModelCostDetail` dataclass instances to plain dicts
  - Known pitfall: `span.add_event()` only accepts primitive attribute types (str, int, float, bool). Complex dicts won't work. Keep the event attributes flat.
  - Use `import json` and `json.dumps()` for the log line (structured JSON output)
  - Use `dataclasses.asdict(summary)` for state storage. Verify it produces JSON-serializable dicts.

### T21-07 - Create TraceContextFilter in logging_config.py

- **Description**: Add a `TraceContextFilter` logging filter that injects trace_id and span_id into every log record.
- **Spec refs**: FR-701, Section 8.4
- **Parallel**: Yes (independent of timing.py tasks)
- **Acceptance criteria**:
  - [ ] `TraceContextFilter` is a `logging.Filter` subclass in `logging_config.py`
  - [ ] `filter()` method always returns `True` (does not filter out records)
  - [ ] Sets `record.trace_id` to the current span's trace ID as lowercase 32-char hex, zero-padded
  - [ ] Sets `record.span_id` to the current span's span ID as lowercase 16-char hex, zero-padded
  - [ ] When no active OTel span: `trace_id = "0" * 32`, `span_id = "0" * 16`
  - [ ] When OTel is not available (import error): sets zero IDs (FR-704 backwards-compat)
  - [ ] Filter is safe to use in any logging context (never raises)
- **Test requirements**: unit (T21-10)
- **Depends on**: WP19 (OTel packages installed)
- **Implementation Guidance**:
  - Implementation:
    ```python
    class TraceContextFilter(logging.Filter):
        def filter(self, record):
            try:
                from opentelemetry import trace
                span = trace.get_current_span()
                ctx = span.get_span_context()
                if ctx and ctx.trace_id:
                    record.trace_id = format(ctx.trace_id, "032x")
                    record.span_id = format(ctx.span_id, "016x")
                else:
                    record.trace_id = "0" * 32
                    record.span_id = "0" * 16
            except Exception:
                record.trace_id = "0" * 32
                record.span_id = "0" * 16
            return True
    ```
  - Known pitfall: Import `opentelemetry.trace` inside the method (not at module level) to handle the case where OTel is not installed. If it's at module level, the import-time error would prevent the entire logging_config from loading.
  - Alternative: do a one-time import check at module level with try/except, then use a flag.

### T21-08 - Update text and JSON log formats with trace IDs

- **Description**: Modify `setup_logging()` to attach `TraceContextFilter` and update log format strings to include trace/span IDs.
- **Spec refs**: FR-702, FR-703, FR-704
- **Parallel**: No (depends on T21-07)
- **Acceptance criteria**:
  - [ ] `_TEXT_FORMAT` updated to `"%(asctime)s %(levelname)s %(name)s [trace=%(trace_id)s span=%(span_id)s] %(message)s"` (FR-702)
  - [ ] `_CloudJsonFormatter.format()` includes `trace_id` and `span_id` fields in JSON output (FR-703)
  - [ ] `TraceContextFilter` is added to the `newsletter_agent` logger (or root handler) in `setup_logging()`
  - [ ] When `OTEL_ENABLED=false`, traces still appear as zero IDs (backwards-compatible) (FR-704)
  - [ ] Existing log format structure (timestamp, level, name, message) preserved
  - [ ] No log lines are removed or restructured
- **Test requirements**: unit (T21-10)
- **Depends on**: T21-07
- **Implementation Guidance**:
  - In `setup_logging()`, after handler creation:
    ```python
    trace_filter = TraceContextFilter()
    ns_logger = logging.getLogger("newsletter_agent")
    ns_logger.addFilter(trace_filter)
    ```
  - Update `_TEXT_FORMAT`:
    ```python
    _TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s [trace=%(trace_id)s span=%(span_id)s] %(message)s"
    ```
  - Update `_CloudJsonFormatter.format()`:
    ```python
    entry["trace_id"] = getattr(record, "trace_id", "0" * 32)
    entry["span_id"] = getattr(record, "span_id", "0" * 16)
    ```
  - Known pitfall: If the filter is not attached, `%(trace_id)s` and `%(span_id)s` will cause `KeyError` on format. The filter MUST be attached before any log message is emitted. Since `setup_logging()` is called early, this should be fine.
  - Alternative safety net: use `%(trace_id)s` with a default in the filter, or set defaults on the LogRecord class.

### T21-09 - Unit tests for timing OTel integration

- **Description**: Create `tests/test_timing_otel.py` with tests for span creation, hierarchy, and attributes in the modified timing callbacks.
- **Spec refs**: Section 11.1 (test_timing_otel.py requirements), FR-201, FR-203, FR-204, FR-205, FR-206, FR-207
- **Parallel**: No (depends on T21-01 through T21-06)
- **Acceptance criteria**:
  - [ ] Test: `before_agent_callback` creates span when telemetry enabled (assert span in InMemorySpanExporter)
  - [ ] Test: `before_agent_callback` skips span when telemetry disabled (assert no spans)
  - [ ] Test: `after_agent_callback` ends span and detaches context (assert span is ended with duration)
  - [ ] Test: `after_agent_callback` handles missing span gracefully (no exception, WARNING logged)
  - [ ] Test: Span parent-child relationships are correct for sequential agent execution (parent span contains child spans)
  - [ ] Test: Root agent span has correct attributes (`newsletter.topic_count`, `newsletter.dry_run`)
  - [ ] Test: Topic-scoped agent span has `newsletter.topic.index` and `newsletter.topic.name`
  - [ ] Test: Topic index regex correctly parses `GoogleSearcher_0`, `DeepResearch_2_google`, `Topic3Research`
  - [ ] Test: LlmAgent spans have `gen_ai.tokens_available: false`
  - [ ] Test: Cost summary is logged at INFO on root agent completion (assert in caplog)
  - [ ] Test: Cost summary is recorded as span event on root span
  - [ ] Test: `state["run_cost_usd"]` and `state["cost_summary"]` are set after root agent completion
  - [ ] Test: Existing timing behavior preserved (elapsed time logged, metadata set)
  - [ ] Minimum 80% code, 90% branch coverage for modified `timing.py`
- **Test requirements**: unit (pytest)
- **Depends on**: T21-01 through T21-06
- **Implementation Guidance**:
  - Use `InMemorySpanExporter` with `SimpleSpanProcessor` for test span capture
  - Create mock `callback_context` objects:
    ```python
    class MockCallbackContext:
        def __init__(self, agent_name, invocation_id="test-inv-001", state=None):
            self.agent_name = agent_name
            self.invocation_id = invocation_id
            self.state = state or {}
    ```
  - Test span hierarchy by calling before/after for parent, then before/after for child:
    ```python
    before_agent_callback(parent_ctx)
    before_agent_callback(child_ctx)
    after_agent_callback(child_ctx)
    after_agent_callback(parent_ctx)
    spans = exporter.get_finished_spans()
    # child span's parent_id should match parent span's span_id
    ```
  - Fixture to reset telemetry and cost tracker between tests
  - For cost summary tests: init a CostTracker with known data, then trigger root agent after_callback

### T21-10 - Unit tests for TraceContextFilter and log formats

- **Description**: Create `tests/test_logging_trace.py` with tests for the logging filter and format updates.
- **Spec refs**: Section 11.1 (test_logging_trace.py requirements), FR-701, FR-702, FR-703, FR-704
- **Parallel**: Yes (independent of T21-09)
- **Acceptance criteria**:
  - [ ] Test: `TraceContextFilter` sets `trace_id`/`span_id` from active span context
  - [ ] Test: `TraceContextFilter` sets zero IDs when no active span
  - [ ] Test: `TraceContextFilter` sets zero IDs when OTel is not importable
  - [ ] Test: Text log format includes `[trace=... span=...]` segment
  - [ ] Test: JSON log format (CloudJsonFormatter) includes `trace_id` and `span_id` fields
  - [ ] Test: When `OTEL_ENABLED=false`, filter outputs zero IDs (FR-704)
  - [ ] Minimum 80% code, 90% branch coverage for TraceContextFilter
- **Test requirements**: unit (pytest)
- **Depends on**: T21-07, T21-08
- **Implementation Guidance**:
  - Test active span context:
    ```python
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("test-span") as span:
        record = logging.LogRecord(...)
        filter = TraceContextFilter()
        filter.filter(record)
        assert record.trace_id == format(span.get_span_context().trace_id, "032x")
    ```
  - Test zero IDs: don't create any span, call filter, assert zeros
  - Test OTel not importable: mock the import to raise ImportError inside filter
  - Test text format: create a formatter with the new format string, format a record, assert output contains `[trace=...`
  - Test JSON format: create `_CloudJsonFormatter`, format a record, parse JSON output, assert keys exist

## Implementation Notes

- **Execution order**: T21-01 -> T21-02 -> T21-03 + T21-04 + T21-05 (parallel) -> T21-06 -> T21-07 -> T21-08 -> T21-09 + T21-10 (parallel)
- **Key files modified**: `newsletter_agent/timing.py`, `newsletter_agent/logging_config.py`
- **Test files created**: `tests/test_timing_otel.py`, `tests/test_logging_trace.py`
- **Critical dependency**: T21-06 (cost summary) requires WP20's CostTracker to be working
- **Span hierarchy validation**: After this WP, running the pipeline should produce a complete span tree visible in ConsoleSpanExporter output

## Parallel Opportunities

- T21-03 (root attributes), T21-04 (topic attributes), T21-05 (LlmAgent marker) are independent enhancements to before_callback [P]
- T21-07 (TraceContextFilter) is independent of all timing.py work [P]
- T21-09 (timing tests) and T21-10 (logging tests) are independent test suites [P]

## Risks & Mitigations

- **Risk**: ADK callbacks do not fire for dynamically created LlmAgents inside DeepResearchOrchestrator (OQ-3 in spec). **Mitigation**: Test with a minimal BaseAgent that creates and runs inner LlmAgent. If callbacks don't fire, add manual span creation in the orchestrator. Document finding.
- **Risk**: `context.attach()`/`context.detach()` ordering breaks in async concurrent execution (ParallelAgent). **Mitigation**: Python 3.11+ copies contextvars to new tasks (Assumption A3). Test with ParallelAgent + 2 child agents.
- **Risk**: Log format change breaks existing log parsing/monitoring. **Mitigation**: The added `[trace=... span=...]` segment is new content between name and message. Existing parsers that match on level+name+message may need updating. FR-704 ensures zero IDs when OTel disabled, so the format always includes the trace segment.
- **Risk**: Cost summary serialization in `state["cost_summary"]` fails if dataclass contains non-serializable types. **Mitigation**: Use `dataclasses.asdict()` which produces plain dicts. Verify with `json.dumps()` in test.

## Activity Log

- 2025-07-18T00:00:00Z - planner - lane=planned - Work package created
