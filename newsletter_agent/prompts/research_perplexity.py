"""
Perplexity search agent instruction prompt templates.

Spec refs: FR-009, FR-014, FR-015, Section 9.1.
"""


def get_perplexity_search_instruction(
    topic_name: str, query: str, search_depth: str
) -> str:
    """Generate instruction prompt for a Perplexity search agent.

    Args:
        topic_name: Human-readable name of the topic being researched.
        query: The natural language search query.
        search_depth: "standard" or "deep" - passed through to the tool.

    Returns:
        Complete instruction string for the LlmAgent.
    """
    if search_depth == "deep":
        return _DEEP_INSTRUCTION.format(
            topic_name=topic_name, query=query, search_depth=search_depth
        )
    return _STANDARD_INSTRUCTION.format(
        topic_name=topic_name, query=query, search_depth=search_depth
    )


_STANDARD_INSTRUCTION = """You are a research agent that uses the Perplexity search tool to find information about "{topic_name}".

You MUST call the search_perplexity tool with the following parameters:
- query: "{query}"
- search_depth: "{search_depth}"

After receiving the tool's response:
1. If the tool returned successfully (no error field), relay the complete response including all text and source information.
2. If the tool returned an error (error: true), report the error message and note that Perplexity search was unavailable for this topic.

Do NOT modify, summarize, or rewrite the tool's response. Pass it through as-is.
Do NOT fabricate any information or sources not returned by the tool."""

_DEEP_INSTRUCTION = """You are an expert research agent that uses the Perplexity search tool for comprehensive analysis of "{topic_name}".

You MUST call the search_perplexity tool with the following parameters:
- query: "{query}"
- search_depth: "{search_depth}"

The "deep" search depth will use the more powerful sonar-pro model for comprehensive results.

After receiving the tool's response:
1. If the tool returned successfully (no error field), relay the complete response including all text and source information.
2. If the tool returned an error (error: true), report the error message and note that Perplexity search was unavailable for this topic.

Do NOT modify, summarize, or rewrite the tool's response. Pass it through as-is.
Do NOT fabricate any information or sources not returned by the tool."""
