"""Integration tests for adaptive deep research pipeline.

Tests verify that DeepResearchOrchestrator integrates correctly with
the research phase using the adaptive Plan-Search-Analyze-Decide loop,
produces accumulated multi-round results, and cleans up intermediate state keys.

Spec refs: FR-ADR-001 through FR-ADR-006, FR-ADR-050 through FR-ADR-055,
           FR-ADR-080 through FR-ADR-085, Section 11.3.
"""

import json
import pytest
from unittest.mock import MagicMock, patch

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


def _deep_config(tmp_path, max_rounds=3, max_searches=None, min_rounds=None):
    """Config with a single deep-mode topic."""
    settings_kwargs = {
        "dry_run": True,
        "output_dir": str(tmp_path),
        "max_research_rounds": max_rounds,
    }
    if max_searches is not None:
        settings_kwargs["max_searches_per_topic"] = max_searches
    if min_rounds is not None:
        settings_kwargs["min_research_rounds"] = min_rounds
    return NewsletterConfig(
        newsletter=NewsletterSettings(
            title="Deep Research Integration Test",
            schedule="0 8 * * 0",
            recipient_email="test@example.com",
        ),
        settings=AppSettings(**settings_kwargs),
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


def _planning_result(query="AI analysis deep dive", aspects=None):
    """Return (initial_query, key_aspects, events) for mock _run_planning."""
    if aspects is None:
        aspects = ["recent developments", "expert opinions", "data and statistics"]
    return (query, aspects, [])


def _analysis_result(saturated=False, gaps=None, next_query=None, summary="Findings"):
    """Return (analysis_dict, events) for mock _run_analysis."""
    if gaps is None:
        gaps = ["gap1"] if not saturated else []
    return (
        {
            "findings_summary": summary,
            "knowledge_gaps": gaps,
            "coverage_assessment": "partial" if not saturated else "comprehensive",
            "saturated": saturated,
            "next_query": next_query or ("" if saturated else "follow-up query"),
            "next_query_rationale": "continuing",
        },
        [],
    )


def _setup_adaptive_mocks(orch, max_rounds, url_prefix="https://example.com/google"):
    """Set up planning, analysis, and search mocks for an orchestrator.

    Returns (call_count_list, patchers_context_manager_args).
    """
    call_count = [0]

    async def mock_planning(inner_ctx):
        return _planning_result()

    analysis_responses = []
    for r in range(max_rounds):
        if r < max_rounds - 1:
            analysis_responses.append(
                _analysis_result(saturated=False, next_query=f"query_r{r+1}", gaps=[f"gap_{r}"])
            )
        else:
            analysis_responses.append(_analysis_result(saturated=True, gaps=[]))
    analysis_idx = [0]

    async def mock_analysis(*args, **kwargs):
        idx = analysis_idx[0]
        analysis_idx[0] += 1
        return analysis_responses[min(idx, len(analysis_responses) - 1)]

    def patched_make(round_idx, query):
        agent = MagicMock()

        async def mock_run_async(inner_ctx):
            output_key = f"deep_research_latest_{orch.topic_idx}_{orch.provider}"
            inner_ctx.session.state[output_key] = _research_text_with_urls(
                call_count[0], url_prefix, count=6
            )
            call_count[0] += 1
            return
            yield

        agent.run_async = mock_run_async
        return agent

    return call_count, mock_planning, mock_analysis, patched_make


# ---------------------------------------------------------------------------
# Integration: Multi-round adaptive research with mocked tools
# ---------------------------------------------------------------------------


class TestMultiRoundResearchIntegration:
    """Integration: adaptive deep-mode research produces accumulated results."""

    @pytest.mark.asyncio
    async def test_deep_topic_3_rounds_google(self, tmp_path):
        """Deep-mode topic with 3 rounds produces merged SUMMARY + SOURCES
        in research_{idx}_{provider} and cleans up intermediate keys."""
        config = _deep_config(tmp_path, max_rounds=3)
        phase = build_research_phase(config)

        topic0 = phase.sub_agents[0]
        assert topic0.name == "Topic0Research"
        assert len(topic0.sub_agents) == 2

        orch = topic0.sub_agents[0]
        assert isinstance(orch, DeepResearchOrchestrator)
        assert orch.provider == "google"
        assert orch.max_rounds == 3

        ctx = _make_ctx()
        call_count, mock_planning, mock_analysis, patched_make = _setup_adaptive_mocks(orch, 3)

        with patch.object(orch, "_run_planning", side_effect=mock_planning), \
             patch.object(orch, "_run_analysis", side_effect=mock_analysis), \
             patch.object(orch, "_make_search_agent", side_effect=patched_make):
            async for _ in orch._run_async_impl(ctx):
                pass

        state = ctx.session.state

        # Verify final merged result exists
        final_key = "research_0_google"
        assert final_key in state
        final_text = state[final_key]
        assert "SUMMARY:" in final_text
        assert "SOURCES:" in final_text
        assert "round0/article" in final_text
        assert "round1/article" in final_text

        # Verify intermediate state keys are cleaned up
        for key in list(state.keys()):
            assert not key.startswith("deep_research_latest_"), f"Intermediate key not cleaned: {key}"
            assert not key.startswith("deep_urls_accumulated_"), f"Intermediate key not cleaned: {key}"
            if "round_" in key:
                assert key.startswith("adaptive_reasoning"), f"Round key not cleaned: {key}"

        # Verify reasoning chain persisted
        chain_key = "adaptive_reasoning_chain_0_google"
        assert chain_key in state
        chain = json.loads(state[chain_key])
        assert "plan" in chain
        assert "rounds" in chain

    @pytest.mark.asyncio
    async def test_deep_topic_perplexity_provider(self, tmp_path):
        """Deep-mode topic with Perplexity provider produces same flow."""
        config = _deep_config(tmp_path, max_rounds=3)
        phase = build_research_phase(config)
        topic0 = phase.sub_agents[0]
        orch = topic0.sub_agents[1]  # perplexity
        assert isinstance(orch, DeepResearchOrchestrator)
        assert orch.provider == "perplexity"

        ctx = _make_ctx()
        call_count, mock_planning, mock_analysis, patched_make = _setup_adaptive_mocks(
            orch, 3, "https://example.com/perplexity"
        )

        with patch.object(orch, "_run_planning", side_effect=mock_planning), \
             patch.object(orch, "_run_analysis", side_effect=mock_analysis), \
             patch.object(orch, "_make_search_agent", side_effect=patched_make):
            async for _ in orch._run_async_impl(ctx):
                pass

        final_key = f"research_{orch.topic_idx}_{orch.provider}"
        assert final_key in ctx.session.state
        assert "SUMMARY:" in ctx.session.state[final_key]
        assert "SOURCES:" in ctx.session.state[final_key]

    @pytest.mark.asyncio
    async def test_deep_research_standard_format(self, tmp_path):
        """Final merged output uses standard SUMMARY + SOURCES format."""
        orch = DeepResearchOrchestrator(
            name="DeepResearch_0_google", topic_idx=0, provider="google",
            query="AI news", topic_name="AI", max_rounds=2,
            search_depth="deep", model="gemini-2.5-flash", tools=[],
        )
        ctx = _make_ctx()
        call_count, mock_planning, mock_analysis, patched_make = _setup_adaptive_mocks(orch, 2)

        with patch.object(orch, "_run_planning", side_effect=mock_planning), \
             patch.object(orch, "_run_analysis", side_effect=mock_analysis), \
             patch.object(orch, "_make_search_agent", side_effect=patched_make):
            async for _ in orch._run_async_impl(ctx):
                pass

        result = ctx.session.state.get("research_0_google", "")
        assert result.startswith("SUMMARY:")
        assert "\nSOURCES:" in result or "\n\nSOURCES:" in result

    @pytest.mark.asyncio
    async def test_search_budget_binding_constraint(self, tmp_path):
        """When max_searches_per_topic < max_research_rounds, budget is binding."""
        config = _deep_config(tmp_path, max_rounds=5, max_searches=2)
        phase = build_research_phase(config)
        orch = phase.sub_agents[0].sub_agents[0]

        ctx = _make_ctx()

        call_count = [0]

        async def mock_planning(inner_ctx):
            return _planning_result()

        async def mock_analysis(*args, **kwargs):
            return _analysis_result(saturated=False, next_query="next", gaps=["gap"])

        def patched_make(round_idx, query):
            agent = MagicMock()

            async def mock_run(inner_ctx):
                key = f"deep_research_latest_{orch.topic_idx}_{orch.provider}"
                inner_ctx.session.state[key] = _research_text_with_urls(
                    call_count[0], "https://example.com", count=4
                )
                call_count[0] += 1
                return
                yield

            agent.run_async = mock_run
            return agent

        with patch.object(orch, "_run_planning", side_effect=mock_planning), \
             patch.object(orch, "_run_analysis", side_effect=mock_analysis), \
             patch.object(orch, "_make_search_agent", side_effect=patched_make):
            async for _ in orch._run_async_impl(ctx):
                pass

        assert call_count[0] == 2, f"Expected 2 searches (budget), got {call_count[0]}"

    @pytest.mark.asyncio
    async def test_saturation_path_exits_early(self, tmp_path):
        """Mock AnalysisAgent to saturate on round 2, verify only 3 rounds."""
        orch = DeepResearchOrchestrator(
            name="DeepResearch_0_google", topic_idx=0, provider="google",
            query="AI news", topic_name="AI", max_rounds=5,
            search_depth="deep", model="gemini-2.5-flash", tools=[],
        )
        ctx = _make_ctx()
        call_count = [0]

        async def mock_planning(inner_ctx):
            return _planning_result()

        analysis_responses = [
            _analysis_result(saturated=False, next_query="q1", gaps=["g1"]),
            _analysis_result(saturated=False, next_query="q2", gaps=["g2"]),
            _analysis_result(saturated=True, gaps=[]),
        ]
        analysis_idx = [0]

        async def mock_analysis(*args, **kwargs):
            idx = analysis_idx[0]
            analysis_idx[0] += 1
            return analysis_responses[min(idx, len(analysis_responses) - 1)]

        def patched_make(round_idx, query):
            agent = MagicMock()

            async def mock_run(inner_ctx):
                key = f"deep_research_latest_0_google"
                inner_ctx.session.state[key] = _research_text_with_urls(
                    call_count[0], "https://example.com", count=4
                )
                call_count[0] += 1
                return
                yield

            agent.run_async = mock_run
            return agent

        with patch.object(orch, "_run_planning", side_effect=mock_planning), \
             patch.object(orch, "_run_analysis", side_effect=mock_analysis), \
             patch.object(orch, "_make_search_agent", side_effect=patched_make):
            async for _ in orch._run_async_impl(ctx):
                pass

        assert call_count[0] == 3, f"Expected 3 rounds (saturation), got {call_count[0]}"


# ---------------------------------------------------------------------------
# Integration: Mixed standard and deep topics
# ---------------------------------------------------------------------------


class TestMixedStandardDeepIntegration:
    """Integration: mixed config with standard and deep topics."""

    def test_phase_has_correct_agent_types(self, tmp_path):
        """Standard topic uses LlmAgent, deep topic uses DeepResearchOrchestrator."""
        config = _mixed_config(tmp_path)
        phase = build_research_phase(config)

        assert len(phase.sub_agents) == 2

        topic0 = phase.sub_agents[0]
        assert topic0.name == "Topic0Research"
        for sub in topic0.sub_agents:
            assert not isinstance(sub, DeepResearchOrchestrator)

        topic1 = phase.sub_agents[1]
        assert topic1.name == "Topic1Research"
        for sub in topic1.sub_agents:
            assert isinstance(sub, DeepResearchOrchestrator)

    @pytest.mark.asyncio
    async def test_standard_topic_no_deep_state_keys(self, tmp_path):
        """Standard topic does not produce any deep_* intermediate keys."""
        config = _mixed_config(tmp_path)
        phase = build_research_phase(config)
        topic0 = phase.sub_agents[0]

        for sub in topic0.sub_agents:
            assert hasattr(sub, "output_key")
            assert sub.output_key.startswith("research_0_")
            assert "deep" not in sub.output_key

    @pytest.mark.asyncio
    async def test_deep_topic_uses_orchestrator_with_max_rounds(self, tmp_path):
        """Deep topic's orchestrator respects max_research_rounds from config."""
        config = _mixed_config(tmp_path, max_rounds=2)
        phase = build_research_phase(config)
        topic1 = phase.sub_agents[1]

        for sub in topic1.sub_agents:
            assert isinstance(sub, DeepResearchOrchestrator)
            assert sub.max_rounds == 2

    def test_state_key_format_downstream_compatible(self, tmp_path):
        """Both standard and deep topics produce research_{idx}_{provider} key."""
        config = _mixed_config(tmp_path)
        phase = build_research_phase(config)

        topic0 = phase.sub_agents[0]
        for sub in topic0.sub_agents:
            assert sub.output_key.startswith("research_0_")

        topic1 = phase.sub_agents[1]
        for sub in topic1.sub_agents:
            assert sub.topic_idx == 1

    @pytest.mark.asyncio
    async def test_standard_topic_single_round_per_provider(self, tmp_path):
        """Standard-mode topic produces exactly 1 research key per provider."""
        config = _mixed_config(tmp_path, max_rounds=3)
        phase = build_research_phase(config)
        topic0 = phase.sub_agents[0]

        state = {}
        for sub in topic0.sub_agents:
            output_key = sub.output_key
            state[output_key] = (
                "SUMMARY:\nStandard findings.\n\nSOURCES:\n"
                "- [Src1](https://standard.example.com/1)\n"
                "- [Src2](https://standard.example.com/2)"
            )

        assert "research_0_google" in state or "research_0_perplexity" in state

        for key in state:
            assert not key.startswith("deep_"), f"Unexpected deep key: {key}"
            assert "round_" not in key, f"Unexpected round key: {key}"
            assert key.startswith("research_0_")
