# Observability, Cost Monitoring & Debug Tracing - Ideation Brief

## The Idea

Add comprehensive observability to the NewsletterAgent pipeline using OpenTelemetry, giving operators full visibility into what every agent does, how much each LLM call costs, and structured trace data that works both locally (console/Jaeger) and in production (GCP Cloud Trace). Every agent invocation becomes an OTel span with attributes for topic, provider, token counts, and cost. A run-level cost summary is logged at pipeline completion.

## Problem & Opportunity

The newsletter pipeline orchestrates 5+ topics across multiple LLM providers (Gemini Flash for research, Gemini Pro for synthesis/refinement), link verification, and email delivery. Today, when something goes wrong - a topic returns empty, costs spike, or an agent stalls - the only diagnostic tool is grepping a single flat log stream. There is:

- **No token or cost tracking at all.** The `response.usage_metadata` from every Gemini call is discarded. Operators have no idea how much a run costs or which topic/phase consumes the most.
- **No distributed tracing.** There are no trace IDs, no span hierarchy, no way to correlate a synthesis failure back to the specific research round that produced bad data.
- **No per-agent structured debugging.** All agents log to one stream via `logging.getLogger(__name__)`. Isolating what happened in `DeepResearch_2_google round 3` requires manual grep-fu.
- **No latency breakdown.** Only coarse agent-phase timing exists (`timing.py`). Per-LLM-call, per-HTTP-request, and per-round latencies are invisible.

This matters because the pipeline runs unattended (Cloud Run scheduler) and processes real content for delivery. Without observability, failures are discovered after the fact from the output HTML, and cost overruns are invisible until the GCP billing page.

## Competitive Landscape

### Existing LLM observability tools

| Tool | Stars | Approach | Gemini Support | Fit for this project |
|------|-------|----------|----------------|---------------------|
| **OpenLLMetry** (Traceloop) | 6.9k | OTel instrumentation for LLM providers. Auto-instruments google-generativeai, Vertex AI. Exports to any OTel backend. | Yes - dedicated Gemini instrumentation | Strong. Pure OTel, no vendor lock-in. Can auto-instrument `genai.Client()` calls. Apache 2.0. |
| **Pydantic Logfire** | 4.1k | OTel wrapper with dedicated google_genai integration. Rich Python-centric dashboard. | Yes - first-class integration | Good UI but SaaS dependency. Enterprise self-host costs money. |
| **Arize Phoenix** | Large | Open-source local trace viewer with eval support. OTel-based via OpenInference. | Yes - via instrumentation | Heavier footprint (local server). Best for teams doing evals/fine-tuning. |
| **LangSmith** (LangChain) | N/A | SaaS tracing for LangChain/LangGraph apps. | Limited - not designed for ADK | Wrong framework. Would require manual integration. |
| **GCP Cloud Trace** | N/A | Google's managed tracing service. Native OTel OTLP ingestion. | N/A (infrastructure) | Natural fit for production on Cloud Run. Free tier: 2.5M spans/month. |

**Differentiation:** This project uses Google ADK (not LangChain or LlamaIndex), so framework-level auto-instrumentation from OpenLLMetry or Phoenix will not cover the orchestration layer. The best approach is: use OpenLLMetry for Gemini API call instrumentation (token counts, latency) and add manual OTel spans for the ADK agent lifecycle. This gives both low-level LLM visibility and high-level pipeline tracing.

### How users currently debug LLM agent systems

Forum threads (Reddit r/LocalLLaMA, r/MachineLearning, GitHub Issues on ADK repos) consistently surface these frustrations:
- "I have no idea why my agent decided to do X" - lack of decision tracing
- "My costs doubled and I don't know which prompt caused it" - no per-call cost attribution
- "Debugging multi-agent is like debugging microservices without distributed tracing" - the analogy is exact

## Vision

After this feature ships, an operator can:
1. Run the pipeline locally and see a structured trace in the console showing the full span tree: pipeline > research_phase > topic_0 > deep_research_round_1 > gemini_call, with token counts and costs on each span.
2. Deploy to Cloud Run and see the same spans in GCP Cloud Trace, searchable by topic name, provider, cost, or error status.
3. Open a cost summary at the end of each run showing total tokens (input/output), total cost in USD, and a per-topic breakdown.
4. Filter spans by agent name, topic index, or provider to isolate exactly what happened in any part of the pipeline.

## Target Users

- **Primary:** The newsletter operator (you) - needs to understand costs, debug failures, and tune the pipeline without reading raw logs.
- **Secondary:** Future contributors - need structured trace data to understand multi-agent flow when modifying or extending the pipeline.

## Core Value Proposition

Full visibility into every LLM call, every agent decision, and every dollar spent - without changing how the pipeline runs.

## Key Capabilities

### P1 - Must-Have (MVP)

- **Token tracking on every LLM call:** Extract `usage_metadata` (input_tokens, output_tokens, total_tokens) from every `genai.Client().aio.models.generate_content()` response. Store on OTel span attributes following the `gen_ai.*` semantic conventions.
- **Cost calculation per call:** Compute USD cost from token counts using configurable price-per-token rates (Gemini Flash vs Pro have different pricing). Attach `gen_ai.cost.usd` attribute to each span.
- **OTel span hierarchy for the pipeline:** Wrap each BaseAgent/LlmAgent execution in an OTel span. Parent-child relationships mirror the agent tree: pipeline > phase > topic > round > llm_call. Span attributes include: agent name, topic index, topic name, provider, round number.
- **Run-level cost summary:** At pipeline completion, log a structured cost summary: total tokens, total cost, per-topic cost breakdown, per-phase cost breakdown (research vs synthesis vs refinement vs verification).
- **Dual export: console + OTLP:** Locally, export spans to console (human-readable trace tree). In production, export via OTLP to any backend (GCP Cloud Trace, Jaeger, etc). Controlled by env vars (`OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`).
- **Logging bridge to OTel:** Bridge existing `logging.getLogger()` calls into OTel log records so they appear as span events in the trace, preserving the current log investment.

### P2 - Important (next increment)

- **Per-provider cost dashboards:** Pre-built GCP Cloud Monitoring dashboard definition (JSON/Terraform) showing cost trends over time, cost-per-topic, and anomaly detection.
- **Cost budget warnings:** Configurable per-run cost threshold in `topics.yaml`. Log a WARNING when exceeded (no hard abort per user preference). State key `run_cost_usd` available for downstream agents.
- **Perplexity and external API span instrumentation:** Wrap `search_perplexity()` and `verify_urls()` calls in spans with request/response size, status code, and latency.
- **Trace context propagation for HTTP handler:** When triggered by Cloud Scheduler, propagate the incoming trace context through the pipeline so the full request lifecycle is one trace.

### P3 - Nice-to-Have (future)

- **Auto-instrumentation via OpenLLMetry:** Add `opentelemetry-instrumentation-google-generativeai` for automatic Gemini call instrumentation, reducing manual code. Evaluate fit with ADK's internal call patterns.
- **Trace-based alerting:** Cloud Monitoring alerts when a span error rate exceeds threshold or latency spikes.
- **Historical cost tracking:** Persist per-run cost summaries to a local SQLite or GCS file for trend analysis across runs.
- **Interactive local trace viewer:** Lightweight local Jaeger or Zipkin instance via Docker Compose for visual trace exploration during development.

## Out of Scope

- **Prompt content logging in traces:** Sending full prompt text to OTel backends raises privacy/size concerns. Only metadata (token counts, model name, topic name) goes into spans. Full prompts remain in local logs only.
- **Real-time streaming dashboards:** This is a batch pipeline, not a live service. Near-real-time is sufficient.
- **Multi-tenant cost attribution:** Single-operator system. No per-user or per-team cost splitting.
- **LLM response quality evaluation/scoring:** That is a separate concern (eval frameworks like Phoenix evals). This feature is strictly operational observability.
- **Changing the existing logging infrastructure:** The current `logging_config.py` setup stays. OTel augments it, does not replace it.

## Assumptions & Risks

| Assumption | Risk if wrong | Mitigation |
|-----------|---------------|------------|
| Gemini API responses include `usage_metadata` with token counts | Some response types or error paths may not include it | Graceful fallback: log a warning and set tokens to 0. Verify with integration test. |
| OTel Python SDK overhead is negligible for a batch pipeline | Span creation adds measurable latency | OTel SDK is designed for production. Batch span export is async. Benchmark before/after. |
| Gemini pricing is stable enough for hardcoded rates | Google changes pricing | Make rates configurable in `topics.yaml` under a `pricing` section. Update as needed. |
| GCP Cloud Trace accepts OTLP directly from Cloud Run | Networking or auth issues | GCP Cloud Trace has native OTLP support. Fall back to `google-cloud-trace-exporter` if needed. |
| ADK does not interfere with OTel context propagation | ADK's internal async patterns may break context | Manual context propagation in BaseAgent subclasses. Test with a simple 2-agent pipeline first. |

## Technical Feasibility

- **OTel Python SDK** (`opentelemetry-api`, `opentelemetry-sdk`) is stable (v1.x). Supports Python 3.9+. Our project uses 3.13.
- **Span creation in BaseAgent:** All custom agents (`PerTopicSynthesizerAgent`, `DeepResearchOrchestrator`, `LinkVerifierAgent`, etc.) are `BaseAgent` subclasses with `_run_async_impl`. Wrapping in `tracer.start_as_current_span()` is straightforward.
- **Token extraction:** `google.genai` responses have `.usage_metadata.prompt_token_count` and `.usage_metadata.candidates_token_count`. Already available - just not read.
- **LlmAgent instrumentation:** ADK's `LlmAgent` is a black box - we cannot easily wrap its internal LLM calls. Options: (a) use OpenLLMetry auto-instrumentation for the genai client, or (b) use ADK callbacks (`before_agent_callback`/`after_agent_callback`) which already exist in `timing.py`.
- **Export:** `opentelemetry-exporter-otlp-proto-grpc` for production OTLP export. `opentelemetry-sdk` ConsoleSpanExporter for local dev. Conditional setup based on env vars.
- **Key constraint:** The ADK `LlmAgent` (used for standard-mode research) makes internal Gemini calls that we cannot directly wrap. For these, OpenLLMetry auto-instrumentation or ADK callbacks are the only options. For `BaseAgent` subclasses that call `genai.Client()` directly (synthesizer, refiner, deep research), we have full control.

## Open Questions

1. **ADK callback access to response metadata:** Do `after_agent_callback` functions receive the LLM response object (with usage_metadata), or only the agent event? If only the event, token tracking for `LlmAgent`-based agents requires auto-instrumentation.
2. **OpenLLMetry + ADK compatibility:** Has anyone tested `opentelemetry-instrumentation-google-generativeai` with ADK's internal Gemini client? Need a spike to verify no conflicts.
3. **Gemini pricing tiers:** Should pricing differentiate between Gemini 2.5 Flash (research) and Gemini 2.5 Pro (synthesis), or use a blended rate? Current Gemini API pricing may differ from Vertex AI pricing.
4. **Span volume in GCP free tier:** A deep-research run with 5 topics x 4 rounds x 2 providers could generate 100+ spans per run. At 1 run/day, that is well within GCP Cloud Trace free tier (2.5M spans/month). But if frequency increases, verify limits.

## Next Step

Hand off to the **Spec Architect** agent to translate this brief into a full, implementation-ready specification covering OTel setup, token extraction patterns, span hierarchy design, cost calculation logic, export configuration, and test strategy.
