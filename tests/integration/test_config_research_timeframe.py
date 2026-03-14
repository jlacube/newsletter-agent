"""Integration test: Config + Research Timeframe Flow.

Verifies that timeframe configuration flows correctly from config schema
through the timeframe resolver to the research phase agent instructions.

Spec refs: FR-001, FR-002, FR-006, FR-009, FR-027, FR-028, Section 11.3.
"""

import pytest
from unittest.mock import MagicMock

from newsletter_agent.agent import build_research_phase, ConfigLoaderAgent
from newsletter_agent.config.schema import (
    AppSettings,
    NewsletterConfig,
    NewsletterSettings,
    TopicConfig,
)
from newsletter_agent.config.timeframe import resolve_timeframe


def _make_config_with_timeframes():
    """Config: global last_week, topic 1 overrides to last_month."""
    return NewsletterConfig(
        newsletter=NewsletterSettings(
            title="Timeframe Test",
            schedule="0 8 * * 0",
            recipient_email="test@example.com",
        ),
        settings=AppSettings(
            dry_run=True,
            output_dir="output/",
            timeframe="last_week",
        ),
        topics=[
            TopicConfig(
                name="AI News",
                query="Latest AI developments",
            ),
            TopicConfig(
                name="Cloud Updates",
                query="Cloud computing news",
                timeframe="last_month",
            ),
        ],
    )


class TestConfigResearchTimeframeIntegration:
    def test_global_timeframe_in_research_instructions(self):
        """Topic 0 inherits global timeframe; instructions contain date clause."""
        config = _make_config_with_timeframes()
        phase = build_research_phase(config)

        # Topic 0 (AI News) gets global "last_week"
        topic0 = phase.sub_agents[0]
        for sub in topic0.sub_agents:
            instruction = sub.instruction.lower()
            assert "last week" in instruction or "week" in instruction, (
                f"Expected date clause in topic 0 instruction: {sub.instruction}"
            )

    def test_per_topic_override_in_research_instructions(self):
        """Topic 1 overrides to last_month; instructions reflect override."""
        config = _make_config_with_timeframes()
        phase = build_research_phase(config)

        # Topic 1 (Cloud Updates) overrides to "last_month"
        topic1 = phase.sub_agents[1]
        for sub in topic1.sub_agents:
            instruction = sub.instruction.lower()
            assert "month" in instruction, (
                f"Expected 'month' in topic 1 instruction: {sub.instruction}"
            )

    @pytest.mark.asyncio
    async def test_config_timeframes_in_session_state(self):
        """ConfigLoaderAgent stores resolved timeframes in session state."""
        config = _make_config_with_timeframes()
        agent = ConfigLoaderAgent(name="ConfigLoader", config=config)

        ctx = MagicMock()
        ctx.session.state = {}
        async for _ in agent._run_async_impl(ctx):
            pass

        state = ctx.session.state
        assert state["config_timeframes"] is not None
        assert len(state["config_timeframes"]) == 2

        # Topic 0: inherited global last_week -> filter "week"
        assert state["config_timeframes"][0]["perplexity_recency_filter"] == "week"
        # Topic 1: override last_month -> filter "month"
        assert state["config_timeframes"][1]["perplexity_recency_filter"] == "month"

    def test_no_timeframe_means_no_date_clause(self):
        """When no timeframe configured, instructions have no date text."""
        config = NewsletterConfig(
            newsletter=NewsletterSettings(
                title="No TF Test",
                schedule="0 8 * * 0",
                recipient_email="test@example.com",
            ),
            settings=AppSettings(dry_run=True),
            topics=[TopicConfig(name="AI", query="AI news")],
        )
        phase = build_research_phase(config)
        topic0 = phase.sub_agents[0]
        for sub in topic0.sub_agents:
            assert "time constraint" not in sub.instruction.lower()
