# Plan Index - Newsletter Agent

> **Spec**: `specs/newsletter-agent.spec.md`
> **Generated**: 2025-07-25

## Work Packages

| ID | Title | Priority | Status | Depends On | Parallelisable |
|----|-------|----------|--------|-----------|----------------|
| [WP01](WP01-project-scaffolding.md) | Project Scaffolding and Config System | P0 | Complete | none | - |
| [WP02](WP02-research-pipeline.md) | Research Pipeline | P1 | Complete | WP01 | No |
| [WP03](WP03-synthesis-formatting.md) | Content Synthesis and Formatting | P1 | Not Started | WP01, WP02 | No |
| [WP04](WP04-email-delivery.md) | Email Delivery and Local Output | P1 | Not Started | WP01, WP03 | No |
| [WP05](WP05-orchestration-deployment.md) | Orchestration, Deployment, and Observability | P1 | Not Started | WP01, WP02, WP03, WP04 | No |

## MVP Scope

All five work packages constitute the minimum releasable increment: WP01, WP02, WP03, WP04, WP05.

- **WP01** (P0) is the foundation - project scaffolding, config system, and validation. No user-facing functionality.
- **WP02-WP04** (P1) are the core MVP user stories: research, synthesis, formatting, and email delivery.
- **WP05** (P1) wires everything together and makes it deployable.

There are no post-MVP work packages in this plan. All WPs are required for the system to function end-to-end.

## Dependency and Execution Summary

- **Sequence**: WP01 -> WP02 -> WP03 -> WP04 -> WP05
- **Parallelization**: Limited. WP02 and WP04 both depend on WP01, but WP04 also depends on WP03 (which depends on WP02), so the practical path is sequential.
- **Critical path**: WP01 -> WP02 -> WP03 -> WP04 -> WP05 (linear chain)

### Within-WP Parallelization

Each work package has internal tasks that can be parallelized:

| WP | Parallelizable Tasks |
|----|---------------------|
| WP01 | T01-01 + T01-02 can start simultaneously; T01-08, T01-09 (tests) can be parallelized |
| WP02 | T02-01 + T02-02 (Google and Perplexity tools) are independent; T02-06, T02-07, T02-08 (tests) are parallelizable |
| WP03 | T03-01 + T03-03 (synthesis agent + Jinja2 template); T03-06, T03-07 (tests) are parallelizable |
| WP04 | T04-01 + T04-03 + T04-05 (auth, file output, setup script); T04-07, T04-08, T04-09 (tests) are parallelizable |
| WP05 | T05-01 + T05-02 + T05-05 + T05-12 (factory, logging, deploy docs, README); T05-07, T05-08, T05-11 (tests) are parallelizable |

## Sequencing Notes

The Newsletter Agent is a greenfield project with a linear pipeline architecture. Dependencies flow strictly from infrastructure (WP01) through the processing stages (WP02 research -> WP03 synthesis -> WP04 delivery) to final integration (WP05).

**WP01 (Foundation)** must be completed first as it provides the project structure, dependency installation, configuration system, and Pydantic models that all other WPs depend on.

**WP02 (Research)** builds the Google Search and Perplexity tools that feed into synthesis. It depends only on WP01 for the config models and project scaffolding.

**WP03 (Synthesis and Formatting)** depends on WP02 because it reads research results from session state. The synthesis agent and formatter are implemented here.

**WP04 (Email Delivery)** depends on WP03 because it reads the formatted `newsletter_html` from session state. It also depends on WP01 for config (recipient email, dry-run flag).

**WP05 (Orchestration)** assembles all components into the dynamic agent tree Integrates the root SequentialAgent, adds logging and timing, implements the Cloud Run HTTP endpoint, and includes E2E/performance/security tests. This is the final WP and depends on all others.

## Task Index

| Task ID | Summary | Work Package | Parallel? |
|---------|---------|--------------|----------|
| T01-01 | Project scaffolding and directory structure | WP01 | No |
| T01-02 | Python dependencies and pyproject.toml | WP01 | Yes |
| T01-03 | Pydantic config models | WP01 | No |
| T01-04 | YAML config loader with validation | WP01 | No |
| T01-05 | Environment variable and .env loading | WP01 | Yes |
| T01-06 | Config loader agent (BaseAgent) | WP01 | No |
| T01-07 | Sample topics.yaml | WP01 | Yes |
| T01-08 | Unit tests for config models | WP01 | Yes |
| T01-09 | Unit tests for config loader | WP01 | Yes |
| T01-10 | BDD tests for config validation | WP01 | No |
| T02-01 | Google Search agent implementation | WP02 | Yes |
| T02-02 | Perplexity Sonar tool implementation | WP02 | Yes |
| T02-03 | Research instruction prompt templates | WP02 | Yes |
| T02-04 | Per-topic research SequentialAgent | WP02 | No |
| T02-05 | Error handling and fallback markers | WP02 | No |
| T02-06 | Unit tests for Perplexity tool | WP02 | Yes |
| T02-07 | Unit tests for research agents | WP02 | Yes |
| T02-08 | BDD tests for research pipeline | WP02 | No |
| T03-01 | Synthesis agent with Gemini Pro | WP03 | Yes |
| T03-02 | Synthesis instruction prompt | WP03 | Yes |
| T03-03 | Jinja2 HTML newsletter template | WP03 | Yes |
| T03-04 | Formatter agent (BaseAgent) | WP03 | No |
| T03-05 | HTML sanitization with nh3 | WP03 | Yes |
| T03-06 | Unit tests for formatter | WP03 | Yes |
| T03-07 | Unit tests for synthesis | WP03 | Yes |
| T03-08 | BDD tests for synthesis and formatting | WP03 | No |
| T04-01 | Gmail OAuth2 token management | WP04 | Yes |
| T04-02 | Gmail send function | WP04 | No |
| T04-03 | HTML file output (dry-run/fallback) | WP04 | Yes |
| T04-04 | Delivery agent | WP04 | No |
| T04-05 | Gmail OAuth2 setup script | WP04 | Yes |
| T04-06 | Wire delivery agent into pipeline | WP04 | No |
| T04-07 | Unit tests for Gmail auth | WP04 | Yes |
| T04-08 | Unit tests for Gmail send | WP04 | Yes |
| T04-09 | Unit tests for file output | WP04 | Yes |
| T04-10 | Unit tests for delivery agent | WP04 | Yes |
| T04-11 | BDD tests for email delivery | WP04 | No |
| T05-01 | Dynamic agent factory | WP05 | No |
| T05-02 | Structured logging configuration | WP05 | Yes |
| T05-03 | Pipeline timing instrumentation | WP05 | Yes |
| T05-04 | Cloud Run HTTP trigger handler | WP05 | No |
| T05-05 | Cloud Run deployment configuration | WP05 | Yes |
| T05-06 | Root agent module-level setup | WP05 | No |
| T05-07 | Unit tests for agent factory | WP05 | Yes |
| T05-08 | Unit tests for logging config | WP05 | Yes |
| T05-09 | E2E test: full pipeline dry-run | WP05 | No |
| T05-10 | Performance validation tests | WP05 | Yes |
| T05-11 | Security tests | WP05 | Yes |
| T05-12 | Project README | WP05 | Yes |
