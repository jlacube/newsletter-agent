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
  recipient_email: "email"     # Required, valid email address

# Application settings
settings:
  dry_run: true|false          # Default: false
  output_dir: "path/"          # Default: "output/"

# Research topics (1-20 items)
topics:
  - name: "string"             # Required, 1-100 chars, must be unique
    query: "string"            # Required, 1-500 chars
    search_depth: "standard"|"deep"  # Default: "standard"
    sources:                   # Default: ["google_search", "perplexity"]
      - google_search
      - perplexity
```

### Section: `newsletter`

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| `title` | string | Yes | 1-200 chars | Newsletter display title, shown in header and email subject |
| `schedule` | string | Yes | Non-empty | Cron expression for Cloud Scheduler (not enforced locally) |
| `recipient_email` | string | Yes | Valid email format | Email address for newsletter delivery |

### Section: `settings`

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `dry_run` | boolean | No | `false` | When `true`, saves HTML to disk instead of sending email |
| `output_dir` | string | No | `"output/"` | Directory for HTML output (created automatically) |
| `timeframe` | string | No | `null` | Global search timeframe constraint (see Timeframe Values below) |
| `verify_links` | boolean | No | `false` | When `true`, verifies source URLs and removes broken links |

### Section: `topics`

Each topic is a mapping with these fields:

| Field | Type | Required | Default | Constraints | Description |
|-------|------|----------|---------|-------------|-------------|
| `name` | string | Yes | -- | 1-100 chars, unique | Display name for the topic section |
| `query` | string | Yes | -- | 1-500 chars | Natural language search query |
| `search_depth` | string | No | `"standard"` | `"standard"` or `"deep"` | Controls model selection and prompt detail |
| `sources` | list | No | Both providers | `"google_search"`, `"perplexity"` | Which search providers to use |
| `timeframe` | string | No | Inherits from settings | See Timeframe Values | Per-topic timeframe override |

### Search Depth Behavior

| Depth | Google Search | Perplexity Model | Use Case |
|-------|--------------|-----------------|----------|
| `standard` | Standard instruction prompt | `sonar` | Quick research, news summaries |
| `deep` | Detailed multi-faceted prompt | `sonar-pro` | Comprehensive analysis, trend reports |

### Timeframe Values

The `timeframe` field accepts the following values:

| Value | Description | Perplexity Filter |
|-------|-------------|-------------------|
| `last_day` | Past 24 hours | `day` |
| `last_week` | Past 7 days | `week` |
| `last_2_weeks` | Past 14 days | `week` |
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
- The `recipient_email` must match standard email format

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
