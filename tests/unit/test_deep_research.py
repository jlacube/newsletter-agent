"""Unit tests for DeepResearchOrchestrator.

Covers: URL tracking, round merging, state cleanup, helper methods,
and backward-compatible instantiation.

Spec refs: FR-ADR-001 through FR-ADR-085, Section 11.1.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from newsletter_agent.tools.deep_research import (
    DeepResearchOrchestrator,
    _MARKDOWN_LINK_RE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(state: dict | None = None) -> MagicMock:
    """Create a mock InvocationContext with session state."""
    ctx = MagicMock()
    ctx.session.state = state if state is not None else {}
    return ctx


def _make_orchestrator(**overrides) -> DeepResearchOrchestrator:
    """Create a DeepResearchOrchestrator with sensible defaults."""
    defaults = dict(
        name="DeepResearch_0_google",
        topic_idx=0,
        provider="google",
        query="AI news latest developments",
        topic_name="Artificial Intelligence",
        max_rounds=3,
        search_depth="deep",
        model="gemini-2.5-flash",
        tools=[],
    )
    defaults.update(overrides)
    return DeepResearchOrchestrator(**defaults)


def _research_text(urls: list[tuple[str, str]], summary: str = "Some findings") -> str:
    """Build research text with markdown links."""
    sources = "\n".join(f"- [{t}]({u})" for t, u in urls)
    return f"SUMMARY:\n{summary}\n\nSOURCES:\n{sources}"


async def _mock_search_round(ctx, output_key, content):
    """Simulate what a search LlmAgent does: write to output_key in state."""
    ctx.session.state[output_key] = content
    return
    yield  # make it an async generator


# ---------------------------------------------------------------------------
# Test: Class instantiation and properties (T12-03)
# ---------------------------------------------------------------------------


class TestOrchestratorInstantiation:

    def test_creates_with_required_fields(self):
        orch = _make_orchestrator()
        assert orch.topic_idx == 0
        assert orch.provider == "google"
        assert orch.query == "AI news latest developments"
        assert orch.topic_name == "Artificial Intelligence"
        assert orch.max_rounds == 3
        assert orch.search_depth == "deep"

    def test_max_searches_default(self):
        orch = _make_orchestrator()
        assert orch.max_searches == 3

    def test_min_rounds_default(self):
        orch = _make_orchestrator()
        assert orch.min_rounds == 2

    def test_custom_max_searches(self):
        orch = _make_orchestrator(max_searches=5)
        assert orch.max_searches == 5

    def test_custom_min_rounds(self):
        orch = _make_orchestrator(min_rounds=1)
        assert orch.min_rounds == 1

    def test_is_base_agent(self):
        from google.adk.agents import BaseAgent
        orch = _make_orchestrator()
        assert isinstance(orch, BaseAgent)

    def test_perplexity_provider(self):
        orch = _make_orchestrator(provider="perplexity")
        assert orch.provider == "perplexity"


# ---------------------------------------------------------------------------
# Test: URL extraction regex (T12-06)
# ---------------------------------------------------------------------------


class TestURLExtraction:

    def test_extracts_http_urls(self):
        text = "See [Article](http://example.com) and [Other](http://other.com)"
        urls = DeepResearchOrchestrator._extract_urls(text)
        assert urls == {"http://example.com", "http://other.com"}

    def test_extracts_https_urls(self):
        text = "Check [Title](https://example.com/path?q=1)"
        urls = DeepResearchOrchestrator._extract_urls(text)
        assert urls == {"https://example.com/path?q=1"}

    def test_empty_text_returns_empty_set(self):
        assert DeepResearchOrchestrator._extract_urls("") == set()

    def test_none_text_returns_empty_set(self):
        assert DeepResearchOrchestrator._extract_urls(None) == set()

    def test_no_links_returns_empty_set(self):
        assert DeepResearchOrchestrator._extract_urls("plain text only") == set()

    def test_excludes_image_links(self):
        text = "![image](http://img.com/pic.png) and [link](http://link.com)"
        urls = DeepResearchOrchestrator._extract_urls(text)
        assert urls == {"http://link.com"}

    def test_deduplicates_same_url(self):
        text = "[A](https://a.com) and [B](https://a.com)"
        urls = DeepResearchOrchestrator._extract_urls(text)
        assert urls == {"https://a.com"}

    def test_extracts_bare_urls(self):
        text = (
            "- RAG in 2026 - ZDNET\n"
            "  https://vertexaisearch.cloud.google.com/grounding-api-redirect/ABC123\n"
            "- Another Article - TechCrunch\n"
            "  https://vertexaisearch.cloud.google.com/grounding-api-redirect/DEF456"
        )
        urls = DeepResearchOrchestrator._extract_urls(text)
        assert "https://vertexaisearch.cloud.google.com/grounding-api-redirect/ABC123" in urls
        assert "https://vertexaisearch.cloud.google.com/grounding-api-redirect/DEF456" in urls
        assert len(urls) == 2

    def test_extracts_mixed_markdown_and_bare_urls(self):
        text = (
            "SOURCES:\n"
            "- [Markdown Source](https://example.com/article1)\n"
            "- Bare Source Title\n"
            "  https://vertexaisearch.cloud.google.com/grounding-api-redirect/XYZ\n"
        )
        urls = DeepResearchOrchestrator._extract_urls(text)
        assert "https://example.com/article1" in urls
        assert "https://vertexaisearch.cloud.google.com/grounding-api-redirect/XYZ" in urls
        assert len(urls) == 2

    def test_does_not_double_count_markdown_urls(self):
        text = "[Title](https://example.com/page)"
        urls = DeepResearchOrchestrator._extract_urls(text)
        assert urls == {"https://example.com/page"}


# ---------------------------------------------------------------------------
# Test: Section splitting (T12-07)
# ---------------------------------------------------------------------------


class TestSplitSections:

    def test_splits_summary_and_sources(self):
        text = "SUMMARY:\nHello world\n\nSOURCES:\n- [A](http://a.com)"
        summ, src = DeepResearchOrchestrator._split_sections(text)
        assert "Hello world" in summ
        assert "[A](http://a.com)" in src

    def test_no_summary_header(self):
        text = "Just text\n\nSOURCES:\n- [A](http://a.com)"
        summ, src = DeepResearchOrchestrator._split_sections(text)
        assert "Just text" in summ
        assert "[A](http://a.com)" in src

    def test_no_sources_header(self):
        text = "SUMMARY:\nOnly summary"
        summ, src = DeepResearchOrchestrator._split_sections(text)
        assert "Only summary" in summ
        assert src == ""


# ---------------------------------------------------------------------------
# Test: Round merging (T12-07)
# ---------------------------------------------------------------------------


class TestMergeRounds:

    def test_merges_two_rounds(self):
        state = {
            "research_0_google_round_0": _research_text(
                [("A", "https://a.com")], "Round 0 findings"
            ),
            "research_0_google_round_1": _research_text(
                [("B", "https://b.com")], "Round 1 findings"
            ),
        }
        orch = _make_orchestrator()
        merged = orch._merge_rounds(state, 2)

        assert "SUMMARY:" in merged
        assert "SOURCES:" in merged
        assert "Round 0 findings" in merged
        assert "Round 1 findings" in merged
        assert "https://a.com" in merged
        assert "https://b.com" in merged

    def test_deduplicates_urls_across_rounds(self):
        state = {
            "research_0_google_round_0": _research_text(
                [("A", "https://a.com"), ("B", "https://b.com")]
            ),
            "research_0_google_round_1": _research_text(
                [("A copy", "https://a.com"), ("C", "https://c.com")]
            ),
        }
        orch = _make_orchestrator()
        merged = orch._merge_rounds(state, 2)

        # Count URL occurrences in SOURCES section
        sources_section = merged.split("SOURCES:")[1]
        assert sources_section.count("https://a.com") == 1
        assert sources_section.count("https://b.com") == 1
        assert sources_section.count("https://c.com") == 1

    def test_empty_rounds_return_empty_string(self):
        state = {
            "research_0_google_round_0": "",
            "research_0_google_round_1": "",
        }
        orch = _make_orchestrator()
        assert orch._merge_rounds(state, 2) == ""

    def test_single_round_merge(self):
        state = {
            "research_0_google_round_0": _research_text(
                [("A", "https://a.com")], "Only round"
            ),
        }
        orch = _make_orchestrator()
        merged = orch._merge_rounds(state, 1)
        assert "Only round" in merged
        assert "https://a.com" in merged

    def test_missing_round_keys_handled(self):
        state = {
            "research_0_google_round_0": _research_text(
                [("A", "https://a.com")], "First"
            ),
            # round_1 missing
        }
        orch = _make_orchestrator()
        merged = orch._merge_rounds(state, 2)
        assert "First" in merged

    def test_merges_bare_url_sources(self):
        """Bare URLs (Google grounding format) are collected during merge."""
        state = {
            "research_0_google_round_0": (
                "SUMMARY:\nGrounding findings.\n\n"
                "SOURCES:\n"
                "- RAG in 2026 - Squirro\n"
                "  https://vertexaisearch.cloud.google.com/grounding-api-redirect/ABC\n"
                "- AI News Today - ZDNET\n"
                "  https://vertexaisearch.cloud.google.com/grounding-api-redirect/DEF\n"
            ),
        }
        orch = _make_orchestrator()
        merged = orch._merge_rounds(state, 1)
        assert "SOURCES:" in merged
        assert "vertexaisearch.cloud.google.com/grounding-api-redirect/ABC" in merged
        assert "vertexaisearch.cloud.google.com/grounding-api-redirect/DEF" in merged
        assert "RAG in 2026" in merged
        assert "AI News Today" in merged

    def test_merges_mixed_markdown_and_bare_sources(self):
        """Both markdown links and bare URLs are captured in merged output."""
        state = {
            "research_0_google_round_0": (
                "SUMMARY:\nMixed format.\n\n"
                "SOURCES:\n"
                "- [Markdown Source](https://example.com/article1)\n"
                "- Bare Source Title\n"
                "  https://vertexaisearch.cloud.google.com/grounding-api-redirect/XYZ\n"
            ),
        }
        orch = _make_orchestrator()
        merged = orch._merge_rounds(state, 1)
        sources = merged.split("SOURCES:")[1]
        assert "https://example.com/article1" in sources
        assert "vertexaisearch.cloud.google.com/grounding-api-redirect/XYZ" in sources


# ---------------------------------------------------------------------------
# Test: State cleanup (T12-07)
# ---------------------------------------------------------------------------


class TestStateCleanup:

    def test_removes_intermediate_keys(self):
        state = {
            "adaptive_plan_0_google": '{"key": "value"}',
            "adaptive_analysis_0_google": '{"key": "value"}',
            "adaptive_context_0_google": '{"key": "value"}',
            "deep_research_latest_0_google": "latest",
            "deep_urls_accumulated_0_google": ["http://a.com"],
            "research_0_google_round_0": "round 0",
            "research_0_google_round_1": "round 1",
            "research_0_google": "final merged",
            "adaptive_reasoning_chain_0_google": '{"plan": {}}',
            "unrelated_key": "keep me",
        }
        orch = _make_orchestrator()
        orch._cleanup_state(state, 2)

        assert "adaptive_plan_0_google" not in state
        assert "adaptive_analysis_0_google" not in state
        assert "adaptive_context_0_google" not in state
        assert "deep_research_latest_0_google" not in state
        assert "deep_urls_accumulated_0_google" not in state
        assert "research_0_google_round_0" not in state
        assert "research_0_google_round_1" not in state
        # Should NOT remove the final merged key or reasoning chain
        assert state["research_0_google"] == "final merged"
        assert state["adaptive_reasoning_chain_0_google"] == '{"plan": {}}'
        assert state["unrelated_key"] == "keep me"


# ---------------------------------------------------------------------------
# Test: Full orchestrator run (adapted for adaptive loop)
# ---------------------------------------------------------------------------


class TestOrchestratorRun:

    @pytest.mark.asyncio
    async def test_max_rounds_1_skips_planning_and_analysis(self):
        """When max_rounds=1, no planning/analysis, single round only. FR-ADR-080."""
        orch = _make_orchestrator(max_rounds=1)
        ctx = _make_ctx()

        round_output = _research_text(
            [("A", "https://a.com"), ("B", "https://b.com")],
            "Single round findings",
        )

        with patch.object(orch, "_make_search_agent") as mock_make:
            mock_agent = MagicMock()

            async def fake_run_async(run_ctx):
                run_ctx.session.state["deep_research_latest_0_google"] = round_output
                return
                yield

            mock_agent.run_async = fake_run_async
            mock_make.return_value = mock_agent

            events = []
            async for event in orch._run_async_impl(ctx):
                events.append(event)

        # Should have written the final merged key
        assert "research_0_google" in ctx.session.state
        assert "Single round findings" in ctx.session.state["research_0_google"]
        # Intermediate keys should be cleaned up
        assert "deep_research_latest_0_google" not in ctx.session.state

    @pytest.mark.asyncio
    async def test_perplexity_provider_creates_correct_agent(self):
        """Perplexity provider uses perplexity search instruction."""
        orch = _make_orchestrator(provider="perplexity", max_rounds=1)

        agent = orch._make_search_agent(0, "test query")
        assert "DeepSearchRound" in agent.name
        assert agent.output_key == "deep_research_latest_0_perplexity"

    @pytest.mark.asyncio
    async def test_google_provider_creates_correct_agent(self):
        """Google provider uses google search instruction."""
        orch = _make_orchestrator(provider="google", max_rounds=1)

        agent = orch._make_search_agent(0, "test query")
        assert "DeepSearchRound" in agent.name
        assert agent.output_key == "deep_research_latest_0_google"
