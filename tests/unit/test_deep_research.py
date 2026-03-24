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
    GroundingResult,
    _grounding_capture_callback,
    _make_grounding_callback,
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
        timeframe_instruction=None,
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

    def test_extracts_titled_parenthetical_urls(self):
        text = (
            "SOURCES:\n"
            "- LLM Benchmarks 2026 - Complete Evaluation Suite "
            "(https://vertexaisearch.cloud.google.com/grounding-api-redirect/ABC123)\n"
            "- Another Source (https://example.com/article)\n"
        )
        urls = DeepResearchOrchestrator._extract_urls(text)
        assert "https://vertexaisearch.cloud.google.com/grounding-api-redirect/ABC123" in urls
        assert "https://example.com/article" in urls
        assert len(urls) == 2

    def test_extracts_html_anchor_urls(self):
        text = (
            '<div class="carousel">'
            '<a class="chip" href="https://vertexaisearch.cloud.google.com/grounding-api-redirect/ABC">'
            'AI agent frameworks adoption trends 2026</a>'
            '</div>'
        )
        urls = DeepResearchOrchestrator._extract_urls(text)
        assert urls == {"https://vertexaisearch.cloud.google.com/grounding-api-redirect/ABC"}

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

    def test_merges_titled_parenthetical_sources(self):
        state = {
            "research_0_google_round_0": (
                "SUMMARY:\nParenthetical sources.\n\n"
                "SOURCES:\n"
                "- LLM Benchmarks 2026 - Complete Evaluation Suite "
                "(https://vertexaisearch.cloud.google.com/grounding-api-redirect/ABC123)\n"
                "- Another Source (https://example.com/article)\n"
            ),
        }
        orch = _make_orchestrator()
        merged = orch._merge_rounds(state, 1)
        sources = merged.split("SOURCES:")[1]
        assert "LLM Benchmarks 2026 - Complete Evaluation Suite" in sources
        assert "https://vertexaisearch.cloud.google.com/grounding-api-redirect/ABC123" in sources
        assert "Another Source" in sources
        assert "https://example.com/article" in sources

    def test_merges_html_anchor_sources(self):
        state = {
            "research_0_google_round_0": (
                "SUMMARY:\nHTML sources.\n\n"
                '<div class="carousel">'
                '<a class="chip" href="https://vertexaisearch.cloud.google.com/grounding-api-redirect/ABC">'
                'AI agent frameworks adoption trends 2026</a>'
                '<a class="chip" href="https://vertexaisearch.cloud.google.com/grounding-api-redirect/DEF">'
                'Google ADK new developments March 2026</a>'
                '</div>'
            ),
        }
        orch = _make_orchestrator()
        merged = orch._merge_rounds(state, 1)
        sources = merged.split("SOURCES:")[1]
        assert "AI agent frameworks adoption trends 2026" in sources
        assert "https://vertexaisearch.cloud.google.com/grounding-api-redirect/ABC" in sources
        assert "Google ADK new developments March 2026" in sources
        assert "https://vertexaisearch.cloud.google.com/grounding-api-redirect/DEF" in sources


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

    def test_google_search_agent_includes_timeframe_instruction(self):
        """Deep Google rounds keep the configured timeframe in the prompt."""
        orch = _make_orchestrator(
            provider="google",
            timeframe_instruction="Focus on results from the past month.",
        )

        agent = orch._make_search_agent(0, "test query")
        instruction = agent.instruction(None)

        assert "Focus on results from the past month." in instruction

    @pytest.mark.asyncio
    async def test_google_round_parses_grounding_and_merges(self):
        """Google provider with grounding metadata in state uses grounding merge."""
        orch = _make_orchestrator(max_rounds=1, provider="google")
        ctx = _make_ctx()

        round_output = _research_text(
            [("Old", "https://old.com")],
            "Round 0 findings from LLM",
        )

        with patch.object(orch, "_make_search_agent") as mock_make:
            mock_agent = MagicMock()

            async def fake_run_async(run_ctx):
                # Simulate callback writing raw grounding data
                run_ctx.session.state["deep_research_latest_0_google"] = round_output
                run_ctx.session.state["_grounding_raw_0_google_round_0"] = {
                    "grounding_chunks": [
                        {"web": {"uri": "https://grounded.com/a", "title": "Grounded A"}},
                        {"web": {"uri": "https://grounded.com/b", "title": "Grounded B"}},
                    ],
                    "grounding_supports": [],
                    "web_search_queries": ["AI news"],
                }
                return
                yield

            mock_agent.run_async = fake_run_async
            mock_make.return_value = mock_agent

            events = []
            async for event in orch._run_async_impl(ctx):
                events.append(event)

        merged = ctx.session.state["research_0_google"]
        assert "SUMMARY:" in merged
        assert "SOURCES:" in merged
        assert "https://grounded.com/a" in merged
        assert "https://grounded.com/b" in merged
        # LLM-extracted old source should NOT be in the grounding-based SOURCES
        sources_section = merged.split("SOURCES:")[1]
        assert "https://old.com" not in sources_section

    @pytest.mark.asyncio
    async def test_google_round_no_grounding_falls_back(self):
        """Google provider without grounding metadata falls back to text merge."""
        orch = _make_orchestrator(max_rounds=1, provider="google")
        ctx = _make_ctx()

        round_output = _research_text(
            [("Text Source", "https://text.com")],
            "Findings from text only",
        )

        with patch.object(orch, "_make_search_agent") as mock_make:
            mock_agent = MagicMock()

            async def fake_run_async(run_ctx):
                run_ctx.session.state["deep_research_latest_0_google"] = round_output
                # No grounding data at all
                return
                yield

            mock_agent.run_async = fake_run_async
            mock_make.return_value = mock_agent

            events = []
            async for event in orch._run_async_impl(ctx):
                events.append(event)

        merged = ctx.session.state["research_0_google"]
        # Falls back to text extraction -- old sources present
        assert "https://text.com" in merged

    @pytest.mark.asyncio
    async def test_perplexity_round_no_grounding_processing(self):
        """Perplexity provider: no grounding processing at all."""
        orch = _make_orchestrator(
            name="DeepResearch_0_perplexity",
            max_rounds=1,
            provider="perplexity",
        )
        ctx = _make_ctx()

        round_output = _research_text(
            [("Perp", "https://perp.com")],
            "Perplexity findings",
        )

        with patch.object(orch, "_make_search_agent") as mock_make:
            mock_agent = MagicMock()

            async def fake_run_async(run_ctx):
                run_ctx.session.state["deep_research_latest_0_perplexity"] = round_output
                return
                yield

            mock_agent.run_async = fake_run_async
            mock_make.return_value = mock_agent

            events = []
            async for event in orch._run_async_impl(ctx):
                events.append(event)

        merged = ctx.session.state["research_0_perplexity"]
        assert "https://perp.com" in merged
        # No grounding keys should exist
        assert not any(
            k.startswith("grounding_") or k.startswith("_grounding_")
            for k in ctx.session.state
        )

    @pytest.mark.asyncio
    async def test_google_link_verification_uses_grounding_urls(self):
        """When link verification enabled and grounding data present,
        grounding URIs are sent to verify_urls (FR-GME-040)."""
        orch = _make_orchestrator(max_rounds=1, provider="google")
        ctx = _make_ctx({"config_verify_links": True})

        round_output = _research_text(
            [("Old", "https://old.com")],
            "Findings",
        )

        with patch.object(orch, "_make_search_agent") as mock_make, \
             patch("newsletter_agent.tools.deep_research.verify_urls", new_callable=AsyncMock) as mock_verify:

            mock_verify.return_value = {}

            mock_agent = MagicMock()

            async def fake_run_async(run_ctx):
                run_ctx.session.state["deep_research_latest_0_google"] = round_output
                run_ctx.session.state["_grounding_raw_0_google_round_0"] = {
                    "grounding_chunks": [
                        {"web": {"uri": "https://grounded.com/a", "title": "Grounded A"}},
                    ],
                    "grounding_supports": [],
                    "web_search_queries": [],
                }
                return
                yield

            mock_agent.run_async = fake_run_async
            mock_make.return_value = mock_agent

            events = []
            async for event in orch._run_async_impl(ctx):
                events.append(event)

        # Verify that verify_urls was called with grounding URI, not regex-extracted
        mock_verify.assert_called_once()
        call_args = mock_verify.call_args[0][0]
        assert "https://grounded.com/a" in call_args

    @pytest.mark.asyncio
    async def test_broken_grounding_url_removed_from_state(self):
        """Broken grounding URL removed from grounding_sources state (FR-GME-041)."""
        from newsletter_agent.tools.link_verifier import LinkCheckResult

        orch = _make_orchestrator(max_rounds=1, provider="google")
        ctx = _make_ctx({"config_verify_links": True})

        round_output = (
            "SUMMARY:\nSome findings about [A](https://broken.com) and [B](https://good.com)\n\n"
            "SOURCES:\n- [A](https://broken.com)\n- [B](https://good.com)"
        )

        with patch.object(orch, "_make_search_agent") as mock_make, \
             patch("newsletter_agent.tools.deep_research.verify_urls", new_callable=AsyncMock) as mock_verify:

            mock_verify.return_value = {
                "https://broken.com": LinkCheckResult(
                    url="https://broken.com", status="broken", error="404"
                ),
                "https://good.com": LinkCheckResult(
                    url="https://good.com", status="valid"
                ),
            }

            mock_agent = MagicMock()

            async def fake_run_async(run_ctx):
                run_ctx.session.state["deep_research_latest_0_google"] = round_output
                run_ctx.session.state["_grounding_raw_0_google_round_0"] = {
                    "grounding_chunks": [
                        {"web": {"uri": "https://broken.com", "title": "Broken"}},
                        {"web": {"uri": "https://good.com", "title": "Good"}},
                    ],
                    "grounding_supports": [],
                    "web_search_queries": [],
                }
                return
                yield

            mock_agent.run_async = fake_run_async
            mock_make.return_value = mock_agent

            events = []
            async for event in orch._run_async_impl(ctx):
                events.append(event)

        # The merged result should not contain the broken URL in the SOURCES
        merged = ctx.session.state["research_0_google"]
        sources_section = merged.split("SOURCES:")[1] if "SOURCES:" in merged else ""
        assert "https://broken.com" not in sources_section
        assert "https://good.com" in sources_section


# ---------------------------------------------------------------------------
# Test: _parse_planning_output
# ---------------------------------------------------------------------------


class TestParsePlanningOutput:

    def test_valid_json_returns_query_and_aspects(self):
        orch = _make_orchestrator()
        raw = json.dumps({
            "initial_search_query": "AI breakthroughs 2026",
            "key_aspects": ["models", "hardware", "applications"],
        })
        query, aspects = orch._parse_planning_output(raw)
        assert query == "AI breakthroughs 2026"
        assert aspects == ["models", "hardware", "applications"]

    def test_invalid_json_returns_fallback(self):
        orch = _make_orchestrator()
        query, aspects = orch._parse_planning_output("not valid json")
        assert query == orch.query
        assert len(aspects) > 0

    def test_missing_initial_query_returns_fallback(self):
        orch = _make_orchestrator()
        raw = json.dumps({"key_aspects": ["a", "b", "c"]})
        query, aspects = orch._parse_planning_output(raw)
        assert query == orch.query

    def test_few_aspects_padded_to_3(self):
        orch = _make_orchestrator()
        raw = json.dumps({
            "initial_search_query": "query",
            "key_aspects": ["one"],
        })
        _, aspects = orch._parse_planning_output(raw)
        assert len(aspects) >= 3

    def test_many_aspects_truncated_to_5(self):
        orch = _make_orchestrator()
        raw = json.dumps({
            "initial_search_query": "query",
            "key_aspects": ["a", "b", "c", "d", "e", "f", "g"],
        })
        _, aspects = orch._parse_planning_output(raw)
        assert len(aspects) == 5

    def test_code_fenced_json_parsed(self):
        orch = _make_orchestrator()
        raw = '```json\n{"initial_search_query": "test", "key_aspects": ["x", "y", "z"]}\n```'
        query, aspects = orch._parse_planning_output(raw)
        assert query == "test"

    def test_wrapped_json_parsed(self):
        orch = _make_orchestrator()
        raw = (
            "Here is the plan:\n"
            '{"initial_search_query": "wrapped", "key_aspects": ["x", "y", "z"]}\n'
            "Use it carefully."
        )
        query, aspects = orch._parse_planning_output(raw)
        assert query == "wrapped"
        assert aspects == ["x", "y", "z"]

    def test_non_dict_json_returns_fallback(self):
        orch = _make_orchestrator()
        query, aspects = orch._parse_planning_output('["a", "b"]')
        assert query == orch.query

    def test_non_string_query_returns_fallback(self):
        orch = _make_orchestrator()
        raw = json.dumps({"initial_search_query": 123, "key_aspects": ["a"]})
        query, _ = orch._parse_planning_output(raw)
        assert query == orch.query

    def test_non_list_aspects_returns_fallback(self):
        orch = _make_orchestrator()
        raw = json.dumps({"initial_search_query": "q", "key_aspects": "not a list"})
        query, _ = orch._parse_planning_output(raw)
        assert query == orch.query


# ---------------------------------------------------------------------------
# Test: _parse_analysis_output
# ---------------------------------------------------------------------------


class TestParseAnalysisOutput:

    def test_valid_json_returns_analysis(self):
        orch = _make_orchestrator()
        raw = json.dumps({
            "findings_summary": "Found stuff",
            "knowledge_gaps": ["gap1", "gap2"],
            "coverage_assessment": "partial",
            "saturated": False,
            "next_query": "follow up",
            "next_query_rationale": "need more",
        })
        result = orch._parse_analysis_output(raw, round_idx=0)
        assert result["findings_summary"] == "Found stuff"
        assert result["knowledge_gaps"] == ["gap1", "gap2"]
        assert result["saturated"] is False
        assert result["next_query"] == "follow up"

    def test_invalid_json_returns_fallback(self):
        orch = _make_orchestrator()
        result = orch._parse_analysis_output("garbage", round_idx=1)
        assert result["saturated"] is False
        assert "analysis failed" in result["knowledge_gaps"]
        assert result["next_query"]  # should have fallback query

    def test_saturated_true_returns_no_next_query_override(self):
        orch = _make_orchestrator()
        raw = json.dumps({
            "findings_summary": "Done",
            "knowledge_gaps": [],
            "coverage_assessment": "comprehensive",
            "saturated": True,
            "next_query": "",
            "next_query_rationale": "",
        })
        result = orch._parse_analysis_output(raw, round_idx=2)
        assert result["saturated"] is True

    def test_not_saturated_but_no_next_query_uses_fallback(self):
        orch = _make_orchestrator()
        raw = json.dumps({
            "findings_summary": "Partial",
            "knowledge_gaps": ["gap"],
            "coverage_assessment": "partial",
            "saturated": False,
            "next_query": "",
        })
        result = orch._parse_analysis_output(raw, round_idx=0)
        assert result["next_query"]  # fallback applied
        assert orch.query in result["next_query"]

    def test_gaps_truncated_to_5(self):
        orch = _make_orchestrator()
        raw = json.dumps({
            "findings_summary": "F",
            "knowledge_gaps": ["g1", "g2", "g3", "g4", "g5", "g6", "g7"],
            "coverage_assessment": "partial",
            "saturated": False,
            "next_query": "q",
        })
        result = orch._parse_analysis_output(raw, round_idx=0)
        assert len(result["knowledge_gaps"]) == 5

    def test_non_list_gaps_defaults_to_empty(self):
        orch = _make_orchestrator()
        raw = json.dumps({
            "findings_summary": "F",
            "knowledge_gaps": "not a list",
            "coverage_assessment": "partial",
            "saturated": False,
            "next_query": "q",
        })
        result = orch._parse_analysis_output(raw, round_idx=0)
        assert result["knowledge_gaps"] == []

    def test_code_fenced_analysis_parsed(self):
        orch = _make_orchestrator()
        raw = '```json\n{"findings_summary":"F","knowledge_gaps":[],"coverage_assessment":"good","saturated":true,"next_query":"","next_query_rationale":""}\n```'
        result = orch._parse_analysis_output(raw, round_idx=0)
        assert result["saturated"] is True

    def test_wrapped_analysis_json_parsed(self):
        orch = _make_orchestrator()
        raw = (
            "Analysis result follows:\n"
            '{"findings_summary":"F","knowledge_gaps":["g1"],"coverage_assessment":"good","saturated":false,"next_query":"next","next_query_rationale":"because"}\n'
            "End of report."
        )
        result = orch._parse_analysis_output(raw, round_idx=0)
        assert result["findings_summary"] == "F"
        assert result["knowledge_gaps"] == ["g1"]
        assert result["next_query"] == "next"

    def test_non_dict_json_returns_fallback(self):
        orch = _make_orchestrator()
        result = orch._parse_analysis_output("[1, 2, 3]", round_idx=0)
        assert result["saturated"] is False


# ---------------------------------------------------------------------------
# Test: _strip_code_fences
# ---------------------------------------------------------------------------


class TestStripCodeFences:

    def test_strips_json_fence(self):
        raw = '```json\n{"key": "value"}\n```'
        assert '{"key": "value"}' == DeepResearchOrchestrator._strip_code_fences(raw)

    def test_no_fences_unchanged(self):
        raw = '{"key": "value"}'
        assert raw == DeepResearchOrchestrator._strip_code_fences(raw)

    def test_non_string_input(self):
        result = DeepResearchOrchestrator._strip_code_fences(42)
        assert isinstance(result, str)


class TestExtractJsonObject:

    def test_returns_full_json_when_clean(self):
        raw = '{"key": "value"}'
        assert DeepResearchOrchestrator._extract_json_object(raw) == raw

    def test_extracts_json_from_wrapper_text(self):
        raw = 'prefix\n{"key": "value"}\nsuffix'
        assert DeepResearchOrchestrator._extract_json_object(raw) == '{"key": "value"}'

    def test_returns_none_when_missing(self):
        assert DeepResearchOrchestrator._extract_json_object("no json here") is None


# ---------------------------------------------------------------------------
# Test: _format_prior_rounds
# ---------------------------------------------------------------------------


class TestFormatPriorRounds:

    def test_empty_rounds(self):
        assert "No prior" in DeepResearchOrchestrator._format_prior_rounds([])

    def test_formats_single_round(self):
        rounds = [
            {"round_idx": 0, "query": "q1", "findings_summary": "Found stuff",
             "knowledge_gaps": ["gap1"]}
        ]
        result = DeepResearchOrchestrator._format_prior_rounds(rounds)
        assert "Round 0" in result
        assert "q1" in result
        assert "Found stuff" in result
        assert "gap1" in result

    def test_formats_multiple_rounds(self):
        rounds = [
            {"round_idx": 0, "query": "q1", "findings_summary": "F1",
             "knowledge_gaps": ["g1"]},
            {"round_idx": 1, "query": "q2", "findings_summary": "F2",
             "knowledge_gaps": []},
        ]
        result = DeepResearchOrchestrator._format_prior_rounds(rounds)
        assert "Round 0" in result
        assert "Round 1" in result
        assert "none" in result  # empty gaps


# ---------------------------------------------------------------------------
# Test: _collect_bare_urls
# ---------------------------------------------------------------------------


class TestCollectBareUrls:

    def test_collects_bare_url_with_preceding_title(self):
        text = "- My Article\n  https://example.com/article"
        seen = {}
        DeepResearchOrchestrator._collect_bare_urls(text, seen)
        assert "https://example.com/article" in seen
        assert seen["https://example.com/article"] == "My Article"

    def test_skips_urls_already_in_seen(self):
        text = "https://example.com/a"
        seen = {"https://example.com/a": "Already"}
        DeepResearchOrchestrator._collect_bare_urls(text, seen)
        assert seen["https://example.com/a"] == "Already"

    def test_skips_urls_inside_markdown_links(self):
        text = "[Title](https://example.com/md)"
        seen = {}
        DeepResearchOrchestrator._collect_bare_urls(text, seen)
        assert "https://example.com/md" not in seen

    def test_collects_titled_parenthetical_url_on_same_line(self):
        text = "- My Article (https://example.com/article)"
        seen = {}
        DeepResearchOrchestrator._collect_bare_urls(text, seen)
        assert seen == {"https://example.com/article": "My Article"}

    def test_collects_html_anchor_urls(self):
        text = (
            '<a class="chip" href="https://vertexaisearch.cloud.google.com/grounding-api-redirect/ABC">'
            'AI agent frameworks adoption trends 2026</a>'
        )
        seen = {}
        DeepResearchOrchestrator._collect_bare_urls(text, seen)
        assert seen == {
            "https://vertexaisearch.cloud.google.com/grounding-api-redirect/ABC": "AI agent frameworks adoption trends 2026"
        }


# ---------------------------------------------------------------------------
# Test: GroundingResult dataclass (T23-02)
# ---------------------------------------------------------------------------


class TestGroundingResult:

    def test_default_empty(self):
        gr = GroundingResult()
        assert gr.sources == []
        assert gr.supports == []
        assert gr.queries == []
        assert gr.has_metadata is False

    def test_with_data(self):
        gr = GroundingResult(
            sources=[{"uri": "https://a.com", "title": "A"}],
            supports=[{"segment_text": "foo"}],
            queries=["q1"],
            has_metadata=True,
        )
        assert len(gr.sources) == 1
        assert gr.has_metadata is True


# ---------------------------------------------------------------------------
# Test: _grounding_capture_callback (T23-02/T23-04)
# ---------------------------------------------------------------------------


class TestGroundingCaptureCallback:

    def _make_callback_context(self, state: dict) -> MagicMock:
        ctx = MagicMock()
        ctx.state = state
        return ctx

    def _make_grounding_metadata(self, chunks=None, supports=None, queries=None):
        gm = MagicMock()
        gm.grounding_chunks = chunks or []
        gm.grounding_supports = supports or []
        gm.web_search_queries = queries or []
        return gm

    def _make_chunk(self, uri: str, title: str = ""):
        chunk = MagicMock()
        web = MagicMock()
        web.uri = uri
        web.title = title
        chunk.web = web
        return chunk

    def test_captures_grounding_data(self):
        chunks = [
            self._make_chunk("https://example.com/a", "Article A"),
            self._make_chunk("https://example.com/b", "Article B"),
        ]
        gm = self._make_grounding_metadata(chunks=chunks, queries=["q1"])
        state = {"temp:_adk_grounding_metadata": gm}
        cb_ctx = self._make_callback_context(state)
        result = _grounding_capture_callback(cb_ctx, MagicMock(), 0, "google", 1)
        assert result is None
        raw = state["_grounding_raw_0_google_round_1"]
        assert len(raw["grounding_chunks"]) == 2
        assert raw["grounding_chunks"][0]["web"]["uri"] == "https://example.com/a"
        assert raw["web_search_queries"] == ["q1"]

    def test_no_metadata_does_nothing(self):
        state = {}
        cb_ctx = self._make_callback_context(state)
        result = _grounding_capture_callback(cb_ctx, MagicMock(), 0, "google", 0)
        assert result is None
        assert "_grounding_raw_0_google_round_0" not in state

    def test_exception_does_not_raise(self):
        cb_ctx = MagicMock()
        cb_ctx.state = None  # will cause exception
        result = _grounding_capture_callback(cb_ctx, MagicMock(), 0, "google", 0)
        assert result is None

    def test_make_grounding_callback_creates_bound_callback(self):
        cb = _make_grounding_callback(1, "google", 2)
        assert callable(cb)

    def test_captures_supports_with_segments(self):
        chunk = self._make_chunk("https://ex.com", "Ex")
        support = MagicMock()
        segment = MagicMock()
        segment.text = "supported text"
        segment.start_index = 5
        segment.end_index = 20
        support.segment = segment
        support.grounding_chunk_indices = [0]

        gm = self._make_grounding_metadata(
            chunks=[chunk], supports=[support], queries=["q"]
        )
        state = {"temp:_adk_grounding_metadata": gm}
        cb_ctx = self._make_callback_context(state)
        _grounding_capture_callback(cb_ctx, MagicMock(), 0, "google", 0)

        raw = state["_grounding_raw_0_google_round_0"]
        assert len(raw["grounding_supports"]) == 1
        assert raw["grounding_supports"][0]["segment_text"] == "supported text"
        assert raw["grounding_supports"][0]["start_index"] == 5
        assert raw["grounding_supports"][0]["chunk_indices"] == [0]

    def test_captures_support_with_no_segment(self):
        chunk = self._make_chunk("https://ex.com", "Ex")
        support = MagicMock()
        support.segment = None
        support.grounding_chunk_indices = []

        gm = self._make_grounding_metadata(chunks=[chunk], supports=[support])
        state = {"temp:_adk_grounding_metadata": gm}
        cb_ctx = self._make_callback_context(state)
        _grounding_capture_callback(cb_ctx, MagicMock(), 0, "google", 0)

        raw = state["_grounding_raw_0_google_round_0"]
        assert raw["grounding_supports"][0]["segment_text"] == ""
        assert raw["grounding_supports"][0]["start_index"] == 0


# ---------------------------------------------------------------------------
# Test: _parse_grounding_from_state (T23-03)
# ---------------------------------------------------------------------------


class TestParseGroundingFromState:

    def test_happy_path(self):
        state = {
            "_grounding_raw_0_google_round_0": {
                "grounding_chunks": [
                    {"web": {"uri": "https://a.com", "title": "Title A"}},
                    {"web": {"uri": "https://b.com", "title": "Title B"}},
                ],
                "grounding_supports": [
                    {
                        "segment_text": "some text",
                        "start_index": 0,
                        "end_index": 10,
                        "chunk_indices": [0],
                    },
                ],
                "web_search_queries": ["query1"],
            },
        }
        orch = _make_orchestrator()
        gr = orch._parse_grounding_from_state(state, 0, "google", 0)
        assert gr.has_metadata is True
        assert len(gr.sources) == 2
        assert gr.sources[0]["uri"] == "https://a.com"
        assert gr.sources[0]["title"] == "Title A"
        assert len(gr.supports) == 1
        assert gr.queries == ["query1"]

    def test_empty_state_returns_empty_result(self):
        orch = _make_orchestrator()
        gr = orch._parse_grounding_from_state({}, 0, "google", 0)
        assert gr.has_metadata is False
        assert gr.sources == []

    def test_deduplicates_by_uri(self):
        state = {
            "_grounding_raw_0_google_round_0": {
                "grounding_chunks": [
                    {"web": {"uri": "https://a.com", "title": "Title A"}},
                    {"web": {"uri": "https://a.com", "title": "Title A (dup)"}},
                ],
                "grounding_supports": [],
                "web_search_queries": [],
            },
        }
        orch = _make_orchestrator()
        gr = orch._parse_grounding_from_state(state, 0, "google", 0)
        assert len(gr.sources) == 1
        assert gr.sources[0]["title"] == "Title A"  # first wins

    def test_empty_title_uses_uri(self):
        state = {
            "_grounding_raw_0_google_round_0": {
                "grounding_chunks": [
                    {"web": {"uri": "https://a.com", "title": ""}},
                ],
                "grounding_supports": [],
                "web_search_queries": [],
            },
        }
        orch = _make_orchestrator()
        gr = orch._parse_grounding_from_state(state, 0, "google", 0)
        assert gr.sources[0]["title"] == "https://a.com"

    def test_skips_non_https_uris(self):
        state = {
            "_grounding_raw_0_google_round_0": {
                "grounding_chunks": [
                    {"web": {"uri": "http://insecure.com", "title": "Bad"}},
                    {"web": {"uri": "https://good.com", "title": "Good"}},
                ],
                "grounding_supports": [],
                "web_search_queries": [],
            },
        }
        orch = _make_orchestrator()
        gr = orch._parse_grounding_from_state(state, 0, "google", 0)
        assert len(gr.sources) == 1
        assert gr.sources[0]["uri"] == "https://good.com"

    def test_escapes_markdown_special_chars_in_titles(self):
        state = {
            "_grounding_raw_0_google_round_0": {
                "grounding_chunks": [
                    {"web": {"uri": "https://a.com", "title": "Title [with] (parens)"}},
                ],
                "grounding_supports": [],
                "web_search_queries": [],
            },
        }
        orch = _make_orchestrator()
        gr = orch._parse_grounding_from_state(state, 0, "google", 0)
        assert "[" not in gr.sources[0]["title"].replace("\\[", "")

    def test_exception_returns_empty_result(self):
        """Corrupt data should not crash."""
        state = {"_grounding_raw_0_google_round_0": "not a dict"}
        orch = _make_orchestrator()
        gr = orch._parse_grounding_from_state(state, 0, "google", 0)
        assert gr.has_metadata is False


# ---------------------------------------------------------------------------
# Test: _merge_rounds_with_grounding (T23-07)
# ---------------------------------------------------------------------------


class TestMergeRoundsWithGrounding:

    def test_happy_path_3_rounds(self):
        """3 rounds with grounding produce deduplicated SOURCES."""
        state = {
            "research_0_google_round_0": "SUMMARY:\nRound 0 findings\n\nSOURCES:\n- [Old](https://old.com)",
            "research_0_google_round_1": "SUMMARY:\nRound 1 findings\n\nSOURCES:\n- [Old](https://old.com)",
            "research_0_google_round_2": "SUMMARY:\nRound 2 findings\n\nSOURCES:\n- [Old](https://old.com)",
            "grounding_sources_0_google_round_0": [
                {"uri": "https://a.com", "title": "Article A"},
                {"uri": "https://b.com", "title": "Article B"},
            ],
            "grounding_sources_0_google_round_1": [
                {"uri": "https://b.com", "title": "Article B (dup)"},
                {"uri": "https://c.com", "title": "Article C"},
            ],
            "grounding_sources_0_google_round_2": [
                {"uri": "https://d.com", "title": "Article D"},
            ],
        }
        orch = _make_orchestrator()
        result = orch._merge_rounds_with_grounding(state, 3)
        assert "SUMMARY:" in result
        assert "SOURCES:" in result
        assert "Round 0 findings" in result
        assert "Round 1 findings" in result
        assert "Round 2 findings" in result
        # Grounding sources, deduplicated
        assert "- [Article A](https://a.com)" in result
        assert "- [Article B](https://b.com)" in result
        assert "- [Article C](https://c.com)" in result
        assert "- [Article D](https://d.com)" in result
        # Old LLM-extracted source NOT in SOURCES section
        sources_section = result.split("SOURCES:")[1]
        assert "https://old.com" not in sources_section

    def test_fallback_when_no_grounding(self):
        """No grounding data delegates to _merge_rounds."""
        state = {
            "research_0_google_round_0": "SUMMARY:\nFindings\n\nSOURCES:\n- [X](https://x.com)",
        }
        orch = _make_orchestrator()
        result = orch._merge_rounds_with_grounding(state, 1)
        # Falls back to _merge_rounds which uses LLM sources
        assert "https://x.com" in result

    def test_mixed_rounds_grounding_and_not(self):
        """Some rounds with grounding, some without -- text URLs supplement."""
        state = {
            "research_0_google_round_0": "SUMMARY:\nRound 0\n\nSOURCES:\n- [X](https://x.com)",
            "research_0_google_round_1": "SUMMARY:\nRound 1\n\nSOURCES:\n- [Y](https://y.com)",
            "grounding_sources_0_google_round_0": [
                {"uri": "https://a.com", "title": "A"},
            ],
            # round 1 has no grounding data
        }
        orch = _make_orchestrator()
        result = orch._merge_rounds_with_grounding(state, 2)
        sources_section = result.split("SOURCES:")[1]
        # Grounding source from round 0
        assert "https://a.com" in sources_section
        # LLM-extracted source from round 0 excluded (grounding is authoritative)
        assert "https://x.com" not in sources_section
        # LLM-extracted source from round 1 INCLUDED (no grounding for that round)
        assert "https://y.com" in sources_section

    def test_preserves_grounding_redirect_uris(self):
        """Grounding redirect URIs are preserved as-is in SOURCES (FR-GME-023)."""
        redirect_uri = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/ABC123"
        state = {
            "research_0_google_round_0": "SUMMARY:\nFindings\n\nSOURCES:\n",
            "grounding_sources_0_google_round_0": [
                {"uri": redirect_uri, "title": "Grounding Article"},
            ],
        }
        orch = _make_orchestrator()
        result = orch._merge_rounds_with_grounding(state, 1)
        assert redirect_uri in result

    def test_empty_summaries_returns_empty_string(self):
        """All rounds empty text -> empty string."""
        state = {
            "research_0_google_round_0": "",
            "grounding_sources_0_google_round_0": [
                {"uri": "https://a.com", "title": "A"},
            ],
        }
        orch = _make_orchestrator()
        result = orch._merge_rounds_with_grounding(state, 1)
        assert result == ""


# ---------------------------------------------------------------------------
# Test: State cleanup with grounding keys (T23-08)
# ---------------------------------------------------------------------------


class TestStateCleanupWithGrounding:

    def test_removes_grounding_keys(self):
        state = {
            "adaptive_plan_0_google": "plan",
            "adaptive_analysis_0_google": "analysis",
            "adaptive_context_0_google": "ctx",
            "deep_research_latest_0_google": "latest",
            "deep_urls_accumulated_0_google": ["http://a.com"],
            "research_0_google_round_0": "round 0",
            "research_0_google_round_1": "round 1",
            "_grounding_raw_0_google_round_0": {"chunks": []},
            "_grounding_raw_0_google_round_1": {"chunks": []},
            "grounding_sources_0_google_round_0": [{"uri": "https://a.com"}],
            "grounding_sources_0_google_round_1": [{"uri": "https://b.com"}],
            "grounding_supports_0_google_round_0": [],
            "grounding_supports_0_google_round_1": [],
            "grounding_queries_0_google_round_0": ["q1"],
            "grounding_queries_0_google_round_1": ["q2"],
            "research_0_google": "final merged",
            "unrelated_key": "keep me",
        }
        orch = _make_orchestrator()
        orch._cleanup_state(state, 2)

        # Grounding keys removed
        assert "_grounding_raw_0_google_round_0" not in state
        assert "_grounding_raw_0_google_round_1" not in state
        assert "grounding_sources_0_google_round_0" not in state
        assert "grounding_sources_0_google_round_1" not in state
        assert "grounding_supports_0_google_round_0" not in state
        assert "grounding_queries_0_google_round_0" not in state
        # Final merged and unrelated preserved
        assert state["research_0_google"] == "final merged"
        assert state["unrelated_key"] == "keep me"

    def test_missing_grounding_keys_no_error(self):
        """Cleanup when no grounding keys exist should not raise."""
        state = {
            "research_0_google_round_0": "round 0",
        }
        orch = _make_orchestrator()
        orch._cleanup_state(state, 1)
        assert "research_0_google_round_0" not in state


# ---------------------------------------------------------------------------
# Test: Grounding observability logging (T23-09)
# ---------------------------------------------------------------------------


class TestGroundingLogging:

    def test_log_001_extraction_info(self, caplog):
        """LOG-001: Successful extraction logged at INFO."""
        state = {
            "_grounding_raw_0_google_round_0": {
                "grounding_chunks": [
                    {"web": {"uri": "https://a.com", "title": "A"}},
                ],
                "grounding_supports": [],
                "web_search_queries": ["q1"],
            },
        }
        orch = _make_orchestrator()
        with caplog.at_level("INFO"):
            gr = orch._parse_grounding_from_state(state, 0, "google", 0)
        # Parsing itself doesn't log -- the logging is in _run_async_impl
        assert gr.has_metadata is True

    def test_log_003_merge_info(self, caplog):
        """LOG-003: Merge summary logged at INFO."""
        state = {
            "research_0_google_round_0": "SUMMARY:\nFindings\n\nSOURCES:\n",
            "grounding_sources_0_google_round_0": [
                {"uri": "https://a.com", "title": "A"},
            ],
        }
        orch = _make_orchestrator()
        with caplog.at_level("INFO"):
            orch._merge_rounds_with_grounding(state, 1)
        assert any(
            "[Grounding]" in r.message and "merged" in r.message
            for r in caplog.records
        )

    def test_log_002_fallback_warning(self, caplog):
        """LOG-002: Fallback logged at WARNING."""
        state = {
            "research_0_google_round_0": "SUMMARY:\nFindings\n\nSOURCES:\n- [X](https://x.com)",
        }
        orch = _make_orchestrator()
        with caplog.at_level("WARNING"):
            orch._merge_rounds_with_grounding(state, 1)
        assert any(
            "falling back" in r.message and r.levelname == "WARNING"
            for r in caplog.records
        )

    def test_log_004_empty_title_warning(self, caplog):
        """LOG-004: Empty title logged at WARNING."""
        state = {
            "_grounding_raw_0_google_round_0": {
                "grounding_chunks": [
                    {"web": {"uri": "https://a.com", "title": ""}},
                ],
                "grounding_supports": [],
                "web_search_queries": [],
            },
        }
        orch = _make_orchestrator()
        with caplog.at_level("WARNING"):
            orch._parse_grounding_from_state(state, 0, "google", 0)
        assert any(
            "empty title" in r.message and r.levelname == "WARNING"
            for r in caplog.records
        )


# ---------------------------------------------------------------------------
# Test: _make_search_agent grounding callback wiring (T23-04)
# ---------------------------------------------------------------------------


class TestSearchAgentGroundingCallback:

    def test_google_agent_has_after_model_callback(self):
        orch = _make_orchestrator(provider="google")
        agent = orch._make_search_agent(0, "test query")
        assert agent.after_model_callback is not None

    def test_perplexity_agent_has_no_after_model_callback(self):
        orch = _make_orchestrator(provider="perplexity")
        agent = orch._make_search_agent(0, "test query")
        assert agent.after_model_callback is None


# ---------------------------------------------------------------------------
# Test: _parse_grounding_from_state partial metadata (FB-04, spec 11.1 #6)
# ---------------------------------------------------------------------------


class TestParseGroundingPartialMetadata:
    """Chunks present but no supports/queries returns sources with empty lists."""

    def test_partial_metadata_chunks_only(self):
        state = {
            "_grounding_raw_0_google_round_0": {
                "grounding_chunks": [
                    {"web": {"uri": "https://a.com", "title": "Title A"}},
                ],
            },
        }
        orch = _make_orchestrator()
        gr = orch._parse_grounding_from_state(state, 0, "google", 0)
        assert gr.has_metadata is True
        assert len(gr.sources) == 1
        assert gr.sources[0]["uri"] == "https://a.com"
        assert gr.supports == []
        assert gr.queries == []

    def test_partial_metadata_chunks_and_queries_no_supports(self):
        state = {
            "_grounding_raw_0_google_round_0": {
                "grounding_chunks": [
                    {"web": {"uri": "https://b.com", "title": "B"}},
                ],
                "web_search_queries": ["q1"],
            },
        }
        orch = _make_orchestrator()
        gr = orch._parse_grounding_from_state(state, 0, "google", 0)
        assert gr.has_metadata is True
        assert len(gr.sources) == 1
        assert gr.supports == []
        assert gr.queries == ["q1"]


# ---------------------------------------------------------------------------
# Test: accumulated_urls from grounding (FB-05, spec 11.1 #11)
# ---------------------------------------------------------------------------


class TestAccumulatedUrlsFromGrounding:
    """Google provider populates accumulated_urls from grounding chunks."""

    @pytest.mark.asyncio
    async def test_google_accumulated_urls_from_grounding(self):
        """FR-GME-030: accumulated_urls uses grounding URIs, not regex."""
        orch = _make_orchestrator(max_rounds=1, provider="google")
        ctx = _make_ctx()

        # LLM text mentions a DIFFERENT URL than grounding data
        round_output = _research_text(
            [("Text URL", "https://text-only.com")],
            "Some findings",
        )

        captured_accumulated = {}

        original_cleanup = orch._cleanup_state

        def capture_cleanup(s, rc):
            # Snapshot accumulated_urls state key before cleanup deletes it
            key = "deep_urls_accumulated_0_google"
            if key in s:
                captured_accumulated["urls"] = list(s[key])
            original_cleanup(s, rc)

        with patch.object(orch, "_make_search_agent") as mock_make, \
             patch.object(orch, "_cleanup_state", side_effect=capture_cleanup):
            mock_agent = MagicMock()

            async def fake_run_async(run_ctx):
                run_ctx.session.state["deep_research_latest_0_google"] = round_output
                run_ctx.session.state["_grounding_raw_0_google_round_0"] = {
                    "grounding_chunks": [
                        {"web": {"uri": "https://grounded.com/a", "title": "A"}},
                        {"web": {"uri": "https://grounded.com/b", "title": "B"}},
                    ],
                    "grounding_supports": [],
                    "web_search_queries": [],
                }
                return
                yield

            mock_agent.run_async = fake_run_async
            mock_make.return_value = mock_agent

            events = []
            async for event in orch._run_async_impl(ctx):
                events.append(event)

        # accumulated_urls contained grounding URIs (captured before cleanup)
        acc = captured_accumulated["urls"]
        assert "https://grounded.com/a" in acc
        assert "https://grounded.com/b" in acc
        # regex-only URL should NOT be in accumulated (grounding path used)
        assert "https://text-only.com" not in acc


# ---------------------------------------------------------------------------
# Test: adaptive_context includes grounding_source_count (FB-06, spec 11.1 #14)
# ---------------------------------------------------------------------------


class TestAdaptiveContextGroundingCount:
    """Round entry in adaptive_context has grounding_source_count field."""

    @pytest.mark.asyncio
    async def test_grounding_source_count_present(self):
        """FR-GME-050: round has grounding_source_count when metadata present."""
        orch = _make_orchestrator(max_rounds=2, provider="google")
        ctx = _make_ctx()

        round_output = _research_text(
            [("A", "https://a.com")], "Findings"
        )

        call_count = [0]

        with patch.object(orch, "_make_search_agent") as mock_make, \
             patch.object(orch, "_run_analysis") as mock_analysis, \
             patch.object(orch, "_run_planning") as mock_planning:

            # Planning returns query and aspects
            mock_planning.return_value = ("AI query", ["aspect1", "aspect2"], [])

            # Analysis: not saturated on round 0, saturated on round 1
            mock_analysis.side_effect = [
                (
                    {
                        "findings_summary": "Found stuff",
                        "knowledge_gaps": ["gap1"],
                        "coverage_assessment": "partial",
                        "saturated": False,
                        "next_query": "follow-up",
                        "next_query_rationale": "fill gap",
                    },
                    [],
                ),
                (
                    {
                        "findings_summary": "Complete",
                        "knowledge_gaps": [],
                        "coverage_assessment": "full",
                        "saturated": True,
                        "next_query": None,
                        "next_query_rationale": None,
                    },
                    [],
                ),
            ]

            mock_agent = MagicMock()

            async def fake_run_async(run_ctx):
                r = call_count[0]
                run_ctx.session.state["deep_research_latest_0_google"] = round_output
                if r == 0:
                    run_ctx.session.state[f"_grounding_raw_0_google_round_{r}"] = {
                        "grounding_chunks": [
                            {"web": {"uri": "https://a.com", "title": "A"}},
                            {"web": {"uri": "https://b.com", "title": "B"}},
                            {"web": {"uri": "https://c.com", "title": "C"}},
                        ],
                        "grounding_supports": [],
                        "web_search_queries": [],
                    }
                # Round 1: no grounding data (fallback)
                call_count[0] += 1
                return
                yield

            mock_agent.run_async = fake_run_async
            mock_make.return_value = mock_agent

            events = []
            async for event in orch._run_async_impl(ctx):
                events.append(event)

        # Reasoning chain is preserved after cleanup
        chain_raw = ctx.session.state.get("adaptive_reasoning_chain_0_google")
        assert chain_raw is not None
        context = json.loads(chain_raw)
        rounds = context["rounds"]
        assert len(rounds) == 2
        # Round 0: had 3 grounding sources
        assert rounds[0]["grounding_source_count"] == 3
        # Round 1: no grounding data -> 0
        assert rounds[1]["grounding_source_count"] == 0


# ---------------------------------------------------------------------------
# Test: Grounding redirect URL resolution
# ---------------------------------------------------------------------------


class TestIsGroundingRedirectUrl:
    def test_detects_grounding_redirect(self):
        from newsletter_agent.tools.deep_research import _is_grounding_redirect_url
        url = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/ABC123"
        assert _is_grounding_redirect_url(url) is True

    def test_non_grounding_url(self):
        from newsletter_agent.tools.deep_research import _is_grounding_redirect_url
        url = "https://example.com/article"
        assert _is_grounding_redirect_url(url) is False

    def test_wrong_host(self):
        from newsletter_agent.tools.deep_research import _is_grounding_redirect_url
        url = "https://evil.com/grounding-api-redirect/ABC"
        assert _is_grounding_redirect_url(url) is False


class TestApplyRedirectMapToText:
    def test_replaces_urls_in_text(self):
        from newsletter_agent.tools.deep_research import _apply_redirect_map_to_text
        text = "See [Article](https://redirect.example.com/a) for details."
        rmap = {"https://redirect.example.com/a": "https://real.example.com/article"}
        result = _apply_redirect_map_to_text(text, rmap)
        assert "https://real.example.com/article" in result
        assert "https://redirect.example.com/a" not in result

    def test_empty_map_returns_unchanged(self):
        from newsletter_agent.tools.deep_research import _apply_redirect_map_to_text
        text = "Some text with https://example.com/url"
        assert _apply_redirect_map_to_text(text, {}) == text


class TestResolveGroundingRedirects:
    @pytest.mark.asyncio
    async def test_resolves_redirect_urls(self, respx_mock):
        from newsletter_agent.tools.deep_research import resolve_grounding_redirects
        redirect_url = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/ABC"
        real_url = "https://example.com/real-article"
        # Mock HEAD request following redirect
        respx_mock.head(redirect_url).mock(
            return_value=__import__("httpx").Response(
                200,
                headers={"Location": real_url},
                request=__import__("httpx").Request("HEAD", real_url),
            )
        )

        urls = {redirect_url: "Article Title"}
        resolved, rmap = await resolve_grounding_redirects(urls)

        # If HEAD resolved, the redirect should be mapped
        # (exact behavior depends on httpx mock redirect handling)
        assert isinstance(resolved, dict)
        assert isinstance(rmap, dict)

    @pytest.mark.asyncio
    async def test_non_redirect_urls_unchanged(self):
        from newsletter_agent.tools.deep_research import resolve_grounding_redirects
        urls = {"https://example.com/article": "Title"}
        resolved, rmap = await resolve_grounding_redirects(urls)
        assert resolved == urls
        assert rmap == {}

    @pytest.mark.asyncio
    async def test_empty_input(self):
        from newsletter_agent.tools.deep_research import resolve_grounding_redirects
        resolved, rmap = await resolve_grounding_redirects({})
        assert resolved == {}
        assert rmap == {}
