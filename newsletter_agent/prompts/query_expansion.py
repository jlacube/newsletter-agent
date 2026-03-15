"""
DEPRECATED: This module is superseded by newsletter_agent.prompts.reasoning.
The adaptive research loop (spec 002) generates queries per-round via the
AnalysisAgent instead of upfront expansion. This module is retained for
backward compatibility.

Original purpose: Query expansion prompt template for multi-round deep research.
Generates alternative search queries exploring different angles of a topic.

Spec refs: FR-MRR-003, FR-MRR-004, Section 4.3 (QueryExpanderAgent instruction contract).
"""


def get_query_expansion_instruction(
    query: str, topic_name: str, variant_count: int
) -> str:
    """Return the query expansion instruction for a QueryExpanderAgent.

    Args:
        query: The original research query.
        topic_name: Human-readable name of the topic.
        variant_count: Number of alternative queries to generate.

    Returns:
        Complete instruction string for the LlmAgent.
    """
    return _TEMPLATE.format(
        query=query,
        topic_name=topic_name,
        variant_count=variant_count,
    )


_TEMPLATE = """You are a research query strategist. Given the original research query below, \
generate exactly {variant_count} alternative search queries that explore DIFFERENT angles \
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
Example: ["query variant 1", "query variant 2", "query variant 3"]"""
