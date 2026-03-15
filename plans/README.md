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
| [WP13](WP13-source-refinement.md) | Deep Research Source Refinement | P1 | Complete | WP12 | No |
| [WP14](WP14-integration-testing.md) | Integration Testing & Backward Compatibility | P1 | Complete | WP11, WP12, WP13 | No |

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

---

## Enhancement: Adaptive Deep Research

> **Spec**: `specs/002-adaptive-deep-research.spec.md` (v1.0)
> **Added**: 2026-03-15

### Enhancement Work Packages

| ID | Title | Priority | Status | Depends On | Parallelisable |
|----|-------|----------|--------|-----------|----------------|
| [WP15](WP15-config-and-prompts.md) | Config Fields & Prompt Templates | P0 | Complete | WP11-WP14 (base system) | No |
| [WP16](WP16-adaptive-orchestrator.md) | Adaptive Research Orchestrator | P1 | Complete | WP15 | No |
| [WP17](WP17-acceptance-integration-testing.md) | Acceptance & Integration Testing | P1 | Not Started | WP16 | No |
| [WP18](WP18-quality-and-docs.md) | Quality, Performance & Documentation | P2 | Not Started | WP17 | No |

### Enhancement MVP Scope

Three work packages constitute the minimum releasable increment: **WP15, WP16, WP17**.

- **WP15** (P0) delivers the foundational config fields (`max_searches_per_topic`, `min_research_rounds`) and prompt templates (`reasoning.py`) that the adaptive orchestrator depends on.
- **WP16** (P1) delivers the core adaptive research loop (US-ADR-01, US-ADR-02): replaces fan-out query expansion with Plan-Search-Analyze-Decide cycle featuring PlanningAgent, AnalysisAgent, saturation detection, and configurable exit criteria.
- **WP17** (P1) delivers the quality gate: 10 BDD acceptance scenarios, integration tests, backward compatibility verification, and coverage thresholds.

**WP18** (P2) is post-MVP: performance benchmarks, security tests, and documentation updates. Can be deferred without affecting functionality.

### Enhancement Dependency & Execution Summary

- **Prerequisite**: WP01-WP14 must all be complete (base system + prior enhancements including the deep research orchestrator being replaced).
- **Sequence**: WP15 -> WP16 -> WP17 -> WP18
- **Parallelization**: Strictly sequential. Each WP depends on the prior. Within WPs, some tasks are parallelizable (marked in WP files).
- **Critical path**: WP15 (T15-01) -> WP16 (T16-04, T16-05, T16-06) -> WP17 (T17-01) -> WP18

### Enhancement Sequencing Notes

**WP15 (Config & Prompts)** must be completed first. It provides:
1. `max_searches_per_topic` and `min_research_rounds` config fields needed by WP16
2. `get_planning_instruction` and `get_analysis_instruction` prompt functions needed by WP16
3. Deprecation of `query_expansion.py` (still importable but no longer called)

Within WP15, the config tasks (T15-01/T15-02) and prompt tasks (T15-03/T15-04) are independent and can be worked in parallel.

**WP16 (Adaptive Orchestrator)** is the largest WP with 11 tasks. It rewrites `DeepResearchOrchestrator._run_async_impl` from a fan-out approach to an adaptive reasoning loop. Key changes:
- Removes `_expand_queries` and `_parse_variants` methods
- Removes 15-URL threshold early exit
- Adds PlanningAgent and AnalysisAgent LlmAgent sub-agents (created dynamically per invocation)
- Adds AdaptiveContext reasoning chain with persistence
- Adds configurable saturation detection with `min_research_rounds` safety minimum

Within WP16, T16-02 (PlanningAgent) and T16-03 (AnalysisAgent) can be developed in parallel. T16-04 integrates them into the main loop.

**WP17 (Testing)** validates the MVP. It implements all 10 BDD scenarios from the spec, integration tests with mocked tools, backward compatibility checks, and coverage verification.

**WP18 (Quality & Docs)** is post-MVP polish. All 5 tasks are independent and can be worked in parallel.

### OQ Resolutions (Spec v1.0)

All three open questions were resolved before planning:

- **OQ-ADR-1 (Full vs. condensed search results)**: Full text. The latest round's full search results are passed to the AnalysisAgent. Prior rounds use condensed summaries. Token cost is acceptable with gemini-2.5-flash's 1M context window.
- **OQ-ADR-2 (Reasoning chain persistence)**: Persisted. The AdaptiveContext reasoning chain is preserved at `adaptive_reasoning_chain_{idx}_{provider}` state key after merge (not cleaned up). Enables post-run quality analysis.
- **OQ-ADR-3 (Configurable safety minimum)**: Configurable. New `min_research_rounds` field (default: 2, range: 1-3) replaces the hard-coded safety minimum of 2 rounds before saturation can trigger early exit.

### Consistency Notes

Cross-WP consistency audit performed on 2026-03-15. No inconsistencies found. Key validations:
- `max_searches_per_topic` type and constraints: `int | None = Field(default=None, ge=1, le=15)` in WP15 T15-01, consumed as `max_searches: int = 3` in WP16 T16-01, passed from config in WP16 T16-09
- `min_research_rounds` type and constraints: `int = Field(default=2, ge=1, le=3)` in WP15 T15-01, consumed as `min_rounds: int = 2` in WP16 T16-01, passed from config in WP16 T16-09
- PlanningOutput JSON fields (`query_intent`, `key_aspects`, `initial_search_query`, `search_rationale`): prompt defines them in WP15 T15-03, parser validates them in WP16 T16-02
- AnalysisOutput JSON fields (`findings_summary`, `knowledge_gaps`, `coverage_assessment`, `saturated`, `next_query`, `next_query_rationale`): prompt defines them in WP15 T15-04, parser validates them in WP16 T16-03
- `get_planning_instruction` and `get_analysis_instruction` function signatures: created in WP15, called in WP16 -- signatures match
- Coverage thresholds: 80% code, 90% branch consistently stated across WP15 T15-07, WP17 T17-07
- State key `research_{idx}_{provider}` final output format (SUMMARY + SOURCES) preserved unchanged across WP16 merge logic
- All FRs from spec traceability matrix (Section 16) assigned to exactly one task, no orphans, no duplicates
- Dependency graph: WP15 -> WP16 -> WP17 -> WP18, strictly linear, no circular dependencies

### Enhancement Task Index

| Task ID | Summary | Work Package | Parallel? |
|---------|---------|--------------|----------|
| T15-01 | Add max_searches_per_topic and min_research_rounds to AppSettings | WP15 | No |
| T15-02 | Unit tests for new config fields | WP15 | No |
| T15-03 | Create reasoning.py with get_planning_instruction | WP15 | Yes |
| T15-04 | Add get_analysis_instruction to reasoning.py | WP15 | No |
| T15-05 | Deprecate query_expansion.py | WP15 | Yes |
| T15-06 | Unit tests for prompt template functions | WP15 | No |
| T15-07 | Coverage verification for WP15 | WP15 | No |
| T16-01 | Update orchestrator constructor and remove URL threshold | WP16 | No |
| T16-02 | Implement PlanningAgent creation and invocation | WP16 | Yes |
| T16-03 | Implement AnalysisAgent creation and invocation | WP16 | Yes |
| T16-04 | Rewrite _run_async_impl with adaptive loop | WP16 | No |
| T16-05 | Implement exit criteria and saturation logic | WP16 | No |
| T16-06 | Implement AdaptiveContext and reasoning chain persistence | WP16 | No |
| T16-07 | Implement duplicate query detection | WP16 | No |
| T16-08 | Update merge and cleanup for new state keys | WP16 | No |
| T16-09 | Update agent.py factory to pass new params | WP16 | No |
| T16-10 | Unit tests for adaptive orchestrator | WP16 | No |
| T16-11 | Update existing unit tests for API changes | WP16 | No |
| T17-01 | Update existing BDD tests for adaptive behavior | WP17 | No |
| T17-02 | Add BDD scenarios: saturation and early exit paths | WP17 | Yes |
| T17-03 | Add BDD scenarios: single-round, standard mode, fallbacks | WP17 | Yes |
| T17-04 | Integration tests: full adaptive flow with mocked tools | WP17 | No |
| T17-05 | Update backward compatibility tests | WP17 | No |
| T17-06 | End-to-end test with dry_run mode | WP17 | No |
| T17-07 | Coverage threshold verification | WP17 | No |
| T18-01 | Performance benchmarks: per-round latency | WP18 | Yes |
| T18-02 | Security tests: prompt injection resistance | WP18 | Yes |
| T18-03 | Update configuration-guide.md | WP18 | Yes |
| T18-04 | Update deployment-guide.md and .env.example | WP18 | Yes |
| T18-05 | Update README.md with adaptive research overview | WP18 | Yes |
