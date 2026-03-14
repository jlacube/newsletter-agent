"""Integration test: Backward Compatibility.

Verifies that an old-format topics.yaml (no timeframe, no verify_links)
loads correctly and produces identical pipeline behavior to pre-change code.

Spec refs: SC-004, FR-004, FR-024, FR-026, Section 11.4.
"""

import pytest
from unittest.mock import MagicMock

from newsletter_agent.agent import build_research_phase, build_pipeline, ConfigLoaderAgent
from newsletter_agent.config.schema import (
    AppSettings,
    NewsletterConfig,
    NewsletterSettings,
    TopicConfig,
)
from newsletter_agent.tools.link_verifier_agent import LinkVerifierAgent


class TestBackwardCompatibility:
    def test_old_format_config_loads(self, config_old_format):
        """Config without new fields loads and defaults correctly."""
        assert config_old_format.settings.timeframe is None
        assert config_old_format.settings.verify_links is False
        assert config_old_format.topics[0].timeframe is None

    def test_pipeline_includes_link_verifier_as_noop(self, config_old_format):
        """Pipeline still includes LinkVerifierAgent but it will no-op."""
        pipeline = build_pipeline(config_old_format)
        agent_types = [type(a).__name__ for a in pipeline.sub_agents]
        # LinkVerifierAgent is always included (no-op when verify_links=false)
        assert "LinkVerifierAgent" in agent_types

    def test_research_instructions_no_date_clause(self, config_old_format):
        """No timeframe = no date clause in research instructions."""
        phase = build_research_phase(config_old_format)
        for topic_agent in phase.sub_agents:
            for sub in topic_agent.sub_agents:
                assert "time constraint" not in sub.instruction.lower(), (
                    f"Unexpected date clause: {sub.instruction}"
                )

    @pytest.mark.asyncio
    async def test_session_state_no_timeframes(self, config_old_format):
        """ConfigLoaderAgent sets config_timeframes to None when no timeframe."""
        agent = ConfigLoaderAgent(name="ConfigLoader", config=config_old_format)
        ctx = MagicMock()
        ctx.session.state = {}
        async for _ in agent._run_async_impl(ctx):
            pass

        state = ctx.session.state
        assert state["config_timeframes"] is None
        assert state["config_verify_links"] is False

    @pytest.mark.asyncio
    async def test_link_verifier_noop_with_old_config(self, config_old_format):
        """LinkVerifierAgent does nothing when verify_links=false."""
        state = {
            "config_verify_links": False,
            "config_topic_count": 1,
            "synthesis_0": {
                "topic_name": "Tech",
                "body_markdown": "See [Link](https://example.com).",
                "sources": [{"title": "Link", "url": "https://example.com"}],
            },
        }
        agent = LinkVerifierAgent(name="LinkVerifier")
        ctx = MagicMock()
        ctx.session.state = state

        async for _ in agent._run_async_impl(ctx):
            pass

        # State unchanged
        assert len(state["synthesis_0"]["sources"]) == 1
        assert state["synthesis_0"]["body_markdown"] == "See [Link](https://example.com)."

    def test_existing_config_keys_preserved(self, config_old_format):
        """Existing session state keys still populated correctly."""
        agent = ConfigLoaderAgent(name="ConfigLoader", config=config_old_format)

        async def _run():
            ctx = MagicMock()
            ctx.session.state = {}
            async for _ in agent._run_async_impl(ctx):
                pass
            return ctx.session.state

        import asyncio
        state = asyncio.get_event_loop().run_until_complete(_run())

        assert state["config_newsletter_title"] == "Legacy Config Test"
        assert state["config_recipient_email"] == "test@example.com"
        assert state["config_dry_run"] is True
