"""
Newsletter Agent - root agent, research phase, synthesis, and formatting.

Spec refs: Section 9.1, FR-008 through FR-035.
"""

import dataclasses
import logging
from collections.abc import AsyncGenerator

from newsletter_agent.logging_config import setup_logging

setup_logging()

from google.adk.agents import BaseAgent, LlmAgent, ParallelAgent, SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.adk.tools import FunctionTool, google_search
from google.genai import types

from newsletter_agent.config.schema import NewsletterConfig, load_config
from newsletter_agent.config.timeframe import resolve_timeframe
from newsletter_agent.prompts.research_google import get_google_search_instruction
from newsletter_agent.prompts.research_perplexity import get_perplexity_search_instruction
from newsletter_agent.prompts.synthesis import get_synthesis_instruction
from newsletter_agent.tools.delivery import DeliveryAgent
from newsletter_agent.tools.formatter import FormatterAgent
from newsletter_agent.tools.link_verifier_agent import LinkVerifierAgent
from newsletter_agent.tools.perplexity_search import perplexity_search_tool, search_perplexity
from newsletter_agent.tools.synthesis_utils import parse_synthesis_output
from newsletter_agent.timing import after_agent_callback, before_agent_callback

logger = logging.getLogger(__name__)

_ROOT_AGENT_NAME = "NewsletterPipeline"
_RESEARCH_MODEL = "gemini-2.5-flash"
_SYNTHESIS_MODEL = "gemini-2.5-pro"


def _make_perplexity_tool(recency_filter: str | None) -> FunctionTool:
    """Create a FunctionTool wrapping search_perplexity with a bound recency filter."""
    if recency_filter is None:
        return perplexity_search_tool

    def _search_with_filter(query: str, search_depth: str = "standard") -> dict:
        return search_perplexity(query, search_depth, search_recency_filter=recency_filter)

    _search_with_filter.__name__ = "search_perplexity"
    _search_with_filter.__doc__ = search_perplexity.__doc__
    return FunctionTool(func=_search_with_filter)


def build_research_phase(config: NewsletterConfig) -> ParallelAgent:
    """Build the research phase ParallelAgent from config.

    Creates one SequentialAgent per topic, each containing LlmAgents
    for the configured search providers. All topic agents run in parallel.
    """
    topic_agents = []

    for idx, topic in enumerate(config.topics):
        sub_agents = []

        effective_tf = topic.timeframe or config.settings.timeframe
        resolved = resolve_timeframe(effective_tf)
        tf_instruction = resolved.prompt_date_instruction
        pf = resolved.perplexity_recency_filter

        if effective_tf:
            logger.info(
                "Timeframe for topic '%s': %s -> perplexity_filter=%s",
                topic.name,
                effective_tf,
                pf,
            )

        if "google_search" in topic.sources:
            google_agent = LlmAgent(
                name=f"GoogleSearcher_{idx}",
                model=_RESEARCH_MODEL,
                instruction=get_google_search_instruction(
                    topic.name, topic.query, topic.search_depth,
                    timeframe_instruction=tf_instruction,
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
                    topic.name, topic.query, topic.search_depth,
                    timeframe_instruction=tf_instruction,
                ),
                tools=[_make_perplexity_tool(pf)],
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


class ConfigLoaderAgent(BaseAgent):
    """Loads validated config values into session state.

    Reads the NewsletterConfig and populates config_* state keys
    so downstream agents (Formatter, Delivery) can access them.
    Spec refs: Section 9.1, FR-026.
    """

    model_config = {"arbitrary_types_allowed": True}
    config: NewsletterConfig | None = None

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        if self.config is not None:
            state["config_newsletter_title"] = self.config.newsletter.title
            state["config_recipient_email"] = self.config.newsletter.recipient_email
            state["config_recipient_emails"] = self.config.newsletter.recipient_emails
            state["config_dry_run"] = self.config.settings.dry_run
            state["config_output_dir"] = self.config.settings.output_dir
            state["config_verify_links"] = self.config.settings.verify_links

            # Resolve timeframes per topic
            has_any_tf = (
                self.config.settings.timeframe is not None
                or any(t.timeframe is not None for t in self.config.topics)
            )
            if has_any_tf:
                tf_list = []
                for topic in self.config.topics:
                    effective = topic.timeframe or self.config.settings.timeframe
                    resolved = resolve_timeframe(effective)
                    tf_list.append(dataclasses.asdict(resolved))
                state["config_timeframes"] = tf_list
            else:
                state["config_timeframes"] = None

            logger.info(
                "Config loaded into state: title=%s, dry_run=%s, verify_links=%s",
                self.config.newsletter.title,
                self.config.settings.dry_run,
                self.config.settings.verify_links,
            )
        yield Event(
            author=self.name,
            content=types.Content(
                parts=[types.Part(text="Config loaded into session state")]
            ),
        )


class ResearchValidatorAgent(BaseAgent):
    """Checks research state keys after ResearchPhase completes.

    If all research keys are missing or have error=True, sets
    research_all_failed=True in state and logs at CRITICAL level.
    Spec refs: FR-013, T02-06.
    """

    model_config = {"arbitrary_types_allowed": True}
    topic_count: int = 0
    providers: list = []

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        all_failed = True

        for idx in range(self.topic_count):
            for provider in self.providers:
                key = f"research_{idx}_{provider}"
                val = state.get(key)
                if val is not None and not (isinstance(val, dict) and val.get("error")):
                    all_failed = False
                    break
            if not all_failed:
                break

        if all_failed and self.topic_count > 0:
            state["research_all_failed"] = True
            logger.critical(
                "All research providers failed for all %d topics", self.topic_count
            )
            yield Event(
                author=self.name,
                content=types.Content(
                    parts=[types.Part(text="All research providers failed")]
                ),
            )
        else:
            state["research_all_failed"] = False
            yield Event(
                author=self.name,
                content=types.Content(
                    parts=[types.Part(text="Research validation passed")]
                ),
            )


class PipelineAbortCheckAgent(BaseAgent):
    """Aborts the pipeline if all research providers failed.

    Checks research_all_failed state key. If True, saves a fallback HTML
    file and raises RuntimeError to halt the pipeline before synthesis.
    Spec refs: FR-013.
    """

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        if state.get("research_all_failed"):
            output_dir = state.get("config_output_dir", "output/")
            from newsletter_agent.tools.file_output import save_newsletter_html

            error_html = (
                "<html><body><h1>Newsletter Generation Failed</h1>"
                "<p>All research providers failed for all topics. "
                "No newsletter was generated.</p></body></html>"
            )
            path = save_newsletter_html(error_html, output_dir, "error")
            state["delivery_status"] = {
                "status": "aborted",
                "error": "All research providers failed for all topics",
                "fallback_file": path,
            }
            logger.error(
                "Pipeline aborted: all research failed. Error page saved to %s", path
            )
            raise RuntimeError(
                "Pipeline aborted: all research providers failed for all topics"
            )
        yield Event(
            author=self.name,
            content=types.Content(
                parts=[types.Part(text="Pipeline abort check passed")]
            ),
        )


class SynthesisPostProcessorAgent(BaseAgent):
    """Parses synthesis_raw into synthesis_N and executive_summary state keys.

    Bridges the gap between the Synthesizer LlmAgent output and the
    FormatterAgent input. Spec refs: FR-019, T03-02.
    """

    model_config = {"arbitrary_types_allowed": True}
    topic_names: list = []

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        raw = state.get("synthesis_raw", "")

        parsed = parse_synthesis_output(str(raw), self.topic_names)

        for key, value in parsed.items():
            state[key] = value

        state["config_topic_count"] = len(self.topic_names)

        section_count = sum(1 for k in parsed if k.startswith("synthesis_"))
        logger.info(
            "Synthesis post-processing: %d sections parsed from raw output",
            section_count,
        )
        yield Event(
            author=self.name,
            content=types.Content(
                parts=[types.Part(text=f"Parsed {section_count} synthesis sections")]
            ),
        )


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
    config_loader = ConfigLoaderAgent(
        name="ConfigLoader",
        config=config,
    )

    research_phase = build_research_phase(config)

    # Collect providers configured across all topics
    all_providers = set()
    for topic in config.topics:
        for src in topic.sources:
            if src == "google_search":
                all_providers.add("google")
            elif src == "perplexity":
                all_providers.add("perplexity")

    research_validator = ResearchValidatorAgent(
        name="ResearchValidator",
        topic_count=len(config.topics),
        providers=sorted(all_providers),
    )

    abort_check = PipelineAbortCheckAgent(name="PipelineAbortCheck")

    synthesis_agent = build_synthesis_agent(config)

    topic_names = [t.name for t in config.topics]
    synthesis_post_processor = SynthesisPostProcessorAgent(
        name="SynthesisPostProcessor",
        topic_names=topic_names,
    )

    output_phase = SequentialAgent(
        name="OutputPhase",
        sub_agents=[
            build_formatter_agent(),
            build_delivery_agent(),
        ],
    )

    link_verifier = LinkVerifierAgent(
        name="LinkVerifier",
        topic_count=len(config.topics),
        providers=sorted(all_providers),
    )

    logger.info(
        "Pipeline built: %d topics, root=%s",
        len(config.topics),
        _ROOT_AGENT_NAME,
    )

    return SequentialAgent(
        name=_ROOT_AGENT_NAME,
        sub_agents=[
            config_loader,
            research_phase,
            research_validator,
            abort_check,
            link_verifier,
            synthesis_agent,
            synthesis_post_processor,
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

