# User Guide

## Overview

Newsletter Agent is an autonomous multi-agent system that researches configured topics using Google Search and Perplexity AI, synthesizes findings into a professional HTML newsletter, and optionally delivers it via Gmail.

## Getting Started

### Prerequisites

- Python 3.11 or later
- A Google API key with Gemini API access
- A Perplexity API key (for Perplexity Sonar search)
- Gmail OAuth2 credentials (only required for email delivery)

### Installation

```bash
# Clone the repository
git clone <repo-url> && cd NewsletterAgent

# Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate       # Windows
# source .venv/bin/activate  # Linux/macOS

# Install dependencies
pip install -r requirements.txt
```

### Environment Setup

Copy the example environment file and fill in your API keys:

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_API_KEY` | Yes | Gemini API key for LLM and Google Search |
| `PERPLEXITY_API_KEY` | Yes | Perplexity Sonar API key |
| `GMAIL_CLIENT_ID` | For email | Gmail OAuth2 client ID |
| `GMAIL_CLIENT_SECRET` | For email | Gmail OAuth2 client secret |
| `GMAIL_REFRESH_TOKEN` | For email | Gmail OAuth2 refresh token |
| `LOG_LEVEL` | No | Logging level (default: INFO) |

## Configuring Your Newsletter

Edit `config/topics.yaml` to define what the newsletter covers:

```yaml
newsletter:
  title: "Weekly Tech Digest"
  schedule: "0 8 * * 0"                    # Cron: Sunday 8am UTC
  recipient_emails:                         # 1-10 email addresses
    - "alice@example.com"
    - "bob@example.com"

settings:
  dry_run: true                             # true = save HTML only, false = send email
  output_dir: "output/"
  max_research_rounds: 3                    # 1-5, rounds per provider for deep topics

topics:
  - name: "AI Frameworks"
    query: "Latest developments in AI agent frameworks"
    search_depth: "deep"
    sources:
      - google_search
      - perplexity

  - name: "Cloud Native"
    query: "Recent cloud-native technology developments"
```

The old `recipient_email` field (single string) is still accepted for backward
compatibility but is deprecated. Use `recipient_emails` for new configurations.

### Topic Configuration Options

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `name` | Yes | -- | Display name for the topic section (1-100 chars, must be unique) |
| `query` | Yes | -- | Natural language search query (1-500 chars) |
| `search_depth` | No | `"standard"` | `"standard"` for quick research, `"deep"` for multi-round comprehensive analysis |
| `sources` | No | Both | List of `"google_search"` and/or `"perplexity"` |

### Configuration Rules

- Between 1 and 20 topics are allowed
- Topic names must be unique
- `search_depth: "deep"` performs multi-round research: the system generates alternative query angles, runs multiple search rounds per provider (up to `max_research_rounds` in settings), and combines all results for richer analysis. After link verification, a refinement step selects the 5-10 most relevant sources per provider using LLM-based evaluation. It also uses the Perplexity `sonar-pro` model and more detailed Google Search prompts
- If `sources` is omitted, both Google Search and Perplexity are used

## Running the Newsletter

### Dry-Run Mode (Default)

With `dry_run: true` in `config/topics.yaml`, the pipeline saves the newsletter as an HTML file instead of sending email. This is recommended for development and testing.

```bash
# Using ADK dev UI (opens browser)
adk web

# Using ADK command line (interactive)
adk run newsletter_agent

# Autonomous CLI runner (no interactive input needed)
python -m newsletter_agent
```

The generated HTML file is saved to the configured `output_dir` (default: `output/`) with the filename format `YYYY-MM-DD-newsletter.html`.

### Autonomous CLI Runner

The `python -m newsletter_agent` command runs the entire pipeline without interactive input. It is designed for scheduled/automated execution (cron, Cloud Scheduler, CI/CD). On completion it prints a JSON summary line and exits with code 0 (success) or 1 (failure).

### Email Delivery Mode

Set `dry_run: false` and ensure Gmail OAuth2 credentials are configured:

1. Set up Gmail OAuth2 (see below)
2. Set `dry_run: false` in `config/topics.yaml`
3. Run the pipeline

The newsletter is sent as an HTML email with a plain-text fallback.

## Gmail OAuth2 Setup

To enable email delivery:

1. Go to [Google Cloud Console > APIs & Services > Credentials](https://console.cloud.google.com/apis/credentials)
2. Create an OAuth 2.0 Client ID (Desktop application type)
3. Enable the Gmail API in your Google Cloud project
4. Download the client secrets JSON file
5. Run the setup script:

```bash
python setup_gmail_oauth.py --client-secrets-file path/to/client_secret.json
```

6. Complete the browser-based OAuth consent flow
7. Copy the three values printed to your `.env` file:
   - `GMAIL_CLIENT_ID`
   - `GMAIL_CLIENT_SECRET`
   - `GMAIL_REFRESH_TOKEN`

### Troubleshooting OAuth

- If no refresh token is received, revoke the app's access at [Google Account Permissions](https://myaccount.google.com/permissions) and run the setup script again
- The default callback port is 8080; use `--port 9000` if 8080 is in use

## Understanding the Output

### Newsletter Structure

Each generated newsletter contains:

1. **Header** -- Newsletter title and generation date
2. **Executive Summary** -- Bulleted list with a 1-3 sentence overview per topic
3. **Table of Contents** -- Clickable anchor links to each topic section
4. **Topic Sections** -- Deep analysis per topic with inline source citations
5. **Source Appendix** -- Consolidated numbered list of all referenced sources
6. **Footer** -- Generation timestamp and elapsed time

### Email Format

Emails are sent as MIME multipart messages with both HTML and plain-text parts. The subject line follows the format: `{Newsletter Title} - {YYYY-MM-DD}`.

## HTTP Endpoint

For Cloud Run deployment, the system exposes a `POST /run` endpoint. See the [Deployment Guide](deployment-guide.md) for details.

### Response Format

**Success (200)**:
```json
{
  "status": "success",
  "newsletter_date": "2026-03-14",
  "topics_processed": 3,
  "email_sent": true
}
```

**Dry-run success (200)**:
```json
{
  "status": "success",
  "newsletter_date": "2026-03-14",
  "topics_processed": 3,
  "email_sent": false,
  "output_file": "/app/output/2026-03-14-newsletter.html"
}
```

**Error (500)**:
```json
{
  "status": "error",
  "message": "Pipeline failed: RuntimeError: ..."
}
```

## Troubleshooting

| Symptom | Cause | Solution |
|---------|-------|----------|
| "Config file not found" | Missing `config/topics.yaml` | Create the config file from the template above |
| "Missing GOOGLE_API_KEY" | Environment variable not set | Add to `.env` or set in your shell |
| "GmailAuthError" | OAuth2 credentials expired or missing | Run `python setup_gmail_oauth.py` to refresh |
| "Perplexity API error" | Invalid or exhausted API key | Check key at https://www.perplexity.ai/settings/api |
| HTML output is empty | Synthesis agent failed | Check logs; verify Gemini API access to `gemini-2.5-pro` |
| Pipeline aborted | All research providers failed | Check API keys and network connectivity |
| Timeout on Cloud Run | Too many topics with deep search | Reduce topics or increase Cloud Run timeout |
