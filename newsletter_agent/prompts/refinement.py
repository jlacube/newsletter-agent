"""
Source refinement prompt template for deep research.

Instructs the LLM to evaluate and select the most relevant sources
from a large pool after multi-round deep research.

Spec refs: FR-REF-003, Section 4.4 (Refinement LLM prompt contract).
"""


def get_refinement_instruction(
    topic_name: str,
    target_count: int,
    research_text: str,
    source_list: str,
) -> str:
    """Return the source refinement instruction for an LLM evaluation call.

    Args:
        topic_name: Human-readable name of the topic being refined.
        target_count: Target number of sources to select (5-10).
        research_text: The full research text (SUMMARY section).
        source_list: The current sources in markdown link format.

    Returns:
        Complete prompt string for the LLM refinement call.
    """
    return _TEMPLATE.format(
        topic_name=topic_name,
        target_count=target_count,
        research_text=research_text,
        source_list=source_list,
    )


_TEMPLATE = """You are a research source curator. Given the following research text and sources \
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

Select between 5 and 10 sources. If fewer than 5 sources are available, keep all."""
