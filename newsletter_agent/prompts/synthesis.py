"""
Synthesis agent instruction prompt templates.

Provides per-topic synthesis prompts for the PerTopicSynthesizerAgent.

Spec refs: FR-016, FR-017, FR-018, FR-019, FR-020.
"""


def get_synthesis_instruction(topic_names: list[str], topic_count: int) -> str:
    """Generate static instruction prompt for the synthesis agent (legacy).

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


def build_synthesis_instruction_fn(
    topic_names: list[str],
    providers: list[str],
):
    """Return a callable(ctx) that injects research data into the synthesis prompt.

    The returned function reads ``research_{idx}_{provider}`` keys from
    ``ctx.state`` and embeds their contents directly in the system prompt.
    This guarantees the synthesis model receives the data regardless of
    how the ADK forwards conversation events across model backends.

    Args:
        topic_names: Ordered list of topic names.
        providers: List of provider keys (e.g. ``["google", "perplexity"]``).

    Returns:
        A callable suitable for the ``instruction`` parameter of an LlmAgent.
    """
    topic_count = len(topic_names)

    def _instruction(ctx) -> str:
        # Gather research data from state for each topic/provider
        research_blocks: list[str] = []
        for idx, name in enumerate(topic_names):
            parts: list[str] = []
            for prov in providers:
                key = f"research_{idx}_{prov}"
                data = ctx.state.get(key)
                if data and isinstance(data, str) and data.strip():
                    parts.append(f"--- {prov.upper()} research for \"{name}\" ---\n{data}")
            if parts:
                research_blocks.append("\n\n".join(parts))
            else:
                research_blocks.append(
                    f"--- No research data available for \"{name}\" ---"
                )

        research_section = "\n\n".join(research_blocks)

        topic_list = "\n".join(
            f"  - Topic {i}: \"{name}\""
            for i, name in enumerate(topic_names)
        )

        return _INSTRUCTION_WITH_DATA.format(
            topic_count=topic_count,
            topic_list=topic_list,
            research_data=research_section,
        )

    return _instruction


def build_per_topic_prompt(topic_name: str, research_data: str) -> str:
    """Build a synthesis prompt for a single topic.

    Args:
        topic_name: Name of the topic to synthesize.
        research_data: Combined research text for this topic from all providers.

    Returns:
        Complete prompt string for a single-topic synthesis call.
    """
    return _PER_TOPIC_INSTRUCTION.format(
        topic_name=topic_name,
        research_data=research_data,
    )


_INSTRUCTION = """You are a senior analyst tasked with synthesizing research findings into deep, insightful newsletter sections.

AVAILABLE RESEARCH DATA:
You have access to research results stored in session state for {topic_count} topics:
{topic_list}

Each state key contains research text with source URLs from either Google Search or Perplexity.

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
3. Include as many inline citations as possible using [Title](URL) format - aim for at least 5 per section.
   Every significant claim, statistic, or quote MUST have an inline citation. Not citing a source when one is available is a failure.
4. NEVER fabricate facts, statistics, quotes, or URLs not present in the research data.
5. Use ONLY source URLs that appear in the research results. Include ALL relevant sources - do not drop sources that provide supporting evidence.
6. The executive_summary must have exactly one entry per topic with a 1-3 sentence overview.
7. Sections must appear in the same order as the topics listed above.
8. If research data for a topic is missing or contains errors, note this in the section body and provide whatever analysis is possible from available data.
9. The "sources" list for each section MUST include every source URL cited in body_markdown plus any additional relevant sources from the research data.
   Aim to include ALL unique source URLs from the research data for that topic.

OUTPUT:
Respond with ONLY the JSON object. No additional text before or after."""


_INSTRUCTION_WITH_DATA = """You are a senior analyst tasked with synthesizing research findings into deep, insightful newsletter sections.

TOPICS ({topic_count} total):
{topic_list}

RESEARCH DATA (use ONLY information and URLs from this data):
{research_data}

YOUR TASK:
Produce a JSON object with the following EXACT structure:

{{{{
  "executive_summary": [
    {{{{"topic": "Topic Name", "summary": "1-3 sentence overview of key findings."}}}}
  ],
  "sections": [
    {{{{
      "title": "Topic Name",
      "body_markdown": "Multi-paragraph deep analysis text with [Source Title](URL) inline citations...",
      "sources": [{{{{"url": "https://...", "title": "Source Title"}}}}]
    }}}}
  ]
}}}}

REQUIREMENTS:
1. Each section's body_markdown MUST be at least 200 words of deep analysis.
2. Cross-reference findings from multiple sources when available.
3. Include as many inline citations as possible using [Title](URL) format - aim for at least 5 per section.
   Every significant claim, statistic, or quote MUST have an inline citation. Not citing a source when one is available is a failure.
4. NEVER fabricate facts, statistics, quotes, or URLs not present in the research data above.
5. Use ONLY source URLs that appear in the research data above. Include ALL relevant sources - do not drop sources that provide supporting evidence.
6. The executive_summary must have exactly one entry per topic with a 1-3 sentence overview.
7. Sections must appear in the same order as the topics listed above.
8. If research data for a topic is missing or contains errors, note this in the section body and provide whatever analysis is possible from available data.
9. The "sources" list for each section MUST include every source URL cited in body_markdown plus any additional relevant sources from the research data.
   Aim to include ALL unique source URLs from the research data for that topic.

OUTPUT:
Respond with ONLY the JSON object. No additional text before or after."""


_PER_TOPIC_INSTRUCTION = """You are a senior analyst synthesizing research into a newsletter section for ONE topic.

TOPIC: {topic_name}

RESEARCH DATA (use ONLY information and URLs from this data):
{research_data}

YOUR TASK:
Produce a JSON object with the following EXACT structure:

{{{{
  "executive_summary": "1-3 sentence overview of key findings for this topic.",
  "section": {{{{
    "title": "{topic_name}",
    "body_markdown": "Multi-paragraph deep analysis text with [Source Title](URL) inline citations...",
    "sources": [{{{{ "url": "https://...", "title": "Source Title" }}}}]
  }}}}
}}}}

REQUIREMENTS:
1. body_markdown MUST be at least 200 words of deep analysis.
2. Cross-reference findings from multiple sources when available.
3. Include as many inline citations as possible using [Title](URL) format - aim for at least 5.
   Every significant claim, statistic, or quote MUST have an inline citation.
4. NEVER fabricate facts, statistics, quotes, or URLs not present in the research data above.
5. Use ONLY source URLs that appear in the research data above. Include ALL relevant sources.
6. If research data is missing or contains errors, note this in body_markdown and provide whatever analysis is possible.
7. The "sources" list MUST include every source URL cited in body_markdown plus any additional relevant sources.

OUTPUT:
Respond with ONLY the JSON object. No additional text before or after."""
