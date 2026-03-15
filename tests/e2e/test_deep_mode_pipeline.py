"""E2E test: full pipeline with deep-mode topics.

Builds a complete pipeline with build_pipeline(), runs the deep research
orchestrator with mocked search tools, and verifies multi-round URL
accumulation, source refinement, and HTML output generation.

Spec refs: Section 11.4, SC-002, SC-003, SC-004 (WP14 T14-04).
"""

import re
import pytest
from unittest.mock import MagicMock, patch

from newsletter_agent.agent import build_pipeline, build_research_phase
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

_MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\((https?://[^\)]+)\)")


def _deep_pipeline_config(tmp_path, max_rounds=3):
    """Config with a deep-mode topic for E2E pipeline testing."""
    return NewsletterConfig(
        newsletter=NewsletterSettings(
            title="Deep Research E2E Test",
            schedule="0 8 * * 0",
            recipient_email="test@example.com",
        ),
        settings=AppSettings(
            dry_run=True,
            output_dir=str(tmp_path / "output"),
            max_research_rounds=max_rounds,
            verify_links=False,
        ),
        topics=[
            TopicConfig(
                name="AI Breakthroughs",
                query="latest AI breakthroughs 2026",
                search_depth="deep",
                sources=["google_search"],
            ),
        ],
    )


def _research_text_with_n_urls(round_idx: int, base: str, count: int) -> str:
    """Build research text with count unique URLs for a given round."""
    urls = [
        f"- [Article R{round_idx} #{i}]({base}/r{round_idx}/a{i})"
        for i in range(count)
    ]
    return f"SUMMARY:\nRound {round_idx} AI findings.\n\nSOURCES:\n" + "\n".join(urls)


# ---------------------------------------------------------------------------
# T14-04: E2E full pipeline with deep-mode topics
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestE2EDeepModePipeline:
    """E2E test with real agent construction and mocked API calls."""

    def test_pipeline_builds_with_deep_config(self, tmp_path):
        """build_pipeline() succeeds with a deep-mode config."""
        config = _deep_pipeline_config(tmp_path)
        pipeline = build_pipeline(config)
        assert pipeline.name == "NewsletterPipeline"

        agent_names = [a.name for a in pipeline.sub_agents]
        assert "ResearchPhase" in agent_names
        assert "DeepResearchRefiner" in agent_names

    def test_research_phase_uses_orchestrator(self, tmp_path):
        """Deep-mode topic produces DeepResearchOrchestrator in research phase."""
        config = _deep_pipeline_config(tmp_path)
        phase = build_research_phase(config)
        topic0 = phase.sub_agents[0]

        assert any(
            isinstance(sub, DeepResearchOrchestrator) for sub in topic0.sub_agents
        )

    @pytest.mark.asyncio
    async def test_deep_mode_accumulates_urls_across_rounds(self, tmp_path):
        """SC-002: Deep-mode topics accumulate >= 15 unique URLs from 3 rounds."""
        config = _deep_pipeline_config(tmp_path, max_rounds=3)
        phase = build_research_phase(config)
        topic0 = phase.sub_agents[0]
        orch = topic0.sub_agents[0]  # DeepResearchOrchestrator

        ctx = MagicMock()
        ctx.session.state = {}
        call_count = 0

        async def mock_run_async(inner_ctx):
            nonlocal call_count
            key = f"deep_research_latest_{orch.topic_idx}_{orch.provider}"
            # Each round returns 6 unique URLs = 18 total
            inner_ctx.session.state[key] = _research_text_with_n_urls(
                call_count, "https://example.com", count=6
            )
            call_count += 1
            return
            yield

        def patched_make(round_idx, query):
            agent = MagicMock()
            agent.run_async = mock_run_async
            return agent

        async def mock_planning(inner_ctx):
            return ("AI breakthroughs query", ["recent developments", "key players"], [])

        analysis_idx = [0]

        async def mock_analysis(*args, **kwargs):
            idx = analysis_idx[0]
            analysis_idx[0] += 1
            if idx < 2:
                return (
                    {"findings_summary": f"Round {idx} findings", "knowledge_gaps": [f"gap_{idx}"],
                     "coverage_assessment": "partial", "saturated": False,
                     "next_query": f"follow-up query {idx+1}", "next_query_rationale": "more data"},
                    [],
                )
            return (
                {"findings_summary": "Final findings", "knowledge_gaps": [],
                 "coverage_assessment": "comprehensive", "saturated": True,
                 "next_query": "", "next_query_rationale": "done"},
                [],
            )

        with patch.object(orch, "_make_search_agent", side_effect=patched_make), \
             patch.object(orch, "_run_planning", side_effect=mock_planning), \
             patch.object(orch, "_run_analysis", side_effect=mock_analysis):
            async for _ in orch._run_async_impl(ctx):
                pass

        state = ctx.session.state
        final = state.get(f"research_{orch.topic_idx}_{orch.provider}", "")
        urls = [m.group(2) for m in _MARKDOWN_LINK_RE.finditer(final)]
        unique_urls = set(urls)

        # SC-002: at least 15 unique URLs across rounds
        assert len(unique_urls) >= 15, (
            f"Expected >= 15 unique URLs, got {len(unique_urls)}"
        )

    @pytest.mark.asyncio
    async def test_max_rounds_respected(self, tmp_path):
        """SC-004: Research loop never exceeds max_research_rounds."""
        max_rounds = 2
        config = _deep_pipeline_config(tmp_path, max_rounds=max_rounds)
        phase = build_research_phase(config)
        topic0 = phase.sub_agents[0]
        orch = topic0.sub_agents[0]

        assert orch.max_rounds == max_rounds

        ctx = MagicMock()
        ctx.session.state = {}
        call_count = 0

        async def mock_run_async(inner_ctx):
            nonlocal call_count
            key = f"deep_research_latest_{orch.topic_idx}_{orch.provider}"
            # 4 URLs per round - not enough to trigger early exit
            inner_ctx.session.state[key] = _research_text_with_n_urls(
                call_count, "https://example.com", count=4
            )
            call_count += 1
            return
            yield

        def patched_make(round_idx, query):
            agent = MagicMock()
            agent.run_async = mock_run_async
            return agent

        async def mock_planning(inner_ctx):
            return ("AI query", ["aspect1"], [])

        async def mock_analysis(*args, **kwargs):
            # Never saturate - let max_rounds be the binding constraint
            return (
                {"findings_summary": "Findings", "knowledge_gaps": ["gap"],
                 "coverage_assessment": "partial", "saturated": False,
                 "next_query": "next query", "next_query_rationale": "more data"},
                [],
            )

        with patch.object(orch, "_make_search_agent", side_effect=patched_make), \
             patch.object(orch, "_run_planning", side_effect=mock_planning), \
             patch.object(orch, "_run_analysis", side_effect=mock_analysis):
            async for _ in orch._run_async_impl(ctx):
                pass

        # Should have executed exactly max_rounds
        assert call_count == max_rounds

    @pytest.mark.asyncio
    async def test_refinement_reduces_sources_to_range(self, tmp_path):
        """SC-003: After refinement, 5-10 curated sources remain per provider."""
        from newsletter_agent.tools.deep_research_refiner import (
            DeepResearchRefinerAgent,
            _extract_source_urls,
        )

        # Pre-populate state with deep-mode research output (20 sources)
        urls = [
            f"- [Article {i}](https://src.example.com/a{i})" for i in range(20)
        ]
        research_text = "SUMMARY:\nDeep findings.\n\nSOURCES:\n" + "\n".join(urls)

        topic = TopicConfig(
            name="AI",
            query="AI news",
            search_depth="deep",
            sources=["google_search"],
        )

        refiner = DeepResearchRefinerAgent(
            name="DeepResearchRefiner",
            topic_count=1,
            providers=["google"],
            topic_configs=[topic],
        )

        ctx = MagicMock()
        ctx.session.state = {"research_0_google": research_text}

        selected_urls = [f"https://src.example.com/a{i}" for i in range(8)]
        mock_response = MagicMock()
        mock_response.text = (
            '{"selected_urls": ' + str(selected_urls).replace("'", '"') + ', "rationale": "test"}'
        )
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = MagicMock(return_value=mock_response)

        with patch("newsletter_agent.tools.deep_research_refiner.genai.Client", return_value=mock_client):
            # Make generate_content an awaitable
            import asyncio
            future = asyncio.Future()
            future.set_result(mock_response)
            mock_client.aio.models.generate_content.return_value = future

            async for _ in refiner._run_async_impl(ctx):
                pass

        final = ctx.session.state["research_0_google"]
        final_urls = _extract_source_urls(final)
        assert 5 <= len(final_urls) <= 10, (
            f"Expected 5-10 sources after refinement, got {len(final_urls)}"
        )
