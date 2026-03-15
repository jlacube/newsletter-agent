# Configuration Guide

## Overview

Newsletter Agent uses two configuration sources:

1. **`config/topics.yaml`** -- Newsletter content, topics, and delivery settings
2. **`.env`** -- API keys and secrets (never committed to version control)

## YAML Configuration Schema

The `config/topics.yaml` file is validated at startup using Pydantic models. Invalid configuration prevents the pipeline from starting and produces detailed error messages.

### Full Schema

```yaml
# Newsletter metadata and delivery settings
newsletter:
  title: "string"              # Required, 1-200 characters
  schedule: "cron expression"  # Required, e.g., "0 8 * * 0"
  recipient_emails:            # 1-10 valid email addresses
    - "email1@example.com"
    - "email2@example.com"
  # OR (deprecated, backward compatible):
  # recipient_email: "email"   # Single email address

# Application settings
settings:
  dry_run: true|false          # Default: false
  output_dir: "path/"          # Default: "output/"
  timeframe: "last_week"       # Optional: search timeframe constraint
  verify_links: true|false     # Default: false -- verify source URLs

# Research topics (1-20 items)
topics:
  - name: "string"             # Required, 1-100 chars, must be unique
    query: "string"            # Required, 1-500 chars
    search_depth: "standard"|"deep"  # Default: "standard"
    sources:                   # Default: ["google_search", "perplexity"]
      - google_search
      - perplexity
    timeframe: "last_month"    # Optional: per-topic timeframe override
```

### Section: `newsletter`

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| `title` | string | Yes | 1-200 chars | Newsletter display title, shown in header and email subject |
| `schedule` | string | Yes | Non-empty | Cron expression for Cloud Scheduler (not enforced locally) |
| `recipient_emails` | list of strings | Yes (or `recipient_email`) | 1-10 unique valid emails | Email addresses for newsletter delivery |
| `recipient_email` | string | Deprecated | Valid email format | Single email address (use `recipient_emails` instead) |

**Note**: You must provide either `recipient_emails` or `recipient_email`, but not both. The singular `recipient_email` field is deprecated and will be removed in a future version. Use `recipient_emails` for new configurations.

### Section: `settings`

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `dry_run` | boolean | No | `false` | When `true`, saves HTML to disk instead of sending email |
| `output_dir` | string | No | `"output/"` | Directory for HTML output (created automatically) |
| `timeframe` | string | No | `null` | Global search timeframe constraint (see Timeframe Values below) |
| `verify_links` | boolean | No | `false` | When `true`, verifies source URLs and removes broken links |
| `max_research_rounds` | integer | No | `3` | Number of research rounds for deep-mode topics (1-5). Only affects topics with `search_depth: deep`. Standard-mode topics always perform 1 round. |
| `max_searches_per_topic` | integer | No | Same as `max_research_rounds` | Maximum search API calls per topic (1-10). Defaults to `max_research_rounds` if omitted. |
| `min_research_rounds` | integer | No | `2` | Minimum rounds before saturation exit is allowed (1-5). Must be <= `max_research_rounds`. |

### Section: `topics`

Each topic is a mapping with these fields:

| Field | Type | Required | Default | Constraints | Description |
|-------|------|----------|---------|-------------|-------------|
| `name` | string | Yes | -- | 1-100 chars, unique | Display name for the topic section |
| `query` | string | Yes | -- | 1-500 chars | Natural language search query |
| `search_depth` | string | No | `"standard"` | `"standard"` or `"deep"` | Controls research mode: standard uses single-round search, deep uses adaptive Plan-Search-Analyze loop |
| `sources` | list | No | Both providers | `"google_search"`, `"perplexity"` | Which search providers to use |
| `timeframe` | string | No | Inherits from settings | See Timeframe Values | Per-topic timeframe override |

### Search Depth Behavior

| Depth | Google Search | Perplexity Model | Research Rounds | Adaptive Loop | Use Case |
|-------|--------------|-----------------|----------------|--------------|----------|
| `standard` | Standard instruction prompt | `sonar` | 1 (single round) | No | Quick research, news summaries |
| `deep` | Detailed multi-faceted prompt | `sonar-pro` | Up to `max_research_rounds` | Yes (Plan-Search-Analyze-Decide) | Comprehensive analysis, trend reports |

When `search_depth: "deep"`, each provider runs a `DeepResearchOrchestrator` that:
1. Invokes a PlanningAgent to identify key aspects and an initial search query
2. Executes search rounds, each followed by an AnalysisAgent that evaluates findings
3. Exits when saturation is detected (and `min_research_rounds` met), knowledge gaps are empty, the search budget is exhausted, or `max_research_rounds` is reached
4. Merges all round results into a single research output and persists a reasoning chain

### Adaptive Research Settings

The adaptive deep research loop is controlled by three settings that work together:

| Setting | Default | Range | Role |
|---------|---------|-------|------|
| `max_research_rounds` | `3` | 1-5 | Maximum reasoning rounds (Plan-Search-Analyze cycles) |
| `max_searches_per_topic` | same as `max_research_rounds` | 1-10 | Search budget cap per topic-provider pair |
| `min_research_rounds` | `2` | 1-3 | Minimum rounds before saturation exit is allowed |

**How the settings interact:**

- `max_research_rounds` controls how many adaptive reasoning rounds the orchestrator can execute. Each round performs a search, then analyzes the results to decide whether to continue.
- `max_searches_per_topic` acts as a **binding search budget constraint**. Even if `max_research_rounds` allows more rounds, the loop exits once the search budget is exhausted. When omitted, it defaults to `max_research_rounds` so each round gets exactly one search.
- `min_research_rounds` prevents premature early exit. Even if the AnalysisAgent reports saturation at round 1, the orchestrator continues until `min_research_rounds` is met. Must be `<=` `max_research_rounds`.
- Setting `max_research_rounds: 1` disables the adaptive loop entirely (no planning or analysis agents are invoked), equivalent to the original single-round deep research.

**Example: configuring adaptive research**

```yaml
settings:
  max_research_rounds: 3       # Up to 3 adaptive rounds
  max_searches_per_topic: 5    # Allow up to 5 searches (budget > rounds)
  min_research_rounds: 2       # Always do at least 2 rounds
```

**Backward compatibility:** Existing configurations that do not include `max_searches_per_topic` or `min_research_rounds` continue to work unchanged. The defaults (`max_searches_per_topic` = `max_research_rounds`, `min_research_rounds` = 2) preserve the behavior of the original deep research mode.

### Timeframe Values

The `timeframe` field accepts the following values:

| Value | Description | Perplexity Filter |
|-------|-------------|-------------------|
| `last_day` | Past 24 hours | `day` |
| `last_week` | Past 7 days | `week` |
| `last_2_weeks` | Past 14 days | `month` |
| `last_month` | Past 30 days | `month` |
| `last_year` | Past 365 days | None |
| `last_N_days` | Custom: past N days (1-365) | Mapped automatically |
| `YYYY-MM-DD..YYYY-MM-DD` | Absolute date range | None |

When a timeframe is set, research agents include date constraints in their
prompts. For Perplexity, the `search_recency_filter` parameter is used when
the timeframe maps to a supported filter value (`day`, `week`, or `month`).

Per-topic `timeframe` overrides the global setting for that topic only.
Omitting `timeframe` entirely preserves the default behavior (no filtering).

### Link Verification Behavior

When `verify_links: true`, the pipeline inserts a LinkVerifier stage after
synthesis. It concurrently checks all source URLs via HTTP HEAD (with GET
fallback) and removes broken links from the output:

- URLs returning 4xx/5xx status codes are removed
- URLs that time out (10s default) are removed
- URLs with DNS failures or SSL errors are removed
- Broken markdown links `[Title](url)` become plain text `Title`
- SSRF protections block requests to private IPs and non-HTTP schemes
- Maximum 10 concurrent verification requests

### Validation Rules

- The `topics` list must contain between 1 and 20 items
- All topic names must be unique (case-sensitive)
- Empty `sources` lists default to `["google_search", "perplexity"]`
- Extra fields in any section cause validation errors (strict schema)
- The `recipient_emails` list must contain 1-10 unique valid email addresses
- The deprecated `recipient_email` field is accepted for backward compatibility
- Specifying both `recipient_email` and `recipient_emails` causes a validation error

### Validation Error Example

```
Config validation failed with 2 error(s):
  topics.0.name: String should have at least 1 character;
  newsletter.recipient_email: 'not-an-email' is not a valid email address
```

## Environment Variables

All secrets and API keys are configured via environment variables, typically in a `.env` file (loaded automatically by ADK).

### Required Variables

| Variable | Purpose | How to Obtain |
|----------|---------|---------------|
| `GOOGLE_API_KEY` | Gemini LLM access and Google Search grounding | [Google AI Studio](https://aistudio.google.com/apikey) |
| `PERPLEXITY_API_KEY` | Perplexity Sonar web search | [Perplexity Settings](https://www.perplexity.ai/settings/api) |

### Gmail OAuth2 Variables (Required for Email Delivery)

| Variable | Purpose | How to Obtain |
|----------|---------|---------------|
| `GMAIL_CLIENT_ID` | OAuth2 client identifier | Google Cloud Console > Credentials |
| `GMAIL_CLIENT_SECRET` | OAuth2 client secret | Google Cloud Console > Credentials |
| `GMAIL_REFRESH_TOKEN` | Long-lived OAuth2 token | Run `python setup_gmail_oauth.py` |

### Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Python logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `LOG_FORMAT_JSON` | `false` | Set to `true` to emit JSON-structured logs (auto-enabled on Cloud Run) |

### .env File Template

```bash
# Google AI / ADK
GOOGLE_API_KEY=your-google-api-key-here

# Perplexity AI
PERPLEXITY_API_KEY=your-perplexity-api-key-here

# Gmail OAuth2 (run setup_gmail_oauth.py to obtain these)
GMAIL_CLIENT_ID=your-gmail-client-id-here
GMAIL_CLIENT_SECRET=your-gmail-client-secret-here
GMAIL_REFRESH_TOKEN=your-gmail-refresh-token-here
```

## Example Configurations

### Minimal Configuration (1 Topic, Defaults)

```yaml
newsletter:
  title: "My Newsletter"
  schedule: "0 8 * * 1"
  recipient_email: "me@example.com"

topics:
  - name: "Tech News"
    query: "Latest technology news and developments"
```

### Full Configuration (Multiple Topics, Mixed Depths)

```yaml
newsletter:
  title: "Weekly Tech Digest"
  schedule: "0 8 * * 0"
  recipient_email: "team@company.com"

settings:
  dry_run: false
  output_dir: "output/"

topics:
  - name: "AI Frameworks"
    query: >-
      Latest developments in AI agent frameworks, including LangChain,
      CrewAI, Google ADK, and AutoGen. Focus on new releases, benchmarks,
      and adoption trends.
    search_depth: "deep"
    sources:
      - google_search
      - perplexity

  - name: "Cloud Native"
    query: >-
      Recent developments in cloud-native technologies, Kubernetes,
      serverless platforms, and major cloud provider announcements.

  - name: "Open Source Highlights"
    query: >-
      Notable new open source projects, major releases, and community
      trends in software development.
    sources:
      - google_search
```

### Development Configuration (Dry-Run, Single Source)

```yaml
newsletter:
  title: "Dev Test"
  schedule: "0 0 * * *"
  recipient_email: "dev@example.com"

settings:
  dry_run: true
  output_dir: "output/dev/"

topics:
  - name: "Test Topic"
    query: "Latest Python releases and features"
    sources:
      - perplexity
```

## Configuration Loading

The configuration is loaded and validated at pipeline startup:

1. Read `config/topics.yaml` using PyYAML's `safe_load`
2. Validate the parsed data against Pydantic models
3. On success, the validated config object is used to build the agent pipeline
4. On failure, a `ConfigValidationError` is raised with field-level details

The validated config values (title, recipient email, dry_run, output_dir) are injected into ADK session state by the `ConfigLoaderAgent` at the start of each pipeline run, making them available to all downstream agents.
