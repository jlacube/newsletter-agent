# Autonomous Execution and Multi-Round Deep Research -- Specification

> **Source brief**: User request -- autonomous startup without fake input; multi-round deep research with source refinement
> **Feature branch**: `autonomous-deep-research`
> **Status**: Draft
> **Version**: 1.0

---

## 1. Overview

This specification adds two capabilities to the Newsletter Agent:

1. **Autonomous CLI runner** -- a `python -m newsletter_agent` entry point that executes the full pipeline programmatically without interactive user input, replacing the need to type a trigger message in `adk run`.
2. **Multi-round deep research** -- when `search_depth: "deep"`, each provider performs multiple search rounds with varied query angles, accumulates a large pool of source URLs, verifies them, and then a new refinement agent selects the 5-10 most relevant per provider per topic before synthesis.

Standard-mode topics (`search_depth: "standard"`) are completely unaffected.

---

## 2. Goals & Success Criteria

- **SC-001**: `python -m newsletter_agent` runs the full pipeline to completion without any interactive user input; exit code 0 on success, 1 on failure.
- **SC-002**: Deep-mode topics collect at least 15 unique source URLs per provider per topic across all research rounds (before verification).
- **SC-003**: After verification and refinement, each deep-mode topic retains exactly 5-10 curated source URLs per provider.
- **SC-004**: The `max_research_rounds` config field is respected -- the research loop for deep-mode topics never exceeds the configured value.
- **SC-005**: Standard-mode topics produce identical results to the current pipeline (no behavioral change).
- **SC-006**: All existing tests (437) continue to pass.

---

## 3. Users & Roles

- **Operator**: Configures `topics.yaml` and triggers pipeline execution via CLI, HTTP endpoint, or Cloud Scheduler. Has full system access. Primary use case: run the newsletter generation autonomously on a schedule.
- **Recipient**: Receives the generated newsletter email. No system interaction.

---

## 4. Functional Requirements

### 4.1 Autonomous CLI Runner

- **FR-CLI-001**: The system SHALL provide a `newsletter_agent/__main__.py` module that enables execution via `python -m newsletter_agent`.
- **FR-CLI-002**: The CLI runner SHALL use ADK's `Runner` and `InMemorySessionService` to execute the pipeline programmatically, sending an automatic trigger message (`"Generate newsletter"`) without requiring interactive input.
- **FR-CLI-003**: The CLI runner SHALL log pipeline progress events to stdout using the existing logging configuration.
- **FR-CLI-004**: The CLI runner SHALL exit with code 0 on successful completion and code 1 on any unhandled exception or pipeline abort.
- **FR-CLI-005**: The CLI runner SHALL print a final summary to stdout containing: `newsletter_date`, `topics_processed`, `email_sent` (boolean), and `output_file` (if dry_run).
- **FR-CLI-006**: The existing `http_handler.py` (Cloud Run) and `adk run`/`adk web` (development) entry points SHALL remain functional and unchanged.

**Implementation Contract -- CLI Runner**:

| Item | Detail |
|------|--------|
| Module path | `newsletter_agent/__main__.py` |
| Invocation | `python -m newsletter_agent` |
| Dependencies | `google.adk.runners.Runner`, `google.adk.sessions.InMemorySessionService`, `google.genai.types` |
| Input | None (reads config from `config/topics.yaml` and environment variables, as existing) |
| Output | Structured log lines to stdout; JSON summary line on completion |
| Exit code | 0 = success, 1 = failure |
| Error behavior | Catches all exceptions from pipeline execution, logs the error, prints error summary, exits with code 1 |

### 4.2 Multi-Round Deep Research Configuration

- **FR-CFG-001**: `NewsletterConfig.settings` SHALL accept a new optional field `max_research_rounds` of type `int`.
- **FR-CFG-002**: `max_research_rounds` SHALL have a default value of 3.
- **FR-CFG-003**: `max_research_rounds` SHALL be validated: minimum 1, maximum 5. Values outside this range SHALL raise `ConfigValidationError`.
- **FR-CFG-004**: `max_research_rounds` SHALL only affect topics where `search_depth` is `"deep"`. Standard-mode topics SHALL always perform exactly 1 research round regardless of this setting.

**Implementation Contract -- Config Field**:

```python
# In SettingsConfig (newsletter_agent/config/schema.py)
max_research_rounds: int = Field(default=3, ge=1, le=5)
```

YAML example:
```yaml
settings:
  max_research_rounds: 3  # 1-5, only affects deep mode
```

### 4.3 Multi-Round Research Phase (Deep Mode)

- **FR-MRR-001**: For each deep-mode topic and each configured provider, the research phase SHALL use a custom `DeepResearchOrchestrator` (BaseAgent subclass) that internally manages multi-round search via explicit sub-agent invocation (ADK custom agent pattern). This replaces the originally proposed LoopAgent approach due to OQ-1/OQ-2 resolution (see Section 14).
- **FR-MRR-002**: The first research round SHALL use the original topic query as-is.
- **FR-MRR-003**: Subsequent research rounds (2 through N) SHALL use query variants generated by an LLM-based query expansion step. Each variant SHALL explore a different angle of the topic (e.g., trends, expert opinions, data/statistics, controversies, implications).
- **FR-MRR-004**: The query expansion step SHALL generate exactly `max_research_rounds - 1` query variants from the original query. The `DeepResearchOrchestrator` SHALL call a `QueryExpanderAgent` (LlmAgent) as a sub-agent and read the variants from session state key `deep_queries_{topic_idx}_{provider}` (a JSON list of strings).
- **FR-MRR-005**: The `DeepResearchOrchestrator` SHALL invoke a `DeepSearchRound` LlmAgent sub-agent for each round, reading its output from the fixed `output_key` `deep_research_latest_{idx}_{provider}`, then copying the content to a round-specific key `research_{idx}_{provider}_round_{round_idx}` before invoking the next round.
- **FR-MRR-006**: After all rounds complete (or early exit), the `DeepResearchOrchestrator` SHALL merge all round results into the standard `research_{idx}_{provider}` state key. The merged output SHALL:
  - Concatenate summary text from all rounds
  - Deduplicate source URLs (keep first occurrence)
  - Produce a unified SOURCES section with all unique URLs
- **FR-MRR-007**: The research loop MAY exit early (before `max_research_rounds`) if the `DeepResearchOrchestrator` determines that at least 15 unique source URLs have been collected for the current topic-provider combination. Early exit uses a Python `break` in the orchestrator's round loop (no ADK escalation API needed).
- **FR-MRR-008**: For standard-mode topics, the research phase SHALL remain unchanged -- a single `LlmAgent` search per provider, no loop, no query expansion.
- **FR-MRR-009**: For Google Search rounds, each round's `LlmAgent` SHALL use the `google_search` grounding tool with the round's query and request at least 8 sources.
- **FR-MRR-010**: For Perplexity rounds, each round's `LlmAgent` SHALL call the `search_perplexity` tool with the round's query and `search_depth="deep"`.
- **FR-MRR-011**: The query expansion agent SHALL use the same research model (`gemini-2.5-flash`) as the search agents.

**Implementation Contract -- Multi-Round Research**:

Per deep-mode topic, per provider, the agent subtree:
```
DeepResearchOrchestrator_{idx}_{provider} (BaseAgent)
    # Internally creates and invokes:
    #   1. QueryExpanderAgent (LlmAgent) - generates query variants
    #   2. For each round: DeepSearchRound (LlmAgent) - searches with current query
    # Handles: round accumulation, URL tracking, early exit, result merging
```

**State keys written by multi-round research**:

| Key | Type | Written by | Description |
|-----|------|------------|-------------|
| `deep_queries_{idx}_{provider}` | `list[str]` | QueryExpanderAgent (sub-agent) | N-1 query variants |
| `deep_research_latest_{idx}_{provider}` | `str` | DeepSearchRound LlmAgent (output_key) | Latest round output (overwritten each round) |
| `research_{idx}_{provider}_round_{N}` | `str` | DeepResearchOrchestrator (copied from latest) | Raw search results for round N |
| `deep_urls_accumulated_{idx}_{provider}` | `list[str]` | DeepResearchOrchestrator | Running list of unique URLs found |
| `research_{idx}_{provider}` | `str` | DeepResearchOrchestrator | Final merged research text (same format as standard mode) |

**QueryExpanderAgent instruction contract**:

```
You are a research query strategist. Given the original research query below,
generate exactly {N} alternative search queries that explore DIFFERENT angles
of the same topic.

Original query: {query}
Topic: {topic_name}

Each alternative should focus on a distinct aspect:
- Industry trends and emerging patterns
- Expert opinions, interviews, and analysis
- Data points, statistics, and benchmarks
- Controversies, debates, and competing viewpoints
- Future implications and predictions

Output a JSON array of strings, one per query variant. No other text.
Example: ["query variant 1", "query variant 2", "query variant 3"]
```

**DeepResearchOrchestrator behavior contract**:

1. Create `QueryExpanderAgent` (LlmAgent) sub-agent with appropriate prompt
2. Invoke QueryExpanderAgent via `async for event in query_expander.run_async(ctx)` -- reads output from `deep_queries_{idx}_{provider}` state key
3. Parse query variants from state; if invalid JSON, fall back to suffix-based variants
4. For round 0: set current query to original query
5. For each round (0 to max_research_rounds - 1):
   a. Create/invoke `DeepSearchRound` LlmAgent sub-agent with current query in instruction
   b. Read round output from `deep_research_latest_{idx}_{provider}` state key
   c. Copy to `research_{idx}_{provider}_round_{round_count}`
   d. Extract all markdown URLs (`[title](url)`) from the round output
   e. Append new unique URLs to `deep_urls_accumulated_{idx}_{provider}`
   f. If `len(deep_urls_accumulated) >= 15`: break (exit loop early)
   g. For next round: set current query from `deep_queries` variant list
   h. Yield event with progress: "Round {N}: {X} unique URLs accumulated"
6. After loop: merge all round results into `research_{idx}_{provider}`:
   a. Concatenate SUMMARY sections with round separators
   b. Collect all unique URLs across all rounds (deduplicate by URL)
   c. Write combined text to `research_{idx}_{provider}` in standard format
7. Clean up intermediate state keys (delete `research_{idx}_{provider}_round_N`, `deep_*` keys)

### 4.4 Deep Research Source Refinement

- **FR-REF-001**: A new `DeepResearchRefinerAgent` SHALL be added to the pipeline between `LinkVerifierAgent` and `Synthesizer`.
- **FR-REF-002**: For each topic where `search_depth` is `"deep"`, the refiner SHALL evaluate all verified source URLs in `research_{idx}_{provider}` and select the 5-10 most relevant per provider.
- **FR-REF-003**: Source relevance SHALL be evaluated by an LLM (using the research model `gemini-2.5-flash`) based on: topical relevance, source authority/diversity, recency, and information density.
- **FR-REF-004**: The refiner SHALL update `research_{idx}_{provider}` state keys in-place, removing references to non-selected sources from both the text and the SOURCES section.
- **FR-REF-005**: After refinement, each deep-mode topic-provider combination SHALL have between 5 and 10 source URLs (inclusive). If fewer than 5 verified sources exist after verification, the refiner SHALL keep all remaining sources without filtering.
- **FR-REF-006**: For standard-mode topics, the refiner SHALL be a no-op (pass through without modification).
- **FR-REF-007**: The refiner SHALL log the count of sources before and after refinement for each topic-provider combination.

**Implementation Contract -- DeepResearchRefinerAgent**:

```python
class DeepResearchRefinerAgent(BaseAgent):
    """Selects the most relevant sources per deep-mode topic after verification."""
    
    model_config = {"arbitrary_types_allowed": True}
    topic_count: int = 0
    providers: list = []
    topic_configs: list = []  # List of TopicConfig for search_depth check
    
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        ...
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `topic_count` | `int` | Number of topics in config |
| `providers` | `list[str]` | Provider names (e.g., `["google", "perplexity"]`) |
| `topic_configs` | `list[TopicConfig]` | Full topic configs for `search_depth` check |

| Input state key | Type | Description |
|----------------|------|-------------|
| `research_{idx}_{provider}` | `str` | Verified research text with sources |

| Output state key | Type | Description |
|-----------------|------|-------------|
| `research_{idx}_{provider}` | `str` | Refined research text (5-10 sources per provider, in-place update) |

**Refinement LLM prompt contract**:

```
You are a research source curator. Given the following research text and sources
for the topic "{topic_name}", select the {target_count} most relevant and diverse sources.

Evaluation criteria (in order of importance):
1. Topical relevance: How directly does the source address the topic?
2. Source diversity: Prefer sources from different publications/sites
3. Recency: Prefer more recent sources
4. Information density: Prefer sources with specific data, quotes, or analysis

Research text:
{research_text}

Current sources:
{source_list}

Return a JSON object with:
- "selected_urls": list of the {target_count} most relevant URLs (strings)
- "rationale": one-sentence explanation of selection strategy

Select between 5 and 10 sources. If fewer than 5 sources are available, keep all.
```

Error behavior:
- If the LLM call fails, log warning and keep all sources (no filtering)
- If the LLM returns invalid JSON, log warning and keep all sources
- If the LLM selects fewer than 5 or more than 10, clamp to [5, 10] range

### 4.5 Pipeline Order Change

- **FR-PIP-001**: The pipeline order SHALL be: ConfigLoader, ResearchPhase, ResearchValidator, PipelineAbortCheck, LinkVerifier, **DeepResearchRefiner**, Synthesizer, SynthesisPostProcessor, OutputPhase.
- **FR-PIP-002**: `DeepResearchRefinerAgent` SHALL run after `LinkVerifierAgent` and before `Synthesizer`.
- **FR-PIP-003**: The `ResearchPhase` ParallelAgent SHALL use multi-round agents for deep-mode topics and standard single-round agents for standard-mode topics, determined at pipeline build time based on `TopicConfig.search_depth`.

### 4.6 Backward Compatibility

- **FR-BC-001**: Standard-mode topics SHALL produce identical behavior and results to the current pipeline.
- **FR-BC-002**: When `max_research_rounds` is 1, deep-mode topics SHALL behave identically to the current single-round deep research (no query expansion, no loop, no refinement beyond what exists).
- **FR-BC-003**: The `adk run`, `adk web`, and HTTP handler entry points SHALL remain functional.
- **FR-BC-004**: All existing session state keys consumed by downstream agents (Synthesizer, Formatter, Delivery) SHALL maintain their current format.

---

## 5. User Stories

### US-01 -- Autonomous CLI Execution (Priority: P1) MVP

**As an** Operator, **I want** to run the newsletter pipeline with a single command (`python -m newsletter_agent`) that requires no interactive input, **so that** I can schedule it via cron, systemd, or task scheduler without needing to pipe fake input.

**Why P1**: The current `adk run` interactive mode prevents true autonomous execution, which is the primary deployment model.

**Independent Test**: Run `python -m newsletter_agent` in a terminal with `dry_run: true`. Verify it completes without prompting for input, produces an HTML file in `output/`, and exits with code 0.

**Acceptance Scenarios**:
1. **Given** valid `config/topics.yaml` and environment variables, **When** `python -m newsletter_agent` is executed, **Then** the pipeline runs to completion without user input and exits with code 0.
2. **Given** valid config with `dry_run: true`, **When** CLI executes, **Then** an HTML file is saved to `output/` and a JSON summary is printed to stdout with `email_sent: false` and a non-empty `output_file` path.
3. **Given** an invalid config (missing required field), **When** CLI executes, **Then** the process logs the config error and exits with code 1.
4. **Given** all research providers fail (network down), **When** CLI executes, **Then** the pipeline aborts, an error page is saved, and the process exits with code 1.

### US-02 -- Multi-Round Deep Research (Priority: P1) MVP

**As an** Operator, **I want** deep-mode topics to perform multiple rounds of research with different query angles, **so that** the newsletter covers each topic from diverse perspectives with a comprehensive source pool.

**Why P1**: Single-round research often produces sparse or one-dimensional coverage for complex topics. Multi-round research is the core feature enabling higher-quality deep analysis.

**Independent Test**: Configure a topic with `search_depth: "deep"` and `max_research_rounds: 3`. Run the pipeline. Verify that the research state key contains sources from at least 2 distinct search rounds (visible in logs as "Round N: X unique URLs").

**Acceptance Scenarios**:
1. **Given** a topic with `search_depth: "deep"` and `max_research_rounds: 3`, **When** research phase runs, **Then** the system executes up to 3 search rounds per provider with different query angles.
2. **Given** `max_research_rounds: 3`, **When** round 2 accumulates 15+ unique URLs, **Then** the loop exits early (round 3 is skipped).
3. **Given** a topic with `search_depth: "standard"`, **When** research phase runs, **Then** exactly 1 search round occurs per provider (unchanged behavior).
4. **Given** `max_research_rounds: 1`, **When** deep-mode topic runs, **Then** behavior is identical to current single-round deep research.

### US-03 -- Configurable Research Rounds (Priority: P2)

**As an** Operator, **I want** to configure the maximum number of research rounds via `max_research_rounds` in `topics.yaml`, **so that** I can balance research depth against execution time and API costs.

**Why P2**: Configurability adds flexibility but the default (3) is sufficient for most use cases.

**Independent Test**: Set `max_research_rounds: 2` in config. Run a deep-mode topic. Verify logs show at most 2 search rounds per provider.

**Acceptance Scenarios**:
1. **Given** `max_research_rounds: 2`, **When** deep-mode research runs, **Then** at most 2 rounds of search execute per provider.
2. **Given** `max_research_rounds: 6` (invalid), **When** config loads, **Then** `ConfigValidationError` is raised with message indicating max is 5.
3. **Given** `max_research_rounds` is omitted from config, **When** config loads, **Then** default value of 3 is used.

### US-04 -- Source Refinement for Deep Research (Priority: P1) MVP

**As an** Operator, **I want** the system to select the 5-10 most relevant sources per provider per topic from the multi-round research pool, **so that** the newsletter cites only high-quality, diverse sources instead of an overwhelming dump of every URL found.

**Why P1**: Without refinement, multi-round research would flood synthesis with too many sources, degrading newsletter quality.

**Independent Test**: Configure a deep-mode topic. After pipeline completes, inspect the synthesis output: each topic section should cite between 5 and 10 sources per provider. Verify via log output that refinement reduced the source count.

**Acceptance Scenarios**:
1. **Given** a deep-mode topic with 20 verified sources from Google, **When** refinement runs, **Then** between 5 and 10 Google sources remain.
2. **Given** a deep-mode topic with 3 verified sources from Perplexity (below minimum), **When** refinement runs, **Then** all 3 sources are kept (no filtering when below 5).
3. **Given** a standard-mode topic, **When** refinement step runs, **Then** no sources are added or removed (no-op).
4. **Given** the refinement LLM call fails, **When** refinement step runs, **Then** all verified sources are kept and a warning is logged.

### Edge Cases

- What happens when a deep-mode topic has only 1 configured provider? Multi-round research runs for that provider only; refinement targets 5-10 from that single provider.
- What happens when query expansion LLM returns invalid JSON? Fall back to generating simple variants by appending angle suffixes to the original query (e.g., "{query} trends", "{query} expert analysis").
- What happens when all rounds produce 0 sources? ResearchValidator catches this and sets `research_all_failed` for that topic, same as current behavior.
- What happens when max_research_rounds is 1? No query expansion, no loop -- equivalent to current single-round deep search. Refinement still runs but likely has fewer sources to refine.

---

## 6. User Flows

### Flow A: Autonomous CLI Execution

1. Operator runs `python -m newsletter_agent` in terminal.
2. System loads `config/topics.yaml` and environment variables.
3. If config invalid: log error, print error summary, exit code 1. **STOP**.
4. System creates in-memory ADK session and Runner.
5. System sends automatic trigger message `"Generate newsletter"` to Runner.
6. Pipeline executes: ConfigLoader -> Research -> Validate -> Abort check -> Verify -> Refine -> Synthesize -> PostProcess -> Format -> Deliver.
7. System consumes all pipeline events, logging each to stdout.
8. On completion: print JSON summary (`newsletter_date`, `topics_processed`, `email_sent`, `output_file`).
9. Exit code 0. **STOP**.
10. On exception at any step: log error, print error summary, exit code 1. **STOP**.

### Flow B: Deep Multi-Round Research (per topic, per provider)

1. Pipeline build: for each topic with `search_depth: "deep"`, construct `DeepResearchOrchestrator` (BaseAgent) instead of single LlmAgent.
2. **Query expansion**: DeepResearchOrchestrator invokes QueryExpanderAgent (LlmAgent sub-agent), which generates `max_research_rounds - 1` query variants, stored in state.
3. **Round 0**: Orchestrator sets current query to original query. Invokes DeepSearchRound LlmAgent sub-agent, reads output from state, copies to `research_{idx}_{provider}_round_0`.
4. **URL tracking**: Orchestrator extracts URLs from round 0 output, adds to accumulated set. If 15+ URLs: break (exit loop). Otherwise: set next query from variants list.
5. **Round 1**: Orchestrator invokes DeepSearchRound with variant query 1, reads output, copies to round_1 key.
6. **URL tracking**: same as step 4 for round 1.
7. **Repeat** until max_research_rounds reached or early exit.
8. **Merge**: Orchestrator reads all round keys, merges into final `research_{idx}_{provider}` key with deduplicated SOURCES section.
9. **Cleanup**: Orchestrator deletes intermediate state keys.
10. Control returns to main pipeline for verification and refinement.

### Flow C: Source Refinement (per topic, per provider)

1. DeepResearchRefinerAgent reads config: check which topics have `search_depth: "deep"`.
2. For each deep topic, for each provider:
   a. Read `research_{idx}_{provider}` from state.
   b. Extract all markdown URLs.
   c. If count <= 10: skip refinement for this combination (already within target).
   d. If count > 10: call LLM with refinement prompt, get selected URLs.
   e. If LLM fails: log warning, keep all sources.
   f. Remove non-selected source references from research text.
   g. Write updated text back to state key.
   h. Log: "Refined topic {name}/{provider}: {before} -> {after} sources".
3. For standard topics: no-op, yield "Refinement skipped for standard topics" event.

---

## 7. Data Model

### 7.1 Config Schema Changes

**SettingsConfig** (modified):

| Field | Type | Required | Default | Constraints | Description |
|-------|------|----------|---------|-------------|-------------|
| `max_research_rounds` | `int` | No | 3 | 1 <= x <= 5 | Max search rounds for deep-mode topics |

All existing fields in `SettingsConfig` remain unchanged.

### 7.2 Session State -- New Keys (Deep Research)

| Key pattern | Type | Lifecycle | Written by | Read by |
|-------------|------|-----------|------------|---------|
| `deep_queries_{idx}_{provider}` | `list[str]` | Research phase | QueryExpanderAgent (sub-agent of orchestrator) | DeepResearchOrchestrator |
| `deep_research_latest_{idx}_{provider}` | `str` | Research phase | DeepSearchRound LlmAgent (output_key) | DeepResearchOrchestrator |
| `research_{idx}_{provider}_round_{N}` | `str` | Research phase | DeepResearchOrchestrator (copied from latest) | DeepResearchOrchestrator |
| `deep_urls_accumulated_{idx}_{provider}` | `list[str]` | Research phase | DeepResearchOrchestrator | DeepResearchOrchestrator |

All of these keys are intermediate and SHALL be cleaned up (deleted) by ResearchCombiner after merging. The final output remains the standard `research_{idx}_{provider}` key.

### 7.3 Session State -- Existing Keys (Unchanged)

| Key | Written by | Read by | Format change |
|-----|------------|---------|---------------|
| `research_{idx}_{provider}` | ResearchCombiner (deep) or LlmAgent (standard) | LinkVerifier, DeepResearchRefiner, Synthesizer | None -- same string format |
| `config_verify_links` | ConfigLoader | LinkVerifier | None |
| `research_all_failed` | ResearchValidator | PipelineAbortCheck | None |

---

## 8. API / Interface Design

### 8.1 CLI Entry Point

| Aspect | Detail |
|--------|--------|
| Invocation | `python -m newsletter_agent` |
| Arguments | None (all config from `config/topics.yaml` and env vars) |
| Stdout | Structured log lines (per existing logging config) + final JSON summary line |
| Stderr | None (all output to stdout via logging) |
| Exit codes | 0 = success, 1 = failure |

**Final summary JSON schema** (printed to stdout on completion):

```json
{
  "status": "success",
  "newsletter_date": "2026-03-15",
  "topics_processed": 3,
  "email_sent": false,
  "output_file": "output/newsletter_2026-03-15.html"
}
```

On failure:
```json
{
  "status": "error",
  "message": "Pipeline failed: RuntimeError: All research providers failed"
}
```

### 8.2 Config Schema Extension

```yaml
# topics.yaml -- new field
settings:
  max_research_rounds: 3  # integer, 1-5, default 3
```

Validation error on invalid value:
```
ConfigValidationError: 1 validation error for SettingsConfig
max_research_rounds
  Input should be less than or equal to 5 [type=less_than_equal, input_value=6, input_type=int]
```

### 8.3 New Agent Contracts

#### QueryExpanderAgent (LlmAgent)

| Property | Value |
|----------|-------|
| Type | `LlmAgent` |
| Model | `gemini-2.5-flash` |
| Input | State: none read directly. Instruction embeds `{query}`, `{topic_name}`, `{variant_count}`. Also sets `deep_query_current_{idx}_{provider}` to original query. |
| Output key | `deep_queries_{idx}_{provider}` |
| Output format | JSON array of strings, parsed by RoundAccumulator |
| Error behavior | If LLM returns non-JSON: fall back to suffix-based variants |
| Tools | None |

#### DeepSearchRound (LlmAgent)

| Property | Value |
|----------|-------|
| Type | `LlmAgent` |
| Model | `gemini-2.5-flash` |
| Input | Reads `{deep_query_current_{idx}_{provider}}` from instruction via ADK state variable interpolation |
| Output key | `deep_research_latest_{idx}_{provider}` (fixed key, overwritten each round; RoundAccumulator copies to round-specific key) |
| Output format | Same as current deep research: `SUMMARY:` + `SOURCES:` sections |
| Tools | `google_search` (for Google provider) or `search_perplexity` (for Perplexity provider) |
| Error behavior | If search fails: output empty string, RoundAccumulator handles gracefully |

#### DeepResearchOrchestrator (BaseAgent)

| Property | Value |
|----------|-------|
| Type | `BaseAgent` (custom, replaces LoopAgent + RoundAccumulator + ResearchCombiner) |
| Model | None (no LLM directly; invokes LlmAgent sub-agents) |
| Constructor params | `topic_idx: int`, `provider: str`, `query: str`, `topic_name: str`, `max_rounds: int`, `search_depth: str`, `model: str`, `tools: list` |
| Sub-agents created | `QueryExpanderAgent` (LlmAgent), `DeepSearchRound` (LlmAgent) -- created in constructor, invoked via `run_async(ctx)` |
| Input state | None (receives config via constructor params) |
| Output state | `research_{idx}_{provider}` (standard format, same as single-round mode) |
| Intermediate state | `deep_queries_{idx}_{provider}`, `deep_research_latest_{idx}_{provider}`, `research_{idx}_{provider}_round_{N}`, `deep_urls_accumulated_{idx}_{provider}` -- all cleaned up after merge |
| Early exit | Python `break` when 15+ unique URLs accumulated |
| Error behavior | If a search round fails: empty result, continue to next round. If all rounds fail: set `research_{idx}_{provider}` to empty string. |

#### DeepResearchRefinerAgent (BaseAgent)

| Property | Value |
|----------|-------|
| Type | `BaseAgent` (custom, uses LLM internally for evaluation) |
| Model (internal) | `gemini-2.5-flash` |
| Input state | `research_{idx}_{provider}` for deep-mode topics |
| Output state | `research_{idx}_{provider}` updated in-place (non-selected sources removed) |
| Target source count | 5-10 per provider per topic |
| Error behavior | If LLM fails or returns invalid response: keep all sources, log warning |
| No-op condition | `search_depth != "deep"` for the topic, or source count already <= 10 |

---

## 9. Architecture

### 9.1 System Design

The pipeline remains a single `SequentialAgent` with one new agent added (DeepResearchRefiner). The research phase construction becomes conditional based on `search_depth`:

```
NewsletterPipeline (SequentialAgent)
  |
  +-- ConfigLoader
  +-- ResearchPhase (ParallelAgent)
  |     +-- Topic0Research (SequentialAgent)
  |     |     +-- [standard] GoogleSearcher_0 (LlmAgent)
  |     |     +-- [deep]     DeepResearchOrchestrator_0_google (BaseAgent)
  |     |     |     # Internally invokes: QueryExpanderAgent, DeepSearchRound (per round)
  |     |     +-- [standard] PerplexitySearcher_0 (LlmAgent)
  |     |     +-- [deep]     DeepResearchOrchestrator_0_perplexity (BaseAgent)
  |     |           # Internally invokes: QueryExpanderAgent, DeepSearchRound (per round)
  |     +-- Topic1Research ...
  |
  +-- ResearchValidator
  +-- PipelineAbortCheck
  +-- LinkVerifier
  +-- DeepResearchRefiner    <-- NEW
  +-- Synthesizer
  +-- SynthesisPostProcessor
  +-- OutputPhase
```

### 9.2 Technology Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Agent framework | Google ADK >= 1.0.0 | Existing framework. LoopAgent available per ADK docs for iterative patterns. |
| Research model | gemini-2.5-flash | Existing choice; fast and cost-effective for search + query expansion. |
| Synthesis model | gemini-2.5-pro | Existing choice; higher quality for final content generation. |
| CLI runner | Python asyncio + ADK Runner | Matches existing http_handler.py pattern for programmatic execution. |
| Workflow orchestration | Custom BaseAgent (DeepResearchOrchestrator) | ADK custom agent pattern (like StoryFlowAgent) for iterative agent loops with explicit sub-agent invocation. Replaces LoopAgent per OQ-1/OQ-2 resolution. Reference: ADK Custom Agents docs. |

### 9.3 Directory & Module Structure

New/modified files:

| Path | Responsibility |
|------|---------------|
| `newsletter_agent/__main__.py` | CLI entry point for autonomous execution |
| `newsletter_agent/config/schema.py` | Add `max_research_rounds` field to SettingsConfig |
| `newsletter_agent/agent.py` | Conditional research phase build (standard vs deep), add DeepResearchRefiner to pipeline |
| `newsletter_agent/tools/deep_research.py` | New module: `DeepResearchOrchestrator` (BaseAgent custom agent for multi-round research) |
| `newsletter_agent/tools/deep_research_refiner.py` | New module: `DeepResearchRefinerAgent` |
| `newsletter_agent/prompts/research_google.py` | Add deep round prompt variant |
| `newsletter_agent/prompts/research_perplexity.py` | Add deep round prompt variant |
| `newsletter_agent/prompts/query_expansion.py` | New module: query expansion prompt template |

### 9.4 Key Design Decisions

**Decision 1: Custom BaseAgent (DeepResearchOrchestrator) for multi-round research**
- **Rationale**: ADK's LoopAgent has two limitations discovered during OQ analysis: (a) `output_key` is fixed at construction time (OQ-1), requiring a manual copy pattern; (b) BaseAgent sub-agents inside LoopAgent cannot trigger escalation via `tool_context.actions.escalate` since that API is only available in LlmAgent tool functions (OQ-2). A custom BaseAgent follows the ADK "StoryFlowAgent" pattern -- it creates LlmAgent sub-agents and invokes them via `async for event in sub_agent.run_async(ctx)`, with full Python control flow for iteration, URL tracking, and early exit.
- **Alternatives considered**: (a) LoopAgent with RoundAccumulator + ResearchCombiner -- rejected due to OQ-2 (no escalation from BaseAgent). (b) LoopAgent with LlmAgent "exit_loop" tool -- wasteful LLM call just to evaluate a threshold condition. (c) LoopAgent ignoring output_key issue -- loses round-specific results.
- **Consequences**: Single BaseAgent replaces LoopAgent + RoundAccumulator + ResearchCombiner (3 agents -> 1). Simpler agent tree. Slightly more code in one class but cleaner overall architecture.

**Decision 2: LLM-based query expansion**
- **Rationale**: LLM can generate semantically diverse query variants that cover different angles of the topic. Rule-based expansion (e.g., appending "trends", "analysis") would produce less relevant variants.
- **Alternatives considered**: (a) Static query templates -- too rigid, does not adapt to topic diversity. (b) User-defined query variants -- adds config complexity, defeats "autonomous" goal.
- **Consequences**: Adds one LLM call per topic-provider combination before the research loop. Cost: minimal (flash model, short prompt).

**Decision 3: LLM-based source refinement**
- **Rationale**: Source relevance evaluation requires semantic understanding of topic-source alignment, which rules-based approaches cannot provide.
- **Alternatives considered**: (a) Rule-based: sort by domain authority, recency -- cannot evaluate topical relevance. (b) Embedding-based similarity -- adds a dependency on an embedding model for marginal benefit over LLM evaluation.
- **Consequences**: One additional LLM call per deep-mode topic-provider combination. Cost: minimal with flash model.

**Decision 4: CLI runner reuses http_handler pattern**
- **Rationale**: The `http_handler.py` already solves programmatic execution via ADK Runner. The CLI runner copies this proven pattern.
- **Alternatives considered**: (a) Custom agent loop bypassing Runner -- loses ADK's event system, callbacks, and session management. (b) Piping stdin to `adk run` -- fragile and platform-dependent.
- **Consequences**: ADK's Runner API requires a `new_message` parameter. The CLI sends `"Generate newsletter"` as a trigger event, but no interactive input is needed.

### 9.5 External Integrations

| System | Purpose | Auth | Failure strategy |
|--------|---------|------|-----------------|
| Gemini API (google_search grounding) | Multi-round Google Search | API key via ADK config | Per-round failure: empty result, loop continues. All-round failure: ResearchValidator catches. |
| Perplexity API | Multi-round Perplexity search | `PERPLEXITY_API_KEY` env var | Per-round failure: tool returns `{error: true}`. All-round failure: ResearchValidator catches. |

---

## 10. Non-Functional Requirements

### 10.1 Performance

- Multi-round deep research adds up to `max_research_rounds` sequential LLM calls per provider per topic. Expected latency increase for deep mode: ~10-30 seconds per additional round (gemini-2.5-flash response time).
- Query expansion adds 1 LLM call (~2 seconds) per topic-provider combination.
- Source refinement adds 1 LLM call (~2 seconds) per deep-mode topic-provider combination.
- Standard-mode topics: no performance change.
- Total deep-mode overhead estimate: (rounds * ~15s + ~4s expansion + ~4s refinement) per topic. With 3 rounds, ~50-60 seconds per topic (vs ~15-20s currently).

### 10.2 Security

- No new external attack surface. CLI runner reads local config only.
- Query expansion prompts use topic config values (operator-controlled, not user-controlled). No injection risk.
- Refinement prompts consume research text from trusted LLM/API outputs. No additional OWASP concerns beyond existing SSRF protections in link verification.
- CLI runner does NOT accept command-line arguments that could be used for path traversal or injection.

### 10.3 Scalability & Availability

- Multi-round research increases API call volume by up to 5x per deep-mode topic. Operators should consider API rate limits and quotas.
- No change to horizontal scaling strategy (stateless pipeline per execution).

### 10.4 Accessibility

N/A -- no UI changes.

### 10.5 Observability

- **Logging**: Each research round SHALL log: `"[DeepResearch] Topic {name}/{provider} round {N}: {query_snippet}..."` at INFO level.
- **Logging**: RoundAccumulator SHALL log: `"[DeepResearch] Topic {name}/{provider} round {N}: {X} new URLs, {Y} total accumulated"` at INFO level.
- **Logging**: Early exit SHALL log: `"[DeepResearch] Topic {name}/{provider}: early exit at round {N} with {Y} URLs (threshold: 15)"` at INFO level.
- **Logging**: Refinement SHALL log: `"[Refinement] Topic {name}/{provider}: {before} -> {after} sources"` at INFO level.
- **Logging**: CLI runner SHALL log: `"[CLI] Pipeline starting..."` and `"[CLI] Pipeline completed in {seconds}s"` at INFO level.

---

## 11. Test Requirements

### 11.1 Unit Tests

**CLI runner** (`tests/unit/test_cli_runner.py`):
- Test that `__main__.py` module exists and is importable
- Test `main()` function creates Runner, sends trigger message, returns results
- Test exit code 0 on success (mock pipeline)
- Test exit code 1 on exception (mock pipeline to raise)
- Test summary JSON output format on success
- Test summary JSON output format on failure

**Config field** (`tests/unit/test_config_models.py` -- extend existing):
- Test `max_research_rounds` default is 3
- Test `max_research_rounds` accepts valid values (1, 2, 3, 4, 5)
- Test `max_research_rounds` rejects 0 (below min)
- Test `max_research_rounds` rejects 6 (above max)
- Test `max_research_rounds` rejects non-integer

**QueryExpanderAgent** (mocked LLM):
- Test generates correct number of variants
- Test fallback on invalid LLM JSON output
- Test state key written correctly

**DeepResearchOrchestrator**:
- Test invokes QueryExpanderAgent sub-agent for query expansion
- Test executes correct number of rounds (respects max_research_rounds)
- Test round 0 uses original query
- Test subsequent rounds use expanded query variants
- Test URL extraction from round output
- Test deduplication across rounds
- Test early exit at 15+ URLs (break)
- Test graceful handling of empty round output
- Test merges multiple rounds into single output
- Test URL deduplication in SOURCES section
- Test cleanup of intermediate state keys
- Test handles zero round outputs

**DeepResearchRefinerAgent**:
- Test no-op for standard-mode topics
- Test selects 5-10 sources when pool > 10 (mocked LLM)
- Test keeps all sources when pool < 5
- Test keeps all sources on LLM failure
- Test keeps all sources on invalid LLM JSON
- Test state key updated in-place
- Test log output for source counts

**Pipeline order** (extend `tests/unit/test_agent_factory.py`):
- Test DeepResearchRefiner at position [5] in pipeline sub_agents
- Test deep-mode topic produces DeepResearchOrchestrator (BaseAgent) in research phase
- Test standard-mode topic produces single LlmAgent in research phase

Minimum coverage: 80% code, 90% branch.

### 11.2 BDD / Acceptance Tests

```gherkin
Feature: Autonomous CLI Execution

  Scenario: Successful pipeline run via CLI
    Given valid config with dry_run true
    And all environment variables are set
    When python -m newsletter_agent is executed
    Then the pipeline runs to completion
    And an HTML file is saved to output/
    And a JSON summary is printed with status "success"
    And the process exits with code 0

  Scenario: CLI handles config error
    Given config with missing required field
    When python -m newsletter_agent is executed
    Then a config error is logged
    And the process exits with code 1

  Scenario: CLI handles pipeline failure
    Given valid config
    And all research providers are mocked to fail
    When python -m newsletter_agent is executed
    Then a pipeline error is logged
    And the process exits with code 1

Feature: Multi-Round Deep Research

  Scenario: Deep mode executes multiple research rounds
    Given a topic with search_depth "deep"
    And max_research_rounds is 3
    When the research phase runs
    Then 3 search rounds are executed per provider
    And each round uses a different query angle
    And results are combined into the standard research state key

  Scenario: Early exit when enough URLs collected
    Given a topic with search_depth "deep"
    And max_research_rounds is 3
    And round 2 accumulates 15+ unique URLs
    When the research phase runs
    Then only 2 search rounds execute
    And the loop exits early via escalation

  Scenario: Standard mode is unaffected
    Given a topic with search_depth "standard"
    And max_research_rounds is 3
    When the research phase runs
    Then exactly 1 search round executes per provider
    And no query expansion occurs

  Scenario: max_research_rounds of 1 is single-round
    Given a topic with search_depth "deep"
    And max_research_rounds is 1
    When the research phase runs
    Then exactly 1 search round executes per provider
    And no query expansion occurs

Feature: Deep Research Source Refinement

  Scenario: Sources refined to 5-10 per provider
    Given a deep-mode topic with 20 verified Google sources
    When the refinement agent runs
    Then between 5 and 10 Google sources remain

  Scenario: Few sources kept without filtering
    Given a deep-mode topic with 3 verified sources
    When the refinement agent runs
    Then all 3 sources are kept

  Scenario: Refinement no-op for standard mode
    Given a standard-mode topic with 5 sources
    When the refinement agent runs
    Then all 5 sources remain unchanged

  Scenario: Refinement graceful degradation on LLM failure
    Given a deep-mode topic with 20 verified sources
    And the refinement LLM call fails
    When the refinement agent runs
    Then all 20 sources are kept
    And a warning is logged
```

### 11.3 Integration Tests

- Test multi-round research with mocked Google Search and Perplexity tools: verify that N rounds produce accumulated results in correct state keys.
- Test pipeline with mixed topics (some standard, some deep): verify standard topics unaffected.
- Test CLI runner end-to-end with mocked search tools: verify complete pipeline execution and exit code.

### 11.4 End-to-End Tests

- Test full pipeline with `dry_run: true` and deep-mode topics: verify HTML output contains sources from multiple research rounds.
- Test CLI runner in subprocess: `subprocess.run(["python", "-m", "newsletter_agent"])` and verify exit code and output file.

### 11.5 Performance Tests

- Benchmark deep-mode research time: measure per-round latency with real API calls.
- Verify total pipeline time with 3 deep-mode topics stays under 5 minutes.

### 11.6 Security Tests

- Verify CLI runner does not accept arbitrary command-line arguments.
- Verify query expansion prompt does not leak system instructions.
- Existing SSRF tests continue to pass.

---

## 12. Constraints & Assumptions

### Constraints

- Google ADK `BaseAgent` custom agent pattern is available in `google-adk >= 1.0.0` (verified from ADK docs).
- `google_search` grounding tool is only accessible via LlmAgent; cannot be called directly from BaseAgent.
- Perplexity `search_perplexity` function CAN be called directly from BaseAgent.
- ADK's Runner API requires a `new_message` parameter; the CLI runner must provide one (synthetic trigger).
- `tool_context.actions.escalate` is only available in LlmAgent tool functions, not from BaseAgent (OQ-2 resolution).
- `output_key` on LlmAgent is fixed at construction time, cannot change per iteration (OQ-1 resolution).

### Assumptions

- **A1**: ADK `BaseAgent` sub-agents can be invoked via `async for event in sub_agent.run_async(ctx)` within `_run_async_impl` (verified from ADK custom agent docs / StoryFlowAgent pattern).
- **A2**: Sub-agent LlmAgent `output_key` writes to session state accessible by the parent BaseAgent after the sub-agent run completes.
- **A3**: The `gemini-2.5-flash` model can reliably generate JSON query variant arrays from the query expansion prompt. Fallback logic is specified for failure cases.
- **A4**: Query expansion adds negligible latency (~2s) relative to actual search rounds (~15s each).
- **A5**: Multiple `DeepResearchOrchestrator` instances can run in parallel within the `ParallelAgent` research phase without state key conflicts (each uses unique `{idx}_{provider}` suffixes).

---

## 13. Out of Scope

- **Per-topic max_research_rounds**: The config field is global (in `settings`), not per-topic. Per-topic override could be added later.
- **Parallel research rounds**: Rounds execute sequentially to allow gap analysis between rounds. Parallel rounds would lose the iterative refinement benefit.
- **Cross-provider source deduplication**: Refinement selects per-provider. Cross-provider dedup before synthesis is not included.
- **CLI arguments**: No `--dry-run`, `--config`, or other CLI flags. All config comes from `topics.yaml` and environment variables.
- **Streaming output**: CLI prints final summary only, not streaming events.
- **Changes to standard mode**: Standard-mode research behavior is completely unchanged.

---

## 14. Open Questions

| # | Question | Resolution | Owner |
|---|----------|-----------|-------|
| OQ-1 | Does ADK's `LoopAgent` support dynamic `output_key` per iteration, or does each sub-agent need a fixed output_key? | **RESOLVED**: Confirmed `output_key` is fixed at LlmAgent construction time. However, this is now moot -- the DeepResearchOrchestrator (custom BaseAgent) reads state directly after each sub-agent call, so no output_key workaround is needed. | Planner |
| OQ-2 | Can a BaseAgent inside a LoopAgent trigger escalation via the event system, or must it use a tool with `tool_context.actions.escalate`? | **RESOLVED**: `tool_context.actions.escalate` is only available inside LlmAgent tool functions, not from BaseAgent's `_run_async_impl`. Resolution: replaced LoopAgent + RoundAccumulator + ResearchCombiner with a single `DeepResearchOrchestrator` (custom BaseAgent) that uses Python `break` for early exit. Follows ADK's documented StoryFlowAgent pattern for custom agents. | Planner |

---

## 15. Glossary

| Term | Definition |
|------|-----------|
| Deep mode | Research configuration where `search_depth: "deep"` for a topic, triggering multi-round research and source refinement |
| Standard mode | Default research configuration (`search_depth: "standard"`), single-round search per provider |
| Research round | A single execution of a search query against one provider (Google or Perplexity) |
| Query expansion | LLM-driven generation of alternative search queries from the original query |
| Source refinement | LLM-driven selection of the most relevant sources from a larger pool |
| Escalation | ADK mechanism for a sub-agent to signal that its parent workflow agent (LoopAgent) should stop iterating |
| RoundAccumulator | Custom BaseAgent that tracks URL accumulation across research rounds and manages loop state |
| ResearchCombiner | Custom BaseAgent that merges multi-round research outputs into the standard state key format |

---

## 16. Traceability Matrix

| FR ID | Requirement Summary | User Story | Acceptance Scenario | Test Type | Test Section Ref |
|-------|-------------------|------------|--------------------|-----------|-================|
| FR-CLI-001 | CLI __main__.py module | US-01 | Scenario 1 | unit, BDD | 11.1, 11.2 |
| FR-CLI-002 | CLI uses ADK Runner programmatically | US-01 | Scenario 1 | unit, integration | 11.1, 11.3 |
| FR-CLI-003 | CLI logs to stdout | US-01 | Scenario 1 | unit | 11.1 |
| FR-CLI-004 | CLI exit codes 0/1 | US-01 | Scenario 1, 3, 4 | unit, BDD | 11.1, 11.2 |
| FR-CLI-005 | CLI prints JSON summary | US-01 | Scenario 2 | unit, BDD | 11.1, 11.2 |
| FR-CLI-006 | Existing entry points unchanged | US-01 | Scenario 1 | integration | 11.3 |
| FR-CFG-001 | max_research_rounds config field | US-03 | Scenario 1, 2, 3 | unit | 11.1 |
| FR-CFG-002 | Default value 3 | US-03 | Scenario 3 | unit | 11.1 |
| FR-CFG-003 | Validation 1-5 | US-03 | Scenario 2 | unit | 11.1 |
| FR-CFG-004 | Only affects deep mode | US-02, US-03 | US-02 Scenario 3 | unit, BDD | 11.1, 11.2 |
| FR-MRR-001 | DeepResearchOrchestrator for multi-round search | US-02 | Scenario 1 | unit, BDD | 11.1, 11.2 |
| FR-MRR-002 | First round uses original query | US-02 | Scenario 1 | unit | 11.1 |
| FR-MRR-003 | Subsequent rounds use variants | US-02 | Scenario 1 | unit | 11.1 |
| FR-MRR-004 | Query expansion generates N-1 variants | US-02 | Scenario 1 | unit | 11.1 |
| FR-MRR-005 | Round-specific state keys | US-02 | Scenario 1 | unit | 11.1 |
| FR-MRR-006 | Combiner merges rounds | US-02 | Scenario 1 | unit | 11.1 |
| FR-MRR-007 | Early exit at 15+ URLs | US-02 | Scenario 2 | unit, BDD | 11.1, 11.2 |
| FR-MRR-008 | Standard mode unchanged | US-02 | Scenario 3 | unit, BDD | 11.1, 11.2 |
| FR-MRR-009 | Google round prompt | US-02 | Scenario 1 | unit | 11.1 |
| FR-MRR-010 | Perplexity round prompt | US-02 | Scenario 1 | unit | 11.1 |
| FR-MRR-011 | Query expansion uses flash model | US-02 | Scenario 1 | unit | 11.1 |
| FR-REF-001 | Refiner in pipeline | US-04 | Scenario 1 | unit | 11.1 |
| FR-REF-002 | Evaluates and selects 5-10 per provider | US-04 | Scenario 1 | unit, BDD | 11.1, 11.2 |
| FR-REF-003 | LLM-based relevance evaluation | US-04 | Scenario 1 | unit | 11.1 |
| FR-REF-004 | Updates state in-place | US-04 | Scenario 1 | unit | 11.1 |
| FR-REF-005 | 5-10 target, keep all if < 5 | US-04 | Scenario 1, 2 | unit, BDD | 11.1, 11.2 |
| FR-REF-006 | No-op for standard mode | US-04 | Scenario 3 | unit, BDD | 11.1, 11.2 |
| FR-REF-007 | Logs before/after counts | US-04 | Scenario 1 | unit | 11.1 |
| FR-PIP-001 | Pipeline order with refiner | US-04 | Scenario 1 | unit | 11.1 |
| FR-PIP-002 | Refiner after verifier, before synthesizer | US-04 | Scenario 1 | unit | 11.1 |
| FR-PIP-003 | Conditional research build | US-02 | Scenario 1, 3 | unit | 11.1 |
| FR-BC-001 | Standard mode identical | US-02 | Scenario 3 | BDD | 11.2 |
| FR-BC-002 | max_rounds=1 identical | US-02 | Scenario 4 | BDD | 11.2 |
| FR-BC-003 | Existing entry points work | US-01 | Scenario 1 | integration | 11.3 |
| FR-BC-004 | State key format unchanged | US-02, US-04 | Scenario 1, 3 | integration | 11.3 |

---

## 17. Technical References

### Architecture & Patterns
- Google ADK Custom Agents documentation (BaseAgent pattern, StoryFlowAgent example), https://google.github.io/adk-docs/agents/custom-agents/, consulted 2026-03-15
- Google ADK LoopAgent documentation (reviewed for OQ analysis, superseded by custom agent approach), https://google.github.io/adk-docs/agents/workflow-agents/loop-agents/, consulted 2026-03-15
- Google ADK Agents overview (agent types: LlmAgent, SequentialAgent, ParallelAgent, LoopAgent, BaseAgent), https://google.github.io/adk-docs/agents/, consulted 2026-03-15

### Technology Stack
- Google ADK Python SDK, google-adk >= 1.0.0, https://github.com/google/adk-python
- Gemini 2.5 Flash model for research and query expansion
- Gemini 2.5 Pro model for synthesis

### Standards & Specifications
- ADK BaseAgent sub-agent invocation pattern: `async for event in sub_agent.run_async(ctx)` for orchestrating LlmAgent calls from custom BaseAgent

---

## 18. Version History

| Version | Date | Author | Summary of Changes |
|---------|------|--------|--------------------|
| 1.0 | 2026-03-15 | Spec Architect | Initial specification |
| 1.0.1 | 2026-03-15 | Spec Architect | Self-review corrections: added error behaviors for query expansion fallback, clamping of refinement selection count, explicit escalation mechanism notes in OQ-2 |
| 1.1 | 2026-03-15 | Planner | OQ-1/OQ-2 resolution: replaced LoopAgent + RoundAccumulator + ResearchCombiner with single DeepResearchOrchestrator (custom BaseAgent). Updated FR-MRR-001/005/007, Sections 8.3, 9.1, 9.2, 9.3, 9.4, 12, 14. |
