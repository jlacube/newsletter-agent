"""
Newsletter Agent - root agent, research phase, synthesis, and formatting.

Spec refs: Section 9.1, FR-008 through FR-035.
"""

import logging

from newsletter_agent.logging_config import setup_logging

setup_logging()

from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent
from google.adk.tools import google_search

from newsletter_agent.config.schema import NewsletterConfig, load_config
from newsletter_agent.prompts.research_google import get_google_search_instruction
from newsletter_agent.prompts.research_perplexity import get_perplexity_search_instruction
from newsletter_agent.prompts.synthesis import get_synthesis_instruction
from newsletter_agent.tools.delivery import DeliveryAgent
from newsletter_agent.tools.formatter import FormatterAgent
from newsletter_agent.tools.perplexity_search import perplexity_search_tool
from newsletter_agent.timing import after_agent_callback, before_agent_callback

logger = logging.getLogger(__name__)

_ROOT_AGENT_NAME = "NewsletterPipeline"
_RESEARCH_MODEL = "gemini-2.5-flash"
_SYNTHESIS_MODEL = "gemini-2.5-pro"


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


def build_synthesis_agent(config: NewsletterConfig) -> LlmAgent:
    """Build the synthesis LlmAgent from config.

    The synthesis agent reads research state keys and produces a JSON
    blob with executive summary and per-topic analysis. The raw output
    is stored in session state via output_key for post-processing.
    """
    topic_names = [t.name for t in config.topics]
    instruction = get_synthesis_instruction(topic_names, len(topic_names))

    return LlmAgent(
        name="Synthesizer",
        model=_SYNTHESIS_MODEL,
        instruction=instruction,
        output_key="synthesis_raw",
    )


def build_formatter_agent() -> FormatterAgent:
    """Build the FormatterAgent that renders HTML from synthesis state."""
    return FormatterAgent(name="FormatterAgent")


def build_delivery_agent() -> DeliveryAgent:
    """Build the DeliveryAgent that sends email or saves to disk."""
    return DeliveryAgent(name="DeliveryAgent")


def build_pipeline(config: NewsletterConfig) -> SequentialAgent:
    """Build the complete multi-agent pipeline from config.

    Assembles the root SequentialAgent with research, synthesis, and
    output phases per spec Section 9.1.
    """
    research_phase = build_research_phase(config)
    synthesis_agent = build_synthesis_agent(config)
    output_phase = SequentialAgent(
        name="OutputPhase",
        sub_agents=[
            build_formatter_agent(),
            build_delivery_agent(),
        ],
    )

    logger.info(
        "Pipeline built: %d topics, root=%s",
        len(config.topics),
        _ROOT_AGENT_NAME,
    )

    return SequentialAgent(
        name=_ROOT_AGENT_NAME,
        sub_agents=[
            research_phase,
            synthesis_agent,
            output_phase,
        ],
        before_agent_callback=before_agent_callback,
        after_agent_callback=after_agent_callback,
    )


# ---------------------------------------------------------------------------
# Build root agent at module level (ADK discovery convention)
# ---------------------------------------------------------------------------

try:
    _config = load_config()
    root_agent = build_pipeline(_config)
except Exception as e:
    logger.error("Failed to initialize pipeline: %s", e)
    raise RuntimeError(
        f"Newsletter Agent failed to start: {e}. "
        "Check config/topics.yaml and environment variables."
    ) from e

