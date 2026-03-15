# Architecture

## System Overview

Newsletter Agent is a multi-agent pipeline built with Google Agent Development Kit (ADK). The system uses a `SequentialAgent` as its root, orchestrating research, synthesis, formatting, and delivery phases. Topics configured with `search_depth: "deep"` use an adaptive research orchestrator that follows a Plan-Search-Analyze-Decide loop: a PlanningAgent identifies key aspects and an initial search query, each round is followed by an AnalysisAgent that evaluates findings and suggests the next query, and the orchestrator exits when saturation is detected or configured limits are reached.

## Agent Pipeline

```
root_agent (SequentialAgent: "NewsletterPipeline")
|
+-- ConfigLoader (Custom BaseAgent)
|     Reads topics.yaml config and stores values in session state
|
+-- ResearchPhase (ParallelAgent)
|     For each topic, runs in parallel:
|     +-- TopicNResearch (SequentialAgent)
|           For standard-mode topics:
|           +-- GoogleSearcher_N (LlmAgent, gemini-2.5-flash)
|           |     tools: [google_search]
|           |     output_key: research_N_google
|           +-- PerplexitySearcher_N (LlmAgent, gemini-2.5-flash)
|                 tools: [search_perplexity FunctionTool]
|                 output_key: research_N_perplexity
|           For deep-mode topics (search_depth: "deep"):
|           +-- DeepResearch_N_google (DeepResearchOrchestrator)
|           |     Adaptive loop: Plan -> Search -> Analyze -> Decide
|           |     Sub-agents: AdaptivePlanner, DeepSearchRound, AdaptiveAnalyzer
|           |     output_key: research_N_google (merged)
|           +-- DeepResearch_N_perplexity (DeepResearchOrchestrator)
|                 Adaptive loop: Plan -> Search -> Analyze -> Decide
|                 Sub-agents: AdaptivePlanner, DeepSearchRound, AdaptiveAnalyzer
|                 output_key: research_N_perplexity (merged)
|
+-- ResearchValidator (Custom BaseAgent)
|     Checks all research state keys; sets research_all_failed if none succeeded
|
+-- PipelineAbortCheck (Custom BaseAgent)
|     Aborts pipeline with RuntimeError if all research failed (FR-013)
|
+-- LinkVerifier (Custom BaseAgent)
|     Verifies source URLs in research data; removes broken links before
|     synthesis when verify_links=true (no-ops otherwise)
|
+-- DeepResearchRefiner (Custom BaseAgent)
|     For deep-mode topics with >10 sources, uses LLM to select the
|     5-10 most relevant per provider. No-op for standard-mode topics.
|
+-- Synthesizer (LlmAgent, gemini-2.5-pro)
|     Reads all research_N_* from state (pre-verified when verify_links=true)
|     output_key: synthesis_raw
|
+-- SynthesisPostProcessor (Custom BaseAgent)
|     Parses synthesis_raw JSON into synthesis_N and executive_summary state keys
|
+-- OutputPhase (SequentialAgent)
      +-- FormatterAgent (Custom BaseAgent)
      |     Reads synthesis state, renders Jinja2 HTML template
      |     Stores newsletter_html and newsletter_metadata in state
      +-- DeliveryAgent (Custom BaseAgent)
            Reads newsletter_html, sends via Gmail or saves to disk
```

## Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Agent Framework | Google ADK (google-adk) | Multi-agent orchestration, Gemini integration |
| LLM - Research | Gemini 2.5 Flash | Fast search grounding tasks |
| LLM - Synthesis | Gemini 2.5 Pro | Deep analysis and cross-source synthesis |
| Search - Google | ADK google_search tool | Web search via Google Search grounding |
| Search - Perplexity | Perplexity Sonar API (OpenAI-compatible) | AI-powered web research |
| Config Validation | Pydantic v2 | Schema validation with detailed error messages |
| Config Format | YAML (PyYAML) | Human-readable topic configuration |
| HTML Rendering | Jinja2 | Newsletter template engine with autoescape |
| HTML Sanitization | nh3 | Strips dangerous tags from LLM-generated content |
| Markdown Processing | python-markdown | Converts LLM markdown output to HTML |
| Email | Gmail API (google-api-python-client) | OAuth2-authenticated email delivery |
| HTTP | Flask | Cloud Run HTTP trigger endpoint |
| Logging | Python logging | Structured logging to stdout/stderr |

## Data Flow

### Session State Keys

The pipeline communicates between agents exclusively through ADK session state. Here are all state keys used:

| Key | Set By | Read By | Type |
|-----|--------|---------|------|
| `config_newsletter_title` | ConfigLoader | Formatter | str |
| `config_recipient_email` | ConfigLoader | Delivery | str |
| `config_dry_run` | ConfigLoader | Delivery | bool |
| `config_output_dir` | ConfigLoader | Delivery | str |
| `config_timeframes` | ConfigLoader | Research agents | dict or None |
| `config_verify_links` | ConfigLoader | LinkVerifier | bool |
| `config_topic_count` | SynthesisPostProcessor | Formatter | int |
| `pipeline_start_time` | before_agent_callback | Formatter | str (ISO 8601) |
| `research_N_google` | GoogleSearcher_N or DeepResearchOrchestrator | LinkVerifier, Synthesizer | str (raw LLM output) |
| `research_N_perplexity` | PerplexitySearcher_N or DeepResearchOrchestrator | LinkVerifier, Synthesizer | str (raw LLM output) |
| `adaptive_context_N_{provider}` | DeepResearchOrchestrator | -- | dict (plan + per-round analysis) |
| `adaptive_reasoning_chain_N_{provider}` | DeepResearchOrchestrator | -- | str (JSON, persisted reasoning chain) |
| `deep_urls_accumulated_N_{provider}` | DeepResearchOrchestrator | -- | list[str] (accumulated unique URLs) |
| `research_all_failed` | ResearchValidator | PipelineAbortCheck | bool |
| `synthesis_raw` | Synthesizer | SynthesisPostProcessor | str (JSON) |
| `synthesis_N` | SynthesisPostProcessor | Formatter | dict |
| `executive_summary` | SynthesisPostProcessor | Formatter | list[dict] |
| `newsletter_html` | Formatter | Delivery | str (HTML) |
| `newsletter_metadata` | Formatter / after_agent_callback | Delivery / HTTP handler | dict |
| `delivery_status` | Delivery | HTTP handler | dict |

### Pipeline Phases

1. **Config Loading**: `ConfigLoaderAgent` reads the validated `NewsletterConfig` and writes config values into session state so all downstream agents can access them.

2. **Research Phase**: A `ParallelAgent` runs one `SequentialAgent` per topic. All topics execute in parallel. For standard-mode topics, Google Search and Perplexity LlmAgents run sequentially. For deep-mode topics (`search_depth: "deep"`), a `DeepResearchOrchestrator` (custom BaseAgent) replaces each LlmAgent. The orchestrator follows an adaptive Plan-Search-Analyze-Decide loop: a PlanningAgent identifies key aspects and an initial search query, each round is followed by an AnalysisAgent that evaluates findings and suggests the next query, and the loop exits when saturation is detected, knowledge gaps are empty, the search budget (`max_searches_per_topic`) is exhausted, or `max_research_rounds` is reached. A configurable `min_research_rounds` prevents premature saturation exit. All round results are merged into the standard `research_N_{provider}` state key and a reasoning chain is persisted at `adaptive_reasoning_chain_N_{provider}`.

3. **Research Validation**: Checks all research state keys. If every provider failed for every topic, sets `research_all_failed = True`.

4. **Abort Check**: If `research_all_failed` is True, saves an error HTML page and raises `RuntimeError` to halt the pipeline.

5. **Synthesis**: The Gemini Pro model reads all research results from state and produces a JSON blob with executive summary and per-topic analysis sections.

6. **Post-Processing**: Parses the raw synthesis JSON into individual `synthesis_N` state keys and the `executive_summary` list.

7. **Link Verification**: When `verify_links=true`, verifies all source URLs concurrently via HTTP HEAD/GET. Removes broken links from sources and inline markdown citations. SSRF protections block private IPs and non-HTTP schemes. No-ops when `verify_links=false` or omitted.

8. **Formatting**: Renders the Jinja2 HTML template with synthesis data. Sanitizes LLM-generated content through nh3 to prevent XSS.

9. **Delivery**: Sends the newsletter via Gmail (if not dry-run and recipient is configured) or saves it as an HTML file.

## Dynamic Agent Construction

The number of research agents is determined at startup by the topic count in `config/topics.yaml`. A factory function (`build_research_phase()`) reads the config and constructs the `ParallelAgent` sub-tree dynamically. This supports 1 to 20 topics. For each topic, the factory conditionally creates either standard `LlmAgent` instances (for `search_depth: "standard"`) or `DeepResearchOrchestrator` instances (for `search_depth: "deep"`). Both produce the same `research_N_{provider}` state keys, making the deep/standard distinction transparent to downstream agents.

## Security Design

- **HTML Sanitization**: All LLM-generated markdown is converted to HTML via `python-markdown`, then sanitized with `nh3` using a strict allowlist of tags (`a`, `p`, `strong`, `em`, `ul`, `ol`, `li`, `h3`, `h4`, `br`) and attributes (`href` on `a` only). Only `http://` and `https://` URL schemes are permitted.
- **URL Filtering**: Source URLs from both research and synthesis are filtered to allow only `http://` and `https://` schemes, preventing `javascript:`, `data:`, and other dangerous URI schemes.
- **Jinja2 Autoescape**: The HTML template uses `autoescape=True` to prevent XSS from any unescaped variables.
- **No Secrets in Code**: All credentials are loaded from environment variables. The `.env` file is gitignored.
- **SSRF Prevention**: The Perplexity API URL is hardcoded. The link verifier makes outbound requests to user-sourced URLs but applies SSRF protections: private IP ranges (127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, ::1, fc00::/7) are blocked, only http/https schemes are allowed, and post-redirect destinations are re-checked.
- **Gmail OAuth2**: Uses refresh tokens with minimal scope (`gmail.send` only).

## Error Handling Strategy

| Scenario | Behavior |
|----------|----------|
| Single provider fails for a topic | Logged; pipeline continues with other provider's results |
| Deep research round produces no results | Logged; orchestrator continues to next round |
| All providers fail for one topic | Topic section shows "Research unavailable" placeholder |
| All providers fail for all topics | Pipeline aborts with RuntimeError; error HTML saved |
| Synthesis produces invalid JSON | Fallback output with error message per topic |
| Gmail send fails | Newsletter HTML saved to disk as fallback |
| Config validation fails | Pipeline refuses to start; detailed Pydantic error message |

## Logging

Logs use the format: `{timestamp} {level} {logger_name} {message}`

- `INFO` and below go to stdout
- `ERROR` and above go to stderr
- Third-party loggers are suppressed to WARNING
- Log level is configurable via the `LOG_LEVEL` environment variable

Pipeline timing is instrumented via ADK `before_agent_callback` / `after_agent_callback`, which log per-phase and total execution time.
