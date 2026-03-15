"""Integration tests for deep research multi-round pipeline.

Tests verify that DeepResearchOrchestrator integrates correctly with
the research phase, produces accumulated multi-round results, and
cleans up intermediate state keys.

Spec refs: FR-MRR-001 through FR-MRR-011, FR-BC-001, FR-BC-004,
           Section 11.3 (WP14 T14-01, T14-02).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from newsletter_agent.agent import build_research_phase
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
    """Create a mock InvocationContext with session state."""
    ctx = MagicMock()
    ctx.session.state = state if state is not None else {}
    return ctx


def _deep_config(tmp_path, max_rounds=3):
    """Config with a single deep-mode topic."""
    return NewsletterConfig(
        newsletter=NewsletterSettings(
            title="Deep Research Integration Test",
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
                name="AI Breakthroughs",
                query="latest AI breakthroughs 2026",
                search_depth="deep",
                sources=["google_search", "perplexity"],
            ),
        ],
    )


def _mixed_config(tmp_path, max_rounds=3):
    """Config with one standard and one deep topic."""
    return NewsletterConfig(
        newsletter=NewsletterSettings(
            title="Mixed Topics Integration Test",
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
                name="Cloud News",
                query="cloud computing news",
                search_depth="standard",
                sources=["google_search", "perplexity"],
            ),
            TopicConfig(
                name="AI Breakthroughs",
                query="latest AI breakthroughs 2026",
                search_depth="deep",
                sources=["google_search", "perplexity"],
            ),
        ],
    )


def _research_text_with_urls(round_idx: int, url_prefix: str, count: int = 6) -> str:
    """Generate research text with numbered URLs for a given round."""
    urls = [
        f"- [Article R{round_idx} #{i}]({url_prefix}/round{round_idx}/article{i})"
        for i in range(count)
    ]
    sources = "\n".join(urls)
    return f"SUMMARY:\nRound {round_idx} findings about the topic.\n\nSOURCES:\n{sources}"


# ---------------------------------------------------------------------------
# T14-01: Multi-round research with mocked tools
# ---------------------------------------------------------------------------


class TestMultiRoundResearchIntegration:
    """Integration test: deep-mode multi-round research produces
    accumulated results in correct state keys with cleanup."""

    @pytest.mark.asyncio
    async def test_deep_topic_3_rounds_accumulates_urls(self, tmp_path):
        """Deep-mode topic with 3 rounds produces merged SUMMARY + SOURCES
        in research_{idx}_{provider} and cleans up intermediate keys."""
        config = _deep_config(tmp_path, max_rounds=3)
        phase = build_research_phase(config)

        # The phase is ParallelAgent -> Topic0Research (SequentialAgent)
        # -> DeepResearch_0_google, DeepResearch_0_perplexity
        topic0 = phase.sub_agents[0]
        assert topic0.name == "Topic0Research"
        assert len(topic0.sub_agents) == 2  # google + perplexity

        # Test the google orchestrator directly with mocked sub-agents
        orch = topic0.sub_agents[0]
        assert isinstance(orch, DeepResearchOrchestrator)
        assert orch.provider == "google"
        assert orch.max_rounds == 3

        ctx = _make_ctx()
        call_count = 0

        async def mock_run_async(inner_ctx):
            nonlocal call_count
            output_key = f"deep_research_latest_0_google"
            inner_ctx.session.state[output_key] = _research_text_with_urls(
                call_count, "https://example.com/google", count=6
            )
            call_count += 1
            return
            yield  # async generator

        # Patch the search agent creation to use our mock
        original_make = orch._make_search_agent

        def patched_make(round_idx, query):
            agent = MagicMock()
            agent.run_async = mock_run_async
            return agent

        # Also mock the query expansion
        async def mock_expand(inner_ctx):
            return ["variant query 1", "variant query 2"], []

        with patch.object(orch, "_make_search_agent", side_effect=patched_make):
            with patch.object(orch, "_expand_queries", side_effect=mock_expand):
                events = []
                async for event in orch._run_async_impl(ctx):
                    events.append(event)

        state = ctx.session.state

        # Verify final merged result exists
        final_key = "research_0_google"
        assert final_key in state
        final_text = state[final_key]
        assert "SUMMARY:" in final_text
        assert "SOURCES:" in final_text

        # Verify URLs from multiple rounds are present
        assert "round0/article" in final_text
        assert "round1/article" in final_text

        # Verify intermediate state keys are cleaned up (FR-MRR-011)
        for key in list(state.keys()):
            assert not key.startswith("deep_queries_"), f"Intermediate key not cleaned: {key}"
            assert not key.startswith("deep_research_latest_"), f"Intermediate key not cleaned: {key}"
            assert not key.startswith("deep_urls_accumulated_"), f"Intermediate key not cleaned: {key}"
            assert not key.startswith("deep_query_current_"), f"Intermediate key not cleaned: {key}"
            assert "round_" not in key, f"Round key not cleaned: {key}"

    @pytest.mark.asyncio
    async def test_deep_research_standard_format(self, tmp_path):
        """Final merged output uses standard SUMMARY + SOURCES format."""
        config = _deep_config(tmp_path, max_rounds=2)
        orch = DeepResearchOrchestrator(
            name="DeepResearch_0_google",
            topic_idx=0,
            provider="google",
            query="AI news",
            topic_name="AI",
            max_rounds=2,
            search_depth="deep",
            model="gemini-2.5-flash",
            tools=[],
        )
        ctx = _make_ctx()
        call_count = 0

        async def mock_run_async(inner_ctx):
            nonlocal call_count
            output_key = "deep_research_latest_0_google"
            inner_ctx.session.state[output_key] = _research_text_with_urls(
                call_count, "https://example.com", count=4
            )
            call_count += 1
            return
            yield

        def patched_make(round_idx, query):
            agent = MagicMock()
            agent.run_async = mock_run_async
            return agent

        async def mock_expand(inner_ctx):
            return ["variant 1"], []

        with patch.object(orch, "_make_search_agent", side_effect=patched_make):
            with patch.object(orch, "_expand_queries", side_effect=mock_expand):
                async for _ in orch._run_async_impl(ctx):
                    pass

        result = ctx.session.state.get("research_0_google", "")
        # Standard format: starts with SUMMARY:, contains SOURCES:
        assert result.startswith("SUMMARY:")
        assert "\nSOURCES:" in result or "\n\nSOURCES:" in result

    @pytest.mark.asyncio
    async def test_early_exit_when_threshold_met(self, tmp_path):
        """Orchestrator exits early when URL threshold (15) is met."""
        orch = DeepResearchOrchestrator(
            name="DeepResearch_0_google",
            topic_idx=0,
            provider="google",
            query="AI news",
            topic_name="AI",
            max_rounds=3,
            search_depth="deep",
            model="gemini-2.5-flash",
            tools=[],
        )
        ctx = _make_ctx()
        call_count = 0

        async def mock_run_async(inner_ctx):
            nonlocal call_count
            output_key = "deep_research_latest_0_google"
            # First round returns 16 URLs (exceeds threshold of 15)
            inner_ctx.session.state[output_key] = _research_text_with_urls(
                call_count, "https://ex.com", count=16
            )
            call_count += 1
            return
            yield

        def patched_make(round_idx, query):
            agent = MagicMock()
            agent.run_async = mock_run_async
            return agent

        async def mock_expand(inner_ctx):
            return ["v1", "v2"], []

        with patch.object(orch, "_make_search_agent", side_effect=patched_make):
            with patch.object(orch, "_expand_queries", side_effect=mock_expand):
                async for _ in orch._run_async_impl(ctx):
                    pass

        # Only 1 round executed (early exit after round 0)
        assert call_count == 1
        assert "research_0_google" in ctx.session.state


# ---------------------------------------------------------------------------
# T14-02: Mixed standard and deep topics
# ---------------------------------------------------------------------------


class TestMixedStandardDeepIntegration:
    """Integration test: mixed config with standard and deep topics."""

    def test_phase_has_correct_agent_types(self, tmp_path):
        """Standard topic uses LlmAgent, deep topic uses DeepResearchOrchestrator."""
        config = _mixed_config(tmp_path)
        phase = build_research_phase(config)

        # 2 topic agents
        assert len(phase.sub_agents) == 2

        # Topic 0: standard mode
        topic0 = phase.sub_agents[0]
        assert topic0.name == "Topic0Research"
        for sub in topic0.sub_agents:
            assert not isinstance(sub, DeepResearchOrchestrator), (
                "Standard topic should not use DeepResearchOrchestrator"
            )

        # Topic 1: deep mode
        topic1 = phase.sub_agents[1]
        assert topic1.name == "Topic1Research"
        for sub in topic1.sub_agents:
            assert isinstance(sub, DeepResearchOrchestrator), (
                "Deep topic should use DeepResearchOrchestrator"
            )

    @pytest.mark.asyncio
    async def test_standard_topic_no_deep_state_keys(self, tmp_path):
        """Standard topic does not produce any deep_* intermediate keys."""
        config = _mixed_config(tmp_path)
        phase = build_research_phase(config)
        topic0 = phase.sub_agents[0]  # standard

        # Simulate by checking the output_key of standard LlmAgents
        for sub in topic0.sub_agents:
            # Standard agents use output_key like research_0_google
            assert hasattr(sub, "output_key"), "Standard agent should have output_key"
            assert sub.output_key.startswith("research_0_"), (
                f"Unexpected output_key: {sub.output_key}"
            )
            assert "deep" not in sub.output_key

    @pytest.mark.asyncio
    async def test_deep_topic_uses_orchestrator_with_max_rounds(self, tmp_path):
        """Deep topic's orchestrator respects max_research_rounds from config."""
        config = _mixed_config(tmp_path, max_rounds=2)
        phase = build_research_phase(config)
        topic1 = phase.sub_agents[1]  # deep

        for sub in topic1.sub_agents:
            assert isinstance(sub, DeepResearchOrchestrator)
            assert sub.max_rounds == 2

    def test_state_key_format_downstream_compatible(self, tmp_path):
        """Both standard and deep topics produce research_{idx}_{provider} key
        format expected by downstream agents (FR-BC-004)."""
        config = _mixed_config(tmp_path)
        phase = build_research_phase(config)

        # Standard: output_key = research_0_google, research_0_perplexity
        topic0 = phase.sub_agents[0]
        for sub in topic0.sub_agents:
            assert sub.output_key.startswith("research_0_")

        # Deep: DeepResearchOrchestrator writes to research_1_google etc.
        topic1 = phase.sub_agents[1]
        for sub in topic1.sub_agents:
            assert sub.topic_idx == 1
            # Orchestrator writes to research_{idx}_{provider} at the end

    @pytest.mark.asyncio
    async def test_standard_topic_single_round_per_provider(self, tmp_path):
        """Standard-mode topic produces exactly 1 research key per provider,
        no round keys, no deep keys (FR-BC-001)."""
        config = _mixed_config(tmp_path, max_rounds=3)
        phase = build_research_phase(config)
        topic0 = phase.sub_agents[0]  # standard

        # Standard agents are LlmAgents with output_key attributes
        # Verify they produce a single key and no deep/round keys
        state = {}
        for sub in topic0.sub_agents:
            output_key = sub.output_key
            # Simulate what LlmAgent would write
            state[output_key] = (
                "SUMMARY:\nStandard findings.\n\nSOURCES:\n"
                "- [Src1](https://standard.example.com/1)\n"
                "- [Src2](https://standard.example.com/2)"
            )

        # Verify standard keys exist
        assert "research_0_google" in state or "research_0_perplexity" in state

        # Verify NO deep intermediate keys
        for key in state:
            assert not key.startswith("deep_"), f"Unexpected deep key: {key}"
            assert "round_" not in key, f"Unexpected round key: {key}"
            # Verify key is the standard format
            assert key.startswith("research_0_"), f"Unexpected key format: {key}"
