# API Reference

## HTTP Endpoint

### POST /run

Triggers a full newsletter generation cycle. Designed to be called by Cloud Scheduler or manually via `curl`.

**Handler**: `newsletter_agent.http_handler.run_pipeline()`

**Request**: Empty body (no parameters required).

**Responses**:

| Status | Condition | Body |
|--------|-----------|------|
| 200 | Pipeline completed (email sent) | `{"status": "success", "newsletter_date": "...", "topics_processed": N, "email_sent": true}` |
| 200 | Pipeline completed (dry-run) | `{"status": "success", "newsletter_date": "...", "topics_processed": N, "email_sent": false, "output_file": "..."}` |
| 500 | Pipeline failed | `{"status": "error", "message": "..."}` |

## CLI Entry Point

### `python -m newsletter_agent`

Runs the full pipeline autonomously without interactive input. Sends a `"Generate newsletter"` trigger message using ADK's `Runner` and `InMemorySessionService`.

**Module**: `newsletter_agent/__main__.py`

**Exit codes**:

| Code | Condition |
|------|-----------|
| 0 | Pipeline completed successfully |
| 1 | Any exception or pipeline failure |

**Stdout output**: A single JSON line with the pipeline summary:

- On success: `{"status": "success", "newsletter_date": "...", "topics_processed": N, "email_sent": true/false}`
- On dry-run success: adds `"output_file": "..."` to the above
- On failure: `{"status": "error", "message": "..."}`

### `main() -> int`

Synchronous entry point. Sets up logging, runs the async pipeline via `asyncio.run()`, and returns an exit code (0 or 1).

### `run_pipeline() -> dict`

Async function that creates an ADK `Runner`, sends the trigger message, consumes all events, and returns the final session state as a dict.

## Configuration Models

### `NewsletterConfig`

Top-level configuration model.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `newsletter` | `NewsletterSettings` | Yes | Newsletter metadata |
| `settings` | `AppSettings` | No | Application settings (defaults applied) |
| `topics` | `list[TopicConfig]` | Yes | 1-20 topic definitions |

### `NewsletterSettings`

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `title` | `str` | 1-200 chars | Newsletter display title |
| `schedule` | `str` | Non-empty | Cron expression |
| `recipient_emails` | `list[str]` | 1-10 unique valid emails | Delivery targets |
| `recipient_email` | `str` | Valid email format | Deprecated alias (single recipient) |

### `AppSettings`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | Save HTML only (no email) |
| `output_dir` | `str` | `"output/"` | Output directory path |
| `timeframe` | `str \| None` | `None` | Global search timeframe constraint |
| `verify_links` | `bool` | `False` | Verify source URLs and remove broken links |
| `max_research_rounds` | `int` | `3` | Research rounds for deep-mode topics (1-5) |
| `max_searches_per_topic` | `int \| None` | Same as `max_research_rounds` | Search budget per topic-provider (1-15). Defaults to `max_research_rounds` if omitted. |
| `min_research_rounds` | `int` | `2` | Minimum rounds before saturation exit (1-3). Must be <= `max_research_rounds`. |

### `TopicConfig`

| Field | Type | Default | Constraints | Description |
|-------|------|---------|-------------|-------------|
| `name` | `str` | -- | 1-100 chars | Unique topic name |
| `query` | `str` | -- | 1-500 chars | Search query |
| `search_depth` | `str` | `"standard"` | `"standard"` or `"deep"` | Research depth |
| `sources` | `list[str]` | `["google_search", "perplexity"]` | Valid provider names | Search providers |

### `load_config(path: str) -> NewsletterConfig`

Loads and validates a YAML configuration file.

**Parameters**: `path` -- Path to the YAML file (default: `"config/topics.yaml"`)

**Returns**: Validated `NewsletterConfig` instance.

**Raises**:
- `FileNotFoundError` if the file does not exist
- `ConfigValidationError` if YAML is invalid or validation fails

## Custom Agents

### `ConfigLoaderAgent`

Populates session state with config values at pipeline start.

**State keys written**:
- `config_newsletter_title` (str)
- `config_recipient_emails` (list[str]) - all recipient addresses
- `config_recipient_email` (str) - first recipient (backward compat)
- `config_dry_run` (bool)
- `config_output_dir` (str)

### `ResearchValidatorAgent`

Checks research state keys after the research phase completes.

**Parameters**:
- `topic_count` (int) -- Number of topics
- `providers` (list) -- Provider names to check

**State keys written**:
- `research_all_failed` (bool)

### `PipelineAbortCheckAgent`

Aborts the pipeline if all research failed.

**Reads**: `research_all_failed`, `config_output_dir`

**Behavior**: If `research_all_failed` is True, saves an error HTML page and raises `RuntimeError`.

### `LinkVerifierAgent`

Pre-synthesis agent that verifies source URLs in research results. Runs before synthesis so the LLM only sees verified, accessible sources.

**Parameters**:
- `topic_count` (int) -- Number of topics to check
- `providers` (list) -- Provider names (e.g. `["google", "perplexity"]`)

**Reads**: `config_verify_links`, `research_N_{provider}` state keys

**Behavior**: When `config_verify_links` is True, extracts markdown link URLs from research text, verifies them concurrently via HTTP HEAD/GET, and removes broken links from the research text. No-ops when `config_verify_links` is False.

### `PerTopicSynthesizerAgent`

Synthesizes each topic independently and writes structured section state directly.

**Module**: `newsletter_agent.tools.per_topic_synthesizer`

**Parameters**:
- `topic_names` (list[str]) -- Topic display names in config order
- `providers` (list[str]) -- Provider names to read from research state

**Reads**: `research_N_{provider}` state keys

**State keys written**:
- `synthesis_N` (dict with `title`, `body_markdown`, `sources`)
- `executive_summary` (list of dicts with `topic`, `summary`)
- `config_topic_count` (int)

**Behavior**: Builds one Gemini Pro prompt per topic, calls `traced_generate()` once per topic, parses the returned JSON, and writes synthesis results directly without using a single shared `synthesis_raw` key in the live runtime pipeline.

### `SynthesisLinkVerifierAgent`

Post-synthesis link verifier that validates URLs embedded in synthesized sections.

**Parameters**:
- `topic_count` (int) -- Number of topics to check

**Reads**: `config_verify_links`, `synthesis_N` state keys

**Behavior**: When `config_verify_links` is True, verifies links in section markdown and source lists, removes broken URLs, and leaves title text intact. No-ops when link verification is disabled.

### `SynthesisPostProcessorAgent`

Legacy helper retained for compatibility and tests. It parses a monolithic `synthesis_raw` payload into structured state keys, but it is not wired into the current root pipeline.

**Parameters**:
- `topic_names` (list) -- Expected topic names

**Reads**: `synthesis_raw`

**State keys written**:
- `synthesis_N` (dict with `title`, `body_markdown`, `sources`)
- `executive_summary` (list of dicts with `topic`, `summary`)
- `config_topic_count` (int)

### `FormatterAgent`

Renders the newsletter HTML from synthesis state.

**Reads**: `config_newsletter_title`, `config_topic_count`, `pipeline_start_time`, `synthesis_N`, `executive_summary`

**State keys written**:
- `newsletter_html` (str)
- `newsletter_metadata` (dict with `title`, `date`, `topic_count`, `generation_time_seconds`)

### `DeliveryAgent`

Delivers the newsletter via email or saves to disk.

**Reads**: `newsletter_html`, `newsletter_metadata`, `config_dry_run`, `config_output_dir`, `config_recipient_emails`, `config_recipient_email`

**State keys written**:
- `delivery_status` (dict with `status` and delivery details)

**Delivery status values**:
- `{"status": "dry_run", "output_file": "..."}` -- Saved to disk
- `{"status": "sent", "recipients": [...]}` -- All recipients succeeded
- `{"status": "partial", "recipients": [...], "fallback_file": "..."}` -- Some recipients failed
- `{"status": "failed", "fallback_file": "...", "error": "..."}` -- All failed, saved as fallback
- `{"status": "aborted", "error": "...", "fallback_file": "..."}` -- Pipeline aborted

### `DeepResearchOrchestrator`

Custom BaseAgent that orchestrates adaptive deep research for topics with `search_depth: "deep"`. Uses a Plan-Search-Analyze-Decide loop with LlmAgent sub-agents for planning, per-round searching, and analysis.

**Module**: `newsletter_agent.tools.deep_research`

**Parameters**:
- `topic_idx` (int) -- Topic index in config
- `provider` (str) -- `"google"` or `"perplexity"`
- `query` (str) -- Original topic search query
- `topic_name` (str) -- Topic display name
- `max_rounds` (int) -- Maximum research rounds (from `settings.max_research_rounds`)
- `max_searches` (int) -- Maximum search API calls per topic (from `settings.max_searches_per_topic`)
- `min_rounds` (int) -- Minimum rounds before saturation exit is allowed (from `settings.min_research_rounds`)
- `search_depth` (str) -- Always `"deep"` when this agent is used
- `model` (str) -- LLM model name (e.g., `"gemini-2.5-flash"`)
- `tools` (list) -- Search tools for sub-agents (google_search or search_perplexity)

**Behavior**:
1. When `max_rounds > 1`: invokes an internal PlanningAgent (LlmAgent) to identify key aspects and an initial search query
2. Executes up to `max_rounds` search rounds (round 0 uses planning query, subsequent rounds use AnalysisAgent-suggested queries)
3. After each search round (except single-round mode): invokes an AnalysisAgent to evaluate findings, identify knowledge gaps, and suggest the next query
4. **Exit criteria** (checked after each analysis):
   - `saturated == true` AND `round_count >= min_rounds` -> exit with reason `"saturation"`
   - `knowledge_gaps` is empty -> exit with reason `"full_coverage"`
   - `searches_done >= max_searches` -> exit with reason `"search_budget_exhausted"`
   - Loop completes without break -> `"max_rounds_reached"`
5. Duplicate query detection: appends a distinguishing suffix if a query was already used
6. Merges all round results (summaries and deduplicated sources) into a single output
7. Writes merged result to `research_{idx}_{provider}` (same key as standard mode)
8. Persists the reasoning chain and cleans up all intermediate state keys

**State keys written** (intermediate, cleaned up after merge):
- `adaptive_plan_{idx}_{provider}` -- PlanningAgent output
- `adaptive_analysis_{idx}_{provider}` -- AnalysisAgent output (latest round)
- `deep_research_latest_{idx}_{provider}` -- Latest search round output
- `research_{idx}_{provider}_round_{N}` -- Per-round output
- `deep_urls_accumulated_{idx}_{provider}` -- Accumulated URL list

**State keys written** (final, preserved):
- `research_{idx}_{provider}` (str) -- Merged research output (same as standard mode)
- `adaptive_reasoning_chain_{idx}_{provider}` (str) -- JSON reasoning chain with plan, per-round findings, and exit reason

### `DeepResearchRefinerAgent`

Custom BaseAgent that selects the 5-20 most relevant sources per deep-mode topic-provider combination using LLM-based relevance scoring. Runs after LinkVerifier and before PerTopicSynthesizer.

**Module**: `newsletter_agent.tools.deep_research_refiner`

**Parameters**:
- `topic_count` (int) -- Number of topics in config
- `providers` (list[str]) -- Provider names (e.g., `["google", "perplexity"]`)
- `topic_configs` (list[TopicConfig]) -- Full topic configs for `search_depth` check

**Behavior**:
1. Iterates over topics and providers. Skips standard-mode topics (no-op).
2. For deep-mode topics, extracts source URLs from `research_{idx}_{provider}`.
3. If source count < 5: keeps all sources (no LLM call).
4. If source count is 5-20: keeps all sources (already in target range).
5. If source count > 20: calls `gemini-2.5-flash` with refinement prompt to select best 5-20.
6. Filters SOURCES section in-place, preserving SUMMARY text.
7. Logs before/after source counts.

**Error handling**:
- LLM API failure: keeps all sources, logs warning.
- Invalid JSON response: keeps all sources, logs warning.
- Empty selection: keeps all sources, logs warning.
- LLM selects < 5 valid URLs: keeps all original sources.
- LLM selects > 20 URLs: truncates to first 20.

**State keys read/written**:
- `research_{idx}_{provider}` (str) -- Updated in-place with refined sources

### `get_refinement_instruction(topic_name, target_count, research_text, source_list) -> str`

Returns the LLM prompt for source refinement evaluation.

**Module**: `newsletter_agent.prompts.refinement`

**Parameters**:
- `topic_name` (str) -- Topic display name
- `target_count` (int) -- Target number of sources (5-10)
- `research_text` (str) -- SUMMARY text from research
- `source_list` (str) -- Current sources as text list

## Tool Functions

### `search_perplexity(query: str, search_depth: str) -> dict`

Searches the Perplexity Sonar API.

**Parameters**:
- `query` -- Natural language search query
- `search_depth` -- `"standard"` (sonar) or `"deep"` (sonar-pro)

**Returns**: `{"text": "...", "sources": [...], "provider": "perplexity"}` on success, or `{"error": True, "message": "...", "provider": "perplexity"}` on failure.

### `send_newsletter_email(html_content: str, recipient_email: str | list[str], subject: str) -> dict`

Sends an HTML email via Gmail API to one or more recipients.

**Returns** (single string): `{"status": "sent", "message_id": "..."}` or `{"status": "error", "error_message": "..."}`.

**Returns** (list): `{"status": "sent"|"partial"|"failed", "recipients": [{"email": "...", "status": "...", ...}, ...]}`.

### `save_newsletter_html(html_content: str, output_dir: str, newsletter_date: str) -> str`

Saves newsletter HTML to disk.

**Returns**: Absolute path of the saved file.

### `sanitize_synthesis_html(markdown_text: str) -> str`

Converts markdown to sanitized HTML. Allowed tags: `a`, `p`, `strong`, `em`, `ul`, `ol`, `li`, `h3`, `h4`, `br`. Only `http://` and `https://` URL schemes permitted.

### `parse_synthesis_output(raw_output: str, expected_topics: list[str]) -> dict`

Parses raw synthesis LLM output into structured state entries. Handles JSON, markdown-wrapped JSON, and plain text with graceful fallbacks. Never raises exceptions.

### `render_newsletter(template_data: dict) -> str`

Renders the Jinja2 HTML template with the provided data.

**Parameters**: Dict with `newsletter_title`, `newsletter_date`, `executive_summary`, `sections`, `all_sources`, `generation_time_seconds`.

## Pipeline Factory Functions

### `build_pipeline(config: NewsletterConfig) -> SequentialAgent`

Builds the complete live agent pipeline from a validated config. Returns the root `SequentialAgent` with 9 sub-agents: ConfigLoader, ResearchPhase, ResearchValidator, PipelineAbortCheck, LinkVerifier, DeepResearchRefiner, PerTopicSynthesizer, SynthesisLinkVerifier, OutputPhase.

### `build_research_phase(config: NewsletterConfig) -> ParallelAgent`

Builds the research phase `ParallelAgent` with one `SequentialAgent` per topic. For topics with `search_depth: "standard"`, creates `LlmAgent` instances per provider. For topics with `search_depth: "deep"`, creates `DeepResearchOrchestrator` instances per provider that perform adaptive multi-round search with planning and analysis sub-agents.

### `build_synthesis_agent(config: NewsletterConfig, providers: list[str]) -> LlmAgent`

Builds the legacy monolithic synthesis `LlmAgent` with Gemini Pro model. This helper is still present in code and tests, but the live root pipeline uses `PerTopicSynthesizerAgent` instead.

## Telemetry & Cost Tracking

### `traced_generate(model, contents, config, *, agent_name, topic_name, topic_index, phase) -> GenerateContentResponse`

Wraps `genai.Client().aio.models.generate_content()` with OTel span creation, token extraction, and cost recording.

**Module**: `newsletter_agent.telemetry`

**Parameters**:
- `model` (str) -- Gemini model name (e.g., `"gemini-2.5-pro"`)
- `contents` (str | list) -- Prompt contents
- `config` (GenerateContentConfig | None) -- Generation config
- `agent_name` (str) -- Calling agent name for attribution
- `topic_name` (str | None) -- Topic name (optional)
- `topic_index` (int | None) -- Topic index (optional)
- `phase` (str) -- Pipeline phase: `"research"`, `"synthesis"`, `"refinement"`, or `"unknown"`

**Behavior**: Creates an OTel span `llm.generate:{model}`, calls the Gemini API, extracts token counts from `usage_metadata`, sets `gen_ai.*` and `newsletter.cost.*` span attributes, records cost via `CostTracker`, and returns the response unchanged. When telemetry is disabled (`is_enabled() == False`), calls the API directly without instrumentation.

**Span attributes set**:
- `gen_ai.system`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.usage.thinking_tokens`, `gen_ai.usage.total_tokens`
- `newsletter.cost.input_usd`, `newsletter.cost.output_usd`, `newsletter.cost.total_usd`
- `newsletter.cost.pricing_missing` (True when model not in pricing config)
- `newsletter.agent.name`, `newsletter.phase`, `newsletter.topic.name`, `newsletter.topic.index`

### `CostTracker`

Thread-safe accumulator for LLM call cost data.

**Module**: `newsletter_agent.cost_tracker`

**Constructor**: `CostTracker(pricing: dict[str, ModelPricing], cost_budget_usd: float | None = None)`

**Methods**:

| Method | Returns | Description |
|--------|---------|-------------|
| `record_llm_call(**kwargs)` | `LlmCallRecord` | Records an LLM call, computes cost, returns the record |
| `get_summary()` | `CostSummary` | Aggregates all calls into per-model/topic/phase summaries |
| `get_calls()` | `list[LlmCallRecord]` | Returns shallow copy of all recorded calls |
| `has_pricing(model)` | `bool` | Returns True if model has known pricing |

### Module-Level Functions (`cost_tracker.py`)

| Function | Description |
|----------|-------------|
| `init_cost_tracker(pricing, cost_budget_usd)` | Creates global `CostTracker` instance |
| `get_cost_tracker()` | Returns active tracker or silent no-op if not initialized |
| `reset_cost_tracker()` | Clears global tracker (test teardown) |

### Pipeline Timing Callbacks (`timing.py`)

**Module**: `newsletter_agent.timing`

Agent execution callbacks that record timing and create OTel spans with parent-child hierarchy.

| Function | Description |
|----------|-------------|
| `before_agent_callback(callback_context)` | Records start time, creates OTel span with attributes, attaches to context |
| `after_agent_callback(callback_context)` | Logs elapsed time, ends span, records cost summary (root agent only) |

**Module-level state**:
- `_phase_starts: dict[str, float]` -- Start times keyed by `"{invocation_id}:{agent_name}"`
- `_active_spans: dict[str, tuple]` -- Active (span, token) tuples keyed by same scheme

**Span attributes set per agent**:
- `newsletter.agent.name`, `newsletter.invocation_id`, `newsletter.duration_seconds`

**Root agent (`NewsletterPipeline`) additional attributes**:
- `newsletter.topic_count`, `newsletter.dry_run`, `newsletter.pipeline_start_time`

**Topic-scoped agents** (name matching `r'_(\d+)(?:_|$)'`):
- `newsletter.topic.index`, `newsletter.topic.name`

**LlmAgent-based agents** (GoogleSearcher, PerplexitySearcher, AdaptivePlanner, DeepSearchRound, AdaptiveAnalyzer):
- `gen_ai.tokens_available: false`

**Root agent completion side effects**:
- Logs structured JSON cost summary at INFO (`event: "pipeline_cost_summary"`)
- Records `cost_summary` span event with `total_cost_usd`, `total_input_tokens`, `total_output_tokens`, `call_count`
- Sets `state["run_cost_usd"]` and `state["cost_summary"]`

### `TraceContextFilter` (`logging_config.py`)

**Module**: `newsletter_agent.logging_config`

A `logging.Filter` subclass that injects `trace_id` and `span_id` from the current OTel span into every log record.

- Always returns `True` (does not filter out records)
- Sets `record.trace_id` (32-char lowercase hex) and `record.span_id` (16-char lowercase hex)
- When no active span or OTel unavailable: zero IDs (`"0" * 32` / `"0" * 16`)
- Attached to the `newsletter_agent` logger in `setup_logging()`
