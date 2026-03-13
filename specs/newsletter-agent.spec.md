# Newsletter Agent - Specification

> **Source brief**: `ideas/newsletter-agent.md`
> **Feature branch**: `newsletter-agent`
> **Status**: Draft
> **Version**: 1.0

---

## 1. Overview

Newsletter Agent is an autonomous multi-agent system built on Google's Agent Development Kit (ADK) Python SDK. It performs deep, multi-source research on user-defined topics using Google Search grounding and the Perplexity Sonar API, synthesizes findings into a professionally formatted HTML newsletter with citations and an executive summary, and delivers it via Gmail API. Topics, schedules, and delivery settings are declared in a YAML configuration file. The system runs locally for development (via `adk web` / `adk run`) and deploys to GCP Cloud Run with Cloud Scheduler for automated weekly production runs.

---

## 2. Goals & Success Criteria

- **SC-001**: The system generates a complete, multi-topic HTML newsletter from a single trigger (manual or scheduled) with zero human intervention after initial configuration.
- **SC-002**: Each topic section contains a minimum of 3 cited sources drawn from at least 2 distinct search providers (Google Search + Perplexity).
- **SC-003**: End-to-end pipeline execution (config load through email delivery) completes within 10 minutes for a 5-topic newsletter on Cloud Run.
- **SC-004**: The newsletter email renders correctly in Gmail web client and Gmail mobile app (HTML + inline CSS).
- **SC-005**: Dry-run mode produces an identical HTML file locally without sending any email.
- **SC-006**: The system deploys to Cloud Run with a single `adk deploy cloud_run` command and triggers via Cloud Scheduler cron job.

---

## 3. Users & Roles

- **Operator**: The person who configures and deploys the system. Creates the YAML topics file, sets up Gmail OAuth2 credentials, manages GCP project and deployment. Has full access to all configuration, logs, and outputs. This is the same person who receives the newsletter.
- **Recipient**: The email recipient(s) of the generated newsletter. In MVP, the Operator is also the sole Recipient. No separate authentication or role management needed.

---

## 4. Functional Requirements

### 4.1 Topic Configuration

- **FR-001**: The system SHALL load topic definitions from a YAML configuration file at `config/topics.yaml` relative to the project root.
- **FR-002**: Each topic entry SHALL contain the following required fields: `name` (string, 1-100 chars), `query` (string, natural language search description, 1-500 chars).
- **FR-003**: Each topic entry MAY contain the following optional fields: `search_depth` (enum: "standard" | "deep", default: "standard"), `sources` (list of strings from: ["google_search", "perplexity"], default: both).
- **FR-004**: The system SHALL validate the YAML config on startup and fail fast with a descriptive error message if any required field is missing or any field value violates its constraints.
- **FR-005**: The configuration file SHALL also contain top-level `newsletter` settings: `title` (string, 1-200 chars), `schedule` (cron expression string), `recipient_email` (valid email address string).
- **FR-006**: The configuration file SHALL contain a `settings` section with: `dry_run` (boolean, default: false), `output_dir` (string, path for HTML output, default: "output/").
- **FR-007**: The system SHALL support a minimum of 1 and a maximum of 20 topics in a single configuration file.

**Implementation Contract - Topic Configuration**:
- Input: File path `config/topics.yaml`
- Output: Validated `NewsletterConfig` Python dataclass
- Error: `ConfigValidationError` with field-level details on any validation failure
- Error: `FileNotFoundError` if config file does not exist

### 4.2 Research Pipeline

- **FR-008**: For each topic, the system SHALL execute a Google Search grounding query using ADK's built-in `google_search` tool via a dedicated `LlmAgent` (due to single-tool-per-agent constraint).
- **FR-009**: For each topic, the system SHALL execute a Perplexity Sonar API query via a custom ADK `FunctionTool` wrapping the Perplexity Python SDK in a separate `LlmAgent`.
- **FR-010**: Research for all topics SHALL execute in parallel using ADK's `ParallelAgent`, with each topic's Google Search and Perplexity calls running concurrently.
- **FR-011**: Each research agent SHALL store its results in the shared session state using a namespaced key: `research_{topic_index}_{provider}` (e.g., `research_0_google`, `research_0_perplexity`).
- **FR-012**: Each research result stored in state SHALL include: the raw text response, a list of source URLs with titles, and the provider name.
- **FR-013**: If a search provider fails (network error, API error, rate limit), the system SHALL log the error and continue with results from the other provider(s). A topic with zero successful search results SHALL produce a section noting "Research unavailable for this topic" instead of failing the entire pipeline.
- **FR-014**: When `search_depth` is "deep", the Google Search agent SHALL use a more detailed instruction prompt that requests comprehensive, multi-faceted analysis. The Perplexity tool SHALL use the `sonar-pro` model instead of `sonar`.
- **FR-015**: The Perplexity tool function SHALL accept `query` (str) and `search_depth` (str) parameters and return a dict with keys: `text` (str), `sources` (list of dicts with `url` and `title`), `provider` (str = "perplexity").

**Implementation Contract - Research Pipeline**:
- Input: List of validated topic configs from FR-001 through FR-007
- Output: Session state populated with `research_{topic_index}_{provider}` keys
- Error: Individual provider failures are caught, logged, and result in a fallback marker in state. Pipeline never aborts due to a single provider failure.
- Error: If ALL providers fail for ALL topics, the pipeline SHALL abort and log an error without sending an email.

### 4.3 Synthesis

- **FR-016**: After all research completes, a synthesis `LlmAgent` (using Gemini Pro model) SHALL process each topic's research results and produce a deep analysis section.
- **FR-017**: Each synthesized section SHALL be multi-paragraph (minimum 200 words), cross-reference information from multiple sources, highlight key developments, and include inline source citations in the format `[Source Title](URL)`.
- **FR-018**: The synthesis agent SHALL produce an `executive_summary` field: a 1-3 sentence overview of each topic's key finding, stored in session state as `executive_summary`.
- **FR-019**: The synthesis agent SHALL store each completed topic section in state as `synthesis_{topic_index}` containing: `title` (str), `body_markdown` (str with inline citations), `sources` (deduplicated list of all sources used).
- **FR-020**: The synthesis agent instruction SHALL explicitly prohibit fabricating facts or sources not present in the research results.

**Implementation Contract - Synthesis**:
- Input: Session state keys `research_{topic_index}_{provider}` for all topics and providers
- Output: Session state keys `synthesis_{topic_index}` and `executive_summary`
- Error: If research data for a topic is empty/unavailable, the synthesis agent SHALL produce a brief note stating the topic could not be researched this cycle.

### 4.4 Newsletter Formatting

- **FR-021**: A formatting agent or Python function SHALL render the synthesized content into a complete HTML document using inline CSS (no external stylesheets, for email compatibility).
- **FR-022**: The HTML newsletter SHALL contain the following sections in order: newsletter title and date, executive summary, table of contents (linked to topic sections), topic deep-dive sections, source appendix, footer.
- **FR-023**: The HTML template SHALL use a responsive, single-column layout with a maximum width of 600px, optimized for email rendering in Gmail web and mobile.
- **FR-024**: Each topic section SHALL display: topic name as heading, synthesized body with inline linked citations, list of sources with URLs.
- **FR-025**: The executive summary section SHALL display each topic's 1-3 sentence summary as a bulleted list at the top of the newsletter.
- **FR-026**: The system SHALL store the final HTML string in session state as `newsletter_html` and the newsletter metadata (title, date, topic count) as `newsletter_metadata`.

**Implementation Contract - Formatting**:
- Input: Session state keys `synthesis_{topic_index}`, `executive_summary`, config `newsletter.title`
- Output: Session state key `newsletter_html` (complete HTML string), `newsletter_metadata` (dict)
- Error: If any synthesis section is missing, the formatter SHALL produce the newsletter without that section and include a note.

### 4.5 Email Delivery

- **FR-027**: The system SHALL send the HTML newsletter via Gmail API using OAuth2 credentials stored in the project (local dev) or GCP Secret Manager (production).
- **FR-028**: The OAuth2 flow SHALL use offline access to obtain a refresh token. The system SHALL automatically refresh expired access tokens using the stored refresh token.
- **FR-029**: The email SHALL be sent as a MIME multipart message with both HTML and plain-text parts (the plain-text part is a stripped version of the HTML for fallback rendering).
- **FR-030**: The email `From` field SHALL be the authenticated Gmail account. The `To` field SHALL be the `recipient_email` from config. The `Subject` SHALL follow the format: `{newsletter.title} - {date in YYYY-MM-DD}`.
- **FR-031**: If `settings.dry_run` is true, the system SHALL skip email delivery entirely and instead save the HTML to `{settings.output_dir}/{date}-newsletter.html`.
- **FR-032**: On email delivery failure (Gmail API error, auth error), the system SHALL log the full error, save the HTML locally as a fallback (same path as dry_run), and exit with a non-zero status code.

**Implementation Contract - Email Delivery**:
- Input: Session state `newsletter_html`, config `recipient_email`, `dry_run` flag
- Output: Email sent via Gmail API OR HTML file saved to disk
- Error: `GmailAuthError` if OAuth tokens are invalid/expired and refresh fails - logs error, saves HTML locally
- Error: `GmailSendError` if API call fails - logs error, saves HTML locally

### 4.6 Dry Run & Local Output

- **FR-033**: In dry-run mode, the system SHALL execute the full pipeline (research, synthesis, formatting) but SHALL NOT send any email.
- **FR-034**: The system SHALL save the generated HTML file to `{output_dir}/{YYYY-MM-DD}-newsletter.html` in both dry-run mode and as a fallback on email failure.
- **FR-035**: The output directory SHALL be created automatically if it does not exist.

**Implementation Contract - Dry Run**:
- Input: `settings.dry_run` boolean, `settings.output_dir` path
- Output: HTML file on disk at deterministic path
- Error: `IOError` if output directory cannot be created - log and abort

### 4.7 Deployment & Scheduling

- **FR-036**: The system SHALL be deployable to GCP Cloud Run using `adk deploy cloud_run` with standard ADK project structure.
- **FR-037**: The Cloud Run service SHALL expose an HTTP endpoint that triggers a full newsletter generation cycle when called.
- **FR-038**: A Cloud Scheduler job SHALL call the Cloud Run endpoint on the schedule defined in `config/topics.yaml` (the `newsletter.schedule` cron expression).
- **FR-039**: The Cloud Scheduler job SHALL authenticate to the Cloud Run service using a GCP service account with OIDC token.
- **FR-040**: Secrets (Gmail OAuth2 refresh token, Perplexity API key, Google API key) SHALL be stored in GCP Secret Manager and injected as environment variables on Cloud Run.
- **FR-041**: For local development, secrets SHALL be loaded from a `.env` file (not committed to version control).

**Implementation Contract - Deployment**:
- Input: ADK project structure, GCP project ID, region, service account
- Output: Cloud Run service URL, Cloud Scheduler job
- Error: Deployment failures surface via `adk deploy` or `gcloud` CLI error output

### 4.8 Observability

- **FR-042**: The system SHALL log at INFO level: pipeline start/end timestamps, per-topic research start/end, synthesis start/end, email delivery status.
- **FR-043**: The system SHALL log at ERROR level: any provider failure, synthesis failure, email delivery failure, config validation failure.
- **FR-044**: Logs SHALL use Python's standard `logging` module with structured format: `{timestamp} {level} {agent_name} {message}`.
- **FR-045**: On Cloud Run, logs SHALL be written to stdout/stderr for integration with Cloud Logging.

**Implementation Contract - Observability**:
- Input: All pipeline events
- Output: Structured log lines to stdout/stderr
- Error: Logging failures SHALL NOT crash the pipeline

---

## 5. User Stories

### US-01 - Configure topics via YAML (Priority: P1) MVP

**As an** Operator, **I want** to define my research topics in a simple YAML file with natural language descriptions, **so that** I can customize what the newsletter covers without writing code.

**Why P1**: Foundational - without topic configuration, nothing else works. This is the entry point of the entire system.

**Independent Test**: Create a `config/topics.yaml` with 3 topics. Run the config loader. Verify each topic is parsed into a structured object with correct field values.

**Acceptance Scenarios**:
1. **Given** a valid YAML file with 3 topics, **When** the system loads the config, **Then** it returns 3 validated topic objects with all required fields populated.
2. **Given** a YAML file with a topic missing the `query` field, **When** the system loads the config, **Then** it raises `ConfigValidationError` with a message identifying the missing field and topic name.
3. **Given** a YAML file with 0 topics, **When** the system loads the config, **Then** it raises `ConfigValidationError` stating minimum 1 topic required.
4. **Given** a YAML file with 21 topics, **When** the system loads the config, **Then** it raises `ConfigValidationError` stating maximum 20 topics.

---

### US-02 - Multi-source research per topic (Priority: P1) MVP

**As an** Operator, **I want** each topic to be researched via both Google Search and Perplexity AI, **so that** the newsletter is based on diverse, cross-referenced information.

**Why P1**: Core value proposition - multi-source research is what differentiates this from single-source summarizers.

**Independent Test**: Provide a single topic config. Run the research pipeline. Verify session state contains results from both Google Search and Perplexity with source URLs.

**Acceptance Scenarios**:
1. **Given** a topic with default sources, **When** research runs, **Then** session state contains `research_0_google` and `research_0_perplexity` keys each with text and source URLs.
2. **Given** a topic with `sources: ["google_search"]` only, **When** research runs, **Then** only `research_0_google` is populated.
3. **Given** Perplexity API is unreachable, **When** research runs, **Then** `research_0_perplexity` contains an error marker, `research_0_google` is populated normally, and the pipeline continues.
4. **Given** 5 topics, **When** research runs, **Then** all 5 topics are researched in parallel (total time is roughly equal to the slowest single topic, not 5x sequential).

---

### US-03 - Deep analysis synthesis (Priority: P1) MVP

**As a** Recipient, **I want** each topic section to be a multi-paragraph deep analysis with inline citations, **so that** I get genuine insight rather than shallow bullet points.

**Why P1**: This is the core output quality differentiator. Without deep synthesis, the newsletter is just a link dump.

**Independent Test**: Provide pre-populated research state for one topic. Run the synthesis agent. Verify the output is 200+ words with at least 3 inline citations linking to actual source URLs.

**Acceptance Scenarios**:
1. **Given** research results from 2 providers for a topic, **When** synthesis runs, **Then** the output contains 200+ words, cross-references findings from both providers, and includes 3+ inline `[Title](URL)` citations.
2. **Given** research results from only 1 provider (other failed), **When** synthesis runs, **Then** the output is still produced using available data, with a note about limited sources.
3. **Given** research results with no content (both providers failed), **When** synthesis runs, **Then** the output states "Research was unavailable for this topic in this cycle."

---

### US-04 - HTML newsletter formatting (Priority: P1) MVP

**As a** Recipient, **I want** the newsletter delivered as a well-structured HTML email with sections, a table of contents, and an executive summary, **so that** it is easy to scan and read.

**Why P1**: Delivery format is essential for the newsletter to serve its purpose.

**Independent Test**: Provide pre-populated synthesis state for 3 topics + executive summary. Run the formatter. Verify the HTML output contains all sections, linked TOC, inline CSS, and renders in a browser.

**Acceptance Scenarios**:
1. **Given** 3 synthesized topics and an executive summary in state, **When** formatting runs, **Then** the HTML contains: title/date header, executive summary bullets, linked TOC with 3 entries, 3 topic sections, source appendix, footer.
2. **Given** the output HTML, **When** rendered in a browser at 600px width, **Then** all content is readable without horizontal scrolling.
3. **Given** the output HTML, **When** inspected, **Then** all CSS is inline (no `<link>` tags or `<style>` blocks referencing external resources).

---

### US-05 - Email delivery via Gmail API (Priority: P1) MVP

**As an** Operator, **I want** the newsletter emailed to me automatically via my Gmail account, **so that** I receive it in my inbox without any manual action.

**Why P1**: Email delivery is the final stage of the autonomous pipeline - without it, the system is not "fire and forget."

**Independent Test**: Provide a completed HTML newsletter in state. Configure a valid recipient email. Run the delivery agent. Verify the email arrives with correct subject, HTML body, and plain-text fallback.

**Acceptance Scenarios**:
1. **Given** valid OAuth2 credentials, a newsletter HTML in state, and `dry_run: false`, **When** delivery runs, **Then** an email is sent to the configured recipient with subject `{title} - {date}`, HTML body matching the newsletter, and a plain-text fallback part.
2. **Given** `dry_run: true`, **When** delivery runs, **Then** no email is sent, and the HTML is saved to `output/{date}-newsletter.html`.
3. **Given** expired OAuth2 access token with valid refresh token, **When** delivery runs, **Then** the token is refreshed automatically and the email is sent.
4. **Given** invalid OAuth2 credentials (bad refresh token), **When** delivery runs, **Then** the error is logged, the HTML is saved locally as fallback, and the process exits with non-zero status.

---

### US-06 - Local development workflow (Priority: P1) MVP

**As an** Operator, **I want** to run the full pipeline locally for testing using `adk web` or `adk run`, **so that** I can iterate on topic configs and prompt instructions before deploying.

**Why P1**: Local dev is essential for initial setup and ongoing tuning.

**Independent Test**: Run `adk web` from the project root. Trigger the newsletter agent via the ADK web UI. Verify the full pipeline executes and produces output (dry-run mode).

**Acceptance Scenarios**:
1. **Given** a valid config and `.env` file with API keys, **When** running `adk web` and triggering the agent, **Then** the pipeline executes end-to-end and the ADK web UI shows all agent events.
2. **Given** `dry_run: true` in config, **When** running locally, **Then** the newsletter HTML is saved to the output directory.

---

### US-07 - Cloud Run deployment (Priority: P1) MVP

**As an** Operator, **I want** to deploy the agent to Cloud Run with a single command and schedule it with Cloud Scheduler, **so that** the newsletter runs autonomously in production.

**Why P1**: Autonomous production operation is a core goal.

**Independent Test**: Run `adk deploy cloud_run` targeting a GCP project. Verify the service deploys and responds to an HTTP trigger. Verify Cloud Scheduler job can be created to call the endpoint.

**Acceptance Scenarios**:
1. **Given** a properly configured GCP project and ADK project structure, **When** running `adk deploy cloud_run`, **Then** the service deploys and returns a service URL.
2. **Given** a deployed service, **When** an authenticated HTTP request hits the endpoint, **Then** the full pipeline executes.
3. **Given** a Cloud Scheduler job configured with the service URL and cron expression, **When** the scheduled time arrives, **Then** Cloud Scheduler triggers the service and the newsletter is generated and sent.

---

### US-08 - Executive summary (Priority: P1) MVP

**As a** Recipient, **I want** a brief executive summary at the top of the newsletter listing each topic's key finding in 1-3 sentences, **so that** I can quickly scan what is covered before diving deep.

**Why P1**: User explicitly requested this. Key for newsletter scannability.

**Independent Test**: Provide research state for 3 topics. Run synthesis. Verify the `executive_summary` state key contains exactly 3 bullet points, each 1-3 sentences.

**Acceptance Scenarios**:
1. **Given** 5 topics with completed research, **When** synthesis runs, **Then** `executive_summary` contains 5 entries, each with the topic name and 1-3 sentence summary.
2. **Given** the formatted newsletter HTML, **When** inspecting the executive summary section, **Then** it appears before the table of contents and after the title.

---

### Edge Cases

- What happens when the YAML file contains UTF-8 special characters in topic names? System SHALL handle UTF-8 correctly.
- What happens when a topic query is extremely broad (e.g., "everything about AI")? The search agents return whatever results the providers give; synthesis works with whatever is available.
- What happens when Cloud Run times out before pipeline completes? Cloud Run timeout SHALL be set to 600 seconds (10 min). If exceeded, the request fails and logs an error; no partial email is sent.
- What happens when the YAML file is modified between scheduled runs? The system loads the config fresh on each invocation; changes are picked up on the next run.
- What happens when Gmail sending quota is exceeded? The delivery agent catches the error, saves HTML locally, logs the error.

---

## 6. User Flows

### 6.1 Initial Setup Flow

1. Operator clones the repository.
2. Operator runs `pip install google-adk` (and other deps).
3. Operator creates `config/topics.yaml` with topic definitions and newsletter settings.
4. Operator sets up Gmail OAuth2: runs a one-time auth flow script to obtain refresh token, stores in `.env`.
5. Operator sets Perplexity API key and Google API key in `.env`.
6. Operator runs `adk web` to verify the agent loads in the dev UI.
7. Operator triggers newsletter generation via ADK web UI (with `dry_run: true`).
8. System executes full pipeline, saves HTML to `output/` directory.
9. Operator opens the HTML file in a browser to review.
10. Operator adjusts topic queries or agent instructions as needed.

### 6.2 Newsletter Generation Flow (Happy Path)

1. Trigger arrives (HTTP request from Cloud Scheduler, or manual ADK run).
2. System loads and validates `config/topics.yaml`.
3. For each topic, system creates a per-topic research sub-pipeline:
   a. Google Search agent executes grounded search query.
   b. Perplexity tool agent executes Sonar API query.
   c. Both store results in session state.
4. All per-topic research runs in parallel via `ParallelAgent`.
5. Synthesis agent reads all research results from state, produces deep analysis per topic + executive summary, stores in state.
6. Formatter reads synthesis results from state, renders HTML newsletter with all sections.
7. If `dry_run` is false: Delivery agent sends email via Gmail API.
8. If `dry_run` is true: System saves HTML to output directory.
9. System logs completion with timing metrics.

### 6.3 Newsletter Generation Flow (Partial Failure)

1-4. Same as happy path.
5. During research, Perplexity API returns a 429 rate limit error for topic 3.
   a. Error is logged at ERROR level with topic name and provider.
   b. `research_2_perplexity` in state is set to an error marker dict: `{"error": true, "message": "Rate limited", "provider": "perplexity"}`.
   c. Research for all other topics/providers continues normally.
6. Synthesis agent detects the missing provider for topic 3, synthesizes using only Google Search results, and includes a note: "Note: This analysis is based on limited sources due to a provider outage."
7-9. Same as happy path.

### 6.4 Newsletter Generation Flow (Email Failure)

1-6. Same as happy path.
7. Gmail API returns 401 Unauthorized. System attempts token refresh.
8. Token refresh fails (refresh token revoked).
9. System logs `GmailAuthError` at ERROR level.
10. System saves the newsletter HTML to `output/{date}-newsletter.html` as fallback.
11. Process exits with non-zero status code.

### 6.5 Deployment Flow

1. Operator verifies local pipeline works with `adk web` + dry_run.
2. Operator runs `gcloud auth login` and configures GCP project.
3. Operator stores secrets in GCP Secret Manager: `GOOGLE_API_KEY`, `PERPLEXITY_API_KEY`, `GMAIL_REFRESH_TOKEN`, `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`.
4. Operator runs `adk deploy cloud_run --project=PROJECT --region=REGION ./newsletter_agent`.
5. Cloud Run service deploys and returns service URL.
6. Operator creates Cloud Scheduler job: `gcloud scheduler jobs create http newsletter-weekly --schedule="0 8 * * 0" --uri=SERVICE_URL/run --oidc-service-account-email=SA_EMAIL`.
7. Scheduler triggers the service every Sunday at 8am UTC.

---

## 7. Data Model

### 7.1 NewsletterConfig (loaded from YAML)

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| newsletter.title | string | required, 1-200 chars | Newsletter display title |
| newsletter.schedule | string | required, valid cron | Cron expression for scheduling |
| newsletter.recipient_email | string | required, valid email format | Delivery target |
| settings.dry_run | boolean | optional, default: false | Skip email, save HTML locally |
| settings.output_dir | string | optional, default: "output/" | Local HTML output path |
| topics | list[TopicConfig] | required, 1-20 items | Topic definitions |

### 7.2 TopicConfig

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| name | string | required, 1-100 chars, unique within config | Human-readable topic name |
| query | string | required, 1-500 chars | Natural language search description |
| search_depth | string | optional, "standard" or "deep", default: "standard" | Research intensity |
| sources | list[string] | optional, values from ["google_search", "perplexity"], default: both | Which providers to use |

### 7.3 ResearchResult (session state)

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| text | string | required | Raw research text from provider |
| sources | list[SourceRef] | required | List of source references |
| provider | string | required, "google_search" or "perplexity" | Provider identifier |
| error | boolean | optional, default: false | True if this result is an error marker |
| message | string | optional | Error message if error is true |

### 7.4 SourceRef

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| url | string | required, valid URL | Source page URL |
| title | string | required, 1-300 chars | Source page title |

### 7.5 SynthesisResult (session state)

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| title | string | required | Topic name |
| body_markdown | string | required, min 200 chars | Synthesized analysis with inline citations |
| sources | list[SourceRef] | required | Deduplicated list of all sources referenced |

### 7.6 NewsletterMetadata (session state)

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| title | string | required | Newsletter title from config |
| date | string | required, ISO 8601 date | Generation date |
| topic_count | integer | required, >= 1 | Number of topics in this issue |
| generation_time_seconds | float | required | Total pipeline execution time |

### Relationships

- `NewsletterConfig` 1:N `TopicConfig`
- Each `TopicConfig` produces 1-2 `ResearchResult` entries (one per provider)
- Each `TopicConfig` produces exactly 1 `SynthesisResult`
- All `SynthesisResult` entries produce exactly 1 HTML newsletter

---

## 8. API / Interface Design

### 8.1 Cloud Run HTTP Trigger Endpoint

- **Method**: POST
- **Path**: `/run`
- **Purpose**: Triggers a full newsletter generation cycle
- **Request**: No body required. Authentication via OIDC token in `Authorization` header (Cloud Scheduler).
- **Response 200**: `{"status": "success", "newsletter_date": "2026-03-14", "topics_processed": 5, "email_sent": true}`
- **Response 200 (dry_run)**: `{"status": "success", "newsletter_date": "2026-03-14", "topics_processed": 5, "email_sent": false, "output_file": "output/2026-03-14-newsletter.html"}`
- **Response 500**: `{"status": "error", "message": "Pipeline failed: {details}"}`
- **Response 401**: Returned by Cloud Run IAM if OIDC token is missing/invalid.
- **Auth**: Cloud Run IAM with OIDC. Cloud Scheduler service account must have `roles/run.invoker` on the service.
- **Timeout**: 600 seconds (set on Cloud Run service configuration).

### 8.2 Perplexity Sonar Tool Function Signature

```python
def search_perplexity(query: str, search_depth: str = "standard") -> dict:
    """
    Searches Perplexity Sonar API for information on a topic.

    Args:
        query: Natural language search query describing what to research.
        search_depth: "standard" uses sonar model, "deep" uses sonar-pro model.

    Returns:
        dict with keys:
            - text (str): Synthesized research response
            - sources (list[dict]): List of {url, title} source references
            - provider (str): Always "perplexity"
    """
```

- **Error handling**: On API failure, returns `{"error": True, "message": str(exception), "provider": "perplexity"}`

### 8.3 Gmail Send Tool Function Signature

```python
def send_newsletter_email(
    html_content: str,
    recipient_email: str,
    subject: str
) -> dict:
    """
    Sends an HTML email via Gmail API.

    Args:
        html_content: Complete HTML newsletter string.
        recipient_email: Target email address.
        subject: Email subject line.

    Returns:
        dict with keys:
            - status (str): "sent" or "error"
            - message_id (str): Gmail message ID if sent
            - error_message (str): Error details if failed
    """
```

- **Error handling**: On auth failure, attempts token refresh once. On any failure, returns error dict (does not raise).

### 8.4 Config YAML Schema

```yaml
newsletter:
  title: "Weekly Tech Digest"
  schedule: "0 8 * * 0"  # Every Sunday at 8am UTC
  recipient_email: "user@gmail.com"

settings:
  dry_run: false
  output_dir: "output/"

topics:
  - name: "AI Frameworks"
    query: "Latest developments in AI agent frameworks, including LangChain, CrewAI, Google ADK, and AutoGen. Focus on new releases, benchmarks, and adoption trends."
    search_depth: "deep"
    sources:
      - google_search
      - perplexity

  - name: "Cloud Native"
    query: "Recent developments in cloud-native technologies, Kubernetes, serverless platforms, and major cloud provider announcements from AWS, GCP, and Azure."
    search_depth: "standard"
```

---

## 9. Architecture

### 9.1 System Design

The system is a multi-agent pipeline built with ADK workflow agents. The overall structure is a `SequentialAgent` containing three phases: parallel research, synthesis, and output (format + deliver).

```
root_agent (SequentialAgent: "NewsletterPipeline")
|
+-- config_loader_agent (Custom BaseAgent: "ConfigLoader")
|     Reads topics.yaml, validates, stores config in state
|
+-- research_phase (ParallelAgent: "ResearchPhase")
|     For each topic, runs in parallel:
|     +-- topic_N_research (SequentialAgent: "TopicNResearch")
|           +-- google_search_agent (LlmAgent: "GoogleSearcher_N")
|           |     tools: [google_search]
|           |     model: gemini-2.5-flash
|           |     output_key: research_N_google
|           +-- perplexity_agent (LlmAgent: "PerplexitySearcher_N")
|                 tools: [search_perplexity FunctionTool]
|                 model: gemini-2.5-flash
|                 output_key: research_N_perplexity
|
+-- synthesis_agent (LlmAgent: "Synthesizer")
|     model: gemini-2.5-pro
|     Reads all research_N_* from state
|     Outputs: synthesis_N for each topic + executive_summary
|
+-- output_phase (SequentialAgent: "OutputPhase")
      +-- formatter_agent (Custom BaseAgent: "Formatter")
      |     Reads synthesis state, renders Jinja2 HTML template
      |     output_key: newsletter_html
      +-- delivery_agent (LlmAgent or Custom BaseAgent: "Deliverer")
            Reads newsletter_html, sends via Gmail or saves to disk
```

**Key architectural point**: The `google_search` tool has a single-tool-per-agent constraint. Each Google Search agent instance is dedicated to one topic and uses `google_search` as its only tool. The Perplexity agents use a custom `FunctionTool` with no such constraint but are separated for clarity and parallelization.

**Dynamic agent construction**: Because the number of topics is configurable (1-20), the research phase agents must be constructed dynamically at startup based on the loaded config. A factory function reads the config and builds the `ParallelAgent` sub-tree accordingly.

### 9.2 Technology Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Agent framework | Google ADK Python (google-adk) | Native Gemini integration, built-in google_search tool, Cloud Run deployment support, multi-agent orchestration |
| LLM - Research | Gemini 2.5 Flash | Fast, cost-effective for search grounding tasks. Required for google_search tool. |
| LLM - Synthesis | Gemini 2.5 Pro | Higher quality reasoning for deep analysis and cross-source synthesis |
| Search - Google | ADK google_search tool | Built-in grounding with source citations, zero additional setup |
| Search - Perplexity | Perplexity Python SDK (perplexityai) | Sonar API for web-grounded AI responses with citations |
| Email | google-api-python-client + google-auth | Gmail API with OAuth2, works with personal Gmail accounts |
| Config | PyYAML + Pydantic | YAML parsing with strong validation via Pydantic models |
| Templating | Jinja2 | HTML template rendering for newsletter formatting |
| HTML sanitization | bleach (or equivalent) | Sanitize any LLM-generated HTML/markdown before embedding |
| Deployment | GCP Cloud Run | Serverless, pay-per-invocation, native ADK deploy support |
| Scheduling | GCP Cloud Scheduler | Cron-based HTTP triggering for Cloud Run |
| Secrets | GCP Secret Manager | Secure storage for API keys and OAuth tokens in production |
| Local dev | python-dotenv | Load secrets from .env file during development |
| Python | 3.11+ | Required by ADK, modern async support |

### 9.3 Directory & Module Structure

```
newsletter_agent/
  __init__.py              # ADK entry point: from . import agent
  agent.py                 # Root agent definition + dynamic agent factory
  config/
    topics.yaml            # Topic and newsletter configuration
    schema.py              # Pydantic config models + validation
  tools/
    perplexity_search.py   # Perplexity Sonar API FunctionTool wrapper
    gmail_send.py          # Gmail API send FunctionTool
    gmail_auth.py          # OAuth2 token management utilities
  templates/
    newsletter.html.j2     # Jinja2 HTML email template
  prompts/
    research_google.py     # Google Search agent instruction templates
    research_perplexity.py # Perplexity agent instruction templates
    synthesis.py           # Synthesis agent instruction template
  output/                  # Default directory for dry-run HTML output
  .env                     # Local dev secrets (gitignored)
requirements.txt           # Python dependencies
setup_gmail_oauth.py       # One-time OAuth2 setup script
README.md                  # Project documentation
```

### 9.4 Key Design Decisions

**Decision 1: Dynamic agent construction at startup**
- **Decision**: Build the ParallelAgent sub-tree dynamically based on the number of topics in config, rather than using a fixed number of agents.
- **Rationale**: Config allows 1-20 topics. Hardcoding agents for a fixed number is inflexible. ADK supports programmatic agent construction.
- **Alternatives considered**: Fixed max agents (wasteful), LoopAgent iterating topics sequentially (slow for 5+ topics).
- **Consequences**: Slightly more complex agent.py setup code; tested via unit tests on the factory function.

**Decision 2: Separate Google Search and Perplexity into distinct agents**
- **Decision**: Each topic gets its own dedicated Google Search LlmAgent and a separate Perplexity LlmAgent, rather than combining tools.
- **Rationale**: ADK's `google_search` tool has a single-tool-per-agent constraint. Perplexity as a FunctionTool could technically share an agent with other tools, but separation is cleaner and allows independent parallelization.
- **Alternatives considered**: Single research agent per topic with multiple tools (not possible due to google_search constraint), sequential search calls (slower).
- **Consequences**: More agents in the graph, but each is focused and independently testable.

**Decision 3: Gemini Flash for research, Pro for synthesis**
- **Decision**: Use `gemini-2.5-flash` for all research agents and `gemini-2.5-pro` for the synthesis agent.
- **Rationale**: Research agents primarily invoke tools and format results - Flash is sufficient and cheaper. Synthesis requires higher-quality reasoning for cross-source analysis - Pro delivers better output.
- **Alternatives considered**: Flash everywhere (cheaper but lower synthesis quality), Pro everywhere (higher cost with no research quality gain).
- **Consequences**: Slightly higher cost per newsletter for the synthesis step; justified by output quality.

**Decision 4: Jinja2 HTML templates rather than LLM-generated HTML**
- **Decision**: Use Jinja2 templates for HTML rendering, with LLM output in Markdown inserted into template slots, rather than having the LLM generate HTML directly.
- **Rationale**: LLM-generated HTML is inconsistent, often broken, and harder to style. Templates give predictable, testable output with consistent branding.
- **Alternatives considered**: LLM generates full HTML (unreliable), markdown-to-HTML library only (limited styling control).
- **Consequences**: An additional dependency (Jinja2) and a template file to maintain; far more reliable output.

**Decision 5: Gmail API over SMTP**
- **Decision**: Use Gmail API with OAuth2 rather than SMTP with app passwords.
- **Rationale**: User explicitly chose Gmail API. More robust, supports HTML MIME, better token management, no SMTP throttling concerns.
- **Alternatives considered**: SMTP with Gmail app password (simpler but less reliable), Mailgun (more robust but adds external dependency and signup).
- **Consequences**: OAuth2 setup is more complex initially (one-time auth flow script). Token refresh management needed.

### 9.5 External Integrations

**Google Gemini API (via ADK)**
- Purpose: LLM inference for research agents and synthesis agent
- Authentication: Google API key or Vertex AI application default credentials
- Key operations: Chat completions with tool use (google_search), text generation
- Failure handling: ADK handles retries internally. On persistent failure, the agent returns an error event; the pipeline logs and continues where possible.

**Google Search Grounding (via ADK google_search tool)**
- Purpose: Web search with source-grounded responses
- Authentication: Included with Gemini API key
- Key operations: Search query via tool call, returns grounded text + source URLs
- Failure handling: If search returns no results, the agent produces a response noting this. On API error, ADK surfaces an error event captured by the pipeline.

**Perplexity Sonar API**
- Purpose: Alternative web-grounded AI search with citations
- Authentication: Perplexity API key via environment variable `PERPLEXITY_API_KEY`
- Key operations: `POST /chat/completions` with sonar/sonar-pro model
- Failure handling: Custom function tool catches all exceptions, returns error dict. Pipeline continues with other providers.

**Gmail API**
- Purpose: Send HTML newsletter email
- Authentication: OAuth2 with offline refresh token. Client ID + Client Secret + Refresh Token stored in env/.secrets.
- Key operations: `messages.send` with MIME multipart message
- Failure handling: On 401, attempt token refresh. On any failure, save HTML locally as fallback. Log full error. Exit non-zero.

**GCP Cloud Run**
- Purpose: Serverless hosting of the agent pipeline
- Authentication: Service account with OIDC tokens for Cloud Scheduler invocation
- Key operations: HTTP POST to trigger pipeline
- Failure handling: Cloud Run returns 500 on pipeline failure. Cloud Scheduler retries configurable (recommend 0 retries for newsletter to avoid duplicates).

**GCP Cloud Scheduler**
- Purpose: Cron-based triggering of newsletter generation
- Authentication: Service account with `roles/run.invoker` permission
- Key operations: HTTP POST on cron schedule
- Failure handling: Scheduler logs failures. No retry recommended (newsletter is idempotent per day but sending duplicates is undesirable).

**GCP Secret Manager**
- Purpose: Secure storage of API keys and OAuth tokens in production
- Authentication: Cloud Run service account with `roles/secretmanager.secretAccessor`
- Key operations: Access secret versions at startup
- Failure handling: If secrets cannot be loaded, the pipeline fails immediately with a clear error message.

---

## 10. Non-Functional Requirements

### 10.1 Performance

- End-to-end pipeline for 5 topics SHALL complete within 10 minutes.
- Research phase SHALL use parallel execution for all topics, targeting 2-3 minutes for the research phase regardless of topic count (up to 20).
- Synthesis SHALL complete within 3 minutes for 5 topics.
- HTML rendering SHALL complete within 5 seconds.
- Email delivery SHALL complete within 10 seconds.

### 10.2 Security

- **Authentication**: Gmail OAuth2 with offline access. Perplexity API key. Google API key. All credentials stored in `.env` (local) or GCP Secret Manager (production). NEVER committed to version control.
- **Authorization**: Cloud Run endpoint protected by IAM. Only the Cloud Scheduler service account can invoke it. No public access.
- **OWASP mitigations**:
  - **Injection (A03:2021)**: LLM-generated content is rendered via Jinja2 templates with autoescaping enabled. No raw HTML injection from LLM output into email template. Markdown-to-HTML conversion uses a sanitization library.
  - **Security Misconfiguration (A05:2021)**: `.env` file is gitignored. Secrets in production use Secret Manager. Cloud Run does not allow unauthenticated access.
  - **Cryptographic Failures (A02:2021)**: All API communications use HTTPS. OAuth tokens stored encrypted at rest in Secret Manager.
  - **SSRF (A10:2021)**: The system only makes outbound calls to known, hardcoded API endpoints (Gemini API, Perplexity API, Gmail API). No user-controlled URLs in HTTP requests.
- **Data sensitivity**: API keys and OAuth tokens are HIGH sensitivity. Newsletter content and topic configs are LOW sensitivity (personal but not regulated).

### 10.3 Scalability & Availability

- **Expected load**: 1 invocation per week (scheduled), occasional manual triggers during development. ~20 API calls per invocation (10 topics x 2 providers).
- **Availability target**: Best-effort. This is a personal tool. If a weekly run fails, the operator checks logs and re-triggers manually.
- **Scaling**: No horizontal scaling needed. Cloud Run single instance is sufficient. Cloud Run min-instances=0 to minimize cost.

### 10.4 Accessibility

Not applicable for MVP. The HTML newsletter uses semantic HTML elements (headings, lists, links) which provides basic screen reader compatibility.

### 10.5 Observability

- **Logging**: Python `logging` module. INFO for pipeline milestones, ERROR for failures. Structured format with timestamp, level, agent name, message. On Cloud Run, stdout/stderr integrates with Cloud Logging.
- **Metrics**: Pipeline total execution time logged at completion. Per-phase timing (research, synthesis, formatting, delivery) logged at INFO level.
- **Alerting**: Not in MVP scope. Operator can configure Cloud Monitoring alerts on Cloud Run error rate or log-based metrics if desired.

---

## 11. Test Requirements

### 11.1 Unit Tests

- **Config validation**: Test all valid/invalid YAML scenarios (missing fields, wrong types, boundary values for topic count, character limits).
- **Perplexity tool**: Mock Perplexity SDK, test happy path (returns text + sources), error path (API failure returns error dict), search_depth mapping (standard -> sonar, deep -> sonar-pro).
- **Gmail tool**: Mock Gmail API client, test send success (returns message ID), auth failure (triggers refresh, then fails), MIME message construction (HTML + plain text parts, correct subject/to/from).
- **Config schema Pydantic models**: Test field validation, defaults, enum constraints.
- **HTML formatter**: Test template rendering with mock synthesis data. Verify all sections present. Verify inline CSS.
- **Agent factory**: Test dynamic agent tree construction for 1, 5, and 20 topics. Verify correct number of sub-agents.
- **Minimum coverage threshold**: 80% line coverage on `config/`, `tools/`, and `templates/` modules.

### 11.2 BDD / Acceptance Tests

```gherkin
Feature: Topic Configuration

  Scenario: Valid config with 3 topics
    Given a topics.yaml file with 3 valid topics and all required newsletter settings
    When the config loader runs
    Then it returns a NewsletterConfig with 3 TopicConfig objects
    And each topic has a non-empty name and query

  Scenario: Config with missing required field
    Given a topics.yaml file where the second topic is missing its query field
    When the config loader runs
    Then it raises ConfigValidationError
    And the error message contains the topic name and "query"

  Scenario: Config with too many topics
    Given a topics.yaml file with 21 topics
    When the config loader runs
    Then it raises ConfigValidationError
    And the error message contains "maximum 20 topics"

Feature: Research Pipeline

  Scenario: Successful dual-source research
    Given a valid topic config with both google_search and perplexity sources
    When the research pipeline runs for that topic
    Then session state contains research_0_google with text and sources
    And session state contains research_0_perplexity with text and sources

  Scenario: Single provider failure
    Given a valid topic config with both sources
    And the Perplexity API returns a 429 error
    When the research pipeline runs
    Then session state research_0_perplexity has error=true
    And session state research_0_google has valid research data
    And the pipeline continues without aborting

  Scenario: Parallel execution of multiple topics
    Given 3 valid topic configs
    When the research pipeline runs
    Then all 3 topics are researched
    And the total time is less than 2x the time of a single topic research

Feature: Synthesis

  Scenario: Deep analysis with citations
    Given completed research for a topic from both Google and Perplexity
    When the synthesis agent runs
    Then the synthesis output is at least 200 words
    And the output contains at least 3 inline citations in [Title](URL) format
    And the citations reference URLs from the research results

  Scenario: Synthesis with partial research
    Given completed research from only Google (Perplexity failed)
    When the synthesis agent runs
    Then the synthesis output is produced using available data
    And the output includes a note about limited sources

Feature: Newsletter Formatting

  Scenario: Complete HTML newsletter
    Given synthesis results for 3 topics and an executive summary
    When the formatter runs
    Then the HTML contains a title header with today's date
    And the HTML contains an executive summary with 3 bullet items
    And the HTML contains a table of contents with 3 linked entries
    And the HTML contains 3 topic sections with body text and source lists

Feature: Email Delivery

  Scenario: Successful email send
    Given a completed newsletter HTML and valid Gmail OAuth2 credentials
    And dry_run is false
    When the delivery agent runs
    Then an email is sent to the configured recipient
    And the email subject matches the pattern "{title} - {date}"

  Scenario: Dry run mode
    Given a completed newsletter HTML
    And dry_run is true
    When the delivery agent runs
    Then no email is sent
    And the HTML is saved to the output directory

  Scenario: Email failure with fallback
    Given a completed newsletter HTML and invalid Gmail credentials
    When the delivery agent runs
    Then an error is logged
    And the HTML is saved to the output directory as fallback
```

### 11.3 Integration Tests

- **Research integration**: Test actual Google Search grounding (with real API key) for a known topic. Verify response contains grounded text and source URLs. Run against Perplexity Sonar API with a real key.
- **Gmail integration**: Test actual email sending to a test Gmail account (can be the same operator account). Verify email arrives with correct subject, HTML body.
- **Full pipeline**: Run the complete pipeline with `dry_run: true` using real API keys. Verify HTML output file is generated with all sections.
- **External dependencies to mock vs. real**: Unit tests mock all external APIs. Integration tests use real APIs with dedicated test credentials. BDD acceptance tests can use either depending on CI/CD setup.
- **Data setup/teardown**: Integration tests use a dedicated `config/test_topics.yaml` with 1-2 lightweight topics. Output files are cleaned up after tests.

### 11.4 End-to-End Tests

- **Critical journey**: Trigger the full pipeline via HTTP POST to a locally running ADK API server. Verify response returns success. Verify HTML file is generated (dry_run mode).
- **Target environment**: Local (for CI) and staging Cloud Run deployment (for pre-production validation).
- **Tools/frameworks**: pytest + pytest-asyncio for async ADK tests. httpx for HTTP client in E2E tests.

### 11.5 Performance Tests

- **5-topic newsletter**: Run full pipeline with 5 topics. Verify total time < 10 minutes.
- **20-topic newsletter**: Run full pipeline with 20 topics. Verify total time < 20 minutes.
- **Pass/fail thresholds**: 5 topics < 600s, 20 topics < 1200s.

### 11.6 Security Tests

- **Secrets not in code**: Verify `.env` is in `.gitignore`. Verify no API keys, tokens, or credentials appear in any committed file.
- **Jinja2 autoescaping**: Verify the HTML template has autoescaping enabled. Test with XSS payload in topic name (e.g., `<script>alert('xss')</script>`) and verify it is escaped in output.
- **Cloud Run auth**: Verify unauthenticated HTTP requests to the Cloud Run service are rejected with 401/403.

---

## 12. Constraints & Assumptions

### Constraints

- **ADK google_search single-tool-per-agent**: Each agent using `google_search` cannot have any other tools. This is an ADK framework constraint.
- **Gmail API OAuth2 requires one-time manual setup**: The initial OAuth2 consent flow must be run interactively in a browser. This cannot be fully automated.
- **Cloud Run request timeout**: Maximum 3600 seconds. We set 600 seconds which is sufficient.
- **Cloud Run memory**: Default 512MB. May need increase for 20-topic runs with large LLM responses. Set to 1GB.
- **Gemini API rate limits**: Gemini Flash and Pro have per-minute/per-day quotas. For 20 topics with 2 providers each, 40+ API calls may hit rate limits on free tier. Operator should use a paid tier or implement request spacing.

### Assumptions

- **A-001**: Operator has a GCP project with billing enabled and APIs activated (Cloud Run, Cloud Scheduler, Secret Manager).
- **A-002**: Operator has a personal Gmail account (not Google Workspace) and can complete the OAuth2 consent flow.
- **A-003**: Gemini 2.5 Flash and Pro models remain available via Google AI Studio or Vertex AI at current pricing.
- **A-004**: Perplexity Sonar API remains available with the current SDK (`perplexityai` package).
- **A-005**: The `google-adk` Python package is installed at version supporting `google_search` tool and Cloud Run deployment.
- **A-006**: Newsletter content is in English only.
- **A-007**: The system processes one newsletter run at a time (no concurrent runs).

---

## 13. Out of Scope

- **Subscriber management, sign-up flows, audience analytics**: This is a personal tool, not a newsletter platform.
- **Human-in-the-loop editorial review**: The MVP is fully autonomous. No approval step before sending.
- **Multi-language support**: English only.
- **Real-time or streaming delivery**: Batch/scheduled system only.
- **Custom LLM fine-tuning**: Uses Gemini models as-is.
- **Google Custom Search Engine integration**: Deferred to P2 increment.
- **Newsletter archive in Cloud Storage**: Deferred to P2 increment.
- **Per-topic scheduling flexibility**: Deferred to P2 increment.
- **Multiple recipients with per-recipient preferences**: Deferred to P3.
- **Web UI for topic management**: Deferred to P3.
- **Cross-issue topic tracking / memory**: Deferred to P3.
- **CI/CD pipeline**: Operator deploys manually via `adk deploy cloud_run`.

---

## 14. Open Questions

| # | Question | Impact if Unresolved | Owner |
|---|----------|---------------------|-------|
| OQ-1 | What are the exact Gemini API rate limits on the Operator's current plan? | May need request spacing or paid tier for 20-topic runs | Operator |
| OQ-2 | Does the Operator's GCP project have Cloud Run, Cloud Scheduler, and Secret Manager APIs enabled? | Deployment will fail if not | Operator |
| OQ-3 | What specific Perplexity API plan will be used? Free tier may have tight rate limits. | Research quality/reliability may suffer | Operator |

---

## 15. Glossary

- **ADK**: Agent Development Kit - Google's framework for building AI agent applications
- **Cloud Run**: Google Cloud serverless container platform
- **Cloud Scheduler**: Google Cloud managed cron job service
- **FunctionTool**: ADK wrapper that turns a Python function into a tool callable by an LLM agent
- **Grounding**: The process of connecting an LLM to real-time web information for factual responses
- **LlmAgent**: ADK agent type powered by a large language model
- **OIDC**: OpenID Connect - authentication protocol used by Cloud Scheduler to invoke Cloud Run
- **ParallelAgent**: ADK workflow agent that executes sub-agents concurrently
- **SequentialAgent**: ADK workflow agent that executes sub-agents in order
- **Sonar**: Perplexity's web-grounded AI model family (sonar, sonar-pro)
- **output_key**: ADK LlmAgent property that automatically saves the agent's response to a session state key

---

## 16. Traceability Matrix

| FR ID | Requirement Summary | User Story | Acceptance Scenario | Test Type | Test Section Ref |
|-------|-------------------|------------|--------------------|-----------|--------------------|
| FR-001 | Load topics from YAML | US-01 | Scenario 1 | unit, BDD | 11.1, 11.2 |
| FR-002 | Topic required fields | US-01 | Scenario 1, 2 | unit, BDD | 11.1, 11.2 |
| FR-003 | Topic optional fields | US-01 | Scenario 1 | unit | 11.1 |
| FR-004 | Config validation fail-fast | US-01 | Scenario 2, 3, 4 | unit, BDD | 11.1, 11.2 |
| FR-005 | Newsletter settings in config | US-01 | Scenario 1 | unit | 11.1 |
| FR-006 | Settings section (dry_run, output_dir) | US-06, US-05 | US-05 Scenario 2, US-06 Scenario 2 | unit, BDD | 11.1, 11.2 |
| FR-007 | Topic count limits (1-20) | US-01 | Scenario 3, 4 | unit, BDD | 11.1, 11.2 |
| FR-008 | Google Search per topic | US-02 | Scenario 1 | unit, integration, BDD | 11.1, 11.3, 11.2 |
| FR-009 | Perplexity Sonar per topic | US-02 | Scenario 1 | unit, integration, BDD | 11.1, 11.3, 11.2 |
| FR-010 | Parallel research execution | US-02 | Scenario 4 | integration, performance | 11.3, 11.5 |
| FR-011 | Namespaced state keys for research | US-02 | Scenario 1 | unit | 11.1 |
| FR-012 | Research result structure | US-02 | Scenario 1 | unit | 11.1 |
| FR-013 | Provider failure resilience | US-02 | Scenario 3 | unit, BDD | 11.1, 11.2 |
| FR-014 | Deep search_depth behavior | US-02 | Scenario 1 | unit | 11.1 |
| FR-015 | Perplexity tool signature | US-02 | Scenario 1 | unit | 11.1 |
| FR-016 | Synthesis via Gemini Pro | US-03 | Scenario 1 | unit, integration, BDD | 11.1, 11.3, 11.2 |
| FR-017 | Deep analysis quality requirements | US-03 | Scenario 1 | BDD, integration | 11.2, 11.3 |
| FR-018 | Executive summary generation | US-08 | Scenario 1 | unit, BDD | 11.1, 11.2 |
| FR-019 | Synthesis state structure | US-03 | Scenario 1 | unit | 11.1 |
| FR-020 | No fabricated facts | US-03 | Scenario 1 | BDD | 11.2 |
| FR-021 | HTML rendering with inline CSS | US-04 | Scenario 3 | unit, BDD | 11.1, 11.2 |
| FR-022 | Newsletter section order | US-04 | Scenario 1 | unit, BDD | 11.1, 11.2 |
| FR-023 | Responsive 600px layout | US-04 | Scenario 2 | unit | 11.1 |
| FR-024 | Topic section content | US-04 | Scenario 1 | unit, BDD | 11.1, 11.2 |
| FR-025 | Executive summary display | US-08 | Scenario 2 | unit, BDD | 11.1, 11.2 |
| FR-026 | newsletter_html in state | US-04 | Scenario 1 | unit | 11.1 |
| FR-027 | Gmail API email send | US-05 | Scenario 1 | unit, integration, BDD | 11.1, 11.3, 11.2 |
| FR-028 | OAuth2 token refresh | US-05 | Scenario 3 | unit, BDD | 11.1, 11.2 |
| FR-029 | MIME multipart message | US-05 | Scenario 1 | unit | 11.1 |
| FR-030 | Email subject/from/to | US-05 | Scenario 1 | unit, BDD | 11.1, 11.2 |
| FR-031 | Dry run skips email, saves HTML | US-05, US-06 | US-05 Scenario 2 | unit, BDD | 11.1, 11.2 |
| FR-032 | Email failure fallback | US-05 | Scenario 4 | unit, BDD | 11.1, 11.2 |
| FR-033 | Dry run full pipeline | US-06 | Scenario 2 | E2E, BDD | 11.4, 11.2 |
| FR-034 | HTML file output path | US-05, US-06 | Scenario 2, 4 | unit | 11.1 |
| FR-035 | Auto-create output directory | US-06 | Scenario 2 | unit | 11.1 |
| FR-036 | Cloud Run deployment | US-07 | Scenario 1 | E2E | 11.4 |
| FR-037 | HTTP trigger endpoint | US-07 | Scenario 2 | E2E | 11.4 |
| FR-038 | Cloud Scheduler cron | US-07 | Scenario 3 | E2E | 11.4 |
| FR-039 | Scheduler OIDC auth | US-07 | Scenario 3 | security | 11.6 |
| FR-040 | Secrets in Secret Manager | US-07 | Scenario 1 | security | 11.6 |
| FR-041 | Local .env secrets | US-06 | Scenario 1 | security | 11.6 |
| FR-042 | INFO-level logging | US-06, US-07 | - | unit | 11.1 |
| FR-043 | ERROR-level logging | US-02, US-05 | Scenario 3, 4 | unit | 11.1 |
| FR-044 | Structured log format | US-06, US-07 | - | unit | 11.1 |
| FR-045 | Cloud Run stdout logging | US-07 | - | E2E | 11.4 |

---

## 17. Technical References

### Architecture & Patterns
- ADK Multi-Agent Systems documentation, https://google.github.io/adk-docs/agents/multi-agents/, consulted 2026-03-14
- ADK Parallel Agent documentation with Parallel Web Research example, https://google.github.io/adk-docs/agents/workflow-agents/parallel-agents/, consulted 2026-03-14
- ADK Sequential Agent documentation, https://google.github.io/adk-docs/agents/workflow-agents/sequential-agents/, consulted 2026-03-14

### Technology Stack
- Google ADK Python quickstart, https://google.github.io/adk-docs/get-started/quickstart/, consulted 2026-03-14
- ADK Function Tools documentation, https://google.github.io/adk-docs/tools-custom/function-tools/, consulted 2026-03-14
- ADK Google Search Grounding, https://google.github.io/adk-docs/grounding/google_search_grounding/, consulted 2026-03-14
- ADK Gemini API Google Search tool, https://google.github.io/adk-docs/integrations/google-search/, consulted 2026-03-14
- ADK Deploy to Cloud Run, https://google.github.io/adk-docs/deploy/cloud-run/, consulted 2026-03-14
- Perplexity API quickstart, https://docs.perplexity.ai/docs/getting-started/quickstart, consulted 2026-03-14

### Security
- OWASP Top 10 2021, https://owasp.org/Top10/
- Gmail API OAuth2 reference, https://developers.google.com/gmail/api/auth/about-auth

### Standards & Specifications
- Gmail API messages.send reference, https://developers.google.com/gmail/api/reference/rest/v1/users.messages/send
- Cloud Scheduler HTTP targets, https://cloud.google.com/scheduler/docs/creating

---

## 18. Version History

| Version | Date | Author | Summary of Changes |
|---------|------|--------|--------------------|
| 1.0 | 2026-03-14 | Spec Architect | Initial specification |
