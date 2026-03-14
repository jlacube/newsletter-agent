"""
Newsletter Agent - root agent and research phase factory.

Spec refs: Section 9.1, FR-008 through FR-014.
"""

import logging

from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent
from google.adk.tools import google_search

from newsletter_agent.config.schema import NewsletterConfig, load_config
from newsletter_agent.prompts.research_google import get_google_search_instruction
from newsletter_agent.prompts.research_perplexity import get_perplexity_search_instruction
from newsletter_agent.tools.perplexity_search import perplexity_search_tool

logger = logging.getLogger(__name__)

_RESEARCH_MODEL = "gemini-2.5-flash"


def build_research_phase(config: NewsletterConfig) -> ParallelAgent:
    """Build the research phase ParallelAgent from config.

    Creates one SequentialAgent per topic, each containing LlmAgents
    for the configured search providers. All topic agents run in parallel.
    """
    topic_agents = []

    for idx, topic in enumerate(config.topics):
        sub_agents = []

        if "google_search" in topic.sources:
            google_agent = LlmAgent(
                name=f"GoogleSearcher_{idx}",
                model=_RESEARCH_MODEL,
                instruction=get_google_search_instruction(
                    topic.name, topic.query, topic.search_depth
                ),
                tools=[google_search],
                output_key=f"research_{idx}_google",
            )
            sub_agents.append(google_agent)

        if "perplexity" in topic.sources:
            perplexity_agent = LlmAgent(
                name=f"PerplexitySearcher_{idx}",
                model=_RESEARCH_MODEL,
                instruction=get_perplexity_search_instruction(
                    topic.name, topic.query, topic.search_depth
                ),
                tools=[perplexity_search_tool],
                output_key=f"research_{idx}_perplexity",
            )
            sub_agents.append(perplexity_agent)

        if sub_agents:
            topic_pipeline = SequentialAgent(
                name=f"Topic{idx}Research",
                sub_agents=sub_agents,
            )
            topic_agents.append(topic_pipeline)

    logger.info(
        "Built research phase: %d topics, %d total agents",
        len(config.topics),
        sum(len(ta.sub_agents) for ta in topic_agents),
    )

    return ParallelAgent(name="ResearchPhase", sub_agents=topic_agents)


# ---------------------------------------------------------------------------
# Build root agent at module level (Option 3 from WP02 plan)
# ---------------------------------------------------------------------------

try:
    _config = load_config()
    _research_phase = build_research_phase(_config)
    root_agent = SequentialAgent(
        name="newsletter_agent",
        sub_agents=[_research_phase],
    )
except Exception:
    logger.warning("Config not loaded; using stub agent")
    root_agent = LlmAgent(
        name="newsletter_agent",
        model="gemini-2.5-flash",
        instruction="You are the Newsletter Agent. The pipeline is not yet wired.",
    )

