# Adaptive Reasoning-Based Deep Research

## Problem

The current deep research implementation uses a **pre-generated fan-out** approach:
1. Query expansion generates N variant queries upfront (one LLM call)
2. Each round executes a predetermined query independently
3. No analysis of previous results informs the next search
4. Exit criteria is a simple URL count threshold (15 unique URLs)

This leads to:
- **Inconsistent result volume**: no adaptation when a round returns few/no results
- **No knowledge gap detection**: the system cannot identify what is missing
- **No reasoning between rounds**: queries are fixed before any search happens
- **Shallow coverage**: variant queries may overlap or miss critical angles

## Desired Behavior

Replace the current fan-out approach with an **adaptive reasoning loop** that mirrors how a human researcher works:

1. **Interpret** the original query - understand what the user wants to learn
2. **Plan** an initial search strategy with reasoning about what to look for
3. **Search** using the planned query
4. **Analyze** the results - what was found? what gaps remain? what new angles emerged?
5. **Reason** about the next search - refine the query based on gaps, or explore a new angle
6. **Repeat** steps 3-5 until knowledge saturation or max rounds reached
7. **Synthesize** all findings into a coherent research output

### Key Design Goals

- Each search round should be **informed by previous results** (adaptive, not predetermined)
- There should be explicit **reasoning steps** between searches (visible in logs)
- The system should detect **knowledge saturation** (diminishing returns) and stop early
- Configurable limits: max reasoning rounds (x) and max search calls (y)
- The reasoning agent should be able to decide: "I need to search for X because the previous results didn't cover Y"
- Results should be more consistent in quality and depth across runs

## Constraints

- Must work within Google ADK's BaseAgent/LlmAgent framework
- Must maintain the existing state key contract (`research_{idx}_{provider}`)
- Must work with both Google Search grounding and Perplexity providers
- Must preserve backward compatibility with standard (non-deep) research mode
- Pipeline timeout budget: deep research phase should complete within ~3-5 minutes per topic
- Must remain compatible with the existing ParallelAgent topology (topics run in parallel)

## Context

- Current implementation: `newsletter_agent/tools/deep_research.py` (DeepResearchOrchestrator)
- Query expansion: `newsletter_agent/prompts/query_expansion.py`
- Search instructions: `newsletter_agent/prompts/research_google.py`, `research_perplexity.py`
- Config: `max_research_rounds` in topics.yaml settings (currently 1-5, default 3)
- Existing spec: `specs/autonomous-deep-research.spec.md` (this is an addendum to that spec)
