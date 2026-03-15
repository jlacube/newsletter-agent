"""Performance benchmark: deep research pipeline timing.

Establishes baseline timings for deep-mode research with mocked tools.
Advisory only - does not enforce hard pass/fail thresholds in CI.

Spec refs: Section 10.1, Section 11.5 (WP14 T14-08).
"""

import time

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


def _deep_config(tmp_path, n_topics=1, max_rounds=3):
    topics = [
        TopicConfig(
            name=f"Deep Topic {i}",
            query=f"latest developments in deep topic {i}",
            search_depth="deep",
            sources=["google_search", "perplexity"],
        )
        for i in range(n_topics)
    ]
    settings_kwargs = {
        "dry_run": True,
        "output_dir": str(tmp_path),
        "max_research_rounds": max_rounds,
    }
    if max_rounds < 2:
        settings_kwargs["min_research_rounds"] = max_rounds
    return NewsletterConfig(
        newsletter=NewsletterSettings(
            title="Deep Research Perf Test",
            schedule="0 8 * * 0",
            recipient_email="test@example.com",
        ),
        settings=AppSettings(**settings_kwargs),
        topics=topics,
    )


@pytest.mark.performance
class TestDeepResearchBuildPerformance:
    """Agent tree construction timing for deep-mode topics."""

    def test_build_1_deep_topic_under_500ms(self, tmp_path):
        config = _deep_config(tmp_path, n_topics=1, max_rounds=3)
        start = time.monotonic()
        phase = build_research_phase(config)
        elapsed = time.monotonic() - start
        assert elapsed < 0.5, f"1-deep-topic build took {elapsed:.3f}s"
        assert len(phase.sub_agents) == 1

    def test_build_3_deep_topics_under_1s(self, tmp_path):
        config = _deep_config(tmp_path, n_topics=3, max_rounds=3)
        start = time.monotonic()
        phase = build_research_phase(config)
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, f"3-deep-topic build took {elapsed:.3f}s"
        assert len(phase.sub_agents) == 3

    def test_build_10_deep_topics_under_2s(self, tmp_path):
        config = _deep_config(tmp_path, n_topics=10, max_rounds=3)
        start = time.monotonic()
        phase = build_research_phase(config)
        elapsed = time.monotonic() - start
        assert elapsed < 2.0, f"10-deep-topic build took {elapsed:.3f}s"
        assert len(phase.sub_agents) == 10


@pytest.mark.performance
class TestDeepResearchRoundPerformance:
    """Per-round latency with mocked tools."""

    @pytest.mark.asyncio
    async def test_single_round_under_1s(self, tmp_path):
        """A single mocked research round completes in < 1s."""
        config = _deep_config(tmp_path, n_topics=1, max_rounds=1)
        phase = build_research_phase(config)
        orch = phase.sub_agents[0].sub_agents[0]

        ctx = MagicMock()
        ctx.session.state = {}

        async def mock_run_async(inner_ctx):
            key = f"deep_research_latest_{orch.topic_idx}_{orch.provider}"
            inner_ctx.session.state[key] = (
                "SUMMARY:\nFindings.\n\nSOURCES:\n"
                "- [S1](https://ex.com/1)\n- [S2](https://ex.com/2)"
            )
            return
            yield

        def patched_make(round_idx, query):
            agent = MagicMock()
            agent.run_async = mock_run_async
            return agent

        start = time.monotonic()
        with patch.object(orch, "_make_search_agent", side_effect=patched_make):
            async for _ in orch._run_async_impl(ctx):
                pass
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, f"Single round took {elapsed:.3f}s"

    @pytest.mark.asyncio
    async def test_three_rounds_under_5s(self, tmp_path):
        """Three mocked research rounds complete in < 5s total."""
        config = _deep_config(tmp_path, n_topics=1, max_rounds=3)
        phase = build_research_phase(config)
        orch = phase.sub_agents[0].sub_agents[0]

        ctx = MagicMock()
        ctx.session.state = {}
        round_counter = 0

        async def mock_run_async(inner_ctx):
            nonlocal round_counter
            round_counter += 1
            key = f"deep_research_latest_{orch.topic_idx}_{orch.provider}"
            inner_ctx.session.state[key] = (
                f"SUMMARY:\nRound {round_counter} findings.\n\nSOURCES:\n"
                f"- [S{round_counter}a](https://ex.com/r{round_counter}a)\n"
                f"- [S{round_counter}b](https://ex.com/r{round_counter}b)"
            )
            return
            yield

        def patched_make(round_idx, query):
            agent = MagicMock()
            agent.run_async = mock_run_async
            return agent

        async def mock_expand(inner_ctx):
            return [f"expanded query round {round_counter + 1}"], []

        start = time.monotonic()
        with patch.object(orch, "_make_search_agent", side_effect=patched_make):
            with patch.object(orch, "_expand_queries", side_effect=mock_expand):
                async for _ in orch._run_async_impl(ctx):
                    pass
        elapsed = time.monotonic() - start
        assert elapsed < 5.0, f"Three rounds took {elapsed:.3f}s"


@pytest.mark.performance
class TestDeepResearchPipelineTiming:
    """Full pipeline build timing with deep-mode topics."""

    def test_full_pipeline_build_under_2s(self, tmp_path):
        """Full pipeline with 3 deep topics builds in < 2s."""
        config = _deep_config(tmp_path, n_topics=3, max_rounds=3)
        start = time.monotonic()
        pipeline = build_pipeline(config)
        elapsed = time.monotonic() - start
        assert elapsed < 2.0, f"Pipeline build took {elapsed:.3f}s"
        assert pipeline.name == "NewsletterPipeline"
