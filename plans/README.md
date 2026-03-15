# Plan Index - Newsletter Agent

> **Spec**: `specs/newsletter-agent.spec.md`
> **Generated**: 2025-07-25

## Work Packages

| ID | Title | Priority | Status | Depends On | Parallelisable |
|----|-------|----------|--------|-----------|----------------|
| [WP01](WP01-project-scaffolding.md) | Project Scaffolding and Config System | P0 | Complete | none | - |
| [WP02](WP02-research-pipeline.md) | Research Pipeline | P1 | Complete | WP01 | No |
| [WP03](WP03-synthesis-formatting.md) | Content Synthesis and Formatting | P1 | Complete | WP01, WP02 | No |
| [WP04](WP04-email-delivery.md) | Email Delivery and Local Output | P1 | Complete | WP01, WP03 | No |
| [WP05](WP05-orchestration-deployment.md) | Orchestration, Deployment, and Observability | P1 | Complete | WP01, WP02, WP03, WP04 | No |
| [WP06](WP06-search-timeframe.md) | Search Timeframe Configuration | P2 | Complete | WP01, WP02 | Yes |
| [WP07](WP07-link-verification.md) | Link Verification | P2 | Complete | WP01, WP03 | Yes |
| [WP08](WP08-integration-testing.md) | Integration Testing, E2E & Documentation | P2 | Complete | WP06, WP07 | No |
| [WP09](WP09-multi-recipient.md) | Multi-Recipient Email Delivery | P2 | Complete | WP01-WP05 | Yes |
| [WP10](WP10-pre-synthesis-verification.md) | Pre-Synthesis Source Verification | P2 | Complete | WP01-WP08 | Yes |

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

---

## Enhancement: Link Verification & Search Timeframe

> **Spec**: `specs/link-verification-timeframe.spec.md`
> **Added**: 2025-01-01

### Enhancement Work Packages

| ID | Title | Priority | Status | Depends On | Parallelisable |
|----|-------|----------|--------|-----------|----------------|
| [WP06](WP06-search-timeframe.md) | Search Timeframe Filtering | P1 | Not Started | WP01-WP05 (base system) | Yes |
| [WP07](WP07-link-verification.md) | Source Link Verification | P1 | Not Started | WP01-WP05 (base system) | Yes |
| [WP08](WP08-integration-testing.md) | Integration Testing, E2E & Documentation | P2 | Not Started | WP06, WP07 | No |

### Enhancement MVP Scope

All three enhancement work packages are required for release: **WP06, WP07, WP08**.

- **WP06** delivers search timeframe filtering (config fields, resolver, research builder integration, Perplexity API passthrough).
- **WP07** delivers source link verification (async HTTP checker, SSRF protection, LinkVerifierAgent, pipeline integration).
- **WP08** delivers the cross-feature quality gate (integration tests, E2E tests, backward compatibility verification, documentation).

### Enhancement Dependency & Execution Summary

- **Prerequisite**: WP01-WP05 must all be complete (the base system must be working).
- **Sequence**: WP06 + WP07 (parallel) -> WP08 (integration/quality gate)
- **Parallelization**: WP06 and WP07 have zero shared dependencies and can be worked simultaneously.
- **Critical path**: WP06 or WP07 (whichever finishes last) -> WP08

### Enhancement Sequencing Notes

WP06 (Search Timeframe) and WP07 (Link Verification) are fully independent features modifying different pipeline stages:

- **WP06** touches: config schema (timeframe fields), timeframe resolver (new module), research phase builder, Perplexity search tool
- **WP07** touches: config schema (verify_links field), link verifier (new module), LinkVerifierAgent (new agent), pipeline agent factory

The only shared file is `newsletter_agent/config/schema.py`, where both WPs add new Pydantic fields to `AppSettings`. This is a non-conflicting additive change, so parallel implementation is safe.

WP08 must wait for both WP06 and WP07 because it tests combined behavior, backward compatibility, and the full E2E pipeline with both features active.

### Enhancement Task Index

| Task ID | Summary | Work Package | Parallel? |
|---------|---------|--------------|----------|
| T06-01 | Config schema: timeframe field on AppSettings and TopicConfig | WP06 | No |
| T06-02 | Timeframe resolver: parse presets, custom ranges, absolute dates | WP06 | No |
| T06-03 | Google Search instruction builder: inject date clause | WP06 | Yes |
| T06-04 | Perplexity search: add search_recency_filter parameter | WP06 | Yes |
| T06-05 | Research phase builder: pass resolved timeframe to agents | WP06 | No |
| T06-06 | Session state: populate config_timeframes key | WP06 | No |
| T06-07 | Unit tests: timeframe resolver and config validation | WP06 | Yes |
| T06-08 | Unit tests: research builder with timeframe | WP06 | Yes |
| T06-09 | BDD tests: timeframe configuration scenarios | WP06 | No |
| T06-10 | Unit tests: Perplexity search with recency filter | WP06 | Yes |
| T07-01 | Config schema: verify_links field on AppSettings | WP07 | No |
| T07-02 | URL extraction utility: parse URLs from markdown and sources | WP07 | Yes |
| T07-03 | verify_urls: async HTTP HEAD with GET fallback and concurrency | WP07 | No |
| T07-04 | SSRF protection: private IP blocking and scheme validation | WP07 | No |
| T07-05 | clean_broken_links_from_markdown: remove broken citations | WP07 | Yes |
| T07-06 | LinkVerifierAgent: BaseAgent subclass | WP07 | No |
| T07-07 | All-broken notice: append notice when all sources fail | WP07 | No |
| T07-08 | Pipeline integration: add LinkVerifierAgent to agent factory | WP07 | No |
| T07-09 | Unit tests: link verifier utilities and agent | WP07 | Yes |
| T07-10 | BDD tests: link verification scenarios | WP07 | No |
| T08-01 | Integration test: Config + Research timeframe flow | WP08 | Yes |
| T08-02 | Integration test: Config + Perplexity timeframe passthrough | WP08 | Yes |
| T08-03 | Integration test: Synthesis + LinkVerifier flow | WP08 | Yes |
| T08-04 | Integration test: Timeframe + Link Verification combined | WP08 | No |
| T08-05 | Backward compatibility test suite | WP08 | Yes |
| T08-06 | E2E test: full pipeline with both features | WP08 | No |
| T08-07 | E2E test: full pipeline backward compatibility | WP08 | Yes |
| T08-08 | Performance test: link verification throughput | WP08 | Yes |
| T08-09 | Security test: SSRF prevention in pipeline context | WP08 | Yes |
| T08-10 | Documentation: README and configuration examples | WP08 | Yes |
| T08-11 | Test configuration and CI integration | WP08 | Yes |

---

## Enhancement: Autonomous Execution & Multi-Round Deep Research

> **Spec**: `specs/autonomous-deep-research.spec.md` (v1.1)
> **Added**: 2026-03-15

### Enhancement Work Packages

| ID | Title | Priority | Status | Depends On | Parallelisable |
|----|-------|----------|--------|-----------|----------------|
| [WP11](WP11-config-and-cli-runner.md) | Config Extension & Autonomous CLI Runner | P0/P1 | Complete | WP01-WP10 (base system) | Yes |
| [WP12](WP12-deep-research-orchestrator.md) | Multi-Round Deep Research Orchestrator | P1 | Complete | WP11 | No |
| [WP13](WP13-source-refinement.md) | Deep Research Source Refinement | P1 | Not Started | WP12 | No |
| [WP14](WP14-integration-testing.md) | Integration Testing & Backward Compatibility | P1 | Not Started | WP11, WP12, WP13 | No |

### Enhancement MVP Scope

All four enhancement work packages constitute the minimum releasable increment: **WP11, WP12, WP13, WP14**.

- **WP11** (P0/P1) delivers the foundation config field (`max_research_rounds`) and the autonomous CLI runner (US-01). The CLI runner is independently demonstrable.
- **WP12** (P1) delivers the core multi-round deep research capability (US-02): `DeepResearchOrchestrator` custom BaseAgent with query expansion, multiple search rounds, URL tracking, early exit, and round merging.
- **WP13** (P1) delivers LLM-based source refinement (US-04): `DeepResearchRefinerAgent` selects 5-10 best sources per provider per deep-mode topic after link verification.
- **WP14** (P1) delivers the quality gate: integration tests, E2E tests, backward compatibility verification (SC-005, SC-006), performance benchmarks, and security checks.

### Enhancement Dependency & Execution Summary

- **Prerequisite**: WP01-WP10 must all be complete (base system + prior enhancements).
- **Sequence**: WP11 -> WP12 -> WP13 -> WP14
- **Parallelization**: Limited. WP11's CLI runner (T11-03 to T11-07) is independent of WP12's deep research, but WP12 depends on WP11's config field (T11-01). Within WPs, some tasks are parallelizable (marked [P]).
- **Critical path**: WP11 (T11-01) -> WP12 (T12-01 through T12-11) -> WP13 -> WP14

### Enhancement Sequencing Notes

**WP11 (Config & CLI Runner)** must be completed first. It provides:
1. `max_research_rounds` config field needed by WP12
2. The `__main__.py` CLI runner needed by WP14 E2E tests

Within WP11, the config field (T11-01/T11-02) and CLI runner (T11-03 to T11-07) are independent tracks that can be worked in parallel.

**WP12 (Deep Research Orchestrator)** is the largest WP with 11 tasks. It modifies `build_research_phase()` in `agent.py` to produce `DeepResearchOrchestrator` agents for deep-mode topics. Key architectural decision: uses ADK custom BaseAgent pattern (not LoopAgent) per OQ-1/OQ-2 resolution in spec v1.1.

**WP13 (Source Refinement)** depends on WP12 because it refines the multi-round output. It modifies `build_pipeline()` in `agent.py` -- a different function from WP12's changes, but logically sequential since the refiner processes multi-round results.

**WP14 (Integration & Testing)** is the final quality gate. It cannot start until all features are implemented. It also verifies backward compatibility (SC-005: standard mode unchanged, SC-006: all existing tests pass).

### OQ Resolutions (Spec v1.1)

Both open questions from the original spec were resolved before planning:

- **OQ-1 (output_key)**: Confirmed ADK `output_key` is fixed per LlmAgent at construction time. Resolved by using DeepResearchOrchestrator which reads state directly after sub-agent invocation -- no output_key workaround needed.
- **OQ-2 (escalation)**: Confirmed `tool_context.actions.escalate` is only available in LlmAgent tool functions, not from BaseAgent. Resolved by replacing LoopAgent + RoundAccumulator + ResearchCombiner with a single DeepResearchOrchestrator custom BaseAgent that uses Python `break` for early exit.

### Consistency Notes

Cross-WP consistency audit performed. No inconsistencies found. Key validations:
- State key `research_{idx}_{provider}` format consistent between WP12 (producer) and WP13 (consumer)
- URL extraction regex (`\[...\]\(https?://...\)`) used in both WP12 T12-06 and WP13 T13-03 -- WP13 notes it should be extracted to a shared utility in `research_utils.py`
- `max_research_rounds` config field consistently defined in WP11 and consumed in WP12/WP14
- All FRs from spec traceability matrix (Section 16) assigned to exactly one task across WPs
- Coverage thresholds: 80% code, 90% branch specified in WP11 T11-08; also applies to WP12 and WP13

### Enhancement Task Index

| Task ID | Summary | Work Package | Parallel? |
|---------|---------|--------------|----------|
| T11-01 | Add max_research_rounds config field | WP11 | Yes |
| T11-02 | Unit tests for max_research_rounds config | WP11 | No |
| T11-03 | Create __main__.py CLI entry point module | WP11 | Yes |
| T11-04 | Implement CLI runner main() function | WP11 | No |
| T11-05 | Preserve existing entry points | WP11 | No |
| T11-06 | Unit tests for CLI runner | WP11 | No |
| T11-07 | BDD tests for CLI execution | WP11 | No |
| T11-08 | Configure coverage thresholds for new modules | WP11 | No |
| T12-01 | Create query expansion prompt template | WP12 | Yes |
| T12-02 | Create deep search round prompt variants | WP12 | Yes |
| T12-03 | Implement DeepResearchOrchestrator BaseAgent | WP12 | No |
| T12-04 | Implement query expansion invocation | WP12 | No |
| T12-05 | Implement multi-round search loop | WP12 | No |
| T12-06 | Implement URL tracking and early exit | WP12 | No |
| T12-07 | Implement round merging and state cleanup | WP12 | No |
| T12-08 | Update build_research_phase() for conditional deep/standard | WP12 | No |
| T12-09 | Unit tests for DeepResearchOrchestrator | WP12 | Yes |
| T12-10 | Unit tests for pipeline structure with deep mode | WP12 | Yes |
| T12-11 | BDD tests for multi-round deep research | WP12 | No |
| T13-01 | Create refinement prompt template | WP13 | Yes |
| T13-02 | Create DeepResearchRefinerAgent BaseAgent | WP13 | Yes |
| T13-03 | Implement source extraction and count check | WP13 | No |
| T13-04 | Implement LLM-based source evaluation | WP13 | No |
| T13-05 | Implement in-place state update | WP13 | No |
| T13-06 | Add DeepResearchRefinerAgent to pipeline | WP13 | No |
| T13-07 | Unit tests for DeepResearchRefinerAgent | WP13 | No |
| T13-08 | BDD tests for source refinement | WP13 | No |
| T14-01 | Integration test: multi-round research with mocked tools | WP14 | Yes |
| T14-02 | Integration test: mixed standard and deep topics | WP14 | Yes |
| T14-03 | Integration test: CLI runner end-to-end with mocks | WP14 | Yes |
| T14-04 | E2E test: full pipeline with deep-mode topics | WP14 | No |
| T14-05 | E2E test: CLI subprocess execution | WP14 | No |
| T14-06 | Backward compatibility: standard mode unchanged | WP14 | Yes |
| T14-07 | Backward compatibility: max_research_rounds=1 | WP14 | Yes |
| T14-08 | Performance benchmark for deep research | WP14 | No |
| T14-09 | Security verification | WP14 | Yes |
| T14-10 | Verify existing entry points remain functional | WP14 | Yes |
