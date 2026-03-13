# Newsletter Agent - Ideation Brief

## The Idea

An autonomous newsletter system built on Google's Agent Development Kit (ADK) that performs deep, multi-source research on user-defined topics on a configurable schedule, synthesizes findings into a professionally formatted HTML newsletter, and delivers it via email. Topics and their search descriptions are declared in natural language within a simple YAML config file. The system runs locally for development and deploys to GCP (Cloud Run + Cloud Scheduler) for production.

## Problem & Opportunity

Staying current across multiple technical or domain-specific areas requires hours of weekly reading, filtering, and cross-referencing. Existing newsletter services (Substack, Revue, Beehiiv) are publishing platforms - they expect a human author to do the research and writing. Generic AI summarizers offer shallow, single-source summaries without proper attribution.

The opportunity is a fully autonomous research-and-write pipeline that:
- Searches across multiple providers (Google Search, Perplexity AI, Google Custom Search) for breadth and depth
- Cross-references and synthesizes findings rather than just summarizing a single source
- Produces a polished, cited newsletter ready for consumption
- Runs on a schedule without human intervention
- Costs near-zero to operate (GCP free tier + API costs only)

## Competitive Landscape

**GraphNews** (github.com/SimonSl07/GraphNews): Multi-agent newsletter system using LangGraph, DeepSeek, and MCP. Self-correcting editorial pipeline. Strengths: editorial quality loop. Weaknesses: tied to LangGraph/DeepSeek, no scheduling or email delivery built-in, no GCP deployment story.

**Multi-Agent-Newsletter-Automation** (n8n-based projects on GitHub): Uses n8n workflow automation with Gemini API agents. Strengths: visual workflow design, easy to modify. Weaknesses: requires n8n hosting, not a code-first approach, limited research depth (single search source), no deep analysis capability.

**Perplexity Pro / ChatGPT Deep Research**: Manual tools - you ask a question and get a research report. Strengths: high-quality synthesis. Weaknesses: not automated, not scheduled, not formatted as a newsletter, no multi-topic batching.

**Traditional newsletter tools (Substack, Mailchimp, Beehiiv)**: Publishing and distribution platforms. Strengths: subscriber management, templates, analytics. Weaknesses: zero research or content generation capability - they are delivery-only.

**This project differentiates by**: being ADK-native (first-class Google ecosystem integration), combining multiple search backends for deeper research, running fully autonomously on GCP with near-zero cost, and being code-first/config-driven for developer control.

## Vision

A personal research assistant that delivers a weekly deep-analysis newsletter to your inbox, covering every domain you care about. You configure topics in plain English, set a schedule, and forget about it. Each issue arrives with well-synthesized insights, proper source citations, and professional formatting. Over time, the system could evolve to learn your preferences, track topic evolution across issues, and support multiple recipients.

## Target Users

**Primary**: Developer/technologist who wants to stay current across 5+ domains (AI, cloud, programming languages, industry trends, etc.) without spending hours reading. Comfortable with YAML configs and GCP deployment. Has a personal Gmail and GCP project.

**Context**: Reads newsletters but finds most too shallow. Wants synthesis, not just links. Values source attribution. Prefers automation over manual curation.

## Core Value Proposition

Automated deep research and synthesis across multiple topics and search sources, delivered as a polished weekly newsletter - zero manual effort after initial configuration.

## Key Capabilities

### P1 - Must-Have (MVP)

- **Topic configuration via YAML**: Define 5+ topics with natural language search descriptions and schedule (e.g., weekly). Each topic has a name, a search query in plain English, and optional parameters like search depth or preferred sources.
- **Multi-source research pipeline**: For each topic, the system searches using ADK's built-in Google Search grounding tool and Perplexity Sonar API (as a custom function tool). Results are gathered, deduplicated, and fed to a synthesis agent.
- **Deep analysis synthesis**: An LLM agent (Gemini) takes the raw research results for each topic and produces a deep analysis section - multi-paragraph, cross-referencing sources, highlighting key developments, with inline citations.
- **HTML newsletter formatting**: A formatting agent or template engine renders the synthesized content into a styled HTML email with sections per topic, source links, table of contents, and a clean reading experience.
- **Email delivery via Gmail API**: Sends the formatted newsletter to the configured recipient(s) using Gmail API with OAuth2 authentication. Works with a personal Gmail account (no Workspace required).
- **Local development runner**: Run the full pipeline locally via `adk web` or `adk run` for testing and iteration before deploying.
- **Cloud Run deployment**: Deploy to GCP Cloud Run using `adk deploy cloud_run`. The deployed service exposes an HTTP endpoint that triggers a full newsletter generation cycle.
- **Cloud Scheduler trigger**: A Cloud Scheduler job calls the Cloud Run endpoint on the configured schedule (e.g., every Sunday at 8am).

### P2 - Important (next increment)

- **Google Custom Search integration**: Add Programmable Search Engine as a third search tool for domain-specific searches (e.g., only HackerNews, only arxiv.org). Configurable per topic in YAML.
- **Newsletter archive**: Store generated newsletters as HTML files in Cloud Storage or locally, enabling a browsable archive and deduplication across issues.
- **Per-topic scheduling flexibility**: Support different frequencies per topic (e.g., "AI news" daily but "Rust ecosystem" weekly) with smart batching into combined or separate newsletters.
- **Evaluation framework**: Use ADK's built-in evaluation to assess research quality, synthesis accuracy, and newsletter readability against test cases.

### P3 - Nice-to-Have (future)

- **Multiple recipients**: Support a list of email recipients, potentially with per-recipient topic preferences.
- **Web UI for topic management**: A simple web interface (could use ADK's web UI as a starting point) for adding/editing topics without touching YAML.
- **Cross-issue topic tracking**: Memory across newsletter issues - detect emerging trends, note what changed since last issue, highlight new developments.
- **Feedback loop**: Allow the recipient to rate sections or provide feedback that influences future research depth or focus.

## Out of Scope

- **Subscriber management and sign-up flows**: This is a personal/small-team tool, not a newsletter platform. No landing pages, subscription forms, or audience analytics.
- **Content moderation or editorial review UI**: The MVP is fully autonomous. No human-in-the-loop review step before sending.
- **Multi-language support**: English only for MVP.
- **Real-time or streaming delivery**: This is a batch/scheduled system, not a live feed.
- **Custom LLM fine-tuning**: Uses Gemini models as-is via ADK. No training or fine-tuning.

## Assumptions & Risks

**Assumptions**:
- Gemini 2 models via Google AI Studio or Vertex AI provide sufficient quality for deep research synthesis
- Google Search grounding tool returns rich enough results for newsletter-grade content
- Perplexity Sonar API remains available and affordable for the research volume needed
- Gmail API OAuth2 works reliably for automated sending from a personal account without Workspace
- Cloud Run cold start times are acceptable for a scheduled weekly job (not latency-sensitive)

**Risks**:
- **Google Search tool limitation**: The `google_search` tool can only be used alone in an agent (single-tool-per-agent constraint). Mitigation: use a multi-agent architecture with a dedicated search agent, which is architecturally clean anyway.
- **Gmail API sending limits**: Personal Gmail has daily sending limits (~500/day). Mitigation: for a personal newsletter this is not an issue; for scaling, switch to Mailgun/SendGrid.
- **OAuth2 token refresh**: Gmail API tokens expire and need refresh. Mitigation: store refresh token securely in GCP Secret Manager; implement automatic token refresh in the email delivery tool.
- **Research quality variability**: LLM synthesis quality depends on the search results returned. Mitigation: use multiple search sources for cross-referencing; consider adding a quality-check agent in the pipeline.
- **Cost**: Gemini API calls + Google Search grounding have per-call costs. Mitigation: use Gemini Flash (cheaper) for research, monitor costs via GCP billing alerts.

## Technical Feasibility

**ADK Python**: Mature framework (v0.1.0+). Supports multi-agent orchestration (sequential, parallel), custom function tools, Google Search grounding built-in. Deploy to Cloud Run via `adk deploy cloud_run`. Python 3.10+ required.

**Multi-agent architecture**: ADK supports agent hierarchies, AgentTool (agent-as-a-tool), and workflow agents (Sequential, Parallel). The newsletter pipeline maps naturally to:
1. **Orchestrator agent**: Reads config, dispatches per-topic research
2. **Search agents** (parallel per topic): Dedicated Google Search agent + Perplexity tool agent
3. **Synthesis agent**: Takes raw research, produces deep analysis per topic
4. **Formatter agent**: Renders to HTML
5. **Delivery agent**: Sends via Gmail API

**Google Search grounding**: Built-in `google_search` tool, returns grounded responses with source URLs and citations metadata. Requires Gemini 2 models. Single-tool-per-agent limitation requires the search to live in its own agent.

**Perplexity Sonar API**: HTTP REST API, easily wrapped as a custom ADK function tool. Returns synthesized answers with source citations.

**Gmail API**: Python client library (`google-api-python-client`). OAuth2 flow with offline access for refresh tokens. Can send HTML emails with attachments. Works with personal Gmail accounts.

**Cloud Run + Cloud Scheduler**: Standard GCP pattern. Cloud Run is serverless, pay-per-invocation. Cloud Scheduler supports cron expressions. Authentication via service account with OIDC tokens.

**Key constraint**: The `google_search` tool mandate of one-tool-per-agent shapes the architecture into a multi-agent system, which is actually the preferred ADK pattern anyway.

## Open Questions

- Should the newsletter include an "executive summary" section at the top that summarizes all topics in 2-3 sentences each, before the deep dives?
- How should Google Custom Search Engine IDs be managed - one per topic or a shared engine with per-search site restrictions?
- Should the system support a "dry run" mode that generates the newsletter but does not send it (preview via local file or ADK web UI)?
- What is the preferred Gemini model tier - Flash (faster/cheaper) for research, Pro for synthesis, or Flash throughout?
- Should the YAML config support templating or variables (e.g., "search for {topic} developments in the last 7 days")?

## Next Step

Hand off to the **Spec Architect** agent to translate this brief into a full, implementation-ready specification covering the multi-agent architecture, tool definitions, config schema, deployment pipeline, and testing strategy.
