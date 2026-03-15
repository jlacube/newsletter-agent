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
