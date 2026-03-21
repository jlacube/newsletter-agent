# Observability Guide

## Scope

This document covers the observability tranche delivered across the last four work packages:

- **WP19** - Telemetry foundation
- **WP20** - Cost tracking and direct LLM instrumentation
- **WP21** - Agent span hierarchy, log correlation, and run-level cost summary
- **WP22** - Acceptance, integration, performance, and security quality gates

It is the operational reference for tracing, debugging, and cost monitoring in Newsletter Agent.

## What Shipped

### WP19 - Telemetry Foundation

- OpenTelemetry SDK dependencies were added to the runtime environment.
- `newsletter_agent.telemetry` now owns initialization, shutdown, tracer access, and the telemetry kill switch.
- Telemetry is initialized during package import and shut down from both CLI and HTTP entry points.
- Pricing configuration was added to `settings.pricing` in `config/topics.yaml`.

### WP20 - Cost Tracking and LLM Instrumentation

- `newsletter_agent.cost_tracker` records direct Gemini call costs using per-model pricing.
- `traced_generate()` wraps the two direct Gemini call sites:
  - `newsletter_agent.tools.per_topic_synthesizer`
  - `newsletter_agent.tools.deep_research_refiner`
- Every direct Gemini call records token counts and USD cost on the child span.
- `ConfigLoaderAgent` initializes the global tracker from validated YAML pricing.

### WP21 - Span Hierarchy and Debug Correlation

- `before_agent_callback()` and `after_agent_callback()` create a span for every agent execution.
- The span tree mirrors the live pipeline hierarchy.
- All `newsletter_agent` log lines include `trace_id` and `span_id` through `TraceContextFilter`.
- The root pipeline span records a `cost_summary` event and writes `run_cost_usd` plus `cost_summary` into session state.

### WP22 - Quality Gate

- BDD, integration, security, and performance tests cover the observability feature set.
- The suite verifies token extraction, pricing, span hierarchy, log correlation, exporter selection, kill-switch behavior, and PII/secret handling.

## Runtime Architecture

The live root pipeline stages relevant to observability are:

1. `ConfigLoader`
2. `ResearchPhase`
3. `ResearchValidator`
4. `PipelineAbortCheck`
5. `LinkVerifier`
6. `DeepResearchRefiner`
7. `PerTopicSynthesizer`
8. `SynthesisLinkVerifier`
9. `OutputPhase`

Observability hooks are concentrated in these modules:

- `newsletter_agent.telemetry` - provider setup, kill switch, tracer access, direct LLM spans
- `newsletter_agent.timing` - agent-level spans and run summary
- `newsletter_agent.cost_tracker` - pricing, accumulation, summaries
- `newsletter_agent.logging_config` - trace/log correlation

## Environment and Configuration

### Telemetry Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `OTEL_ENABLED` | `true` | Disables tracing and cost tracking when set to `false` |
| `OTEL_SERVICE_NAME` | `newsletter-agent` | `service.name` resource attribute |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | empty | OTLP gRPC export target; empty means console-only export |
| `OTEL_EXPORTER_OTLP_HEADERS` | empty | OTLP auth headers, for example `Authorization=Bearer token` |
| `K_SERVICE` | unset locally | Marks Cloud Run and switches `deployment.environment` to `production` |

### Pricing Configuration

Pricing lives under `settings.pricing` in `config/topics.yaml`:

```yaml
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

If `cost_budget_usd` is set and a call pushes the run above budget, the system logs a warning and continues.

## Spans and Attributes

### Agent Spans

Every agent execution produces a span named after `callback_context.agent_name`.

Common attributes:

- `newsletter.agent.name`
- `newsletter.invocation_id`
- `newsletter.duration_seconds`

Root span attributes:

- `newsletter.topic_count`
- `newsletter.dry_run`
- `newsletter.pipeline_start_time`

Topic-scoped attributes:

- `newsletter.topic.index`
- `newsletter.topic.name`

Known LLM-agent spans that do not expose token counts in P1 set:

- `gen_ai.tokens_available: false`

### Direct LLM Call Spans

`traced_generate()` creates child spans named `llm.generate:{model}`.

Recorded attributes include:

- `gen_ai.system`
- `gen_ai.request.model`
- `gen_ai.usage.input_tokens`
- `gen_ai.usage.output_tokens`
- `gen_ai.usage.thinking_tokens`
- `gen_ai.usage.total_tokens`
- `newsletter.cost.input_usd`
- `newsletter.cost.output_usd`
- `newsletter.cost.total_usd`
- `newsletter.cost.pricing_missing` when pricing is unavailable for the model

## Cost Monitoring

### Cost Formula

Per-call cost is calculated as:

```text
input_cost  = prompt_tokens * input_per_million / 1_000_000
output_cost = (completion_tokens + thinking_tokens) * output_per_million / 1_000_000
total_cost  = input_cost + output_cost
```

### Run Summary

At root pipeline completion, the system:

- logs a structured JSON line with `event = "pipeline_cost_summary"`
- records a `cost_summary` span event on the root span
- stores `run_cost_usd` in session state
- stores `cost_summary` in session state

The log payload includes total tokens, total cost, call count, plus `per_model`, `per_topic`, and `per_phase` breakdowns.

## Logging and Debugging

All project logs use trace correlation:

```text
{timestamp} {level} {logger} [trace={trace_id} span={span_id}] {message}
```

When no active span exists, zero IDs are emitted.

### Practical Debug Flow

1. Find the `pipeline_cost_summary` log line for the run.
2. Use the `trace_id` on adjacent log lines to correlate the run in your trace backend or console exporter output.
3. Inspect the root `NewsletterPipeline` span.
4. Drill into child spans to isolate the slow or failing phase.
5. For direct Gemini calls, inspect the `llm.generate:*` spans for token and cost data.

### Common Questions

**Why do some agent spans lack token counts?**

ADK-managed `LlmAgent` responses do not expose raw `usage_metadata` in P1. Only direct Gemini call sites wrapped by `traced_generate()` expose token and cost attributes.

**Why can a run have tracing but zero cost?**

Only direct Gemini call sites are cost-instrumented. Agent spans still exist even when a path does not use those instrumented call sites.

## Acceptance Coverage

WP22 adds coverage in these areas:

- BDD tests for token tracking, cost calculation, cost summary, span hierarchy, log correlation, exporter config, budget warnings, and kill switch behavior
- integration tests for end-to-end observability wiring
- performance tests for tracing overhead and span counts
- security tests for PII and secret leakage

## Compliance Notes

The current docs, plans, runtime behavior, and observability tests are aligned for the WP19-WP22 tranche:

- `PerTopicSynthesizer` is the active synthesis stage in the root pipeline
- `SynthesisLinkVerifier` runs before formatting
- `cost_summary` state and log payloads use the spec-aligned public shape
- the SC-006 benchmark enforces the 5% threshold
- WP19-WP22 plan status is complete

## File Map

- `newsletter_agent/telemetry.py`
- `newsletter_agent/timing.py`
- `newsletter_agent/cost_tracker.py`
- `newsletter_agent/logging_config.py`
- `newsletter_agent/tools/per_topic_synthesizer.py`
- `newsletter_agent/tools/deep_research_refiner.py`
- `tests/bdd/test_token_tracking.py`
- `tests/bdd/test_cost_calculation.py`
- `tests/bdd/test_cost_summary.py`
- `tests/bdd/test_span_hierarchy.py`
- `tests/bdd/test_log_correlation.py`
- `tests/bdd/test_export_config.py`
- `tests/bdd/test_cost_budget.py`
- `tests/bdd/test_kill_switch.py`
- `tests/integration/test_observability.py`
- `tests/performance/test_otel_overhead.py`
- `tests/security/test_otel_security.py`