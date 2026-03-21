# Observability, Cost Monitoring & Debug Tracing - Specification

> **Source brief**: `ideas/003-observability-cost-tracing.md`
> **Feature branch**: `003-observability-cost-tracing`
> **Status**: Draft
> **Version**: 1.0

---

## 1. Overview

Add OpenTelemetry-based observability to the NewsletterAgent pipeline so that every agent invocation becomes a structured span with timing, every direct Gemini API call records token counts and USD cost, and the full span hierarchy (pipeline > phase > topic > round > llm_call) is exported to either console (local development) or any OTLP-compatible backend (GCP Cloud Trace in production). A run-level cost summary is logged at pipeline completion with per-topic and per-phase breakdowns. The existing logging infrastructure is augmented with trace/span IDs for correlation, not replaced.

---

## 2. Goals & Success Criteria

- **SC-001**: Every direct `genai.Client().aio.models.generate_content()` call records `prompt_token_count`, `candidates_token_count`, and `thoughts_token_count` as OTel span attributes and accumulates them in a cost tracker. Verified by unit test asserting non-zero token attributes on spans after a mock LLM call.
- **SC-002**: A 5-topic deep-research pipeline run produces a structured cost summary log line containing total_cost_usd > 0, per_topic breakdown with 5 entries, and per_phase breakdown with entries for "research", "refinement", and "synthesis". Verified by integration test.
- **SC-003**: Console span export shows a tree with at least 3 nesting levels (pipeline > phase > agent) when `OTEL_EXPORTER_OTLP_ENDPOINT` is unset. Verified by capturing ConsoleSpanExporter output in test.
- **SC-004**: When `OTEL_EXPORTER_OTLP_ENDPOINT` is set, spans are exported via OTLP gRPC. Verified by integration test with a mock OTLP collector.
- **SC-005**: Every log line from the `newsletter_agent` logger namespace includes `trace_id` and `span_id` fields that match the active OTel span. Verified by unit test.
- **SC-006**: OTel instrumentation adds less than 5% wall-clock overhead to a pipeline run. Verified by benchmark comparing instrumented vs. non-instrumented runs with mocked LLM calls.
- **SC-007**: When `OTEL_ENABLED=false`, no spans are created and no OTel-related overhead exists. Verified by unit test asserting NoOp tracer is active.

---

## 3. Users & Roles

- **Operator**: The newsletter pipeline operator. Runs the pipeline locally or via Cloud Run. Needs to understand per-run costs, debug failures via trace data, and monitor pipeline health. Has full access to all logs, traces, and configuration.
- **Contributor**: A developer extending or modifying the pipeline. Needs structured trace data to understand multi-agent flow, identify which agent/phase is slow, and validate that new code does not introduce cost regressions. Has full access to local dev traces.

---

## 4. Functional Requirements

### 4.1 OTel Initialization & Configuration

- **FR-101**: System SHALL initialize an OpenTelemetry `TracerProvider` at module import time (in `newsletter_agent/__init__.py`) before any agent code runs, configured with a `Resource` containing `service.name`, `service.version`, and `deployment.environment` attributes.
  - Precondition: Python process starts, `newsletter_agent` package is imported.
  - Postcondition: `trace.get_tracer_provider()` returns the configured provider.
  - Error: If OTel SDK import fails, log a WARNING and continue with stdlib `logging` only (no spans, no cost tracking).

- **FR-102**: System SHALL read the environment variable `OTEL_ENABLED` (default: `"true"`). When set to `"false"` (case-insensitive), the system SHALL use `NoOpTracerProvider` and skip all span creation and cost tracking.
  - Postcondition: `trace.get_tracer_provider()` returns `NoOpTracerProvider`.

- **FR-103**: System SHALL use `OTEL_SERVICE_NAME` (default: `"newsletter-agent"`) as the `service.name` resource attribute.

- **FR-104**: System SHALL set `service.version` from the package version defined in `pyproject.toml` (currently `"0.1.0"`).

- **FR-105**: System SHALL set `deployment.environment` to `"production"` when `K_SERVICE` env var is present (Cloud Run), otherwise `"development"`.

- **FR-106**: System SHALL call `shutdown_telemetry()` at pipeline completion to flush all pending spans before process exit. In the CLI runner (`__main__.py`), this SHALL be called in a `finally` block. In the HTTP handler (`http_handler.py`), this SHALL be called after each `/run` request completes.
  - Error: If shutdown times out (>5 seconds), log WARNING and proceed with process exit.

#### Implementation Contract: `newsletter_agent/telemetry.py`

```
Function: init_telemetry() -> None
  Reads: OTEL_ENABLED, OTEL_SERVICE_NAME, OTEL_EXPORTER_OTLP_ENDPOINT,
         OTEL_EXPORTER_OTLP_HEADERS, K_SERVICE
  Side effects:
    - Registers global TracerProvider via trace.set_tracer_provider()
    - Registers global MeterProvider via metrics.set_meter_provider()
    - Sets module-level _initialized = True
  Error handling:
    - ImportError on OTel packages: log WARNING, set _initialized = False, return
    - Any other exception: log WARNING with traceback, set _initialized = False, return

Function: get_tracer(name: str) -> trace.Tracer
  Returns: trace.get_tracer(name) if _initialized else trace.NoOpTracer
  
Function: shutdown_telemetry() -> None
  Calls: TracerProvider.shutdown(timeout_millis=5000)
  Error: TimeoutError -> log WARNING, return
  
Function: is_enabled() -> bool
  Returns: _initialized
```

### 4.2 Span Hierarchy & Agent Instrumentation

- **FR-201**: System SHALL create an OTel span for every agent execution via the ADK `before_agent_callback` / `after_agent_callback` mechanism. The span name SHALL be the agent's `agent_name`.
  - Attributes on every agent span:
    - `newsletter.agent.name`: str - the agent name
    - `newsletter.invocation_id`: str - the ADK invocation ID
  - Postcondition: After a pipeline run, the exported spans form a tree matching the agent execution order.

- **FR-202**: System SHALL maintain correct parent-child span relationships by attaching the created span to the OTel context in `before_agent_callback` and detaching it in `after_agent_callback`. The span hierarchy SHALL mirror the ADK agent tree:
  ```
  NewsletterPipeline
    ConfigLoader
    ResearchPhase
      Topic0Research
        DeepResearch_0_google
          AdaptivePlanner_0_google
          DeepSearchRound_0_google_r0
          AdaptiveAnalyzer_0_google_r0
          DeepSearchRound_0_google_r1
          ...
        DeepResearch_0_perplexity
          ...
      Topic1Research
        ...
    ResearchValidator
    PipelineAbortCheck
    LinkVerifier
    DeepResearchRefiner
    PerTopicSynthesizer
    SynthesisLinkVerifier
    OutputPhase
      FormatterAgent
      DeliveryAgent
  ```

- **FR-203**: System SHALL record `newsletter.duration_seconds` (float) as a span attribute on every agent span, computed as `time.monotonic()` difference between before and after callbacks. This replaces the existing timing log in `timing.py`.

- **FR-204**: System SHALL store active span references in a dict keyed by `"{invocation_id}:{agent_name}"` to support concurrent agent execution in `ParallelAgent`. This dict SHALL be module-level in the modified `timing.py`.
  - Error: If `after_agent_callback` is called for a key not in the dict (span not found), log WARNING and skip span end.

- **FR-205**: For the root agent span (`NewsletterPipeline`), system SHALL set additional attributes:
  - `newsletter.topic_count`: int - number of topics configured
  - `newsletter.dry_run`: bool - whether in dry-run mode
  - `newsletter.pipeline_start_time`: str - ISO 8601 timestamp

- **FR-206**: For topic-scoped agents (name contains a topic index), system SHALL set:
  - `newsletter.topic.index`: int - zero-based topic index
  - `newsletter.topic.name`: str - topic name from config
  - Topic index SHALL be parsed from the agent name using regex `r'_(\d+)(?:_|$)'` which matches patterns like `GoogleSearcher_0`, `DeepResearch_2_google`, `Topic3Research`. The first captured group is the index. If no match, these attributes are omitted.

- **FR-207**: System SHALL preserve all existing timing functionality: `state["pipeline_start_time"]`, `state["newsletter_metadata"]["generation_time_seconds"]`, and all timing log lines. OTel spans augment but do not replace existing behavior.

- **FR-208**: The `ConfigLoaderAgent` SHALL initialize the CostTracker after parsing the pricing configuration. It SHALL convert `ModelPricingConfig` Pydantic instances from the parsed config to `ModelPricing` frozen dataclass instances expected by `init_cost_tracker()`. If `OTEL_ENABLED=false`, the ConfigLoaderAgent SHALL skip CostTracker initialization (the no-op fallback handles all subsequent calls).
  - Precondition: `settings.pricing` is parsed from `topics.yaml`.
  - Postcondition: `get_cost_tracker()` returns an active CostTracker with correct pricing.

#### Implementation Contract: Modified `newsletter_agent/timing.py`

```
Module-level state:
  _phase_starts: dict[str, float]         # existing, keyed by invocation_id:agent_name
  _active_spans: dict[str, tuple[Span, Token]]  # NEW, same key scheme

Function: before_agent_callback(callback_context) -> None
  Existing behavior: Record start time, log message, set pipeline_start_time.
  New behavior: 
    1. Create span: tracer.start_span(name=callback_context.agent_name)
    2. Set base attributes (FR-201)
    3. If root agent, set attributes (FR-205)
    4. If topic agent, set attributes (FR-206)
    5. Attach context: token = context.attach(trace.set_span_in_context(span))
    6. Store: _active_spans[key] = (span, token)
  Error: If telemetry not initialized (is_enabled() == False), skip span creation.

Function: after_agent_callback(callback_context) -> None
  Existing behavior: Calculate elapsed, log message, set metadata.
  New behavior:
    1. Pop (span, token) from _active_spans[key]
    2. Set span attribute newsletter.duration_seconds = elapsed
    3. If root agent: record cost summary as span events (FR-501)
    4. End span: span.end()
    5. Detach context: context.detach(token)
  Error: KeyError on _active_spans -> log WARNING, skip span operations.
```

### 4.3 Token Tracking & Extraction

- **FR-301**: For every direct `genai.Client().aio.models.generate_content()` call in the codebase, system SHALL extract token counts from `response.usage_metadata` and record them as OTel span attributes using the `gen_ai.*` semantic conventions:
  - `gen_ai.usage.input_tokens`: int - from `usage_metadata.prompt_token_count`
  - `gen_ai.usage.output_tokens`: int - from `usage_metadata.candidates_token_count`
  - `gen_ai.usage.thinking_tokens`: int - from `usage_metadata.thoughts_token_count` (0 if absent)
  - `gen_ai.usage.total_tokens`: int - from `usage_metadata.total_token_count`
  - `gen_ai.request.model`: str - the model name passed to generate_content
  - `gen_ai.system`: str - always `"google_genai"`

- **FR-302**: The direct `genai.Client()` call sites that SHALL be instrumented are:
  1. `per_topic_synthesizer.py` - `_synthesize_topic()` function, model `gemini-2.5-pro`
  2. `deep_research_refiner.py` - `_call_refinement_llm()` function, model `gemini-2.5-flash`
  - These are the only two files with direct `genai.Client().aio.models.generate_content()` calls.

- **FR-303**: System SHALL provide a helper function `traced_generate()` that wraps `genai.Client().aio.models.generate_content()` to:
  1. Create a child OTel span named `"llm.generate:{model}"`
  2. Call the underlying API
  3. Extract usage_metadata and set span attributes (FR-301)
  4. Record the call in the CostTracker (FR-401)
  5. Return the original response object unchanged
  - Error: If `response.usage_metadata` is `None` or missing expected fields, log WARNING, set all token counts to 0, and set span status to `StatusCode.OK` (not an error - the response itself succeeded).

- **FR-304**: For `LlmAgent`-based agents (GoogleSearcher, PerplexitySearcher, Planner, Searcher, Analyzer), token tracking is NOT possible in P1 because ADK callbacks do not expose the LLM response object. These agents SHALL have agent-level spans (FR-201) with timing but without token/cost attributes. The span SHALL include attribute `gen_ai.tokens_available: false` to indicate this limitation.

#### Implementation Contract: `newsletter_agent/telemetry.py` (additional)

```
Function: traced_generate(
    model: str,
    contents: str | list[Any],
    config: types.GenerateContentConfig | None = None,
    *,
    agent_name: str,
    topic_name: str | None = None,
    topic_index: int | None = None,
    phase: str,
) -> types.GenerateContentResponse

  Creates: genai.Client() internally (same pattern as existing code)
  Span: Creates child span "llm.generate:{model}" under current context span
  Span attributes (always set):
    gen_ai.system = "google_genai"
    gen_ai.request.model = model
    newsletter.agent.name = agent_name
    newsletter.phase = phase
  Span attributes (set if topic provided):
    newsletter.topic.name = topic_name
    newsletter.topic.index = topic_index
  Span attributes (set from response):
    gen_ai.usage.input_tokens = usage_metadata.prompt_token_count or 0
    gen_ai.usage.output_tokens = usage_metadata.candidates_token_count or 0
    gen_ai.usage.thinking_tokens = usage_metadata.thoughts_token_count or 0
    gen_ai.usage.total_tokens = usage_metadata.total_token_count or 0
  Side effects: Calls cost_tracker.record_llm_call(...)
  Returns: The GenerateContentResponse object
  Errors:
    - API exception (e.g. google.api_core.exceptions.*):
      Sets span status to ERROR, records exception on span, re-raises
    - usage_metadata is None: log WARNING, tokens default to 0
    - usage_metadata field is None: that field defaults to 0
```

### 4.4 Cost Calculation

- **FR-401**: System SHALL calculate USD cost for each direct LLM call using the formula:
  ```
  input_cost  = prompt_token_count * input_per_million / 1_000_000
  output_cost = (candidates_token_count + thoughts_token_count) * output_per_million / 1_000_000
  total_cost  = input_cost + output_cost
  ```
  Thinking tokens are billed at the output token rate per Gemini API pricing.

- **FR-402**: System SHALL record cost attributes on each LLM call span:
  - `newsletter.cost.input_usd`: float
  - `newsletter.cost.output_usd`: float
  - `newsletter.cost.total_usd`: float

- **FR-403**: System SHALL support configurable per-model pricing via the `pricing` section in `AppSettings` (see FR-601). Default pricing (USD per 1M tokens):
  | Model | Input | Output |
  |-------|-------|--------|
  | `gemini-2.5-flash` | $0.30 | $2.50 |
  | `gemini-2.5-pro` | $1.25 | $10.00 |

- **FR-404**: If an LLM call uses a model not present in the pricing config, system SHALL log a WARNING and use `input_per_million=0.0, output_per_million=0.0` (zero cost). The span SHALL include attribute `newsletter.cost.pricing_missing: true`.

- **FR-405**: System SHALL accumulate all LLM call costs in a `CostTracker` instance for the duration of a pipeline run. The tracker SHALL be thread-safe (using `threading.Lock`) to support concurrent LLM calls in `ParallelAgent`.

- **FR-406**: System SHALL support a configurable cost budget via `settings.pricing.cost_budget_usd` in `topics.yaml`. When a recorded call causes total accumulated cost to exceed the budget, system SHALL log a WARNING with the message: `"Cost budget exceeded: ${accumulated:.4f} > ${budget:.4f} USD"`. System SHALL NOT abort the pipeline (log-only warning per user requirement).

#### Implementation Contract: `newsletter_agent/cost_tracker.py`

```
@dataclass(frozen=True)
class ModelPricing:
    input_per_million: float   # USD per 1M input tokens, >= 0
    output_per_million: float  # USD per 1M output tokens, >= 0

@dataclass(frozen=True)
class LlmCallRecord:
    model: str
    agent_name: str
    phase: str                        # "research" | "synthesis" | "refinement"
    topic_name: str | None
    topic_index: int | None
    prompt_tokens: int                # >= 0
    completion_tokens: int            # >= 0
    thinking_tokens: int              # >= 0
    total_tokens: int                 # >= 0
    input_cost_usd: float             # >= 0.0
    output_cost_usd: float            # >= 0.0
    total_cost_usd: float             # >= 0.0
    timestamp: str                    # ISO 8601

@dataclass
class CostSummary:
    total_input_tokens: int
    total_output_tokens: int
    total_thinking_tokens: int
    total_cost_usd: float
    call_count: int
    per_model: dict[str, dict]        # model -> {input_tokens, output_tokens, cost_usd, call_count}
    per_topic: dict[str, float]       # topic_name -> cost_usd (topics without names keyed as "unknown")
    per_phase: dict[str, float]       # phase -> cost_usd

class CostTracker:
    def __init__(
        self,
        pricing: dict[str, ModelPricing],
        cost_budget_usd: float | None = None,
    ) -> None:
        # pricing: model_name -> ModelPricing, must not be empty
        # cost_budget_usd: None means no budget, float >= 0 means budget
        # Internal: _calls: list[LlmCallRecord], _lock: threading.Lock,
        #           _total_cost: float = 0.0

    def record_llm_call(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        thinking_tokens: int,
        agent_name: str,
        phase: str,
        topic_name: str | None = None,
        topic_index: int | None = None,
    ) -> LlmCallRecord:
        # Thread-safe. Acquires _lock.
        # Looks up pricing for model. If missing: log WARNING, use zero pricing.
        # Calculates costs per FR-401.
        # Appends LlmCallRecord to _calls.
        # Adds to _total_cost.
        # If cost_budget_usd is set and _total_cost > cost_budget_usd: log WARNING (FR-406).
        # Returns the LlmCallRecord.

    def get_summary(self) -> CostSummary:
        # Thread-safe. Acquires _lock.
        # Aggregates all _calls into CostSummary.
        # Returns CostSummary.

    def get_calls(self) -> list[LlmCallRecord]:
        # Thread-safe. Returns shallow copy of _calls.

Module-level functions:
  init_cost_tracker(pricing: dict[str, ModelPricing], cost_budget_usd: float | None = None) -> None
    # Sets module-level _tracker.
  get_cost_tracker() -> CostTracker
    # Returns _tracker. Raises RuntimeError if not initialized.
  reset_cost_tracker() -> None
    # Sets _tracker to None. For test teardown only.
```

### 4.5 Cost Summary & Reporting

- **FR-501**: At pipeline completion (in `after_agent_callback` for the root agent), system SHALL log a structured cost summary at INFO level containing:
  ```json
  {
    "event": "pipeline_cost_summary",
    "total_cost_usd": 0.0423,
    "total_input_tokens": 45230,
    "total_output_tokens": 12450,
    "total_thinking_tokens": 3200,
    "call_count": 18,
    "per_model": {
      "gemini-2.5-flash": {"cost_usd": 0.0198, "call_count": 14},
      "gemini-2.5-pro": {"cost_usd": 0.0225, "call_count": 4}
    },
    "per_topic": {
      "Agentic Frameworks": 0.0112,
      "Cloud Native": 0.0087,
      ...
    },
    "per_phase": {
      "research": 0.0000,
      "refinement": 0.0198,
      "synthesis": 0.0225
    }
  }
  ```
  Note: "research" phase cost is 0.0 for P1 because LlmAgent calls (used in research) do not have token tracking. Only direct `genai.Client()` calls in refinement and synthesis are tracked.

- **FR-502**: System SHALL also record the cost summary as span events on the root pipeline span:
  - Event name: `"cost_summary"`
  - Event attributes: `total_cost_usd`, `total_input_tokens`, `total_output_tokens`, `call_count`

- **FR-503**: System SHALL store `state["run_cost_usd"]` (float) in the ADK session state after computing the cost summary, making it available for downstream agents or reporting.

- **FR-504**: System SHALL store `state["cost_summary"]` (dict) in the ADK session state, containing the full CostSummary as a dict for potential inclusion in newsletter metadata.

### 4.6 Export Configuration

- **FR-601**: System SHALL add a `pricing` configuration section to `AppSettings` in `config/schema.py`:
  ```
  settings:
    pricing:
      models:
        gemini-2.5-flash:
          input_per_million: 0.30
          output_per_million: 2.50
        gemini-2.5-pro:
          input_per_million: 1.25
          output_per_million: 10.00
      cost_budget_usd: null
  ```
  All fields have defaults. The entire `pricing` section is optional.

- **FR-602**: When `OTEL_EXPORTER_OTLP_ENDPOINT` is set (non-empty string), system SHALL configure `BatchSpanProcessor` with `OTLPSpanExporter` (gRPC protocol) pointing to that endpoint. The `OTEL_EXPORTER_OTLP_HEADERS` env var SHALL be passed to the exporter for authentication.

- **FR-603**: When `OTEL_EXPORTER_OTLP_ENDPOINT` is NOT set, system SHALL configure `BatchSpanProcessor` with `ConsoleSpanExporter` for human-readable trace output to stdout.

- **FR-604**: System SHALL always attach a `SimpleSpanProcessor` with `ConsoleSpanExporter` in development mode (`deployment.environment == "development"`) in ADDITION to any OTLP exporter, so developers always see trace output locally even when OTLP is configured. In production mode, only the OTLP exporter is attached.

- **FR-605**: System SHALL add the following environment variables to `.env.example`:
  ```
  OTEL_ENABLED=true
  OTEL_SERVICE_NAME=newsletter-agent
  OTEL_EXPORTER_OTLP_ENDPOINT=
  OTEL_EXPORTER_OTLP_HEADERS=
  ```

### 4.7 Logging Integration

- **FR-701**: System SHALL add a `logging.Filter` subclass (`TraceContextFilter`) to the `newsletter_agent` logger that injects `trace_id` and `span_id` from the current OTel span context into every log record.
  - If no active span: `trace_id = "0" * 32`, `span_id = "0" * 16`.
  - Format: lowercase hex, zero-padded (32 chars for trace_id, 16 for span_id).

- **FR-702**: System SHALL update the text log format in `logging_config.py` to include trace context:
  ```
  "%(asctime)s %(levelname)s %(name)s [trace=%(trace_id)s span=%(span_id)s] %(message)s"
  ```

- **FR-703**: System SHALL update the `_CloudJsonFormatter` to include `trace_id` and `span_id` fields in the JSON output, enabling GCP Cloud Logging to correlate logs with Cloud Trace spans.

- **FR-704**: The log format changes SHALL be backwards-compatible: when `OTEL_ENABLED=false`, the filter still runs but always outputs zero trace/span IDs. No log lines are removed or restructured.

#### Implementation Contract: `newsletter_agent/logging_config.py` (additions)

```
Class: TraceContextFilter(logging.Filter)
  Method: filter(self, record: logging.LogRecord) -> bool
    # Always returns True (does not filter out records)
    # Sets record.trace_id and record.span_id from current OTel span
    # If OTel not available (import error): sets zero IDs
    # If no active span: sets zero IDs

Modified: setup_logging() -> None
  # After existing handler setup, adds TraceContextFilter to root 'newsletter_agent' logger
  # Updates _TEXT_FORMAT to include trace/span IDs
  # Updates _CloudJsonFormatter to include trace_id/span_id in JSON dict
```

---

## 5. User Stories

### US-01 - View token counts for synthesis calls (Priority: P1) MVP

**As an** operator, **I want** to see input/output/thinking token counts for every Gemini API call made during synthesis and refinement, **so that** I can understand which topics consume the most tokens and optimize prompts.

**Why P1**: Token visibility is the foundation for all cost tracking. Without it, cost calculation is impossible.

**Independent Test**: Run the pipeline in dry-run mode with 1 topic. After completion, inspect exported spans and verify that spans named `llm.generate:gemini-2.5-pro` (synthesis) and `llm.generate:gemini-2.5-flash` (refinement) contain `gen_ai.usage.input_tokens > 0` and `gen_ai.usage.output_tokens > 0`.

**Acceptance Scenarios**:
1. **Given** a pipeline run with 1 deep-mode topic, **When** synthesis completes, **Then** the synthesis LLM span has `gen_ai.usage.input_tokens >= 1`, `gen_ai.usage.output_tokens >= 1`, and `gen_ai.request.model == "gemini-2.5-pro"`.
2. **Given** a pipeline run where the LLM response has `usage_metadata = None`, **When** token extraction runs, **Then** all token attributes are set to 0 and a WARNING is logged containing "usage_metadata missing".

### US-02 - View per-run cost summary (Priority: P1) MVP

**As an** operator, **I want** to see a cost summary at the end of each pipeline run showing total USD cost, per-topic breakdown, and per-model breakdown, **so that** I can monitor spending and detect cost anomalies.

**Why P1**: Cost visibility is the primary business value of this feature. Operators need to know how much each run costs.

**Independent Test**: Run the pipeline with 2 topics. After completion, verify that the log stream contains a JSON object with key `"event": "pipeline_cost_summary"` and `total_cost_usd > 0`, `per_topic` has 2 entries, and `per_model` has at least 1 entry.

**Acceptance Scenarios**:
1. **Given** a completed pipeline run with 3 topics, **When** the cost summary is logged, **Then** the summary contains `call_count >= 3`, `per_topic` has exactly 3 keys, and `per_phase` has keys "research", "refinement", "synthesis".
2. **Given** a pipeline run where all LLM calls fail, **When** the cost summary is logged, **Then** `total_cost_usd == 0.0` and `call_count == 0`.

### US-03 - See structured trace hierarchy (Priority: P1) MVP

**As an** operator, **I want** to see a hierarchical trace of agent execution (pipeline > phase > topic > round), **so that** I can identify which phase or topic is slow and drill into specific agent behavior.

**Why P1**: Trace hierarchy is the structural backbone that makes all other observability data useful.

**Independent Test**: Run the pipeline with 1 topic in standard mode. Verify that ConsoleSpanExporter output contains spans with parent_id relationships forming: `NewsletterPipeline` > `ResearchPhase` > `Topic0Research` > `GoogleSearcher_0`.

**Acceptance Scenarios**:
1. **Given** a pipeline run with 2 topics, **When** the trace is exported, **Then** the root span `NewsletterPipeline` has `newsletter.topic_count == 2` and children include `ResearchPhase`, `ResearchValidator`, `PerTopicSynthesizer`.
2. **Given** a pipeline run where an agent raises an exception, **When** the trace is exported, **Then** the failed agent's span has `status == ERROR` and an exception event with the traceback.

### US-04 - Correlate logs with traces (Priority: P1) MVP

**As a** contributor, **I want** every log line to include a trace_id and span_id, **so that** I can search logs by trace ID to find all messages related to a specific run or agent.

**Why P1**: Without log-trace correlation, operators must manually match timestamps to find related log entries.

**Independent Test**: Run the pipeline, capture log output, and verify every log line from the `newsletter_agent` namespace contains `trace=` followed by a 32-char hex string and `span=` followed by a 16-char hex string.

**Acceptance Scenarios**:
1. **Given** a pipeline run with OTel enabled, **When** a log message is emitted during agent execution, **Then** the log line contains `trace={32-char-hex}` where the hex value matches the root span's trace ID.
2. **Given** `OTEL_ENABLED=false`, **When** a log message is emitted, **Then** the log line contains `trace=00000000000000000000000000000000`.

### US-05 - Export traces to OTLP backend (Priority: P1) MVP

**As an** operator, **I want** to export traces to GCP Cloud Trace (or any OTLP backend) in production, **so that** I can search and visualize traces in a managed UI.

**Why P1**: Production observability requires a persistent backend; console output is insufficient for Cloud Run.

**Independent Test**: Set `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317`, run a mock OTLP collector, run the pipeline with 1 topic, and verify the collector receives spans.

**Acceptance Scenarios**:
1. **Given** `OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4317`, **When** the pipeline completes, **Then** spans are exported via gRPC to the endpoint.
2. **Given** `OTEL_EXPORTER_OTLP_ENDPOINT` is unset, **When** the pipeline runs, **Then** spans are exported to console stdout only.

### US-06 - Configure cost budget warning (Priority: P2)

**As an** operator, **I want** to set a per-run cost budget in `topics.yaml` and receive a WARNING log when it is exceeded, **so that** I am alerted to unexpectedly expensive runs without the pipeline aborting.

**Why P2**: Useful for ongoing cost governance but not required for initial visibility.

**Independent Test**: Set `settings.pricing.cost_budget_usd: 0.001` in config, run the pipeline, and verify a WARNING log containing "Cost budget exceeded" is emitted.

**Acceptance Scenarios**:
1. **Given** `cost_budget_usd: 0.01` and a run that costs $0.05, **When** the cost exceeds the budget, **Then** a WARNING log is emitted with the accumulated and budget amounts.
2. **Given** `cost_budget_usd: null`, **When** a run completes, **Then** no budget warning is logged regardless of cost.

### US-07 - Disable telemetry completely (Priority: P1) MVP

**As a** contributor, **I want** to disable all OTel instrumentation via a single env var, **so that** I can run the pipeline without any telemetry overhead during development or debugging.

**Why P1**: Safety valve. If OTel causes issues, operators need a quick kill switch.

**Independent Test**: Set `OTEL_ENABLED=false`, run the pipeline, and verify no span output appears and the pipeline completes successfully.

**Acceptance Scenarios**:
1. **Given** `OTEL_ENABLED=false`, **When** the pipeline runs, **Then** no spans are created, no cost tracking occurs, and the pipeline behaves identically to pre-instrumentation behavior.
2. **Given** `OTEL_ENABLED=false`, **When** `get_cost_tracker()` is called, **Then** it returns a no-op tracker that silently discards all calls.

### Edge Cases

- What happens when `usage_metadata` is missing from an LLM response? Token counts default to 0, WARNING logged, pipeline continues.
- What happens when the OTLP endpoint is unreachable? OTel SDK handles this internally with async export and retries. No pipeline impact; spans are dropped after retry exhaustion.
- What happens when two parallel agents record costs simultaneously? `CostTracker` uses `threading.Lock` for thread safety.
- What happens when a model name in the pricing config does not match the model used in code? Cost defaults to $0.00, WARNING logged with model name.
- What happens when the pipeline crashes mid-run? `shutdown_telemetry()` in `finally` block flushes any accumulated spans. Cost summary may be partial.

---

## 6. User Flows

### 6.1 Local Development Run

1. Operator sets `OTEL_ENABLED=true` (or leaves default) and leaves `OTEL_EXPORTER_OTLP_ENDPOINT` unset.
2. Operator runs `python -m newsletter_agent`.
3. System initializes telemetry with ConsoleSpanExporter.
4. System creates root span `NewsletterPipeline`.
5. Each agent creates a child span via before/after callbacks.
6. Direct LLM calls create nested `llm.generate:*` spans with token/cost attributes.
7. At pipeline end, cost summary is logged to console.
8. All spans are printed to stdout by ConsoleSpanExporter.
9. `shutdown_telemetry()` flushes remaining spans.

### 6.2 Production Cloud Run Execution

1. Cloud Scheduler sends POST to `/run`.
2. HTTP handler initializes telemetry (idempotent - already initialized at import).
3. System detects `K_SERVICE` env var, sets `deployment.environment=production`.
4. System detects `OTEL_EXPORTER_OTLP_ENDPOINT`, configures OTLP gRPC exporter.
5. Pipeline runs, creating span hierarchy identical to local.
6. Spans are batched and exported to Cloud Trace via OTLP.
7. Cost summary is logged (picked up by Cloud Logging with trace_id correlation).
8. `shutdown_telemetry()` flushes remaining spans.
9. HTTP handler returns 200 with run status.
   - Error path: If pipeline fails, the root span is marked ERROR, partial cost summary is logged, HTTP handler returns 500.

### 6.3 Disabled Telemetry Run

1. Operator sets `OTEL_ENABLED=false`.
2. System initializes NoOpTracerProvider.
3. `before_agent_callback` checks `is_enabled()`, skips span creation.
4. `traced_generate()` checks `is_enabled()`, skips span creation but still calls the LLM.
5. `CostTracker` is not initialized; `get_cost_tracker()` returns a no-op instance.
6. Pipeline runs identically to pre-instrumentation behavior.
7. No cost summary is logged (no data to summarize).

### 6.4 Cost Budget Exceeded (P2)

1. Operator sets `settings.pricing.cost_budget_usd: 0.05` in `topics.yaml`.
2. Pipeline runs, accumulating costs after each LLM call.
3. After the 12th LLM call, total cost reaches $0.052.
4. `CostTracker.record_llm_call()` detects `_total_cost > cost_budget_usd`.
5. System logs: `WARNING - Cost budget exceeded: $0.0520 > $0.0500 USD`.
6. Pipeline continues processing all remaining topics.
7. Final cost summary shows the total (which exceeds budget).

---

## 7. Data Model

### 7.1 ModelPricingConfig (Pydantic BaseModel in config/schema.py, new)

Used for YAML config validation. Converted to `ModelPricing` frozen dataclass (Section 7.1b) when passed to `CostTracker`.

| Field | Type | Default | Constraints |
|-------|------|---------|-------------|
| `input_per_million` | `float` | required | `ge=0.0` |
| `output_per_million` | `float` | required | `ge=0.0` |

### 7.1b ModelPricing (frozen dataclass in cost_tracker.py, new)

Internal representation used by `CostTracker`. Created from `ModelPricingConfig` during initialization (FR-208).

| Field | Type | Constraints |
|-------|------|-------------|
| `input_per_million` | `float` | `>= 0.0` |
| `output_per_million` | `float` | `>= 0.0` |

### 7.2 PricingConfig (Pydantic, new)

| Field | Type | Default | Constraints |
|-------|------|---------|-------------|
| `models` | `dict[str, ModelPricingConfig]` | see below | `min_length=1` |
| `cost_budget_usd` | `float \| None` | `None` | `ge=0.0` if not None |

Default `models`:
```python
{
    "gemini-2.5-flash": ModelPricingConfig(input_per_million=0.30, output_per_million=2.50),
    "gemini-2.5-pro": ModelPricingConfig(input_per_million=1.25, output_per_million=10.00),
}
```

### 7.3 AppSettings (modified, existing)

Add field:

| Field | Type | Default | Constraints |
|-------|------|---------|-------------|
| `pricing` | `PricingConfig` | `PricingConfig()` | |

All existing fields remain unchanged.

### 7.4 LlmCallRecord (frozen dataclass, new)

| Field | Type | Constraints |
|-------|------|-------------|
| `model` | `str` | non-empty |
| `agent_name` | `str` | non-empty |
| `phase` | `str` | one of: `"research"`, `"synthesis"`, `"refinement"`, `"unknown"` |
| `topic_name` | `str \| None` | |
| `topic_index` | `int \| None` | `>= 0` if not None |
| `prompt_tokens` | `int` | `>= 0` |
| `completion_tokens` | `int` | `>= 0` |
| `thinking_tokens` | `int` | `>= 0` |
| `total_tokens` | `int` | `>= 0` |
| `input_cost_usd` | `float` | `>= 0.0` |
| `output_cost_usd` | `float` | `>= 0.0` |
| `total_cost_usd` | `float` | `>= 0.0` |
| `timestamp` | `str` | ISO 8601 format |

### 7.5 CostSummary (dataclass, new)

| Field | Type | Constraints |
|-------|------|-------------|
| `total_input_tokens` | `int` | `>= 0` |
| `total_output_tokens` | `int` | `>= 0` |
| `total_thinking_tokens` | `int` | `>= 0` |
| `total_cost_usd` | `float` | `>= 0.0` |
| `call_count` | `int` | `>= 0` |
| `per_model` | `dict[str, ModelCostDetail]` | keys are model names |
| `per_topic` | `dict[str, float]` | keys are topic names, values >= 0.0 |
| `per_phase` | `dict[str, float]` | keys are phase names, values >= 0.0 |

### 7.6 ModelCostDetail (dataclass, new)

| Field | Type | Constraints |
|-------|------|-------------|
| `input_tokens` | `int` | `>= 0` |
| `output_tokens` | `int` | `>= 0` |
| `thinking_tokens` | `int` | `>= 0` |
| `cost_usd` | `float` | `>= 0.0` |
| `call_count` | `int` | `>= 0` |

### 7.7 OTel Span Attributes Schema

#### Agent Span Attributes (all agents)

| Attribute | Type | Source | Required |
|-----------|------|--------|----------|
| `newsletter.agent.name` | string | `callback_context.agent_name` | yes |
| `newsletter.invocation_id` | string | `callback_context.invocation_id` | yes |
| `newsletter.duration_seconds` | float | monotonic timer | yes |

#### Root Agent Span Attributes (NewsletterPipeline only)

| Attribute | Type | Source | Required |
|-----------|------|--------|----------|
| `newsletter.topic_count` | int | `state["config_topic_count"]` | yes |
| `newsletter.dry_run` | bool | `state["config_dry_run"]` | yes |
| `newsletter.pipeline_start_time` | string | ISO 8601 | yes |

#### Topic-Scoped Agent Span Attributes

| Attribute | Type | Source | Required |
|-----------|------|--------|----------|
| `newsletter.topic.index` | int | parsed from agent name | if topic agent |
| `newsletter.topic.name` | string | config lookup | if topic agent |

#### LLM Call Span Attributes (llm.generate:* spans)

| Attribute | Type | Source | Required |
|-----------|------|--------|----------|
| `gen_ai.system` | string | `"google_genai"` | yes |
| `gen_ai.request.model` | string | model parameter | yes |
| `gen_ai.usage.input_tokens` | int | `usage_metadata.prompt_token_count` | yes |
| `gen_ai.usage.output_tokens` | int | `usage_metadata.candidates_token_count` | yes |
| `gen_ai.usage.thinking_tokens` | int | `usage_metadata.thoughts_token_count` | yes |
| `gen_ai.usage.total_tokens` | int | `usage_metadata.total_token_count` | yes |
| `newsletter.cost.input_usd` | float | calculated | yes |
| `newsletter.cost.output_usd` | float | calculated | yes |
| `newsletter.cost.total_usd` | float | calculated | yes |
| `newsletter.agent.name` | string | caller agent name | yes |
| `newsletter.phase` | string | caller phase | yes |
| `newsletter.topic.name` | string | caller topic | if available |
| `newsletter.topic.index` | int | caller topic index | if available |

#### LlmAgent Span Attributes (no token data in P1)

| Attribute | Type | Source | Required |
|-----------|------|--------|----------|
| `gen_ai.tokens_available` | bool | `false` | yes |

---

## 8. API / Interface Design

### 8.1 `newsletter_agent/telemetry.py` - Public Interface

```
init_telemetry() -> None
    Purpose: Initialize OTel providers. Idempotent.
    Called by: newsletter_agent/__init__.py at import time.
    Errors: Never raises. Logs WARNING on failure.

shutdown_telemetry() -> None
    Purpose: Flush and shutdown OTel providers.
    Called by: __main__.py (finally block), http_handler.py (after /run).
    Errors: Never raises. Logs WARNING on timeout.

get_tracer(name: str) -> trace.Tracer
    Purpose: Return a tracer instance for the given module.
    Returns: Real tracer if initialized, NoOpTracer otherwise.

is_enabled() -> bool
    Purpose: Check if telemetry is active.
    Returns: True if initialized successfully, False otherwise.

traced_generate(
    model: str,
    contents: str | list[Any],
    config: types.GenerateContentConfig | None = None,
    *,
    agent_name: str,
    topic_name: str | None = None,
    topic_index: int | None = None,
    phase: str,
) -> types.GenerateContentResponse
    Purpose: Traced wrapper around genai.Client().aio.models.generate_content().
    Creates: Child span "llm.generate:{model}" under current context.
    Side effects: Records cost via get_cost_tracker().record_llm_call().
    Returns: The unmodified GenerateContentResponse.
    Raises: Re-raises any exception from genai API after recording it on the span.
    Errors:
      - usage_metadata is None: tokens default to 0, WARNING logged.
      - Telemetry disabled: calls LLM directly without span or cost tracking.
```

### 8.2 `newsletter_agent/cost_tracker.py` - Public Interface

```
init_cost_tracker(
    pricing: dict[str, ModelPricing],
    cost_budget_usd: float | None = None,
) -> None
    Purpose: Initialize the global CostTracker.
    Called by: ConfigLoaderAgent after parsing pricing config.
    Errors: Never raises.

get_cost_tracker() -> CostTracker
    Purpose: Access the global CostTracker.
    Returns: Active CostTracker, or a no-op instance if not initialized.
    Errors: Never raises (returns no-op instead of raising).

reset_cost_tracker() -> None
    Purpose: Reset global state. For test teardown only.

CostTracker.record_llm_call(...) -> LlmCallRecord
    See Section 4.4 implementation contract.

CostTracker.get_summary() -> CostSummary
    See Section 4.4 implementation contract.
```

### 8.3 Modified `newsletter_agent/timing.py` - Callback Signatures

```
before_agent_callback(callback_context) -> None
    Input: callback_context with .invocation_id (str), .agent_name (str), .state (dict)
    Side effects: Creates OTel span, attaches to context, records start time.
    Errors: Skips OTel operations if is_enabled() is False.

after_agent_callback(callback_context) -> None
    Input: callback_context with .invocation_id (str), .agent_name (str), .state (dict)
    Side effects: Ends OTel span, detaches context, logs timing, records cost summary (root only).
    Errors: Skips OTel operations if span not found for key.
```

### 8.4 Modified `newsletter_agent/logging_config.py` - Filter

```
TraceContextFilter(logging.Filter)
    Method: filter(record: LogRecord) -> bool
        Always returns True.
        Sets record.trace_id (str, 32-char hex) and record.span_id (str, 16-char hex).
```

---

## 9. Architecture

### 9.1 System Design

The observability layer is a cross-cutting concern that wraps the existing pipeline without changing its control flow. Three new modules are introduced:

1. **telemetry.py** - OTel SDK initialization, tracer/meter factory, and the `traced_generate()` helper. This is the single entry point for all OTel configuration.
2. **cost_tracker.py** - Pure Python cost accumulation logic. No OTel dependency. Receives token counts and pricing, calculates costs, and produces summaries.
3. **Modified timing.py** - Existing ADK callbacks enhanced to create OTel spans instead of only logging timing.

Data flow:
```
Pipeline Start
  -> init_telemetry() [telemetry.py]
  -> init_cost_tracker(pricing) [cost_tracker.py, called by ConfigLoader]

Each Agent Execution:
  -> before_agent_callback [timing.py]
     -> Creates OTel span, attaches context

  Inside BaseAgent._run_async_impl():
    -> traced_generate() [telemetry.py]
       -> Creates child span "llm.generate:{model}"
       -> Calls genai.Client().aio.models.generate_content()
       -> Extracts usage_metadata
       -> Calls cost_tracker.record_llm_call()
       -> Sets span attributes
       -> Returns response

  -> after_agent_callback [timing.py]
     -> Sets duration on span
     -> Ends span, detaches context
     -> If root agent: logs cost summary

Pipeline End:
  -> shutdown_telemetry() [telemetry.py]
```

### 9.2 Technology Stack

| Layer | Technology | Version | Rationale |
|-------|-----------|---------|-----------|
| Tracing SDK | `opentelemetry-api` | `>=1.20.0` | Stable Python OTel API. CNCF graduated project. Wide backend compatibility. |
| Tracing SDK | `opentelemetry-sdk` | `>=1.20.0` | Reference implementation. Includes ConsoleSpanExporter, BatchSpanProcessor. |
| OTLP Export | `opentelemetry-exporter-otlp-proto-grpc` | `>=1.20.0` | gRPC-based OTLP export. Required for GCP Cloud Trace native ingestion. Lower overhead than HTTP for batch export. |
| Cost Tracking | Pure Python (stdlib) | N/A | No external dependencies. `threading.Lock` for safety, `dataclasses` for data structures. |
| Config | `pydantic>=2.0` (existing) | N/A | Extend existing schema. Validated pricing config with defaults. |

### 9.3 Directory & Module Structure

```
newsletter_agent/
  __init__.py              # MODIFIED: add init_telemetry() call
  __main__.py              # MODIFIED: add shutdown_telemetry() in finally
  telemetry.py             # NEW: OTel initialization, traced_generate()
  cost_tracker.py          # NEW: CostTracker, LlmCallRecord, CostSummary
  timing.py                # MODIFIED: add OTel span creation in callbacks
  logging_config.py        # MODIFIED: add TraceContextFilter, update formats
  http_handler.py          # MODIFIED: add shutdown_telemetry() after /run
  config/
    schema.py              # MODIFIED: add PricingConfig, ModelPricingConfig
  sub_agents/
    deep_research/
      per_topic_synthesizer.py  # MODIFIED: replace genai call with traced_generate()
      deep_research_refiner.py  # MODIFIED: replace genai call with traced_generate()

tests/
  test_telemetry.py        # NEW: unit tests for telemetry module
  test_cost_tracker.py     # NEW: unit tests for cost tracker
  test_timing_otel.py      # NEW: unit tests for OTel span creation in callbacks
  test_logging_trace.py    # NEW: unit tests for TraceContextFilter
```

### 9.4 Key Design Decisions

#### Decision 1: Manual spans via ADK callbacks rather than monkey-patching

- **Decision**: Use existing `before_agent_callback`/`after_agent_callback` to create OTel spans for all agents.
- **Rationale**: ADK callbacks are the official extensibility mechanism. They already fire for every agent in the tree. This avoids fragile monkey-patching of ADK internals.
- **Alternatives considered**: (a) Decorator on `_run_async_impl` - would miss LlmAgent and structural agents. (b) OpenLLMetry auto-instrumentation - only covers genai Client calls, not agent lifecycle.
- **Consequences**: LlmAgent internal calls are black boxes for token/cost tracking in P1. Accepted trade-off; resolved in P3 with auto-instrumentation.

#### Decision 2: `traced_generate()` helper rather than genai Client wrapper

- **Decision**: Provide a standalone async function that creates a genai Client, calls generate_content, and handles tracing/cost.
- **Rationale**: Each call site currently creates its own `genai.Client()`. A helper function is the minimal change - replace `client = genai.Client(); response = await client.aio.models.generate_content(...)` with `response = await traced_generate(...)`. No class hierarchy changes needed.
- **Alternatives considered**: (a) Subclass genai.Client - invasive, genai Client is not designed for subclassing. (b) Context manager wrapper - more ceremony, same result.
- **Consequences**: Two call sites need modification (per_topic_synthesizer.py, deep_research_refiner.py). Each is a 3-line change.

#### Decision 3: Module-level global CostTracker rather than ADK session state

- **Decision**: Store CostTracker as a module-level singleton in cost_tracker.py, not in ADK session state.
- **Rationale**: CostTracker is infrastructure, not domain data. Storing Python objects in ADK state is fragile and complicates serialization. Module-level global matches OTel's own pattern (`trace.get_tracer_provider()`).
- **Alternatives considered**: (a) ADK session state - state is meant for str/dict/list data, not infrastructure objects. (b) Dependency injection via context vars - over-engineered for a single-process batch pipeline.
- **Consequences**: Must call `reset_cost_tracker()` in test teardown. Acceptable.

#### Decision 4: ConsoleSpanExporter in dev, OTLP in production

- **Decision**: Auto-detect export target based on `OTEL_EXPORTER_OTLP_ENDPOINT` presence within the init code.
- **Rationale**: Zero-config for developers (just run the pipeline, see spans on stdout). Zero-config for production (OTLP endpoint set via Cloud Run env vars, spans route to Cloud Trace).
- **Alternatives considered**: (a) Always require explicit exporter config - worse developer experience. (b) Use `OTEL_TRACES_EXPORTER` standard env var - possible but our programmatic setup already handles this.
- **Consequences**: Developers who want both console AND OTLP in dev get console by default in dev mode (FR-604).

#### Decision 5: Thinking tokens billed at output rate

- **Decision**: Calculate cost of thinking tokens at the same rate as output tokens.
- **Rationale**: Gemini API pricing page states "Output price (including thinking tokens)" for all models with thinking capability (gemini-2.5-flash, gemini-2.5-pro). The `thoughts_token_count` is a separate field from `candidates_token_count` in usage_metadata.
- **Alternatives considered**: (a) Ignore thinking tokens - would under-report costs. (b) Separate thinking rate - not supported by Gemini pricing model.
- **Consequences**: Cost formula uses `(candidates_token_count + thoughts_token_count) * output_rate`.

### 9.5 External Integrations

#### OpenTelemetry OTLP Endpoint (GCP Cloud Trace)

- **Purpose**: Export trace spans to a managed tracing backend for search, visualization, and alerting.
- **Authentication**: GCP Cloud Trace accepts OTLP from Cloud Run workloads using the default service account. No explicit auth headers needed when running on Cloud Run. For external endpoints, `OTEL_EXPORTER_OTLP_HEADERS` provides auth.
- **Key operations**: `BatchSpanProcessor` batches spans and exports via gRPC to the configured endpoint.
- **Failure handling**: OTel SDK's `BatchSpanProcessor` retries failed exports with exponential backoff (default: 5 retries, 5s initial backoff). After retry exhaustion, spans are dropped silently. No pipeline impact. Export runs in a background thread.

---

## 10. Non-Functional Requirements

### 10.1 Performance

- OTel span creation overhead SHALL be less than 1ms per span (OTel SDK benchmark: ~0.5us per span).
- `BatchSpanProcessor` SHALL use default batch size (512 spans) and schedule delay (5000ms) to minimize export overhead.
- Cost calculation (floating-point arithmetic) is negligible (<1us per call).
- Total instrumentation overhead for a typical 5-topic run (producing ~50-100 spans) SHALL be less than 5% of total wall-clock time. The pipeline is I/O bound (LLM calls take seconds); instrumentation overhead is negligible.

### 10.2 Security

- **No prompt content in spans**: Span attributes SHALL NOT include prompt text, response text, or any PII. Only metadata (token counts, model name, topic name, cost, timing) is recorded. Full prompts remain in local logs only.
- **OTEL_EXPORTER_OTLP_HEADERS handling**: The env var may contain authentication tokens. It SHALL be read but never logged. The OTel SDK passes it to the gRPC channel metadata.
- **API key protection**: `GOOGLE_API_KEY` and `PERPLEXITY_API_KEY` SHALL NOT appear in any span attribute or event.
- **SSRF**: No new network calls introduced. OTel export connects only to the explicitly configured `OTEL_EXPORTER_OTLP_ENDPOINT`. The endpoint value is operator-controlled, not user-input.
- **OWASP mitigations**: No new injection surfaces (no user input processed). No new authentication/authorization surfaces. Existing security posture maintained.

### 10.3 Scalability & Availability

- The pipeline runs as a batch job (1-4 times per week). Span volume per run: ~50-200 spans depending on topic count and research depth.
- At 1 run/day with 200 spans/run: ~6,000 spans/month. Well within GCP Cloud Trace free tier (2.5M spans/month).
- CostTracker memory: ~1KB per LlmCallRecord. A run with 50 LLM calls uses ~50KB. Negligible.
- No horizontal scaling concerns - single-process batch pipeline.

### 10.4 Accessibility

Not applicable. This feature has no user-facing UI. All outputs are structured logs and OTel spans consumed by backend tools.

### 10.5 Observability

- **Logging**: Telemetry initialization success SHALL be logged at INFO. Telemetry errors and fallbacks (OTel import failure, missing usage_metadata, unknown model pricing, budget exceeded, span not found, shutdown timeout) SHALL be logged at WARNING. Configuration details (exporter type, endpoint, service name) SHALL be logged at DEBUG.
- **Metrics**: P1 does not add OTel metrics (counters, histograms). Token counts and costs are tracked via span attributes and the CostTracker. OTel metrics (e.g., `gen_ai.client.token.usage` histogram) are deferred to P2.
- **Self-diagnosis**: If `OTEL_ENABLED=true` but the OTel SDK fails to import, the system logs: `WARNING - OpenTelemetry SDK not available. Install opentelemetry-sdk to enable tracing.`

---

## 11. Test Requirements

### 11.1 Unit Tests

**Minimum coverage**: 80% code, 90% branch for new modules (`telemetry.py`, `cost_tracker.py`).

#### `test_cost_tracker.py`

- `CostTracker.record_llm_call()` calculates correct cost for known model
- `CostTracker.record_llm_call()` uses zero cost for unknown model and logs WARNING
- `CostTracker.get_summary()` aggregates per-model, per-topic, per-phase correctly
- `CostTracker.record_llm_call()` is thread-safe (concurrent calls from multiple threads)
- Cost budget exceeded triggers WARNING log
- Cost budget None means no warning regardless of cost
- `get_cost_tracker()` returns no-op when not initialized
- `reset_cost_tracker()` clears global state

#### `test_telemetry.py`

- `init_telemetry()` with `OTEL_ENABLED=false` results in NoOp tracer
- `init_telemetry()` with no OTLP endpoint configures ConsoleSpanExporter
- `init_telemetry()` with OTLP endpoint configures OTLPSpanExporter
- `is_enabled()` returns correct state
- `traced_generate()` creates span with correct attributes (mock genai Client)
- `traced_generate()` handles missing `usage_metadata` gracefully
- `traced_generate()` records cost in CostTracker
- `traced_generate()` re-raises API exceptions after recording on span
- `shutdown_telemetry()` does not raise on timeout

#### `test_timing_otel.py`

- `before_agent_callback` creates span when telemetry enabled
- `before_agent_callback` skips span when telemetry disabled
- `after_agent_callback` ends span and detaches context
- `after_agent_callback` handles missing span gracefully
- Span parent-child relationships are correct for sequential agent execution
- Root agent span has correct attributes (topic_count, dry_run)

#### `test_logging_trace.py`

- `TraceContextFilter` sets trace_id/span_id from active span
- `TraceContextFilter` sets zero IDs when no active span
- Text log format includes trace and span IDs
- JSON log format includes trace_id and span_id fields

#### `test_config_pricing.py`

- `PricingConfig` validates with defaults
- `PricingConfig` validates with custom model pricing
- `PricingConfig` rejects negative prices
- `PricingConfig` rejects negative budget
- `AppSettings` includes pricing field with defaults

### 11.2 BDD / Acceptance Tests

```gherkin
Feature: Token Tracking on LLM Calls

  Scenario: Successful synthesis records token counts
    Given a pipeline configuration with 1 topic in deep mode
    And the LLM mock returns usage_metadata with prompt_token_count=1000 and candidates_token_count=500 and thoughts_token_count=200
    When the PerTopicSynthesizer agent completes
    Then the span "llm.generate:gemini-2.5-pro" has attribute gen_ai.usage.input_tokens = 1000
    And the span has attribute gen_ai.usage.output_tokens = 500
    And the span has attribute gen_ai.usage.thinking_tokens = 200

  Scenario: Missing usage_metadata defaults to zero
    Given a pipeline configuration with 1 topic
    And the LLM mock returns a response with usage_metadata = None
    When the PerTopicSynthesizer agent completes
    Then the span "llm.generate:gemini-2.5-pro" has attribute gen_ai.usage.input_tokens = 0
    And a WARNING log contains "usage_metadata missing"

Feature: Cost Calculation

  Scenario: Cost computed correctly for gemini-2.5-pro
    Given pricing config with gemini-2.5-pro input_per_million=1.25 and output_per_million=10.00
    And an LLM call with prompt_tokens=10000, completion_tokens=2000, thinking_tokens=500
    When cost is calculated
    Then input_cost_usd = 0.0125
    And output_cost_usd = 0.025
    And total_cost_usd = 0.0375

  Scenario: Unknown model uses zero cost
    Given pricing config without model "gemini-3.0-flash"
    And an LLM call with model "gemini-3.0-flash"
    When cost is calculated
    Then total_cost_usd = 0.0
    And a WARNING log contains "gemini-3.0-flash"

Feature: Cost Summary at Pipeline End

  Scenario: Summary includes per-topic breakdown
    Given a pipeline run with topics "AI Frameworks" and "Cloud Native"
    And 2 synthesis calls (one per topic) complete with tracked costs
    When the pipeline finishes
    Then the cost summary log contains per_topic with keys "AI Frameworks" and "Cloud Native"
    And total_cost_usd equals the sum of both topic costs

  Scenario: Empty run produces zero summary
    Given a pipeline run where no LLM calls succeed
    When the pipeline finishes
    Then the cost summary log contains total_cost_usd = 0.0 and call_count = 0

Feature: Span Hierarchy

  Scenario: Agent spans form correct tree
    Given a pipeline with 1 topic in standard mode
    When the pipeline completes
    Then span "NewsletterPipeline" is the root span (no parent)
    And span "ResearchPhase" has parent "NewsletterPipeline"
    And span "Topic0Research" has parent "ResearchPhase"

  Scenario: Failed agent span records error
    Given a pipeline where PerTopicSynthesizer raises an exception
    When the pipeline completes
    Then the span "PerTopicSynthesizer" has status ERROR
    And the span has an exception event

Feature: Log-Trace Correlation

  Scenario: Log lines include trace context
    Given OTEL_ENABLED=true and a pipeline is running
    When a log message is emitted from the newsletter_agent namespace
    Then the log line contains a 32-character hex trace_id matching the root span

  Scenario: Disabled telemetry produces zero trace IDs
    Given OTEL_ENABLED=false
    When a log message is emitted
    Then the log line contains trace=00000000000000000000000000000000

Feature: Export Configuration

  Scenario: Console export when no OTLP endpoint
    Given OTEL_EXPORTER_OTLP_ENDPOINT is not set
    When telemetry initializes
    Then ConsoleSpanExporter is configured
    And spans are written to stdout

  Scenario: OTLP export when endpoint is set
    Given OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
    When telemetry initializes
    Then OTLPSpanExporter is configured with endpoint http://localhost:4317

Feature: Cost Budget Warning

  Scenario: Budget exceeded logs warning
    Given cost_budget_usd = 0.01
    And accumulated cost is 0.009
    When an LLM call adds 0.005 to the cost
    Then a WARNING log contains "Cost budget exceeded"
    And the pipeline continues running

  Scenario: No budget means no warning
    Given cost_budget_usd is null
    And accumulated cost is 100.0
    When another LLM call completes
    Then no budget warning is logged

Feature: Telemetry Kill Switch

  Scenario: Disabled telemetry has no overhead
    Given OTEL_ENABLED=false
    When the pipeline runs
    Then no spans are created
    And no cost tracking occurs
    And the pipeline produces identical output to a non-instrumented run
```

### 11.3 Integration Tests

- **OTel end-to-end**: Run pipeline with mocked LLM calls, capture spans via `InMemorySpanExporter`, assert span tree structure and attributes.
- **Cost pipeline**: Run pipeline with mocked LLM returning known token counts, assert cost summary values are mathematically correct.
- **Config loading**: Load `topics.yaml` with pricing section, verify `PricingConfig` is parsed and `CostTracker` is initialized with correct pricing.
- **Mock dependencies**: All genai API calls mocked. No real LLM calls in integration tests.
- **Teardown**: Each test calls `reset_cost_tracker()` and resets the global TracerProvider.

### 11.4 End-to-End Tests

- **Local smoke test**: Run `python -m newsletter_agent` with 1 topic, dry_run=true, verify console output includes span data and cost summary.
- **Target environment**: Local development only. E2E with real Cloud Trace deferred to deployment validation.

### 11.5 Performance Tests

- **Benchmark**: Compare wall-clock time of pipeline run with OTel enabled vs. disabled, using mocked LLM calls. Assert overhead < 5%.
- **Span volume**: Run 5-topic deep-research pipeline, count total spans, assert < 500 per run.

### 11.6 Security Tests

- **No PII in spans**: Export all spans from a test run, assert no span attribute value contains prompt text, response text, email addresses, or API keys.
- **OTLP headers not logged**: Set `OTEL_EXPORTER_OTLP_HEADERS=Bearer secret-token`, run pipeline, grep all log output for "secret-token" and assert zero matches.

---

## 12. Constraints & Assumptions

### Constraints

- **Python 3.11+**: Required by project. OTel Python SDK supports 3.8+, no conflict.
- **No new runtime services**: Cannot require Jaeger, Prometheus, or any sidecar for P1. Console and OTLP-to-Cloud-Trace are the only export targets.
- **ADK callback interface**: Limited to `before_agent_callback`/`after_agent_callback` on the root agent. Cannot inject per-agent callbacks or modify ADK internals.
- **Single-process execution**: Pipeline runs in a single Python process. No distributed tracing context propagation needed between processes.
- **Existing test infrastructure**: Tests use `pytest` + `pytest-asyncio`. No new test frameworks.

### Assumptions

| # | Assumption | Risk if Wrong | Mitigation |
|---|-----------|---------------|------------|
| A1 | `response.usage_metadata` from `genai.Client().aio.models.generate_content()` contains `prompt_token_count`, `candidates_token_count`, `thoughts_token_count`, and `total_token_count` as integer fields. | Fields are named differently or absent for some response types. | Graceful fallback: `getattr(usage_metadata, field, 0)` with WARNING log. Verify with integration test against real API. |
| A2 | ADK `before_agent_callback`/`after_agent_callback` fire in correct nesting order (before parent, before child, after child, after parent) for SequentialAgent and ParallelAgent. | Callbacks fire in unexpected order, producing incorrect span hierarchy. | Write integration test with 3-level agent tree and assert span parent-child relationships. |
| A3 | Python `contextvars` propagation works correctly across `asyncio.create_task()` calls in ADK's `ParallelAgent`. | OTel context is lost in parallel tasks, producing flat span tree. | Python 3.11+ copies context to new tasks by default. Test with ParallelAgent + 2 children and verify parent-child spans. |
| A4 | GCP Cloud Trace accepts OTLP gRPC from Cloud Run without explicit authentication headers (uses workload identity). | Auth fails, spans not exported. | `opentelemetry-exporter-gcp-trace` package as fallback. Test in staging. |
| A5 | Gemini API pricing (gemini-2.5-flash: $0.30/$2.50, gemini-2.5-pro: $1.25/$10.00 per 1M tokens) remains stable during implementation. | Prices change, cost tracking is inaccurate. | Pricing is configurable in `topics.yaml`. Operator updates config when prices change. |
| A6 | `thoughts_token_count` is separate from `candidates_token_count` (not included in it). | Double-counting thinking tokens in cost calculation. | Verify with a real API call that `total_token_count == prompt_token_count + candidates_token_count + thoughts_token_count`. If not, adjust formula. |
| A7 | OTel Python SDK packages (`opentelemetry-api>=1.20.0`, `opentelemetry-sdk>=1.20.0`, `opentelemetry-exporter-otlp-proto-grpc>=1.20.0`) are compatible with Python 3.13. | Import errors or runtime failures. | Test import in Python 3.13 environment before implementation. Latest OTel SDK supports 3.8-3.13. |

---

## 13. Out of Scope

- **Prompt content in spans**: Full prompt/response text is never placed in span attributes or events. Only metadata (token counts, model, topic name).
- **Perplexity API cost tracking (P1)**: Perplexity calls go through `FunctionTool` invoked by LlmAgent. Instrumenting these requires either auto-instrumentation or modifying the tool function. Deferred to P2.
- **LlmAgent token tracking (P1)**: ADK's LlmAgent does not expose response metadata via callbacks. Token tracking for GoogleSearcher, PerplexitySearcher, and dynamically created Planner/Searcher/Analyzer agents requires auto-instrumentation. Deferred to P3.
- **OTel metrics (counters, histograms)**: P1 uses span attributes for all numeric data. Dedicated OTel metrics (e.g., `gen_ai.client.token.usage` histogram) are deferred to P2 when dashboard definitions are created.
- **Dashboards and alerting**: GCP Cloud Monitoring dashboard JSON and alert policies are P2.
- **Historical cost persistence**: Storing cost summaries in SQLite or GCS for trend analysis is P3.
- **Real-time streaming observability**: Pipeline is batch; near-real-time via span export is sufficient.
- **Multi-tenant cost attribution**: Single-operator system.
- **LLM response quality evaluation**: Separate concern from operational observability.
- **Replacing existing logging**: `logging_config.py` setup stays. OTel augments it.

---

## 14. Open Questions

| # | Question | Impact if Unresolved | Owner |
|---|---------|---------------------|-------|
| OQ-1 | Does `total_token_count` equal `prompt_token_count + candidates_token_count + thoughts_token_count`, or does `candidates_token_count` already include thinking tokens? | Cost formula may double-count or under-count tokens. | Implementer - verify with one real API call before finalizing cost formula. |
| OQ-2 | Does GCP Cloud Trace accept OTLP gRPC from Cloud Run without explicit auth, or does it require the `google-cloud-opentelemetry` resource detector? | Production export may fail silently. | Implementer - test in staging Cloud Run environment. |
| OQ-3 | Do ADK callbacks fire for dynamically created LlmAgents inside `DeepResearchOrchestrator._run_async_impl()`? The planner/searcher/analyzer are created and `run_async`'d within the BaseAgent's implementation. | Dynamically created agents may not get spans. | Implementer - test with a minimal BaseAgent that creates and runs an inner LlmAgent. If callbacks don't fire, add manual span creation in DeepResearchOrchestrator. |

---

## 15. Glossary

- **ADK**: Google Agent Development Kit - the framework used to build the multi-agent pipeline.
- **BaseAgent**: ADK agent type that requires manual `_run_async_impl()`. Full control over execution, including direct LLM calls.
- **LlmAgent**: ADK agent type that automatically manages LLM interactions. Acts as a black box for token/cost tracking.
- **OTel**: OpenTelemetry - vendor-neutral observability framework for traces, metrics, and logs.
- **OTLP**: OpenTelemetry Protocol - the standard wire protocol for exporting telemetry data.
- **Span**: A unit of work in a distributed trace. Has a name, start/end time, attributes, and parent.
- **TracerProvider**: OTel component that creates Tracer instances and manages span export.
- **BatchSpanProcessor**: OTel component that batches spans and exports them asynchronously.
- **ConsoleSpanExporter**: OTel exporter that writes spans to stdout for local development.
- **usage_metadata**: Gemini API response field containing token counts for the request and response.
- **gen_ai.* semantic conventions**: OpenTelemetry standard attribute names for generative AI operations.
- **CostTracker**: New module that accumulates LLM call costs within a pipeline run.
- **NoOpTracerProvider**: OTel provider that creates no-op spans, used when telemetry is disabled.

---

## 16. Traceability Matrix

| FR ID | Requirement Summary | User Story | Acceptance Scenario | Test Type | Test Section Ref |
|-------|-------------------|------------|--------------------|-----------|----|
| FR-101 | Initialize TracerProvider at import time | US-03, US-05 | US-05 Scenario 1, 2 | unit | 11.1 (test_telemetry.py) |
| FR-102 | OTEL_ENABLED kill switch | US-07 | US-07 Scenario 1, 2 | unit | 11.1 (test_telemetry.py) |
| FR-103 | OTEL_SERVICE_NAME configuration | US-05 | US-05 Scenario 1 | unit | 11.1 (test_telemetry.py) |
| FR-104 | service.version from pyproject.toml | US-05 | US-05 Scenario 1 | unit | 11.1 (test_telemetry.py) |
| FR-105 | deployment.environment detection | US-05 | US-05 Scenario 1 | unit | 11.1 (test_telemetry.py) |
| FR-106 | shutdown_telemetry at pipeline end | US-03, US-05 | US-03 Scenario 1 | unit | 11.1 (test_telemetry.py) |
| FR-201 | OTel span for every agent via callbacks | US-03 | US-03 Scenario 1, 2 | unit, integration | 11.1 (test_timing_otel.py), 11.3 |
| FR-202 | Correct parent-child span hierarchy | US-03 | US-03 Scenario 1 | integration | 11.3 |
| FR-203 | duration_seconds span attribute | US-03 | US-03 Scenario 1 | unit | 11.1 (test_timing_otel.py) |
| FR-204 | Concurrent span storage by phase key | US-03 | US-03 Scenario 1 | unit | 11.1 (test_timing_otel.py) |
| FR-205 | Root agent span attributes | US-03 | US-03 Scenario 1 | unit | 11.1 (test_timing_otel.py) |
| FR-206 | Topic-scoped agent span attributes | US-03 | US-03 Scenario 1 | unit | 11.1 (test_timing_otel.py) |
| FR-207 | Preserve existing timing functionality | US-03 | US-03 Scenario 1 | unit | 11.1 (test_timing_otel.py) |
| FR-208 | ConfigLoaderAgent initializes CostTracker | US-02 | US-02 Scenario 1 | integration | 11.3 |
| FR-301 | Extract token counts from usage_metadata | US-01 | US-01 Scenario 1, 2 | unit | 11.1 (test_telemetry.py) |
| FR-302 | Instrument direct genai calls | US-01 | US-01 Scenario 1 | unit, integration | 11.1 (test_telemetry.py), 11.3 |
| FR-303 | traced_generate() helper function | US-01 | US-01 Scenario 1, 2 | unit | 11.1 (test_telemetry.py) |
| FR-304 | LlmAgent limitation documented | US-01 | N/A (non-functional) | unit | 11.1 (test_timing_otel.py) |
| FR-401 | Cost calculation formula | US-02 | US-02 Scenario 1 | unit | 11.1 (test_cost_tracker.py) |
| FR-402 | Cost attributes on LLM spans | US-02 | US-02 Scenario 1 | unit | 11.1 (test_telemetry.py) |
| FR-403 | Configurable per-model pricing | US-02, US-06 | US-02 Scenario 1 | unit | 11.1 (test_cost_tracker.py, test_config_pricing.py) |
| FR-404 | Unknown model zero cost fallback | US-02 | US-02 Scenario 2 | unit | 11.1 (test_cost_tracker.py) |
| FR-405 | Thread-safe CostTracker | US-02 | Edge case: parallel | unit | 11.1 (test_cost_tracker.py) |
| FR-406 | Cost budget warning (P2) | US-06 | US-06 Scenario 1, 2 | unit | 11.1 (test_cost_tracker.py) |
| FR-501 | Cost summary log at pipeline end | US-02 | US-02 Scenario 1, 2 | integration | 11.3 |
| FR-502 | Cost summary as span event | US-02 | US-02 Scenario 1 | integration | 11.3 |
| FR-503 | state["run_cost_usd"] | US-02 | US-02 Scenario 1 | integration | 11.3 |
| FR-504 | state["cost_summary"] | US-02 | US-02 Scenario 1 | integration | 11.3 |
| FR-601 | PricingConfig in AppSettings | US-02, US-06 | US-06 Scenario 1 | unit | 11.1 (test_config_pricing.py) |
| FR-602 | OTLP export when endpoint set | US-05 | US-05 Scenario 1 | unit | 11.1 (test_telemetry.py) |
| FR-603 | Console export when no endpoint | US-05 | US-05 Scenario 2 | unit | 11.1 (test_telemetry.py) |
| FR-604 | Dual export in dev mode | US-05 | US-05 Scenario 1, 2 | unit | 11.1 (test_telemetry.py) |
| FR-605 | .env.example updated | US-05 | N/A (documentation) | manual | N/A |
| FR-701 | TraceContextFilter | US-04 | US-04 Scenario 1, 2 | unit | 11.1 (test_logging_trace.py) |
| FR-702 | Text log format with trace IDs | US-04 | US-04 Scenario 1 | unit | 11.1 (test_logging_trace.py) |
| FR-703 | JSON log format with trace IDs | US-04 | US-04 Scenario 1 | unit | 11.1 (test_logging_trace.py) |
| FR-704 | Backwards-compatible log format | US-04 | US-04 Scenario 2 | unit | 11.1 (test_logging_trace.py) |

**Validation**: Every FR maps to at least one US. Every US maps to at least one acceptance scenario. Every acceptance scenario maps to a test type and section reference.

---

## 17. Technical References

### Architecture & Patterns
- OpenTelemetry Concepts: Traces, Spans, Context Propagation - https://opentelemetry.io/docs/concepts/ (consulted 2025-07-18)
- OpenTelemetry Python Manual Instrumentation - https://opentelemetry.io/docs/languages/python/instrumentation/ (consulted 2025-07-18)

### Technology Stack
- OpenTelemetry Python SDK Getting Started - https://opentelemetry.io/docs/languages/python/getting-started/ (consulted 2025-07-18)
- OpenTelemetry Python Exporters (OTLP, Console, Jaeger) - https://opentelemetry.io/docs/languages/python/exporters/ (consulted 2025-07-18)
- google-genai Python SDK Token Counting - https://ai.google.dev/gemini-api/docs/tokens?lang=python (consulted 2025-07-18)
- OpenTelemetry Semantic Conventions for GenAI - https://opentelemetry.io/docs/specs/semconv/gen-ai/ (consulted 2025-07-18)

### Pricing
- Gemini Developer API Pricing - https://ai.google.dev/gemini-api/docs/pricing (consulted 2025-07-18)
  - gemini-2.5-flash: $0.30 input / $2.50 output per 1M tokens (paid tier)
  - gemini-2.5-pro: $1.25 input / $10.00 output per 1M tokens (paid tier, <=200k context)

### Security
- OWASP Top 10 2021 - https://owasp.org/Top10/ (consulted 2025-07-18)
  - A01:2021 Broken Access Control - N/A (no user auth in this feature)
  - A02:2021 Cryptographic Failures - N/A (no encryption added)
  - A03:2021 Injection - No new input processing; span attributes are typed, not interpolated

### Standards & Specifications
- OpenTelemetry Protocol (OTLP) Specification - https://opentelemetry.io/docs/specs/otlp/ (consulted 2025-07-18)
- GCP Cloud Trace OTLP Ingestion - https://cloud.google.com/trace/docs/setup/python-ot (consulted 2025-07-18)

---

## 18. Version History

| Version | Date | Author | Summary of Changes |
|---------|------|--------|--------------------|
| 1.0 | 2025-07-18 | Spec Architect | Initial specification. Self-review corrections: added FR-207 (preserve existing timing), clarified A6 (thinking vs candidates token relationship), added OQ-3 (dynamic LlmAgent callbacks), expanded error handling in traced_generate contract, added no-op CostTracker for disabled telemetry (US-07 Scenario 2). |
