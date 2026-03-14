---
lane: for_review
---

# WP05 - Orchestration, Deployment, and Observability

> **Spec**: `specs/newsletter-agent.spec.md`
> **Status**: Complete
> **Priority**: P1
> **Goal**: The root agent pipeline is fully assembled, the Cloud Run HTTP endpoint triggers newsletter generation, Cloud Scheduler automates weekly runs, and structured logging provides observability across all phases
> **Independent Test**: Run `adk web`, trigger the full pipeline, verify all phases execute in sequence and structured logs appear; deploy to Cloud Run, POST to `/run` endpoint, verify newsletter generation completes
> **Depends on**: WP01, WP02, WP03, WP04
> **Parallelisable**: No (integrates all previous WPs)
> **Prompt**: `plans/WP05-orchestration-deployment.md`

## Objective

This work package assembles the complete multi-agent pipeline, implements the dynamic agent factory that builds the research ParallelAgent tree based on the loaded config, creates the Cloud Run HTTP trigger endpoint, provides deployment documentation and configuration for Cloud Scheduler, and implements structured logging across all pipeline phases. It also includes the full E2E test suite and performance validation tests.

Upon completion, the system is fully functional end-to-end: configurable, researching, synthesizing, formatting, delivering, observable, and deployable.

## Spec References

- FR-036: Cloud Run deployment via `adk deploy cloud_run`
- FR-037: HTTP endpoint triggers full newsletter generation
- FR-038: Cloud Scheduler calls endpoint on cron schedule
- FR-039: Cloud Scheduler OIDC authentication
- FR-040: Secrets in GCP Secret Manager
- FR-041: Local secrets from `.env`
- FR-042: INFO-level logging (pipeline start/end, per-phase, delivery status)
- FR-043: ERROR-level logging (provider failures, synthesis/delivery failures, config errors)
- FR-044: Structured log format (`{timestamp} {level} {agent_name} {message}`)
- FR-045: Cloud Run stdout logging for Cloud Logging integration
- Section 6.2: Newsletter generation flow (happy path)
- Section 6.3: Partial failure flow
- Section 6.4: Email failure flow
- Section 6.5: Deployment flow
- Section 8.1: Cloud Run HTTP trigger endpoint spec
- Section 9.1: Architecture - root SequentialAgent, dynamic agent construction
- Section 9.3: Directory and module structure
- Section 9.4: Key design decisions (dynamic agent construction, Decision 1)
- Section 10.1: Performance requirements
- Section 10.3: Scalability and availability
- Section 10.5: Observability requirements
- Section 11.3: Integration tests
- Section 11.4: E2E tests
- Section 11.5: Performance tests
- Section 11.6: Security tests
- US-06: Local development workflow
- US-07: Cloud Run deployment and scheduling

## Tasks

### T05-01 - Implement Dynamic Agent Factory

- **Description**: Implement the agent factory function in `newsletter_agent/agent.py` that builds the complete multi-agent tree dynamically based on the loaded configuration. The factory reads the validated config, creates per-topic research sub-pipelines (each containing a Google Search agent and a Perplexity agent), assembles them into a ParallelAgent, and wraps everything in the root SequentialAgent. This is the core architectural element that makes the system configurable.

- **Spec refs**: Section 9.1 (architecture), Section 9.4 Decision 1 (dynamic agent construction), FR-010

- **Parallel**: No (foundational task for this WP)

- **Acceptance criteria**:
  - [ ] File `newsletter_agent/agent.py` exports a `root_agent` variable (required by ADK convention)
  - [ ] A factory function `build_pipeline(config: NewsletterConfig) -> Agent` constructs the full agent tree
  - [ ] For N topics in config, the research ParallelAgent contains N sub-pipelines
  - [ ] Each per-topic sub-pipeline is a SequentialAgent with: Google Search LlmAgent + Perplexity LlmAgent
  - [ ] Google Search agents use `gemini-2.5-flash` model and have `google_search` as their only tool
  - [ ] Perplexity agents use `gemini-2.5-flash` model with the `search_perplexity` FunctionTool
  - [ ] The synthesis agent uses `gemini-2.5-pro` model
  - [ ] The root SequentialAgent order is: config_loader -> research_phase -> synthesis -> output_phase (formatter -> delivery)
  - [ ] Agent names follow the naming pattern from Section 9.1 (e.g., `GoogleSearcher_0`, `PerplexitySearcher_0`)
  - [ ] The factory handles 1 topic and 20 topics correctly

- **Test requirements**: unit (test factory with 1, 5, 20 topics)

- **Depends on**: none (but uses components from WP01-WP04)

- **Implementation Guidance**:
  - ADK agent construction pattern:
    ```python
    from google.adk.agents import Agent, LlmAgent, SequentialAgent, ParallelAgent, BaseAgent
    from google.adk.tools import google_search, FunctionTool
    
    def build_pipeline(config: NewsletterConfig) -> Agent:
        # Build per-topic research sub-pipelines
        topic_pipelines = []
        for i, topic in enumerate(config.topics):
            google_agent = LlmAgent(
                name=f"GoogleSearcher_{i}",
                model="gemini-2.5-flash",
                tools=[google_search],
                instruction=build_google_instruction(topic),
                output_key=f"research_{i}_google",
            )
            perplexity_agent = LlmAgent(
                name=f"PerplexitySearcher_{i}",
                model="gemini-2.5-flash",
                tools=[search_perplexity_tool],
                instruction=build_perplexity_instruction(topic),
                output_key=f"research_{i}_perplexity",
            )
            topic_pipeline = SequentialAgent(
                name=f"Topic{i}Research",
                sub_agents=[google_agent, perplexity_agent],
            )
            topic_pipelines.append(topic_pipeline)
        
        research_phase = ParallelAgent(
            name="ResearchPhase",
            sub_agents=topic_pipelines,
        )
        
        # Synthesis, formatter, delivery from respective WPs
        root = SequentialAgent(
            name="NewsletterPipeline",
            sub_agents=[
                config_loader_agent,
                research_phase,
                synthesis_agent,
                formatter_agent,
                delivery_agent,
            ],
        )
        return root
    ```
  - Official docs: ADK agent types - https://google.github.io/adk-docs/agents/
  - Known pitfalls:
    - ADK requires `root_agent` to be a module-level variable in `agent.py`. The factory must be invoked at import time or use a lazy initialization pattern.
    - The `google_search` tool must be the ONLY tool on its agent. ADK enforces this constraint.
    - Agent names must be unique within the pipeline. Use the topic index suffix to ensure uniqueness.
    - The `output_key` parameter on LlmAgent stores the agent's final text output in session state at that key.

---

### T05-02 - Implement Structured Logging Configuration

- **Description**: Set up the Python logging configuration for the entire pipeline. Configure structured log format with timestamp, level, agent name, and message. Ensure logs go to stdout/stderr for Cloud Logging compatibility. Create a logging setup function that is called once at pipeline startup.

- **Spec refs**: FR-042, FR-043, FR-044, FR-045, Section 10.5

- **Parallel**: Yes (independent of agent factory)

- **Acceptance criteria**:
  - [ ] File `newsletter_agent/logging_config.py` exists with `setup_logging()` function
  - [ ] Log format is: `{ISO-timestamp} {LEVEL} [{agent_name}] {message}`
  - [ ] INFO-level logs include: pipeline start, pipeline end, per-phase start/end, delivery status
  - [ ] ERROR-level logs include: provider failures, synthesis failures, delivery failures, config validation errors
  - [ ] All logs go to stdout (INFO and below) and stderr (ERROR and above)
  - [ ] The logging level is configurable via environment variable `LOG_LEVEL` (default: INFO)
  - [ ] Logging setup does not interfere with ADK's internal logging
  - [ ] Third-party library log levels (google-api, httplib2) are set to WARNING to reduce noise

- **Test requirements**: unit

- **Depends on**: none

- **Implementation Guidance**:
  - Standard Python logging setup:
    ```python
    import logging
    import sys
    import os
    
    LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"
    
    def setup_logging():
        level = os.environ.get("LOG_LEVEL", "INFO").upper()
        
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
        
        root_logger = logging.getLogger("newsletter_agent")
        root_logger.setLevel(getattr(logging, level, logging.INFO))
        root_logger.addHandler(handler)
        
        # Reduce noise from third-party libraries
        logging.getLogger("googleapiclient").setLevel(logging.WARNING)
        logging.getLogger("google.auth").setLevel(logging.WARNING)
        logging.getLogger("httplib2").setLevel(logging.WARNING)
    ```
  - Known pitfalls:
    - Cloud Logging on Cloud Run automatically captures stdout/stderr. Structured JSON logging is optional but not required for MVP.
    - ADK has its own logging. Avoid configuring the root logger (`logging.getLogger()`) which would affect ADK internals. Use a namespaced logger (`newsletter_agent`).
    - On Cloud Run, `sys.stdout` may be buffered. Use `flush=True` or configure unbuffered output.

---

### T05-03 - Implement Pipeline Timing Instrumentation

- **Description**: Add timing instrumentation to the pipeline to measure and log execution time for each phase (config loading, research, synthesis, formatting, delivery) and total pipeline time. Store timing data in session state as `newsletter_metadata.generation_time_seconds`.

- **Spec refs**: FR-042, Section 7.6 (NewsletterMetadata.generation_time_seconds), Section 10.1 (performance)

- **Parallel**: Yes (independent of other tasks)

- **Acceptance criteria**:
  - [ ] Pipeline start time is recorded when the root agent begins execution
  - [ ] Each phase (research, synthesis, formatting, delivery) logs its start and end time at INFO level
  - [ ] Total pipeline execution time is calculated and stored in `newsletter_metadata.generation_time_seconds`
  - [ ] Per-phase timing is logged in the format: `{phase_name} completed in {seconds:.1f}s`
  - [ ] Total pipeline timing is logged: `Pipeline completed in {seconds:.1f}s`
  - [ ] Timing does not interfere with agent execution (minimal overhead)

- **Test requirements**: unit (mock time, verify logging)

- **Depends on**: T05-01

- **Implementation Guidance**:
  - Use a timing wrapper or `before_agent_callback`/`after_agent_callback` in ADK:
    ```python
    import time
    import logging
    
    logger = logging.getLogger("newsletter_agent.timing")
    
    class TimingCallbacks:
        def __init__(self):
            self.phase_starts = {}
            self.pipeline_start = None
        
        def before_agent(self, callback_context):
            agent_name = callback_context.agent_name
            self.phase_starts[agent_name] = time.monotonic()
            if agent_name == "NewsletterPipeline":
                self.pipeline_start = time.monotonic()
                logger.info("Pipeline started")
        
        def after_agent(self, callback_context):
            agent_name = callback_context.agent_name
            if agent_name in self.phase_starts:
                elapsed = time.monotonic() - self.phase_starts[agent_name]
                logger.info("%s completed in %.1fs", agent_name, elapsed)
            if agent_name == "NewsletterPipeline" and self.pipeline_start:
                total = time.monotonic() - self.pipeline_start
                logger.info("Pipeline completed in %.1fs", total)
                ctx = callback_context
                ctx.session.state.setdefault("newsletter_metadata", {})
                ctx.session.state["newsletter_metadata"]["generation_time_seconds"] = total
    ```
  - Known pitfalls:
    - ADK callback signature may vary by version. Check ADK docs for exact callback context structure.
    - `time.monotonic()` is preferred over `time.time()` for measuring elapsed time (immune to clock adjustments).

---

### T05-04 - Implement Cloud Run HTTP Trigger Handler

- **Description**: Implement the HTTP endpoint handler that Cloud Scheduler (or manual triggers) calls to start a newsletter generation cycle. The handler accepts a POST request at `/run`, triggers the full ADK pipeline, waits for completion, and returns a JSON response with the generation result.

- **Spec refs**: FR-037, Section 8.1 (Cloud Run HTTP trigger endpoint)

- **Parallel**: No (requires T05-01 for the pipeline)

- **Acceptance criteria**:
  - [ ] The application exposes a POST endpoint at `/run`
  - [ ] On success, returns HTTP 200 with JSON: `{"status": "success", "newsletter_date": "YYYY-MM-DD", "topics_processed": N, "email_sent": bool}`
  - [ ] On success with dry_run, returns HTTP 200 with additional `"output_file"` field
  - [ ] On pipeline failure, returns HTTP 500 with JSON: `{"status": "error", "message": "Pipeline failed: {details}"}`
  - [ ] The endpoint has no request body requirement (Cloud Scheduler sends empty POST)
  - [ ] The handler runs the full pipeline synchronously within the request lifecycle
  - [ ] Request timeout is documented as 600 seconds in Cloud Run configuration

- **Test requirements**: unit (mock pipeline execution), E2E

- **Depends on**: T05-01

- **Implementation Guidance**:
  - ADK uses its own HTTP handling for Cloud Run. The standard pattern is to use `adk deploy cloud_run` which wraps the agent in an HTTP server. However, if custom endpoint logic is needed:
    ```python
    # If ADK provides a hook for custom HTTP endpoints:
    # Use the ADK Cloud Run adapter
    
    # If manual HTTP handling is needed (e.g., for the /run endpoint):
    from flask import Flask, jsonify
    import asyncio
    
    app = Flask(__name__)
    
    @app.route("/run", methods=["POST"])
    def run_pipeline():
        try:
            result = asyncio.run(execute_pipeline())
            return jsonify(result), 200
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
    ```
  - ADK Cloud Run deployment may handle this automatically. Research the exact ADK Cloud Run integration pattern before implementation.
  - Known pitfalls:
    - Cloud Run has a default 5-minute timeout. Override to 600 seconds in the service configuration.
    - ADK's `adk deploy cloud_run` may provide its own HTTP server. Do not duplicate the HTTP handling if ADK already provides it.
    - The handler must be async-compatible since ADK agents are async.
    - Cloud Scheduler sends a POST with an empty body and an OIDC token in the Authorization header.

---

### T05-05 - Create Cloud Run Deployment Configuration

- **Description**: Create the deployment configuration files and documentation needed for Cloud Run deployment. This includes the Dockerfile (if ADK doesn't generate one), Cloud Run service configuration (memory, timeout, environment variables), and the `gcloud` commands for Secret Manager setup and Cloud Scheduler job creation.

- **Spec refs**: FR-036, FR-038, FR-039, FR-040, Section 6.5 (deployment flow), Section 10.3

- **Parallel**: Yes (documentation task, independent of code)

- **Acceptance criteria**:
  - [ ] Deployment documentation exists in `README.md` with step-by-step Cloud Run deployment instructions
  - [ ] Cloud Run service configuration specifies: memory=1GB, timeout=600s, min-instances=0, max-instances=1
  - [ ] Secret Manager setup commands are documented for all required secrets: `GOOGLE_API_KEY`, `PERPLEXITY_API_KEY`, `GMAIL_REFRESH_TOKEN`, `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`
  - [ ] Cloud Scheduler job creation command is documented with OIDC authentication
  - [ ] The service account setup is documented: one for Cloud Run (secret access + Gmail), one for Scheduler (run.invoker)
  - [ ] `adk deploy cloud_run` command is documented with required arguments

- **Test requirements**: none (documentation, verified manually)

- **Depends on**: none

- **Implementation Guidance**:
  - ADK deployment command:
    ```bash
    adk deploy cloud_run \
      --project=PROJECT_ID \
      --region=us-central1 \
      ./newsletter_agent
    ```
  - Secret Manager setup:
    ```bash
    # Create secrets
    echo -n "YOUR_API_KEY" | gcloud secrets create GOOGLE_API_KEY --data-file=-
    echo -n "YOUR_PERPLEXITY_KEY" | gcloud secrets create PERPLEXITY_API_KEY --data-file=-
    echo -n "YOUR_REFRESH_TOKEN" | gcloud secrets create GMAIL_REFRESH_TOKEN --data-file=-
    echo -n "YOUR_CLIENT_ID" | gcloud secrets create GMAIL_CLIENT_ID --data-file=-
    echo -n "YOUR_CLIENT_SECRET" | gcloud secrets create GMAIL_CLIENT_SECRET --data-file=-
    
    # Grant access to Cloud Run service account
    gcloud secrets add-iam-policy-binding GOOGLE_API_KEY \
      --member="serviceAccount:SA@PROJECT.iam.gserviceaccount.com" \
      --role="roles/secretmanager.secretAccessor"
    ```
  - Cloud Scheduler setup:
    ```bash
    gcloud scheduler jobs create http newsletter-weekly \
      --schedule="0 8 * * 0" \
      --uri="https://SERVICE_URL/run" \
      --http-method=POST \
      --oidc-service-account-email=SCHEDULER_SA@PROJECT.iam.gserviceaccount.com \
      --oidc-token-audience="https://SERVICE_URL"
    ```
  - Known pitfalls:
    - Cloud Run environment variables from Secret Manager use a specific syntax in the service YAML or `--set-secrets` flag.
    - The OIDC audience must match the Cloud Run service URL exactly.
    - Cloud Scheduler and Cloud Run service accounts must be different for proper IAM separation.

---

### T05-06 - Implement Root Agent Module-Level Setup

- **Description**: Wire the `root_agent` variable at the module level in `newsletter_agent/agent.py` so that ADK can discover and run the agent. This includes loading the config, calling the factory, setting up logging, and handling startup errors. The config is loaded once at import time and the agent tree is built before any invocation.

- **Spec refs**: Section 9.1, Section 9.3 (directory structure)

- **Parallel**: No (requires T05-01, T05-02)

- **Acceptance criteria**:
  - [ ] `newsletter_agent/agent.py` contains a module-level `root_agent` variable
  - [ ] On import, the module loads config, sets up logging, and builds the agent tree
  - [ ] If config loading fails, the module raises a clear error (not a cryptic import error)
  - [ ] The `__init__.py` file imports and re-exports `root_agent` for ADK discovery
  - [ ] Running `adk web` loads the agent successfully and shows it in the dev UI
  - [ ] Running `adk run newsletter_agent` executes the pipeline

- **Test requirements**: integration (verify adk web loads)

- **Depends on**: T05-01, T05-02

- **Implementation Guidance**:
  - ADK discovery pattern:
    ```python
    # newsletter_agent/__init__.py
    from .agent import root_agent
    ```
    ```python
    # newsletter_agent/agent.py
    import logging
    from .logging_config import setup_logging
    from .config.schema import load_config
    
    setup_logging()
    logger = logging.getLogger("newsletter_agent.agent")
    
    try:
        config = load_config("config/topics.yaml")
        root_agent = build_pipeline(config)
        logger.info("Newsletter pipeline initialized with %d topics", len(config.topics))
    except Exception as e:
        logger.error("Failed to initialize pipeline: %s", e)
        raise
    ```
  - Known pitfalls:
    - Config path must be relative to the project root, not the module directory. Use `pathlib.Path` to resolve correctly.
    - ADK may reload the module during `adk web` hot-reload. Ensure the setup is idempotent.
    - If the config file is missing, provide a clear error message directing the operator to create the config file.

---

### T05-07 - Write Unit Tests for Agent Factory

- **Description**: Write unit tests for the dynamic agent factory function verifying correct agent tree construction for various topic counts.

- **Spec refs**: Section 11.1 (agent factory unit tests)

- **Parallel**: Yes (after T05-01)

- **Acceptance criteria**:
  - [ ] Test file `tests/test_agent_factory.py` exists with at least 8 test cases
  - [ ] Tests cover: 1 topic produces 1 research sub-pipeline, 5 topics produce 5 sub-pipelines, 20 topics produce 20 sub-pipelines
  - [ ] Tests verify each Google Search agent has exactly one tool (`google_search`)
  - [ ] Tests verify each Perplexity agent has the `search_perplexity` tool
  - [ ] Tests verify agent names follow the naming convention with topic index
  - [ ] Tests verify the root agent is a SequentialAgent with the correct sub-agent order
  - [ ] Tests verify the research phase is a ParallelAgent
  - [ ] Tests verify model assignments: Flash for research, Pro for synthesis
  - [ ] All tests pass via `pytest tests/test_agent_factory.py`

- **Test requirements**: unit

- **Depends on**: T05-01

- **Implementation Guidance**:
  - Create mock configs with different topic counts:
    ```python
    def make_config(num_topics):
        topics = [
            TopicConfig(name=f"Topic {i}", query=f"query for topic {i}")
            for i in range(num_topics)
        ]
        return NewsletterConfig(
            newsletter=NewsletterSettings(
                title="Test", schedule="0 8 * * 0", recipient_email="test@test.com"
            ),
            settings=Settings(dry_run=True, output_dir="output/"),
            topics=topics,
        )
    ```

---

### T05-08 - Write Unit Tests for Logging Configuration

- **Description**: Write unit tests for the logging setup and structured log format.

- **Spec refs**: FR-042, FR-043, FR-044, Section 11.1

- **Parallel**: Yes (after T05-02)

- **Acceptance criteria**:
  - [ ] Test file `tests/test_logging_config.py` exists with at least 5 test cases
  - [ ] Tests verify log format includes timestamp, level, agent name, and message
  - [ ] Tests verify INFO-level messages are emitted for pipeline milestones
  - [ ] Tests verify ERROR-level messages are emitted for failures
  - [ ] Tests verify LOG_LEVEL environment variable is respected
  - [ ] Tests verify third-party library log levels are suppressed
  - [ ] All tests pass via `pytest tests/test_logging_config.py`

- **Test requirements**: unit

- **Depends on**: T05-02

---

### T05-09 - Write E2E Test: Full Pipeline Dry-Run

- **Description**: Write an end-to-end test that runs the complete pipeline in dry-run mode with mocked external APIs. This test verifies the entire agent tree executes correctly from config loading through HTML file output.

- **Spec refs**: Section 11.4 (E2E tests), US-06

- **Parallel**: No (requires all pipeline components)

- **Acceptance criteria**:
  - [ ] Test file `tests/e2e/test_full_pipeline.py` exists
  - [ ] Test runs the full pipeline with `dry_run: true`
  - [ ] External APIs (Gemini, Perplexity, Gmail) are mocked
  - [ ] Test verifies: config is loaded, research results are in state, synthesis results are in state, HTML file is generated in the output directory
  - [ ] Test verifies the HTML file contains expected sections (title, executive summary, topic sections)
  - [ ] Test verifies structured log output includes pipeline start/end messages
  - [ ] Test completes within 30 seconds (mocked APIs should be fast)
  - [ ] All tests pass via `pytest tests/e2e/test_full_pipeline.py`

- **Test requirements**: E2E

- **Depends on**: T05-06

- **Implementation Guidance**:
  - Use pytest fixtures to set up test config and mock responses.
  - Create a test config file `tests/fixtures/test_topics.yaml` with 2 topics.
  - Mock the LLM responses for research and synthesis agents.
  - Verify the output file exists and contains expected HTML elements.

---

### T05-10 - Write Performance Validation Tests

- **Description**: Write performance tests that verify the pipeline meets the timing requirements from the spec. These tests run with real (or realistic mock) APIs and measure execution time.

- **Spec refs**: Section 10.1 (performance), Section 11.5

- **Parallel**: Yes (after T05-09)

- **Acceptance criteria**:
  - [ ] Test file `tests/performance/test_pipeline_timing.py` exists
  - [ ] Test with 5 topics verifies total time < 600 seconds
  - [ ] Test with 20 topics verifies total time < 1200 seconds (if run with real APIs)
  - [ ] Tests are marked with `@pytest.mark.performance` and skipped in CI by default
  - [ ] Tests log the actual execution time for each phase and total
  - [ ] Tests verify parallel execution (research phase time is sublinear in topic count)

- **Test requirements**: performance

- **Depends on**: T05-09

---

### T05-11 - Write Security Tests

- **Description**: Write security tests verifying no secrets in committed files, Jinja2 autoescaping, and proper error handling that does not leak credentials.

- **Spec refs**: Section 10.2 (security), Section 11.6

- **Parallel**: Yes (independent)

- **Acceptance criteria**:
  - [ ] Test file `tests/security/test_secrets.py` exists
  - [ ] Test verifies `.env` is in `.gitignore`
  - [ ] Test verifies no API keys or tokens appear in any committed Python, YAML, or Markdown file (regex scan)
  - [ ] Test verifies Jinja2 template has autoescaping enabled
  - [ ] Test verifies XSS payload in topic name is escaped in HTML output: `<script>alert('xss')</script>` becomes `&lt;script&gt;...`
  - [ ] Test verifies error messages from Gmail auth do not contain full credentials
  - [ ] All tests pass via `pytest tests/security/`

- **Test requirements**: security

- **Depends on**: none

---

### T05-12 - Write Project README

- **Description**: Create the comprehensive project README.md with setup instructions, configuration guide, development workflow, deployment guide, and architecture overview.

- **Spec refs**: Section 6.1 (setup flow), Section 6.5 (deployment flow), Section 9.3 (directory structure)

- **Parallel**: Yes (documentation task)

- **Acceptance criteria**:
  - [ ] `README.md` exists at the project root
  - [ ] README includes: project overview, prerequisites (Python 3.11+, GCP account, API keys), installation steps, configuration guide (topics.yaml format), local development with `adk web`, Gmail OAuth2 setup instructions, deployment to Cloud Run steps, Cloud Scheduler setup, architecture diagram (text-based), troubleshooting section
  - [ ] README references the `setup_gmail_oauth.py` script with usage examples
  - [ ] README includes example `topics.yaml` configuration
  - [ ] README includes a "Quick Start" section for first-time setup

- **Test requirements**: none (documentation)

- **Depends on**: none

## Reference Implementations

### Agent Factory - Complete Reference

```python
"""
Root agent definition and dynamic pipeline factory.

This module constructs the complete multi-agent newsletter pipeline
based on the operator's topic configuration.

Spec refs: Section 9.1, Section 9.4 Decision 1.
"""

import logging
from pathlib import Path

from google.adk.agents import (
    Agent,
    LlmAgent,
    SequentialAgent,
    ParallelAgent,
)
from google.adk.tools import google_search, FunctionTool

from .config.schema import load_config, NewsletterConfig, TopicConfig
from .tools.perplexity_search import search_perplexity
from .tools.gmail_send import send_newsletter_email
from .tools.file_output import save_newsletter_html
from .prompts.research_google import build_google_instruction
from .prompts.research_perplexity import build_perplexity_instruction
from .prompts.synthesis import SYNTHESIS_INSTRUCTION
from .logging_config import setup_logging

logger = logging.getLogger("newsletter_agent.agent")

search_perplexity_tool = FunctionTool(func=search_perplexity)


def _build_topic_research(index: int, topic: TopicConfig) -> Agent:
    """Build a per-topic research sub-pipeline.
    
    Each topic gets a SequentialAgent with:
    1. Google Search agent (single tool constraint)
    2. Perplexity Search agent
    """
    agents = []
    
    if "google_search" in topic.effective_sources:
        google_agent = LlmAgent(
            name=f"GoogleSearcher_{index}",
            model="gemini-2.5-flash",
            tools=[google_search],
            instruction=build_google_instruction(topic),
            output_key=f"research_{index}_google",
        )
        agents.append(google_agent)
    
    if "perplexity" in topic.effective_sources:
        perplexity_agent = LlmAgent(
            name=f"PerplexitySearcher_{index}",
            model="gemini-2.5-flash",
            tools=[search_perplexity_tool],
            instruction=build_perplexity_instruction(topic),
            output_key=f"research_{index}_perplexity",
        )
        agents.append(perplexity_agent)
    
    return SequentialAgent(
        name=f"Topic{index}Research",
        sub_agents=agents,
    )


def build_pipeline(config: NewsletterConfig) -> Agent:
    """Construct the full newsletter pipeline from config."""
    
    # Import agents from their respective modules
    from .agents.config_loader import ConfigLoaderAgent
    from .agents.synthesis_agent import SynthesisAgent
    from .agents.formatter_agent import FormatterAgent
    from .agents.delivery_agent import DeliveryAgent
    
    # Config loader
    config_loader = ConfigLoaderAgent(
        name="ConfigLoader",
        config=config,
    )
    
    # Dynamic research phase
    topic_pipelines = [
        _build_topic_research(i, topic)
        for i, topic in enumerate(config.topics)
    ]
    research_phase = ParallelAgent(
        name="ResearchPhase",
        sub_agents=topic_pipelines,
    )
    
    # Synthesis
    synthesis = LlmAgent(
        name="Synthesizer",
        model="gemini-2.5-pro",
        instruction=SYNTHESIS_INSTRUCTION.format(
            topic_count=len(config.topics)
        ),
    )
    
    # Output phase
    formatter = FormatterAgent(name="Formatter")
    delivery = DeliveryAgent(name="Deliverer")
    output_phase = SequentialAgent(
        name="OutputPhase",
        sub_agents=[formatter, delivery],
    )
    
    # Root pipeline
    root = SequentialAgent(
        name="NewsletterPipeline",
        sub_agents=[
            config_loader,
            research_phase,
            synthesis,
            output_phase,
        ],
    )
    
    logger.info(
        "Pipeline built with %d topics, %d research agents",
        len(config.topics),
        len(topic_pipelines) * 2,
    )
    
    return root


# Module-level setup for ADK discovery
setup_logging()

try:
    _config_path = Path(__file__).parent.parent / "config" / "topics.yaml"
    _config = load_config(str(_config_path))
    root_agent = build_pipeline(_config)
    logger.info(
        "Newsletter Agent initialized: %d topics, title='%s'",
        len(_config.topics),
        _config.newsletter.title,
    )
except FileNotFoundError:
    logger.error(
        "Config file not found at config/topics.yaml. "
        "Create the file using the example in README.md."
    )
    raise
except Exception as e:
    logger.error("Failed to initialize Newsletter Agent: %s", e)
    raise
```

### Logging Configuration - Complete Reference

```python
"""
Structured logging configuration for the Newsletter Agent.

Spec refs: FR-042, FR-043, FR-044, FR-045, Section 10.5.
"""

import logging
import os
import sys


LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"

_configured = False


def setup_logging():
    """Configure structured logging for the Newsletter Agent.
    
    Idempotent - safe to call multiple times (only configures once).
    """
    global _configured
    if _configured:
        return
    
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    
    # Configure newsletter_agent namespace logger
    logger = logging.getLogger("newsletter_agent")
    logger.setLevel(level)
    
    # Stdout handler for all levels
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.DEBUG)
    stdout_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    stdout_handler.addFilter(lambda record: record.levelno < logging.ERROR)
    
    # Stderr handler for ERROR and above
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.ERROR)
    stderr_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    
    logger.addHandler(stdout_handler)
    logger.addHandler(stderr_handler)
    
    # Suppress noisy third-party loggers
    for noisy_logger in [
        "googleapiclient",
        "google.auth",
        "httplib2",
        "urllib3",
    ]:
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)
    
    _configured = True
```

### HTTP Trigger Handler - Reference Pattern

```python
"""
Cloud Run HTTP trigger handler.

This module provides the /run endpoint that Cloud Scheduler calls
to trigger newsletter generation.

Spec refs: FR-037, Section 8.1.
"""

import asyncio
import logging
from datetime import date

from flask import Flask, jsonify, request

logger = logging.getLogger("newsletter_agent.http")

app = Flask(__name__)


@app.route("/run", methods=["POST"])
def run_pipeline():
    """Trigger a full newsletter generation cycle.
    
    Returns:
        JSON response with generation result.
    """
    logger.info("Pipeline triggered via HTTP POST /run")
    
    try:
        # Execute the ADK pipeline
        # The exact invocation depends on ADK's programmatic run API
        from .agent import root_agent, _config
        
        # ADK provides a Runner class or similar for programmatic execution
        # This is a simplified representation
        result = asyncio.run(_execute_pipeline(root_agent))
        
        response = {
            "status": "success",
            "newsletter_date": date.today().isoformat(),
            "topics_processed": len(_config.topics),
            "email_sent": result.get("delivery_status", {}).get("status") == "sent",
        }
        
        if _config.settings.dry_run:
            response["output_file"] = result.get("delivery_status", {}).get("output_file", "")
        
        logger.info("Pipeline completed successfully: %s", response)
        return jsonify(response), 200
        
    except Exception as e:
        error_msg = f"Pipeline failed: {type(e).__name__}: {e}"
        logger.error(error_msg)
        return jsonify({"status": "error", "message": error_msg}), 500


async def _execute_pipeline(agent):
    """Execute the ADK pipeline programmatically."""
    # ADK programmatic execution pattern
    # Exact API depends on ADK version
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    
    session_service = InMemorySessionService()
    runner = Runner(
        agent=agent,
        app_name="newsletter_agent",
        session_service=session_service,
    )
    
    session = await session_service.create_session(
        app_name="newsletter_agent",
        user_id="scheduler",
    )
    
    final_state = {}
    async for event in runner.run_async(
        session_id=session.id,
        user_id="scheduler",
        new_message=types.Content(
            parts=[types.Part(text="Generate newsletter")]
        ),
    ):
        if hasattr(event, "content"):
            pass  # Process events as needed
    
    # Retrieve final state
    updated_session = await session_service.get_session(
        app_name="newsletter_agent",
        user_id="scheduler",
        session_id=session.id,
    )
    return updated_session.state
```

## Detailed Test Plans

### T05-07 Test Plan: Agent Factory Unit Tests

```python
"""
Unit tests for the dynamic agent factory.
Tests: newsletter_agent/agent.py - build_pipeline()
Spec refs: Section 9.1, Section 9.4 Decision 1, Section 11.1
"""

import pytest
from unittest.mock import patch, MagicMock

from newsletter_agent.config.schema import (
    NewsletterConfig,
    NewsletterSettings,
    Settings,
    TopicConfig,
)


def make_config(num_topics, **overrides):
    """Create a test config with N topics."""
    topics = [
        TopicConfig(name=f"Topic {i}", query=f"test query {i}")
        for i in range(num_topics)
    ]
    defaults = {
        "newsletter": NewsletterSettings(
            title="Test Newsletter",
            schedule="0 8 * * 0",
            recipient_email="test@example.com",
        ),
        "settings": Settings(dry_run=True, output_dir="test_output/"),
        "topics": topics,
    }
    defaults.update(overrides)
    return NewsletterConfig(**defaults)


class TestBuildPipeline:
    """Tests for the build_pipeline() factory function."""

    @patch("newsletter_agent.agent.FormatterAgent")
    @patch("newsletter_agent.agent.DeliveryAgent")
    @patch("newsletter_agent.agent.SynthesisAgent")
    @patch("newsletter_agent.agent.ConfigLoaderAgent")
    def test_single_topic_produces_one_research_pipeline(
        self, *mocks
    ):
        """1 topic -> 1 research sub-pipeline in ParallelAgent."""
        from newsletter_agent.agent import build_pipeline
        config = make_config(1)
        root = build_pipeline(config)
        
        # Root is SequentialAgent
        assert root.name == "NewsletterPipeline"
        # Research phase should have 1 sub-pipeline
        research_phase = root.sub_agents[1]
        assert len(research_phase.sub_agents) == 1

    @patch("newsletter_agent.agent.FormatterAgent")
    @patch("newsletter_agent.agent.DeliveryAgent")
    @patch("newsletter_agent.agent.SynthesisAgent")
    @patch("newsletter_agent.agent.ConfigLoaderAgent")
    def test_five_topics_produce_five_research_pipelines(
        self, *mocks
    ):
        """5 topics -> 5 research sub-pipelines."""
        from newsletter_agent.agent import build_pipeline
        config = make_config(5)
        root = build_pipeline(config)
        
        research_phase = root.sub_agents[1]
        assert len(research_phase.sub_agents) == 5

    @patch("newsletter_agent.agent.FormatterAgent")
    @patch("newsletter_agent.agent.DeliveryAgent")
    @patch("newsletter_agent.agent.SynthesisAgent")
    @patch("newsletter_agent.agent.ConfigLoaderAgent")
    def test_twenty_topics_produce_twenty_research_pipelines(
        self, *mocks
    ):
        """20 topics -> 20 research sub-pipelines."""
        from newsletter_agent.agent import build_pipeline
        config = make_config(20)
        root = build_pipeline(config)
        
        research_phase = root.sub_agents[1]
        assert len(research_phase.sub_agents) == 20

    @patch("newsletter_agent.agent.FormatterAgent")
    @patch("newsletter_agent.agent.DeliveryAgent")
    @patch("newsletter_agent.agent.SynthesisAgent")
    @patch("newsletter_agent.agent.ConfigLoaderAgent")
    def test_google_search_agent_has_single_tool(self, *mocks):
        """Each Google Search agent must have exactly one tool."""
        from newsletter_agent.agent import build_pipeline
        config = make_config(3)
        root = build_pipeline(config)
        
        research_phase = root.sub_agents[1]
        for topic_pipeline in research_phase.sub_agents:
            google_agent = topic_pipeline.sub_agents[0]
            assert len(google_agent.tools) == 1

    @patch("newsletter_agent.agent.FormatterAgent")
    @patch("newsletter_agent.agent.DeliveryAgent")
    @patch("newsletter_agent.agent.SynthesisAgent")
    @patch("newsletter_agent.agent.ConfigLoaderAgent")
    def test_agent_names_include_topic_index(self, *mocks):
        """Agent names must include the topic index for uniqueness."""
        from newsletter_agent.agent import build_pipeline
        config = make_config(3)
        root = build_pipeline(config)
        
        research_phase = root.sub_agents[1]
        for i, topic_pipeline in enumerate(research_phase.sub_agents):
            assert str(i) in topic_pipeline.name
            for agent in topic_pipeline.sub_agents:
                assert str(i) in agent.name

    @patch("newsletter_agent.agent.FormatterAgent")
    @patch("newsletter_agent.agent.DeliveryAgent")
    @patch("newsletter_agent.agent.SynthesisAgent")
    @patch("newsletter_agent.agent.ConfigLoaderAgent")
    def test_root_agent_is_sequential_with_correct_order(self, *mocks):
        """Root agent has correct sub-agent ordering."""
        from newsletter_agent.agent import build_pipeline
        config = make_config(2)
        root = build_pipeline(config)
        
        assert root.name == "NewsletterPipeline"
        assert len(root.sub_agents) == 4  # config, research, synthesis, output

    @patch("newsletter_agent.agent.FormatterAgent")
    @patch("newsletter_agent.agent.DeliveryAgent")
    @patch("newsletter_agent.agent.SynthesisAgent")
    @patch("newsletter_agent.agent.ConfigLoaderAgent")
    def test_research_phase_is_parallel_agent(self, *mocks):
        """Research phase must be a ParallelAgent."""
        from newsletter_agent.agent import build_pipeline
        config = make_config(3)
        root = build_pipeline(config)
        
        research_phase = root.sub_agents[1]
        assert research_phase.name == "ResearchPhase"

    @patch("newsletter_agent.agent.FormatterAgent")
    @patch("newsletter_agent.agent.DeliveryAgent")
    @patch("newsletter_agent.agent.SynthesisAgent")
    @patch("newsletter_agent.agent.ConfigLoaderAgent")
    def test_model_assignments(self, *mocks):
        """Research agents use Flash, synthesis uses Pro."""
        from newsletter_agent.agent import build_pipeline
        config = make_config(2)
        root = build_pipeline(config)
        
        research_phase = root.sub_agents[1]
        for topic_pipeline in research_phase.sub_agents:
            for agent in topic_pipeline.sub_agents:
                assert "flash" in agent.model.lower()
        
        synthesis = root.sub_agents[2]
        assert "pro" in synthesis.model.lower()
```

### T05-08 Test Plan: Logging Configuration Tests

```python
"""
Unit tests for logging configuration.
Tests: newsletter_agent/logging_config.py
Spec refs: FR-042, FR-043, FR-044, FR-045
"""

import logging
import os
import pytest
from unittest.mock import patch
from io import StringIO

from newsletter_agent.logging_config import setup_logging


class TestLoggingConfiguration:
    """Tests for the setup_logging() function."""

    def setup_method(self):
        """Reset logging state before each test."""
        # Reset the _configured flag
        import newsletter_agent.logging_config as lc
        lc._configured = False
        # Remove existing handlers
        logger = logging.getLogger("newsletter_agent")
        logger.handlers.clear()

    def test_log_format_includes_required_fields(self):
        """Log format must include timestamp, level, name, message."""
        setup_logging()
        logger = logging.getLogger("newsletter_agent.test")
        
        handler = logging.getLogger("newsletter_agent").handlers[0]
        formatter = handler.formatter
        
        record = logging.LogRecord(
            name="newsletter_agent.test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=None,
            exc_info=None,
        )
        formatted = formatter.format(record)
        
        assert "INFO" in formatted
        assert "newsletter_agent.test" in formatted
        assert "Test message" in formatted

    @patch.dict(os.environ, {"LOG_LEVEL": "DEBUG"})
    def test_log_level_from_environment(self):
        """LOG_LEVEL env var should control the logger level."""
        setup_logging()
        logger = logging.getLogger("newsletter_agent")
        assert logger.level == logging.DEBUG

    @patch.dict(os.environ, {"LOG_LEVEL": "WARNING"})
    def test_warning_level_suppresses_info(self):
        """Setting WARNING should suppress INFO messages."""
        setup_logging()
        logger = logging.getLogger("newsletter_agent")
        assert logger.level == logging.WARNING

    def test_third_party_loggers_suppressed(self):
        """Third-party loggers should be at WARNING level."""
        setup_logging()
        assert logging.getLogger("googleapiclient").level == logging.WARNING
        assert logging.getLogger("httplib2").level == logging.WARNING

    def test_idempotent_setup(self):
        """Calling setup_logging() twice should not duplicate handlers."""
        setup_logging()
        handler_count = len(logging.getLogger("newsletter_agent").handlers)
        setup_logging()
        assert len(logging.getLogger("newsletter_agent").handlers) == handler_count
```

### T05-11 Test Plan: Security Tests

```python
"""
Security tests for the Newsletter Agent.
Tests: Secrets protection, XSS prevention, credential safety.
Spec refs: Section 10.2, Section 11.6
"""

import os
import re
import pytest
from pathlib import Path


class TestSecretsNotInCode:
    """Verify no secrets are committed to version control."""

    PROJECT_ROOT = Path(__file__).parent.parent

    def test_env_file_in_gitignore(self):
        """The .env file must be listed in .gitignore."""
        gitignore = self.PROJECT_ROOT / ".gitignore"
        assert gitignore.exists(), ".gitignore file must exist"
        content = gitignore.read_text()
        assert ".env" in content

    def test_no_api_keys_in_committed_files(self):
        """Scan committed files for potential API key patterns."""
        suspicious_patterns = [
            r'AIza[0-9A-Za-z\-_]{35}',    # Google API key
            r'pplx-[a-z0-9]{48}',          # Perplexity API key
            r'ya29\.[0-9A-Za-z\-_]+',      # Google OAuth2 access token
            r'1//[0-9A-Za-z\-_]+',         # Google refresh token
        ]
        
        code_files = list(self.PROJECT_ROOT.rglob("*.py"))
        code_files += list(self.PROJECT_ROOT.rglob("*.yaml"))
        code_files += list(self.PROJECT_ROOT.rglob("*.yml"))
        code_files += list(self.PROJECT_ROOT.rglob("*.md"))
        
        for filepath in code_files:
            if ".env" in str(filepath) or "node_modules" in str(filepath):
                continue
            content = filepath.read_text(errors="ignore")
            for pattern in suspicious_patterns:
                matches = re.findall(pattern, content)
                assert not matches, (
                    f"Potential API key found in {filepath}: {matches[0][:10]}..."
                )

    def test_no_client_secret_in_code(self):
        """No OAuth client secrets in committed code."""
        code_files = list(self.PROJECT_ROOT.rglob("*.py"))
        for filepath in code_files:
            content = filepath.read_text(errors="ignore")
            # Look for hardcoded client secrets (not env var references)
            assert "GOCSPX-" not in content, (
                f"Potential client secret in {filepath}"
            )


class TestXssPrevention:
    """Verify XSS prevention in HTML output."""

    def test_jinja2_template_has_autoescaping(self):
        """The newsletter template must use autoescaping."""
        template_path = (
            Path(__file__).parent.parent
            / "newsletter_agent"
            / "templates"
            / "newsletter.html.j2"
        )
        if template_path.exists():
            content = template_path.read_text()
            # Check for autoescape block or Jinja2 config
            # Note: autoescaping may be set in the Python code, not the template
            # This test may need adjustment based on implementation

    def test_xss_payload_in_topic_name_is_escaped(self):
        """XSS payloads in content must be escaped in HTML output."""
        # This test requires the formatter to be importable
        # Verify that <script> tags in topic names are escaped
        xss_payload = "<script>alert('xss')</script>"
        # Run formatter with xss_payload as topic name
        # Verify output contains &lt;script&gt; not <script>


class TestErrorMessageSafety:
    """Verify error messages don't leak credentials."""

    def test_gmail_auth_error_no_credential_leak(self):
        """GmailAuthError messages must not contain actual credentials."""
        from newsletter_agent.tools.gmail_auth import GmailAuthError
        
        error = GmailAuthError("Missing GMAIL_CLIENT_ID")
        error_str = str(error)
        
        # Should not contain actual credential values
        assert "GOCSPX-" not in error_str
        assert "ya29." not in error_str
```

## Implementation Notes

### Development Sequence

1. T05-01 (factory) + T05-02 (logging) + T05-05 (deploy docs) + T05-12 (README) in parallel
2. T05-03 (timing) after T05-01
3. T05-04 (HTTP handler) after T05-01
4. T05-06 (module setup) after T05-01 + T05-02
5. T05-07, T05-08 (unit tests) after their implementation tasks
6. T05-09 (E2E test) after T05-06
7. T05-10 (perf tests) and T05-11 (security tests) after T05-09

### ADK Runner API

The programmatic execution of ADK agents (outside of `adk web` or `adk run`) uses the Runner class:

```python
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

session_service = InMemorySessionService()
runner = Runner(
    agent=root_agent,
    app_name="newsletter_agent",
    session_service=session_service,
)

# Create session
session = await session_service.create_session(
    app_name="newsletter_agent",
    user_id="trigger",
)

# Run pipeline
async for event in runner.run_async(
    session_id=session.id,
    user_id="trigger",
    new_message=types.Content(
        parts=[types.Part(text="Generate newsletter")]
    ),
):
    # Process events
    pass
```

The exact API may differ by ADK version. Consult the ADK documentation for the programmatic runner pattern.

### Cloud Run Configuration

```yaml
# cloud-run-config.yaml (for reference, ADK may generate this)
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: newsletter-agent
spec:
  template:
    metadata:
      annotations:
        autoscaling.knative.dev/maxScale: "1"
        run.googleapis.com/execution-environment: gen2
    spec:
      timeoutSeconds: 600
      containerConcurrency: 1
      containers:
        - image: gcr.io/PROJECT/newsletter-agent
          resources:
            limits:
              memory: 1Gi
              cpu: "1"
          env:
            - name: GOOGLE_API_KEY
              valueFrom:
                secretKeyRef:
                  name: GOOGLE_API_KEY
                  key: latest
            - name: PERPLEXITY_API_KEY
              valueFrom:
                secretKeyRef:
                  name: PERPLEXITY_API_KEY
                  key: latest
            - name: GMAIL_REFRESH_TOKEN
              valueFrom:
                secretKeyRef:
                  name: GMAIL_REFRESH_TOKEN
                  key: latest
            - name: GMAIL_CLIENT_ID
              valueFrom:
                secretKeyRef:
                  name: GMAIL_CLIENT_ID
                  key: latest
            - name: GMAIL_CLIENT_SECRET
              valueFrom:
                secretKeyRef:
                  name: GMAIL_CLIENT_SECRET
                  key: latest
```

## Parallel Opportunities

- T05-01 (factory), T05-02 (logging), T05-05 (deploy docs), T05-12 (README) can all be worked concurrently
- T05-07, T05-08, T05-11 can be worked concurrently after their implementation tasks
- T05-10 (perf tests) requires all other tasks to be complete

## Risks & Mitigations

- **Risk**: ADK's programmatic Runner API may differ from what is documented or expected.
  **Mitigation**: Research the exact API during T05-04 implementation. ADK's `adk web` source code is a reference for how it runs agents programmatically. Fall back to using ADK's built-in HTTP server instead of a custom one.

- **Risk**: Cloud Run cold start time may be too long for the 600-second timeout, leaving less time for actual pipeline execution.
  **Mitigation**: Set min-instances=0 for cost optimization but document that the first weekly run may be slower. If needed, set min-instances=1 during business hours.

- **Risk**: The `adk deploy cloud_run` command may not support custom HTTP endpoints or Flask apps.
  **Mitigation**: If ADK uses its own HTTP handler, use ADK's built-in trigger mechanism instead of a custom `/run` endpoint. The pipeline trigger message can be sent via ADK's session API.

- **Risk**: Parallel research for 20 topics may hit Gemini API rate limits.
  **Mitigation**: Document rate limit considerations. If needed, batch topics into groups (e.g., 5 at a time) using nested ParallelAgent groups. This is a post-MVP optimization.

- **Risk**: Log volume on Cloud Run may incur unexpected Cloud Logging costs.
  **Mitigation**: Default to INFO level. The pipeline runs once per week, producing a manageable amount of logs. Add LOG_LEVEL env var to allow operators to reduce verbosity.

- **Risk**: Module-level agent initialization (`root_agent`) may fail silently on import, making debugging difficult.
  **Mitigation**: Catch exceptions at module level but re-raise them. Log the full error before re-raising. ADK surfaces import errors in `adk web`.

## Edge Cases

### Agent Factory Edge Cases

1. **Topic with only one source configured**: If `sources: ["google_search"]` only, the per-topic pipeline has only one agent. The SequentialAgent handles this correctly.

2. **Topic with no sources configured**: Should not occur due to config validation (WP01). If it somehow happens, the per-topic pipeline would have zero agents. Add a defensive check in the factory.

3. **Twenty topics creating 40+ agents**: ADK should handle this, but memory usage may increase. The agents are lightweight (no model loaded until invocation).

4. **Config change between runs**: Since the pipeline is built at import time, hot-reloading during `adk web` requires re-importing the module. ADK's dev server typically handles this.

### HTTP Trigger Edge Cases

1. **Concurrent POST requests**: Cloud Run set to maxScale=1 and containerConcurrency=1 ensures only one pipeline runs at a time. Additional requests queue or fail.

2. **Missing OIDC token**: Cloud Run IAM rejects the request with 401 before it reaches the application code. No custom auth handling needed.

3. **Request timeout at 599 seconds**: The pipeline is almost done but gets killed. The newsletter may have been sent but the response is lost. Gmail send is atomic, so no partial sends. The next run produces a new newsletter for the next date.

4. **Empty POST body**: The handler does not require a request body. Cloud Scheduler sends an empty POST, which is valid.

### Logging Edge Cases

1. **Very long log messages**: LLM responses stored in log messages could be very long. Use truncation in logging (log first 200 chars of large content).

2. **Unicode in logs**: Topic names and research content may contain Unicode. Python's logging module handles this natively.

3. **Log rotation**: On Cloud Run, logs go to stdout and Cloud Logging handles retention. Locally, there is no rotation - logs go to the terminal.

## Detailed E2E and Performance Test Plans

### T05-09 Full Test Plan: E2E Pipeline Test

```python
"""
End-to-end test for the full newsletter pipeline.
Tests: Complete pipeline from config load through HTML output.
Spec refs: Section 11.4, US-06
"""

import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock


# Test fixtures
TEST_CONFIG_YAML = """
newsletter:
  title: "E2E Test Newsletter"
  schedule: "0 8 * * 0"
  recipient_email: "test@example.com"

settings:
  dry_run: true
  output_dir: "{output_dir}"

topics:
  - name: "AI Frameworks"
    query: "Latest developments in AI agent frameworks"
    search_depth: "standard"
  - name: "Cloud Native"
    query: "Cloud native technology updates"
    search_depth: "standard"
"""

MOCK_GOOGLE_RESPONSE = {
    "text": "Google Search found several key developments in AI frameworks...",
    "sources": [
        {"url": "https://example.com/ai-1", "title": "AI Framework Update"},
        {"url": "https://example.com/ai-2", "title": "ADK Release Notes"},
    ],
    "provider": "google_search",
}

MOCK_PERPLEXITY_RESPONSE = {
    "text": "Perplexity analysis shows that AI frameworks are evolving rapidly...",
    "sources": [
        {"url": "https://example.com/px-1", "title": "Framework Comparison"},
        {"url": "https://example.com/px-2", "title": "Industry Trends"},
    ],
    "provider": "perplexity",
}

MOCK_SYNTHESIS = {
    "title": "AI Frameworks",
    "body_markdown": (
        "## AI Frameworks\n\n"
        "The AI framework landscape continues to evolve rapidly. "
        "[AI Framework Update](https://example.com/ai-1) reports that "
        "several major frameworks have released significant updates. "
        "Meanwhile, [Framework Comparison](https://example.com/px-1) "
        "highlights the growing competition in the space.\n\n"
        "Key developments include improved multi-agent orchestration, "
        "better tool integration, and enhanced deployment options. "
        "The trend toward declarative agent definitions is accelerating."
    ),
    "sources": [
        {"url": "https://example.com/ai-1", "title": "AI Framework Update"},
        {"url": "https://example.com/px-1", "title": "Framework Comparison"},
    ],
}


@pytest.fixture
def test_config_file(tmp_path):
    """Create a test config file in a temporary directory."""
    output_dir = str(tmp_path / "output")
    config_content = TEST_CONFIG_YAML.format(output_dir=output_dir)
    config_path = tmp_path / "config" / "topics.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(config_content)
    return str(config_path), output_dir


class TestFullPipelineE2E:
    """End-to-end tests for the complete pipeline."""

    @pytest.mark.asyncio
    async def test_dry_run_produces_html_file(self, test_config_file):
        """Full pipeline with dry_run=true produces an HTML file."""
        config_path, output_dir = test_config_file
        
        # Mock external APIs
        # Execute pipeline
        # Verify HTML file exists
        output_path = Path(output_dir)
        # After pipeline execution:
        # html_files = list(output_path.glob("*-newsletter.html"))
        # assert len(html_files) == 1

    @pytest.mark.asyncio
    async def test_html_contains_expected_sections(self, test_config_file):
        """Output HTML must contain title, executive summary, and topic sections."""
        config_path, output_dir = test_config_file
        
        # Execute pipeline with mocks
        # Read HTML output
        # Verify sections:
        # assert "E2E Test Newsletter" in html_content
        # assert "Executive Summary" in html_content
        # assert "AI Frameworks" in html_content
        # assert "Cloud Native" in html_content

    @pytest.mark.asyncio
    async def test_pipeline_logs_start_and_end(self, test_config_file, caplog):
        """Pipeline must log start and end messages."""
        config_path, output_dir = test_config_file
        
        # Execute pipeline
        # Verify log messages
        # assert "Pipeline started" in caplog.text
        # assert "Pipeline completed" in caplog.text

    @pytest.mark.asyncio
    @pytest.mark.timeout(30)
    async def test_mocked_pipeline_completes_within_30_seconds(
        self, test_config_file
    ):
        """With mocked APIs, pipeline should complete quickly."""
        config_path, output_dir = test_config_file
        
        # Execute pipeline with all external APIs mocked
        # The 30-second timeout decorator will fail the test if it's too slow

    @pytest.mark.asyncio
    async def test_research_results_in_state(self, test_config_file):
        """Session state must contain research results for all topics."""
        config_path, output_dir = test_config_file
        
        # Execute pipeline
        # Check state keys:
        # assert "research_0_google" in state
        # assert "research_0_perplexity" in state
        # assert "research_1_google" in state
        # assert "research_1_perplexity" in state

    @pytest.mark.asyncio
    async def test_synthesis_results_in_state(self, test_config_file):
        """Session state must contain synthesis results for all topics."""
        config_path, output_dir = test_config_file
        
        # Execute pipeline
        # Check state keys:
        # assert "synthesis_0" in state
        # assert "synthesis_1" in state
        # assert "executive_summary" in state
```

### T05-10 Full Test Plan: Performance Tests

```python
"""
Performance tests for the newsletter pipeline.
Tests: Pipeline timing for 5 and 20 topics.
Spec refs: Section 10.1, Section 11.5

These tests are marked with @pytest.mark.performance and are
skipped by default in CI. Run with: pytest -m performance
"""

import time
import pytest
from pathlib import Path


@pytest.mark.performance
class TestPipelinePerformance:
    """Performance validation tests."""

    @pytest.mark.asyncio
    @pytest.mark.timeout(600)
    async def test_five_topics_under_10_minutes(self):
        """5-topic pipeline must complete within 600 seconds.
        
        This test uses real API calls (Google, Perplexity, Gemini).
        Requires valid API keys in environment.
        """
        start = time.monotonic()
        
        # Build config with 5 topics
        # Execute full pipeline
        # Measure time
        
        elapsed = time.monotonic() - start
        assert elapsed < 600, f"5-topic pipeline took {elapsed:.1f}s (limit: 600s)"

    @pytest.mark.asyncio
    @pytest.mark.timeout(1200)
    async def test_twenty_topics_under_20_minutes(self):
        """20-topic pipeline must complete within 1200 seconds.
        
        This test uses real API calls.
        Requires valid API keys in environment.
        """
        start = time.monotonic()
        
        # Build config with 20 topics
        # Execute full pipeline
        # Measure time
        
        elapsed = time.monotonic() - start
        assert elapsed < 1200, f"20-topic pipeline took {elapsed:.1f}s (limit: 1200s)"

    @pytest.mark.asyncio
    async def test_parallel_research_is_sublinear(self):
        """Research for N topics should take roughly the same time
        as research for 1 topic (due to parallel execution).
        
        Verify that 5-topic research takes less than 2x the time
        of 1-topic research.
        """
        # Time 1-topic research
        start_1 = time.monotonic()
        # Execute 1-topic research
        time_1 = time.monotonic() - start_1
        
        # Time 5-topic research
        start_5 = time.monotonic()
        # Execute 5-topic research
        time_5 = time.monotonic() - start_5
        
        assert time_5 < time_1 * 2, (
            f"5-topic research ({time_5:.1f}s) should be < 2x "
            f"1-topic research ({time_1:.1f}s)"
        )

    @pytest.mark.asyncio
    async def test_html_rendering_under_5_seconds(self):
        """HTML rendering must complete within 5 seconds (Section 10.1)."""
        start = time.monotonic()
        
        # Render HTML with 5 topics of mock data
        
        elapsed = time.monotonic() - start
        assert elapsed < 5, f"HTML rendering took {elapsed:.1f}s (limit: 5s)"

    @pytest.mark.asyncio
    async def test_per_phase_timing_logged(self, caplog):
        """Verify that per-phase timing is logged."""
        # Execute pipeline
        
        # Verify timing logs exist
        # assert "ResearchPhase completed in" in caplog.text
        # assert "Synthesizer completed in" in caplog.text
        # assert "OutputPhase completed in" in caplog.text
        # assert "Pipeline completed in" in caplog.text
```

## README Template

The README.md created in T05-12 should follow this structure:

```markdown
# Newsletter Agent

An autonomous multi-agent system that performs deep research on configured topics
using Google Search and Perplexity AI, synthesizes findings into a professional
HTML newsletter, and delivers it via Gmail.

Built with Google Agent Development Kit (ADK).

## Quick Start

1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Create `config/topics.yaml` (see Configuration below)
4. Set up API keys in `.env`
5. Run: `adk web`

## Prerequisites

- Python 3.11+
- Google Cloud project with Gemini API enabled
- Google API key for Gemini models
- Perplexity API key (from perplexity.ai)
- Gmail account for email delivery

## Installation

[Step-by-step installation instructions]

## Configuration

[topics.yaml format with examples]

## Gmail OAuth2 Setup

[Step-by-step OAuth2 setup with screenshots/notes]

## Local Development

[adk web, adk run, dry-run mode]

## Deployment to Cloud Run

[Cloud Run deployment, Secret Manager, Cloud Scheduler]

## Architecture

[Text-based architecture diagram, agent tree description]

## Troubleshooting

[Common issues and solutions]
```

## Deployment Checklist

Before deploying to Cloud Run, verify:

1. [ ] All unit tests pass: `pytest tests/ -v --ignore=tests/e2e --ignore=tests/performance`
2. [ ] Config validation works: load `config/topics.yaml` with no errors
3. [ ] Dry-run works locally: `adk run newsletter_agent` with `dry_run: true`
4. [ ] Email works locally: send a test email with `dry_run: false`
5. [ ] GCP project has required APIs enabled: Cloud Run, Cloud Scheduler, Secret Manager
6. [ ] Service account created with required roles
7. [ ] Secrets stored in Secret Manager
8. [ ] Cloud Run service deployed with correct env vars and timeout
9. [ ] Cloud Scheduler job created with OIDC authentication
10. [ ] Manual trigger of Cloud Scheduler job succeeds

## Dependency Summary for WP05

| Package | Purpose | Already in WP01 |
|---------|---------|-----------------|
| google-adk | Agent framework, CLI, deployment | Yes |
| flask | HTTP handler (if needed beyond ADK) | No (may not be needed) |
| pytest-asyncio | Async test support | Yes |
| pytest-timeout | Test timeouts for performance tests | No |
| httpx | HTTP client for E2E tests | No |

### New Dependencies to Add

The following packages need to be added to `requirements.txt` or `pyproject.toml` if not already present from WP01:

- `pytest-timeout>=2.2.0` - For performance test time limits
- `httpx>=0.25.0` - For E2E HTTP client tests against the running server
- These are dev/test dependencies only, not needed in the production Cloud Run image

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| GOOGLE_API_KEY | Yes | - | Gemini API key |
| PERPLEXITY_API_KEY | Yes | - | Perplexity Sonar API key |
| GMAIL_CLIENT_ID | Yes (prod) | - | Gmail OAuth2 client ID |
| GMAIL_CLIENT_SECRET | Yes (prod) | - | Gmail OAuth2 client secret |
| GMAIL_REFRESH_TOKEN | Yes (prod) | - | Gmail OAuth2 refresh token |
| LOG_LEVEL | No | INFO | Application log level |

## Cross-WP Integration Points

| Integration | From WP | To WP | State Key | Direction |
|-------------|---------|-------|-----------|-----------|
| Config loading | WP01 | WP05 | `config_*` | WP01 stores, WP05 orchestrates |
| Research results | WP02 | WP03 | `research_N_provider` | WP02 stores, WP03 reads |
| Synthesis results | WP03 | WP03 | `synthesis_N` | WP03 stores and reads |
| Newsletter HTML | WP03 | WP04 | `newsletter_html` | WP03 stores, WP04 reads |
| Delivery status | WP04 | WP05 | `delivery_status` | WP04 stores, WP05 reads |
| Pipeline metadata | WP05 | WP05 | `newsletter_metadata` | Timing instrumentation |

### State Key Inventory

All session state keys used across the pipeline:

| Key | Type | Set By | Read By | Description |
|-----|------|--------|---------|-------------|
| `config_topics` | list[dict] | ConfigLoader | ResearchPhase | Topic configurations |
| `config_newsletter_title` | str | ConfigLoader | Formatter, Delivery | Newsletter title |
| `config_recipient_email` | str | ConfigLoader | Delivery | Email recipient |
| `config_dry_run` | bool | ConfigLoader | Delivery | Dry-run flag |
| `config_output_dir` | str | ConfigLoader | Delivery | Output directory path |
| `research_{N}_google` | str/dict | GoogleSearcher_N | Synthesizer | Google search results |
| `research_{N}_perplexity` | str/dict | PerplexitySearcher_N | Synthesizer | Perplexity results |
| `synthesis_{N}` | dict | Synthesizer | Formatter | Per-topic synthesis |
| `executive_summary` | str | Synthesizer | Formatter | Executive summary text |
| `newsletter_html` | str | Formatter | Delivery | Complete HTML newsletter |
| `newsletter_metadata` | dict | Formatter, Timing | Delivery, HTTP handler | Generation metadata |
| `delivery_status` | dict | Delivery | HTTP handler | Delivery result |

## Post-MVP Considerations

This work package completes the MVP. The following enhancements are out of scope for MVP but documented here for future planning:

1. **Multiple recipients**: Extend `recipient_email` to accept a list. Requires looping in the delivery agent.
2. **Webhook notifications**: Add Slack/Discord webhook notifications on pipeline completion or failure.
3. **A/B testing of prompts**: Support multiple prompt variants and track which produces better newsletters.
4. **Newsletter archive**: Save all generated newsletters to a persistent store (Cloud Storage, database) with a browseable web interface.
5. **Analytics**: Track email open rates via tracking pixels (requires a dedicated analytics endpoint).
6. **Retry with backoff**: Add configurable retry logic for transient API failures (rate limits, network errors).
7. **Multi-language support**: Support newsletter generation in languages other than English (requires prompt localization).
8. **Custom HTML themes**: Allow operators to choose from multiple CSS themes or provide custom CSS.
9. **Content moderation**: Add a content safety check before sending (Gemini safety filters).
10. **Cost tracking**: Log API costs per invocation (estimated based on token counts and API pricing).
11. **Scheduled summary reports**: Generate weekly pipeline health summaries with success/failure rates and timing trends.
12. **Topic rotation**: Automatically rotate topics on a configurable schedule (e.g., research different topics on alternating weeks).

These features should each be planned as separate work packages when prioritized.

## Activity Log

- 2025-01-01T00:00:00Z - planner - lane=planned - Work package created
- 2025-07-26T00:00:00Z - coder - lane=doing - Started WP05 implementation
- 2025-07-26T00:30:00Z - coder - lane=for_review - All tasks complete, submitted for review
