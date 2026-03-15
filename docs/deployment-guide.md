# Deployment Guide

## Overview

Newsletter Agent can run locally (using ADK CLI) or be deployed to Google Cloud Run with Cloud Scheduler for automated weekly execution.

## Local Development

### Running with ADK Dev UI

```bash
adk web
```

Opens the ADK development UI in your browser where you can trigger the pipeline interactively and inspect agent execution, state, and events.

### Running from Command Line

```bash
adk run newsletter_agent
```

Runs the pipeline once interactively and exits.

### Autonomous CLI Runner

```bash
python -m newsletter_agent
```

Runs the full pipeline autonomously without interactive input. This is the recommended mode for scheduled/automated execution (e.g., cron, Cloud Scheduler, CI/CD). The runner:

- Sends a `"Generate newsletter"` trigger message automatically
- Logs pipeline progress to stdout
- Prints a JSON summary line on completion
- Exits with code 0 (success) or 1 (failure)

### Dry-Run Mode

Set `dry_run: true` in `config/topics.yaml` to save the newsletter as an HTML file instead of sending email. This is the recommended mode for local development.

Output files are saved to the configured `output_dir` (default: `output/`) with the filename `YYYY-MM-DD-newsletter.html`.

## Cloud Run Deployment

### Prerequisites

- Google Cloud project with billing enabled
- `gcloud` CLI installed and authenticated
- The following GCP APIs enabled:
  - Cloud Run
  - Cloud Scheduler
  - Secret Manager
  - Gmail API
  - Generative Language API (for Gemini)

### Step 1: Deploy the Agent to Cloud Run

```bash
adk deploy cloud_run \
  --project=YOUR_PROJECT_ID \
  --region=us-central1 \
  ./newsletter_agent
```

### Step 2: Store Secrets in Secret Manager

Never pass API keys as plain environment variables in Cloud Run. Use Secret Manager:

```bash
# Create each secret
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

### Step 3: Configure the Cloud Run Service

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

**Recommended resource settings:**

| Setting | Value | Rationale |
|---------|-------|-----------|
| Memory | 1 GiB | Sufficient for LLM response processing |
| Timeout | 600s (10 min) | Allows for multiple LLM calls across topics |
| Min instances | 0 | Scale to zero when idle (cost savings) |
| Max instances | 1 | Newsletter generation is a single-execution job |
| Concurrency | 1 | Only one pipeline run at a time |

For newsletters with many topics (10+) using `search_depth: "deep"`, consider increasing the timeout to 900s. Deep-mode topics perform multiple research rounds (up to `max_research_rounds` per provider), which increases total pipeline time.

### Step 4: Set Up Cloud Scheduler

Create a scheduled job that triggers the pipeline via HTTP POST:

```bash
# Create a dedicated service account for the scheduler
gcloud iam service-accounts create newsletter-scheduler \
  --display-name="Newsletter Scheduler"

# Grant the scheduler permission to invoke the Cloud Run service
gcloud run services add-iam-policy-binding newsletter-agent \
  --region=us-central1 \
  --member="serviceAccount:newsletter-scheduler@YOUR_PROJECT.iam.gserviceaccount.com" \
  --role="roles/run.invoker"

# Get the Cloud Run service URL
SERVICE_URL=$(gcloud run services describe newsletter-agent \
  --region=us-central1 --format="value(status.url)")

# Create the scheduled job (matches the cron in topics.yaml)
gcloud scheduler jobs create http newsletter-weekly \
  --schedule="0 8 * * 0" \
  --uri="${SERVICE_URL}/run" \
  --http-method=POST \
  --oidc-service-account-email=newsletter-scheduler@YOUR_PROJECT.iam.gserviceaccount.com \
  --oidc-token-audience="${SERVICE_URL}"
```

### Step 5: Test the Deployment

Trigger a manual run:

```bash
gcloud scheduler jobs run newsletter-weekly
```

Check the Cloud Run logs:

```bash
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=newsletter-agent" \
  --limit=50 --format="table(timestamp,severity,textPayload)"
```

## HTTP Endpoint Reference

The Cloud Run service exposes a single endpoint:

### POST /run

Triggers a full newsletter generation cycle.

**Request**: Empty body (Cloud Scheduler sends an empty POST).

**Success Response (200)**:
```json
{
  "status": "success",
  "newsletter_date": "2026-03-14",
  "topics_processed": 3,
  "email_sent": true
}
```

**Dry-Run Response (200)**:
```json
{
  "status": "success",
  "newsletter_date": "2026-03-14",
  "topics_processed": 3,
  "email_sent": false,
  "output_file": "/app/output/2026-03-14-newsletter.html"
}
```

**Error Response (500)**:
```json
{
  "status": "error",
  "message": "Pipeline failed: RuntimeError: ..."
}
```

## Deployment Checklist

Pre-deployment:

- [ ] All tests pass: `pytest tests/ -v`
- [ ] `config/topics.yaml` is valid with real topics
- [ ] `dry_run` is set to `false` for production email delivery
- [ ] API keys are valid and have sufficient quota

GCP setup:

- [ ] Cloud Run API enabled
- [ ] Cloud Scheduler API enabled
- [ ] Secret Manager API enabled
- [ ] Gmail API enabled
- [ ] Generative Language API enabled >

Deployment:

- [ ] Agent deployed to Cloud Run via `adk deploy cloud_run`
- [ ] All secrets stored in Secret Manager
- [ ] Cloud Run service configured with secrets, memory, and timeout
- [ ] Scheduler service account created with invoker role
- [ ] Cloud Scheduler job created with OIDC authentication
- [ ] Manual trigger succeeds and newsletter is delivered

## Monitoring

### Cloud Run Logs

Pipeline logs are written to stdout/stderr and captured by Cloud Logging:

- **INFO**: Phase start/completion, timing, config loaded
- **WARNING**: Fallback behavior, missing optional data
- **ERROR**: Provider failures, email failures
- **CRITICAL**: All research providers failed

### Key Log Messages

| Message Pattern | Meaning |
|----------------|---------|
| `Pipeline started` | Pipeline run began |
| `Pipeline completed in Xs` | Total pipeline execution time |
| `Built research phase: N topics` | Agent tree constructed successfully |
| `[DeepResearch] Topic X/provider round N: Y new URLs, Z total accumulated` | Deep research round progress |
| `[DeepResearch] Topic X/provider: early exit at round N with Z URLs` | Early exit from deep research (15+ URLs) |
| `[DeepResearch] Topic X/provider: completed N rounds, Z unique URLs` | Deep research orchestration complete |
| `Config loaded into state` | Config values written to session state |
| `Email sent: message_id=X` | Newsletter delivered successfully |
| `Dry run: newsletter saved to X` | HTML saved (dry-run mode) |
| `All research providers failed` | CRITICAL - pipeline will abort |
| `Pipeline aborted: all research failed` | Pipeline halted, no email sent |

### Alerting

Set up Cloud Monitoring alerts for:

- Cloud Run error rate > 0 (catches pipeline failures)
- Cloud Scheduler job failure (catches authentication or network issues)
- Log-based metric for CRITICAL log level (catches all-research-failed)

## Updating the Deployment

To update topics or settings:

1. Edit `config/topics.yaml`
2. Re-deploy: `adk deploy cloud_run --project=YOUR_PROJECT_ID --region=us-central1 ./newsletter_agent`

To update secrets:

```bash
echo -n "NEW_VALUE" | gcloud secrets versions add SECRET_NAME --data-file=-
```

Cloud Run automatically picks up the latest secret version on the next cold start.
