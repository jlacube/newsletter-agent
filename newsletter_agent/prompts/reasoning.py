"""Prompt templates for adaptive deep research reasoning agents.

Contains instruction generators for the PlanningAgent and AnalysisAgent
used in the adaptive research loop.

Spec refs: FR-ADR-070, Section 4.2, Section 4.4.
"""


def get_planning_instruction(query: str, topic_name: str) -> str:
    """Return the PlanningAgent instruction for a given topic and query.

    Args:
        query: The original research query.
        topic_name: Human-readable name of the topic.

    Returns:
        Complete instruction string for the PlanningAgent LlmAgent.
    """
    return _PLANNING_TEMPLATE.format(query=query, topic_name=topic_name)


def get_analysis_instruction(
    topic_name: str,
    query: str,
    key_aspects: list[str],
    prior_rounds_summary: str,
    latest_results: str,
    round_idx: int,
    current_query: str,
    remaining_searches: int,
) -> str:
    """Return the AnalysisAgent instruction with full research context.

    Args:
        topic_name: Human-readable name of the topic.
        query: The original research query.
        key_aspects: List of distinct investigation angles from PlanningAgent.
        prior_rounds_summary: Pre-formatted summary of prior research rounds.
        latest_results: Full search results from the latest round.
        round_idx: Current round number (0-based).
        current_query: The search query used for the latest round.
        remaining_searches: Number of search budget remaining.

    Returns:
        Complete instruction string for the AnalysisAgent LlmAgent.
    """
    key_aspects_formatted = "\n".join(f"- {a}" for a in key_aspects)
    return _ANALYSIS_TEMPLATE.format(
        topic_name=topic_name,
        query=query,
        key_aspects_formatted=key_aspects_formatted,
        prior_rounds_summary=prior_rounds_summary,
        latest_results=latest_results,
        round_idx=round_idx,
        current_query=current_query,
        remaining_searches=remaining_searches,
    )


_PLANNING_TEMPLATE = """You are a research strategist. Analyze the following research query and plan \
a systematic search strategy.

Topic: {topic_name}
Query: {query}

Your task:
1. Understand the core intent of this research query.
2. Identify 3-5 distinct aspects or angles that a thorough investigation should cover.
3. Determine the single best initial search query to start with.

Produce a JSON object with exactly these fields:
- "query_intent": one sentence describing what the user wants to learn
- "key_aspects": list of 3-5 distinct aspects to investigate (strings)
- "initial_search_query": the first search query to execute (string)
- "search_rationale": one sentence explaining why this query is the best starting point

Output ONLY the JSON object. No other text."""


_ANALYSIS_TEMPLATE = """You are a research analyst evaluating search results for the topic "{topic_name}".

Original research goal: {query}

Key aspects to cover:
{key_aspects_formatted}

Research accumulated so far (prior rounds):
{prior_rounds_summary}

Latest search results (Round {round_idx}, query: "{current_query}"):
{latest_results}

Remaining search budget: {remaining_searches} searches

Your task:
1. Summarize the key NEW information found in the latest search results.
2. Compare what has been found against the key aspects. What gaps remain?
3. Assess whether further searching would add meaningful new information.
4. If not saturated, suggest the single most important next search query to fill the largest gap.

Produce a JSON object with exactly these fields:
- "findings_summary": brief summary of new findings from this round (string)
- "knowledge_gaps": list of remaining gaps or unanswered questions (0-5 strings, empty list if none)
- "coverage_assessment": one sentence describing current coverage completeness (string)
- "saturated": true if further searching would yield diminishing returns, false otherwise (boolean)
- "next_query": the next search query to fill the most important gap, or null if saturated (string or null)
- "next_query_rationale": why this query addresses the most critical gap, or null if saturated (string or null)

Saturation guidelines:
- Set saturated=true if: all key aspects are well-covered, OR the latest round added no significant new information, OR remaining gaps are too narrow for web search to resolve.
- Set saturated=false if: major aspects remain uncovered, OR important contradictions need resolution, OR key data points are missing.

Output ONLY the JSON object. No other text."""
