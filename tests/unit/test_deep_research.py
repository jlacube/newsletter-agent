"""Unit tests for DeepResearchOrchestrator.

Covers: query expansion, multi-round loop, URL tracking, early exit,
round merging, state cleanup, and error handling.

Spec refs: FR-MRR-001 through FR-MRR-011, Section 11.1.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from newsletter_agent.tools.deep_research import (
    DeepResearchOrchestrator,
    _MARKDOWN_LINK_RE,
    _MIN_URLS_THRESHOLD,
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
# Test: Query variant parsing (T12-04)
# ---------------------------------------------------------------------------


class TestParseVariants:

    def test_parses_valid_json_array(self):
        orch = _make_orchestrator()
        variants = orch._parse_variants('["q1", "q2", "q3"]', 3)
        assert variants == ["q1", "q2", "q3"]

    def test_trims_to_variant_count(self):
        orch = _make_orchestrator()
        variants = orch._parse_variants('["q1", "q2", "q3", "q4"]', 2)
        assert len(variants) == 2

    def test_fallback_on_invalid_json(self):
        orch = _make_orchestrator(query="my query")
        variants = orch._parse_variants("not json", 2)
        assert len(variants) == 2
        assert all("my query" in v for v in variants)

    def test_fallback_on_non_string_array(self):
        orch = _make_orchestrator(query="q")
        variants = orch._parse_variants("[1, 2, 3]", 2)
        assert len(variants) == 2
        assert all("q" in v for v in variants)

    def test_strips_code_fences(self):
        raw = '```json\n["q1", "q2"]\n```'
        orch = _make_orchestrator()
        variants = orch._parse_variants(raw, 2)
        assert variants == ["q1", "q2"]

    def test_handles_non_string_input(self):
        orch = _make_orchestrator()
        variants = orch._parse_variants(123, 2)
        assert len(variants) == 2  # falls back


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
            "deep_queries_0_google": '["q1"]',
            "deep_research_latest_0_google": "latest",
            "deep_urls_accumulated_0_google": ["http://a.com"],
            "deep_query_current_0_google": "current q",
            "research_0_google_round_0": "round 0",
            "research_0_google_round_1": "round 1",
            "research_0_google": "final merged",
            "unrelated_key": "keep me",
        }
        orch = _make_orchestrator()
        orch._cleanup_state(state, 2)

        assert "deep_queries_0_google" not in state
        assert "deep_research_latest_0_google" not in state
        assert "deep_urls_accumulated_0_google" not in state
        assert "deep_query_current_0_google" not in state
        assert "research_0_google_round_0" not in state
        assert "research_0_google_round_1" not in state
        # Should NOT remove the final merged key
        assert state["research_0_google"] == "final merged"
        assert state["unrelated_key"] == "keep me"


# ---------------------------------------------------------------------------
# Test: Full orchestrator run (T12-03 through T12-07)
# ---------------------------------------------------------------------------


class TestOrchestratorRun:

    @pytest.mark.asyncio
    async def test_max_rounds_1_skips_expansion(self):
        """When max_rounds=1, no query expansion, single round only. FR-BC-002."""
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
    async def test_three_rounds_with_expansion(self):
        """Three rounds: expansion + 3 search rounds. FR-MRR-001."""
        orch = _make_orchestrator(max_rounds=3)
        ctx = _make_ctx()

        rounds_content = [
            _research_text(
                [(f"R{i}S{j}", f"https://r{i}s{j}.com") for j in range(3)],
                f"Round {i} findings",
            )
            for i in range(3)
        ]

        call_count = [0]

        with patch.object(orch, "_expand_queries", new_callable=AsyncMock) as mock_expand, \
             patch.object(orch, "_make_search_agent") as mock_make:

            mock_expand.return_value = (["variant 1", "variant 2"], [])

            mock_agent = MagicMock()

            async def fake_run_async(run_ctx):
                idx = call_count[0]
                run_ctx.session.state["deep_research_latest_0_google"] = rounds_content[idx]
                call_count[0] += 1
                return
                yield

            mock_agent.run_async = fake_run_async
            mock_make.return_value = mock_agent

            events = []
            async for event in orch._run_async_impl(ctx):
                events.append(event)

        # Verify expansion was called
        mock_expand.assert_called_once()
        # Verify 3 search rounds executed
        assert call_count[0] == 3
        # Final merged state key should exist
        merged = ctx.session.state.get("research_0_google", "")
        assert "Round 0 findings" in merged
        assert "Round 1 findings" in merged
        assert "Round 2 findings" in merged

    @pytest.mark.asyncio
    async def test_early_exit_at_url_threshold(self):
        """Stops early when >= 15 unique URLs accumulated. FR-MRR-007."""
        orch = _make_orchestrator(max_rounds=3)
        ctx = _make_ctx()

        # Round 0: 8 URLs
        round0_urls = [(f"S{i}", f"https://r0-{i}.com") for i in range(8)]
        # Round 1: 8 more URLs (total 16 >= 15 threshold)
        round1_urls = [(f"S{i}", f"https://r1-{i}.com") for i in range(8)]

        rounds_content = [
            _research_text(round0_urls, "Round 0"),
            _research_text(round1_urls, "Round 1"),
            _research_text([], "Round 2 should not execute"),
        ]
        call_count = [0]

        with patch.object(orch, "_expand_queries", new_callable=AsyncMock) as mock_expand, \
             patch.object(orch, "_make_search_agent") as mock_make:

            mock_expand.return_value = (["v1", "v2"], [])

            mock_agent = MagicMock()

            async def fake_run_async(run_ctx):
                idx = call_count[0]
                run_ctx.session.state["deep_research_latest_0_google"] = rounds_content[idx]
                call_count[0] += 1
                return
                yield

            mock_agent.run_async = fake_run_async
            mock_make.return_value = mock_agent

            events = []
            async for event in orch._run_async_impl(ctx):
                events.append(event)

        # Should exit after round 1 (index 1), not run round 2
        assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_empty_round_output_handled(self):
        """Empty round output does not crash; loop continues."""
        orch = _make_orchestrator(max_rounds=2)
        ctx = _make_ctx()

        rounds_content = [
            "",  # empty round 0
            _research_text([("A", "https://a.com")], "Round 1 ok"),
        ]
        call_count = [0]

        with patch.object(orch, "_expand_queries", new_callable=AsyncMock) as mock_expand, \
             patch.object(orch, "_make_search_agent") as mock_make:

            mock_expand.return_value = (["v1"], [])
            mock_agent = MagicMock()

            async def fake_run_async(run_ctx):
                idx = call_count[0]
                run_ctx.session.state["deep_research_latest_0_google"] = rounds_content[idx]
                call_count[0] += 1
                return
                yield

            mock_agent.run_async = fake_run_async
            mock_make.return_value = mock_agent

            events = []
            async for event in orch._run_async_impl(ctx):
                events.append(event)

        # Both rounds should have run
        assert call_count[0] == 2
        # Final merged state key should exist
        assert "research_0_google" in ctx.session.state

    @pytest.mark.asyncio
    async def test_round_0_uses_original_query(self):
        """Round 0 uses the original topic query. FR-MRR-002."""
        orch = _make_orchestrator(max_rounds=2, query="original query")
        ctx = _make_ctx()

        captured_queries = []

        with patch.object(orch, "_expand_queries", new_callable=AsyncMock) as mock_expand, \
             patch.object(orch, "_make_search_agent") as mock_make:

            mock_expand.return_value = (["expanded variant 1"], [])

            def capture_make(round_idx, query):
                captured_queries.append((round_idx, query))
                mock_agent = MagicMock()

                async def fake_run_async(run_ctx):
                    run_ctx.session.state["deep_research_latest_0_google"] = "SUMMARY:\ntext\n\nSOURCES:\n- [A](https://a.com)"
                    return
                    yield

                mock_agent.run_async = fake_run_async
                return mock_agent

            mock_make.side_effect = capture_make

            async for _ in orch._run_async_impl(ctx):
                pass

        assert captured_queries[0] == (0, "original query")
        assert captured_queries[1] == (1, "expanded variant 1")

    @pytest.mark.asyncio
    async def test_perplexity_provider_creates_correct_agent(self):
        """Perplexity provider uses perplexity search instruction."""
        orch = _make_orchestrator(provider="perplexity", max_rounds=1)

        agent = orch._make_search_agent(0, "test query")
        assert "perplexity" in agent.name.lower() or "DeepSearchRound" in agent.name
        assert agent.output_key == "deep_research_latest_0_perplexity"

    @pytest.mark.asyncio
    async def test_google_provider_creates_correct_agent(self):
        """Google provider uses google search instruction."""
        orch = _make_orchestrator(provider="google", max_rounds=1)

        agent = orch._make_search_agent(0, "test query")
        assert "DeepSearchRound" in agent.name
        assert agent.output_key == "deep_research_latest_0_google"

    @pytest.mark.asyncio
    async def test_cleanup_removes_all_intermediate_keys(self):
        """After orchestration, intermediate keys are removed. Section 4.3 step 7."""
        orch = _make_orchestrator(max_rounds=2)
        ctx = _make_ctx()

        rounds_content = [
            _research_text([("A", "https://a.com")], "R0"),
            _research_text([("B", "https://b.com")], "R1"),
        ]
        call_count = [0]

        with patch.object(orch, "_expand_queries", new_callable=AsyncMock) as mock_expand, \
             patch.object(orch, "_make_search_agent") as mock_make:

            mock_expand.return_value = (["v1"], [])

            mock_agent = MagicMock()

            async def fake_run_async(run_ctx):
                idx = call_count[0]
                run_ctx.session.state["deep_research_latest_0_google"] = rounds_content[idx]
                call_count[0] += 1
                return
                yield

            mock_agent.run_async = fake_run_async
            mock_make.return_value = mock_agent

            async for _ in orch._run_async_impl(ctx):
                pass

        state = ctx.session.state
        # Only the final merged key should remain
        assert "research_0_google" in state
        # All intermediate keys should be gone
        for key in list(state.keys()):
            assert not key.startswith("deep_"), f"Intermediate key not cleaned: {key}"
            assert "round_" not in key, f"Round key not cleaned: {key}"


# ---------------------------------------------------------------------------
# Test: Query expansion flow (T12-04)
# ---------------------------------------------------------------------------


class TestQueryExpansion:

    @pytest.mark.asyncio
    async def test_expand_queries_invokes_llm_agent(self):
        """Expansion creates and runs a LlmAgent sub-agent."""
        orch = _make_orchestrator(max_rounds=3)
        ctx = _make_ctx()

        with patch("newsletter_agent.tools.deep_research.LlmAgent") as MockLlmAgent:
            mock_instance = MagicMock()

            async def fake_run_async(run_ctx):
                run_ctx.session.state["deep_queries_0_google"] = '["v1", "v2"]'
                return
                yield

            mock_instance.run_async = fake_run_async
            MockLlmAgent.return_value = mock_instance

            variants, events = await orch._expand_queries(ctx)

        assert variants == ["v1", "v2"]
        MockLlmAgent.assert_called_once()
        # Verify it was created with the right output_key
        call_kwargs = MockLlmAgent.call_args
        assert call_kwargs.kwargs["output_key"] == "deep_queries_0_google"

    @pytest.mark.asyncio
    async def test_expand_queries_fallback_on_bad_json(self):
        """Falls back to suffix-based variants on invalid JSON."""
        orch = _make_orchestrator(max_rounds=3, query="my query")
        ctx = _make_ctx()

        with patch("newsletter_agent.tools.deep_research.LlmAgent") as MockLlmAgent:
            mock_instance = MagicMock()

            async def fake_run_async(run_ctx):
                run_ctx.session.state["deep_queries_0_google"] = "not valid json at all"
                return
                yield

            mock_instance.run_async = fake_run_async
            MockLlmAgent.return_value = mock_instance

            variants, events = await orch._expand_queries(ctx)

        assert len(variants) == 2  # max_rounds - 1
        assert all("my query" in v for v in variants)

    @pytest.mark.asyncio
    async def test_expand_queries_returns_events(self):
        """Expansion collects and returns events from the LlmAgent (FB-02)."""
        from google.adk.events import Event
        from google.genai import types

        orch = _make_orchestrator(max_rounds=3)
        ctx = _make_ctx()

        fake_event = Event(
            author="QueryExpander_0_google",
            content=types.Content(parts=[types.Part(text="expansion output")]),
        )

        with patch("newsletter_agent.tools.deep_research.LlmAgent") as MockLlmAgent:
            mock_instance = MagicMock()

            async def fake_run_async(run_ctx):
                run_ctx.session.state["deep_queries_0_google"] = '["v1", "v2"]'
                yield fake_event

            mock_instance.run_async = fake_run_async
            MockLlmAgent.return_value = mock_instance

            variants, events = await orch._expand_queries(ctx)

        assert variants == ["v1", "v2"]
        assert len(events) == 1
        assert events[0] is fake_event

    @pytest.mark.asyncio
    async def test_expansion_events_yielded_from_run_async_impl(self):
        """Events from query expansion are yielded by _run_async_impl (FB-02)."""
        from google.adk.events import Event
        from google.genai import types

        orch = _make_orchestrator(max_rounds=2)
        ctx = _make_ctx()

        expansion_event = Event(
            author="QueryExpander_0_google",
            content=types.Content(parts=[types.Part(text="expansion result")]),
        )

        round_output = _research_text(
            [("A", "https://a.com")], "Round findings"
        )

        with patch.object(orch, "_expand_queries", new_callable=AsyncMock) as mock_expand, \
             patch.object(orch, "_make_search_agent") as mock_make:

            mock_expand.return_value = (["v1"], [expansion_event])

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

        # The expansion event should be among the yielded events
        assert expansion_event in events
        # It should appear before the round progress events
        expansion_idx = events.index(expansion_event)
        assert expansion_idx == 0
