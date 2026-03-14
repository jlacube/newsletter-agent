# Newsletter Agent

An autonomous multi-agent system that performs deep research on configured topics
using Google Search and Perplexity AI, synthesizes findings into a professional
HTML newsletter, and delivers it via Gmail.

Built with [Google Agent Development Kit (ADK)](https://google.github.io/adk-docs/).

## Quick Start

```bash
# 1. Clone the repository
git clone <repo-url> && cd NewsletterAgent

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env with your API keys (see Environment Setup below)

# 4. Configure topics
# Edit config/topics.yaml with your desired topics

# 5. Run locally (dry-run mode saves HTML instead of sending email)
adk web
```

## Prerequisites

- Python 3.11+
- Google Cloud project with Gemini API enabled
- Google API key for Gemini models ([Get one here](https://aistudio.google.com/apikey))
- Perplexity API key ([Get one here](https://www.perplexity.ai/settings/api))
- Gmail account for email delivery (optional for dry-run mode)

## Installation

```bash
# Create a virtual environment (recommended)
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/macOS

# Install all dependencies
pip install -r requirements.txt
```

## Environment Setup

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_API_KEY` | Yes | Gemini API key for LLM and Google Search |
| `PERPLEXITY_API_KEY` | Yes | Perplexity Sonar API key for deep research |
| `GMAIL_CLIENT_ID` | For email | Gmail OAuth2 client ID |
| `GMAIL_CLIENT_SECRET` | For email | Gmail OAuth2 client secret |
| `GMAIL_REFRESH_TOKEN` | For email | Gmail OAuth2 refresh token |
| `LOG_LEVEL` | No | Logging level (default: INFO) |

## Configuration

Edit `config/topics.yaml` to define your newsletter:

```yaml
newsletter:
  title: "Weekly Tech Digest"
  schedule: "0 8 * * 0"                    # Cron: Sunday 8am UTC
  recipient_email: "your-email@gmail.com"

settings:
  dry_run: true                             # true = save HTML, false = send email
  output_dir: "output/"

topics:
  - name: "AI Frameworks"
    query: "Latest developments in AI agent frameworks"
    search_depth: "deep"                    # "standard" or "deep"
    sources:                                # Optional, defaults to both
      - google_search
      - perplexity

  - name: "Cloud Native"
    query: "Recent cloud-native technology developments"
    # Uses defaults: standard depth, both sources
```

**Configuration rules:**
- 1 to 20 topics allowed
- Topic names must be unique (max 100 chars)
- Queries max 500 chars
- `search_depth`: `"standard"` (default) or `"deep"`
- `sources`: `["google_search", "perplexity"]` (default -- both)

## Gmail OAuth2 Setup

To enable email delivery, set up Gmail OAuth2:

1. Go to [Google Cloud Console > APIs & Services > Credentials](https://console.cloud.google.com/apis/credentials)
2. Create an OAuth 2.0 Client ID (Desktop application type)
3. Download the client ID and secret
4. Add your client ID and secret to `.env`
5. Run the setup script:

```bash
python setup_gmail_oauth.py
```

6. Complete the browser-based OAuth flow
7. Copy the refresh token into `.env` as `GMAIL_REFRESH_TOKEN`

## Local Development

### Interactive Dev UI

```bash
adk web
```

Opens the ADK development UI in your browser where you can trigger the pipeline
and inspect agent execution.

### Command Line

```bash
adk run newsletter_agent
```

Runs the pipeline once from the command line.

### Dry-Run Mode

Set `dry_run: true` in `config/topics.yaml` to save the newsletter as an HTML
file in the `output/` directory instead of sending email. This is the default
for local development.

### Running Tests

```bash
# All tests
pytest tests/ -v

# Unit tests only
pytest tests/unit/ -v

# E2E tests
pytest tests/e2e/ -v

# Security tests
pytest tests/security/ -v

# Performance tests (may be slow)
pytest -m performance -v
```

## Architecture

```
newsletter_agent/
  agent.py           - Root agent and pipeline factory
  logging_config.py  - Structured logging configuration
  timing.py          - Pipeline timing instrumentation
  http_handler.py    - Cloud Run HTTP trigger endpoint
  config/
    schema.py        - Pydantic config models and loader
  prompts/
    research_google.py     - Google Search agent instructions
    research_perplexity.py - Perplexity agent instructions
    synthesis.py           - Synthesis agent instructions
  tools/
    perplexity_search.py   - Perplexity Sonar API tool
    synthesis_utils.py     - Synthesis JSON parser
    sanitizer.py           - HTML sanitization (nh3)
    formatter.py           - HTML rendering (Jinja2)
    delivery.py            - Email/file delivery agent
    gmail_auth.py          - Gmail OAuth2 credentials
    gmail_send.py          - Gmail API send
    file_output.py         - Local file output
  templates/
    newsletter.html.j2     - Newsletter HTML template
```

### Agent Pipeline

```
Root SequentialAgent ("newsletter_agent")
  |
  +-- ResearchPhase (ParallelAgent)
  |     +-- Topic0Research (SequentialAgent)
  |     |     +-- GoogleSearcher_0 (LlmAgent, gemini-2.5-flash)
  |     |     +-- PerplexitySearcher_0 (LlmAgent, gemini-2.5-flash)
  |     +-- Topic1Research (SequentialAgent)
  |     |     +-- GoogleSearcher_1
  |     |     +-- PerplexitySearcher_1
  |     +-- ... (one per topic, all run in parallel)
  |
  +-- SynthesisAgent (LlmAgent, gemini-2.5-pro)
  |
  +-- FormatterAgent (BaseAgent, Jinja2 HTML)
  |
  +-- DeliveryAgent (BaseAgent, Gmail/file)
```

Topics are configured in `config/topics.yaml`. The agent tree is built
dynamically at startup -- N topics produce N parallel research sub-pipelines.

## Deployment to Cloud Run

### 1. Deploy the Agent

```bash
adk deploy cloud_run \
  --project=YOUR_PROJECT_ID \
  --region=us-central1 \
  ./newsletter_agent
```

### 2. Store Secrets in Secret Manager

```bash
# Create secrets
echo -n "YOUR_GOOGLE_API_KEY" | gcloud secrets create GOOGLE_API_KEY --data-file=-
echo -n "YOUR_PERPLEXITY_KEY" | gcloud secrets create PERPLEXITY_API_KEY --data-file=-
echo -n "YOUR_REFRESH_TOKEN" | gcloud secrets create GMAIL_REFRESH_TOKEN --data-file=-
echo -n "YOUR_CLIENT_ID" | gcloud secrets create GMAIL_CLIENT_ID --data-file=-
echo -n "YOUR_CLIENT_SECRET" | gcloud secrets create GMAIL_CLIENT_SECRET --data-file=-

# Grant access to the Cloud Run service account
SA="YOUR_SERVICE_ACCOUNT@YOUR_PROJECT.iam.gserviceaccount.com"
for SECRET in GOOGLE_API_KEY PERPLEXITY_API_KEY GMAIL_REFRESH_TOKEN GMAIL_CLIENT_ID GMAIL_CLIENT_SECRET; do
  gcloud secrets add-iam-policy-binding $SECRET \
    --member="serviceAccount:$SA" \
    --role="roles/secretmanager.secretAccessor"
done
```

### 3. Configure Cloud Run Service

```bash
gcloud run services update newsletter-agent \
  --region=us-central1 \
  --memory=1Gi \
  --timeout=600 \
  --min-instances=0 \
  --max-instances=1 \
  --concurrency=1 \
  --set-secrets="GOOGLE_API_KEY=GOOGLE_API_KEY:latest,PERPLEXITY_API_KEY=PERPLEXITY_API_KEY:latest,GMAIL_REFRESH_TOKEN=GMAIL_REFRESH_TOKEN:latest,GMAIL_CLIENT_ID=GMAIL_CLIENT_ID:latest,GMAIL_CLIENT_SECRET=GMAIL_CLIENT_SECRET:latest"
```

### 4. Set Up Cloud Scheduler

```bash
# Create a service account for the scheduler
gcloud iam service-accounts create newsletter-scheduler \
  --display-name="Newsletter Scheduler"

# Grant invoker role
gcloud run services add-iam-policy-binding newsletter-agent \
  --region=us-central1 \
  --member="serviceAccount:newsletter-scheduler@YOUR_PROJECT.iam.gserviceaccount.com" \
  --role="roles/run.invoker"

# Create the scheduled job (Sunday 8am UTC)
SERVICE_URL=$(gcloud run services describe newsletter-agent --region=us-central1 --format="value(status.url)")
gcloud scheduler jobs create http newsletter-weekly \
  --schedule="0 8 * * 0" \
  --uri="${SERVICE_URL}/run" \
  --http-method=POST \
  --oidc-service-account-email=newsletter-scheduler@YOUR_PROJECT.iam.gserviceaccount.com \
  --oidc-token-audience="${SERVICE_URL}"
```

### 5. Manual Trigger

```bash
gcloud scheduler jobs run newsletter-weekly
```

### Deployment Checklist

- [ ] All tests pass locally: `pytest tests/ -v`
- [ ] `config/topics.yaml` is valid with real topics
- [ ] `dry_run` is set to `false` for production
- [ ] GCP APIs enabled: Cloud Run, Cloud Scheduler, Secret Manager
- [ ] Secrets stored in Secret Manager
- [ ] Cloud Run service deployed with correct memory/timeout
- [ ] Cloud Scheduler job created with OIDC authentication
- [ ] Manual trigger succeeds

## Troubleshooting

**"Config file not found"** -- Ensure `config/topics.yaml` exists. Copy from the
example in this README or the provided template.

**"Missing GOOGLE_API_KEY"** -- Set the environment variable in `.env` (local) or
Secret Manager (Cloud Run). Get a key from https://aistudio.google.com/apikey.

**"GmailAuthError"** -- Run `python setup_gmail_oauth.py` to refresh your OAuth2
credentials. Ensure `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, and
`GMAIL_REFRESH_TOKEN` are set correctly.

**"Perplexity API error"** -- Verify your `PERPLEXITY_API_KEY` is valid and has
available credits at https://www.perplexity.ai/settings/api.

**Pipeline times out on Cloud Run** -- The default timeout is 600 seconds. For
20 topics with deep search, this may not be enough. Increase the timeout or
reduce the number of topics.

**HTML output is empty** -- Check the logs for synthesis errors. The synthesis
agent may have failed to produce valid JSON. Verify your Gemini API key has
access to `gemini-2.5-pro`.
