"""Integration tests: backward compatibility for deep research features.

Verifies that standard-mode topics are unaffected by deep research
additions, and that max_research_rounds=1 behaves like single-round.

Spec refs: FR-BC-001, FR-BC-002, FR-BC-004, SC-005, SC-006 (WP14 T14-06, T14-07).
"""

import pytest
from unittest.mock import MagicMock, patch

from newsletter_agent.agent import build_research_phase, build_pipeline
from newsletter_agent.config.schema import (
    AppSettings,
    NewsletterConfig,
    NewsletterSettings,
    TopicConfig,
)
from newsletter_agent.tools.deep_research import DeepResearchOrchestrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(state: dict | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.session.state = state if state is not None else {}
    return ctx


def _standard_config(tmp_path, max_rounds=3):
    """Config with only standard-mode topics."""
    return NewsletterConfig(
        newsletter=NewsletterSettings(
            title="Standard Mode Compat Test",
            schedule="0 8 * * 0",
            recipient_email="test@example.com",
        ),
        settings=AppSettings(
            dry_run=True,
            output_dir=str(tmp_path),
            max_research_rounds=max_rounds,
        ),
        topics=[
            TopicConfig(
                name="Tech News",
                query="latest technology news",
                search_depth="standard",
                sources=["google_search", "perplexity"],
            ),
        ],
    )


def _deep_single_round_config(tmp_path):
    """Config with deep-mode topic and max_research_rounds=1."""
    return NewsletterConfig(
        newsletter=NewsletterSettings(
            title="Single Round Deep Test",
            schedule="0 8 * * 0",
            recipient_email="test@example.com",
        ),
        settings=AppSettings(
            dry_run=True,
            output_dir=str(tmp_path),
            max_research_rounds=1,
        ),
        topics=[
            TopicConfig(
                name="AI News",
                query="latest AI developments",
                search_depth="deep",
                sources=["google_search", "perplexity"],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# T14-06: Backward compatibility - standard mode unchanged
# ---------------------------------------------------------------------------


class TestStandardModeBackwardCompat:
    """FR-BC-001, SC-005: Standard-mode topics behave identically."""

    def test_standard_topic_uses_llm_agent_not_orchestrator(self, tmp_path):
        """Standard topic uses LlmAgent, not DeepResearchOrchestrator (FR-BC-001)."""
        config = _standard_config(tmp_path, max_rounds=3)
        phase = build_research_phase(config)
        topic0 = phase.sub_agents[0]

        for sub in topic0.sub_agents:
            assert not isinstance(sub, DeepResearchOrchestrator), (
                "Standard topic should NOT use DeepResearchOrchestrator"
            )

    def test_standard_topic_output_key_format(self, tmp_path):
        """Standard topic produces research_{idx}_{provider} key (FR-BC-004)."""
        config = _standard_config(tmp_path)
        phase = build_research_phase(config)
        topic0 = phase.sub_agents[0]

        for sub in topic0.sub_agents:
            assert hasattr(sub, "output_key")
            assert sub.output_key.startswith("research_0_")

    def test_standard_topic_no_deep_state_keys(self, tmp_path):
        """Standard topic creates no deep_* or round_* state keys."""
        config = _standard_config(tmp_path)
        phase = build_research_phase(config)
        topic0 = phase.sub_agents[0]

        # Verify output keys don't contain "deep" or "round"
        for sub in topic0.sub_agents:
            assert "deep" not in sub.output_key
            assert "round" not in sub.output_key

    def test_standard_topic_with_high_max_rounds_still_single_search(self, tmp_path):
        """Even with max_research_rounds=5, standard topics use single LlmAgent."""
        config = _standard_config(tmp_path, max_rounds=5)
        phase = build_research_phase(config)
        topic0 = phase.sub_agents[0]

        for sub in topic0.sub_agents:
            assert not isinstance(sub, DeepResearchOrchestrator), (
                "Standard topic with high max_rounds should still be LlmAgent"
            )

    def test_pipeline_agents_all_present(self, tmp_path):
        """Full pipeline has all expected agents in standard mode (FR-BC-003)."""
        config = _standard_config(tmp_path)
        pipeline = build_pipeline(config)
        agent_names = [a.name for a in pipeline.sub_agents]

        # All pipeline stages present
        assert "ConfigLoader" in agent_names
        assert "ResearchPhase" in agent_names
        assert "ResearchValidator" in agent_names
        assert "PipelineAbortCheck" in agent_names
        assert "LinkVerifier" in agent_names
        assert "DeepResearchRefiner" in agent_names
        assert "Synthesizer" in agent_names
        assert "SynthesisPostProcessor" in agent_names
        assert "OutputPhase" in agent_names

    def test_existing_test_suite_passes(self):
        """SC-006: Baseline - this test existing in the suite confirms no import errors."""
        # This is a placeholder asserting the test infrastructure works.
        # The actual SC-006 verification is running `pytest tests/` at the
        # end of WP14 and confirming all 572+ tests pass.
        from newsletter_agent.agent import root_agent
        assert root_agent is not None


# ---------------------------------------------------------------------------
# T14-07: Backward compatibility - max_research_rounds=1
# ---------------------------------------------------------------------------


class TestMaxRoundsOneBackwardCompat:
    """FR-BC-002: Deep-mode with max_research_rounds=1 behaves like single-round."""

    def test_deep_max_rounds_1_uses_orchestrator(self, tmp_path):
        """Deep topic still uses DeepResearchOrchestrator with max_rounds=1."""
        config = _deep_single_round_config(tmp_path)
        phase = build_research_phase(config)
        topic0 = phase.sub_agents[0]

        for sub in topic0.sub_agents:
            assert isinstance(sub, DeepResearchOrchestrator)
            assert sub.max_rounds == 1

    @pytest.mark.asyncio
    async def test_max_rounds_1_executes_single_round(self, tmp_path):
        """max_research_rounds=1 executes exactly 1 search round."""
        config = _deep_single_round_config(tmp_path)
        phase = build_research_phase(config)
        orch = phase.sub_agents[0].sub_agents[0]

        ctx = _make_ctx()
        call_count = 0

        async def mock_run_async(inner_ctx):
            nonlocal call_count
            key = f"deep_research_latest_{orch.topic_idx}_{orch.provider}"
            inner_ctx.session.state[key] = (
                "SUMMARY:\nFindings.\n\nSOURCES:\n"
                "- [A1](https://ex.com/1)\n- [A2](https://ex.com/2)"
            )
            call_count += 1
            return
            yield

        def patched_make(round_idx, query):
            agent = MagicMock()
            agent.run_async = mock_run_async
            return agent

        with patch.object(orch, "_make_search_agent", side_effect=patched_make):
            async for _ in orch._run_async_impl(ctx):
                pass

        assert call_count == 1, f"Expected 1 round, got {call_count}"

    @pytest.mark.asyncio
    async def test_max_rounds_1_no_query_expansion(self, tmp_path):
        """max_research_rounds=1 skips query expansion entirely."""
        config = _deep_single_round_config(tmp_path)
        phase = build_research_phase(config)
        orch = phase.sub_agents[0].sub_agents[0]

        ctx = _make_ctx()

        async def mock_run_async(inner_ctx):
            key = f"deep_research_latest_{orch.topic_idx}_{orch.provider}"
            inner_ctx.session.state[key] = (
                "SUMMARY:\nFindings.\n\nSOURCES:\n"
                "- [A1](https://ex.com/1)"
            )
            return
            yield

        def patched_make(round_idx, query):
            agent = MagicMock()
            agent.run_async = mock_run_async
            return agent

        expand_called = False
        original_expand = orch._expand_queries

        async def tracked_expand(inner_ctx):
            nonlocal expand_called
            expand_called = True
            return await original_expand(inner_ctx)

        with patch.object(orch, "_make_search_agent", side_effect=patched_make):
            with patch.object(orch, "_expand_queries", side_effect=tracked_expand):
                async for _ in orch._run_async_impl(ctx):
                    pass

        assert not expand_called, "Query expansion should not run with max_rounds=1"

    @pytest.mark.asyncio
    async def test_max_rounds_1_no_intermediate_keys_remain(self, tmp_path):
        """max_research_rounds=1 cleans up all intermediate state keys."""
        config = _deep_single_round_config(tmp_path)
        phase = build_research_phase(config)
        orch = phase.sub_agents[0].sub_agents[0]

        ctx = _make_ctx()

        async def mock_run_async(inner_ctx):
            key = f"deep_research_latest_{orch.topic_idx}_{orch.provider}"
            inner_ctx.session.state[key] = (
                "SUMMARY:\nFindings.\n\nSOURCES:\n"
                "- [A1](https://ex.com/1)"
            )
            return
            yield

        def patched_make(round_idx, query):
            agent = MagicMock()
            agent.run_async = mock_run_async
            return agent

        with patch.object(orch, "_make_search_agent", side_effect=patched_make):
            async for _ in orch._run_async_impl(ctx):
                pass

        state = ctx.session.state
        # Final output exists
        assert f"research_{orch.topic_idx}_{orch.provider}" in state

        # No intermediate keys
        for key in state:
            assert not key.startswith("deep_queries_"), f"Leftover key: {key}"
            assert not key.startswith("deep_research_latest_"), f"Leftover key: {key}"
            assert not key.startswith("deep_urls_accumulated_"), f"Leftover key: {key}"
            assert "round_" not in key, f"Leftover round key: {key}"

    @pytest.mark.asyncio
    async def test_max_rounds_1_produces_standard_format(self, tmp_path):
        """max_research_rounds=1 produces SUMMARY + SOURCES format."""
        config = _deep_single_round_config(tmp_path)
        phase = build_research_phase(config)
        orch = phase.sub_agents[0].sub_agents[0]

        ctx = _make_ctx()

        async def mock_run_async(inner_ctx):
            key = f"deep_research_latest_{orch.topic_idx}_{orch.provider}"
            inner_ctx.session.state[key] = (
                "SUMMARY:\nSingle round findings.\n\nSOURCES:\n"
                "- [Src1](https://ex.com/a1)\n"
                "- [Src2](https://ex.com/a2)"
            )
            return
            yield

        def patched_make(round_idx, query):
            agent = MagicMock()
            agent.run_async = mock_run_async
            return agent

        with patch.object(orch, "_make_search_agent", side_effect=patched_make):
            async for _ in orch._run_async_impl(ctx):
                pass

        result = ctx.session.state[f"research_{orch.topic_idx}_{orch.provider}"]
        assert "SUMMARY:" in result
        assert "SOURCES:" in result
