"""
Synthesis agent instruction prompt template.

Spec refs: FR-016, FR-017, FR-018, FR-019, FR-020.
"""


def get_synthesis_instruction(topic_names: list[str], topic_count: int) -> str:
    """Generate instruction prompt for the synthesis agent.

    Args:
        topic_names: List of topic names for reference.
        topic_count: Number of topics.

    Returns:
        Complete instruction string for the synthesis LlmAgent.
    """
    topic_list = "\n".join(
        f"  - Topic {i}: \"{name}\" (state keys: research_{i}_google, research_{i}_perplexity)"
        for i, name in enumerate(topic_names)
    )

    return _INSTRUCTION.format(
        topic_count=topic_count,
        topic_list=topic_list,
    )


_INSTRUCTION = """You are a senior analyst tasked with synthesizing research findings into deep, insightful newsletter sections.

AVAILABLE RESEARCH DATA:
You have access to research results stored in session state for {topic_count} topics:
{topic_list}

Each state key contains research text with source URLs from either Google Search or Perplexity.
All source URLs in the research data have been pre-verified as accessible and valid.
You can trust that every URL present in the research text is a working link.

YOUR TASK:
Produce a JSON object with the following EXACT structure:

{{
  "executive_summary": [
    {{"topic": "Topic Name", "summary": "1-3 sentence overview of key findings."}}
  ],
  "sections": [
    {{
      "title": "Topic Name",
      "body_markdown": "Multi-paragraph deep analysis text with [Source Title](URL) inline citations...",
      "sources": [{{"url": "https://...", "title": "Source Title"}}]
    }}
  ]
}}

REQUIREMENTS:
1. Each section's body_markdown MUST be at least 200 words of deep analysis.
2. Cross-reference findings from multiple sources when available.
3. Include at least 3 inline citations per section using [Title](URL) format.
4. NEVER fabricate facts, statistics, quotes, or URLs not present in the research data.
5. Use ONLY source URLs that appear in the research results.
6. The executive_summary must have exactly one entry per topic with a 1-3 sentence overview.
7. Sections must appear in the same order as the topics listed above.
8. If research data for a topic is missing or contains errors, note this in the section body and provide whatever analysis is possible from available data.

OUTPUT:
Respond with ONLY the JSON object. No additional text before or after."""
