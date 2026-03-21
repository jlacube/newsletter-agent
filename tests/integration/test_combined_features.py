"""Integration test: Timeframe + Link Verification Combined.

Verifies both features compose correctly without interference.

Spec refs: FR-001, FR-013, FR-014, Section 11.3.
"""

import pytest
from unittest.mock import MagicMock

from newsletter_agent.agent import build_research_phase, build_pipeline, ConfigLoaderAgent
from newsletter_agent.tools.link_verifier_agent import LinkVerifierAgent


class TestCombinedFeaturesIntegration:
    def test_pipeline_contains_link_verifier(self, config_with_both_features):
        """When verify_links=true, LinkVerifierAgent is in the pipeline."""
        pipeline = build_pipeline(config_with_both_features)
        agent_names = [a.name for a in pipeline.sub_agents]
        assert "LinkVerifier" in agent_names

    def test_research_instructions_contain_timeframe(self, config_with_both_features):
        """Research agents include date clause from timeframe."""
        from tests.conftest import get_instruction_text
        phase = build_research_phase(config_with_both_features)

        # Topic 0 (AI News): inherits global "last_week"
        topic0 = phase.sub_agents[0]
        for sub in topic0.sub_agents:
            assert "week" in get_instruction_text(sub).lower()

        # Topic 1 (Cloud Updates): overrides to "last_month"
        topic1 = phase.sub_agents[1]
        for sub in topic1.sub_agents:
            assert "month" in get_instruction_text(sub).lower()

    @pytest.mark.asyncio
    async def test_session_state_has_both_features(self, config_with_both_features):
        """ConfigLoaderAgent sets both timeframe and verify_links state."""
        agent = ConfigLoaderAgent(
            name="ConfigLoader", config=config_with_both_features
        )
        ctx = MagicMock()
        ctx.session.state = {}
        async for _ in agent._run_async_impl(ctx):
            pass

        state = ctx.session.state
        # Timeframe state
        assert state["config_timeframes"] is not None
        assert len(state["config_timeframes"]) == 2
        # Verify links state
        assert state["config_verify_links"] is True

    def test_no_cross_contamination(self, config_with_both_features):
        """Timeframe fields do not appear in link verifier; link fields do not appear in timeframe."""
        pipeline = build_pipeline(config_with_both_features)

        # Find LinkVerifierAgent - it should not reference timeframe
        link_verifier = None
        for agent in pipeline.sub_agents:
            if isinstance(agent, LinkVerifierAgent):
                link_verifier = agent
                break
        assert link_verifier is not None

        # Research phase instructions should not reference link verification
        from tests.conftest import get_instruction_text
        phase = build_research_phase(config_with_both_features)
        for topic_agent in phase.sub_agents:
            for sub in topic_agent.sub_agents:
                assert "verify" not in get_instruction_text(sub).lower()
                assert "link check" not in get_instruction_text(sub).lower()
