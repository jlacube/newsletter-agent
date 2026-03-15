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

### `SynthesisPostProcessorAgent`

Parses the synthesis LLM output into structured state keys.

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

Custom BaseAgent that orchestrates multi-round deep research for topics with `search_depth: "deep"`. Replaces the single LlmAgent in the research phase.

**Module**: `newsletter_agent.tools.deep_research`

**Parameters**:
- `topic_idx` (int) -- Topic index in config
- `provider` (str) -- `"google"` or `"perplexity"`
- `query` (str) -- Original topic search query
- `topic_name` (str) -- Topic display name
- `max_rounds` (int) -- Maximum research rounds (from `settings.max_research_rounds`)
- `search_depth` (str) -- Always `"deep"` when this agent is used
- `model` (str) -- LLM model name (e.g., `"gemini-2.5-flash"`)
- `tools` (list) -- Search tools for sub-agents (google_search or search_perplexity)

**Behavior**:
1. When `max_rounds > 1`: invokes an internal QueryExpanderAgent (LlmAgent) to generate `max_rounds - 1` query variants
2. Executes up to `max_rounds` search rounds (round 0 uses original query, subsequent rounds use variants)
3. After each round, extracts URLs and tracks accumulation
4. Exits early if 15+ unique URLs are accumulated
5. Merges all round results (summaries and deduplicated sources) into a single output
6. Writes merged result to `research_{idx}_{provider}` (same key as standard mode)
7. Cleans up all intermediate state keys

**State keys written** (intermediate, cleaned up after merge):
- `deep_queries_{idx}_{provider}` -- Query expansion output
- `deep_research_latest_{idx}_{provider}` -- Latest round output
- `deep_query_current_{idx}_{provider}` -- Current round query
- `research_{idx}_{provider}_round_{N}` -- Per-round output
- `deep_urls_accumulated_{idx}_{provider}` -- Accumulated URL list

**State keys written** (final):
- `research_{idx}_{provider}` (str) -- Merged research output (same as standard mode)

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

Builds the complete agent pipeline from a validated config. Returns the root `SequentialAgent` with 7 sub-agents.

### `build_research_phase(config: NewsletterConfig) -> ParallelAgent`

Builds the research phase `ParallelAgent` with one `SequentialAgent` per topic. For topics with `search_depth: "standard"`, creates `LlmAgent` instances per provider. For topics with `search_depth: "deep"`, creates `DeepResearchOrchestrator` instances per provider that perform multi-round search with query expansion.

### `build_synthesis_agent(config: NewsletterConfig) -> LlmAgent`

Builds the synthesis `LlmAgent` with Gemini Pro model.
