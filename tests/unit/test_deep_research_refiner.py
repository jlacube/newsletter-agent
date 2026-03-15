"""Unit tests for DeepResearchRefinerAgent.

Covers: no-op for standard-mode, source count thresholds, LLM refinement,
error handling, clamping, in-place state update, and logging.

Spec refs: FR-REF-001 through FR-REF-007, Section 11.1.
"""

import json
import logging

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from newsletter_agent.tools.deep_research_refiner import (
    DeepResearchRefinerAgent,
    _extract_source_urls,
    _filter_sources_in_text,
    _parse_llm_response,
    _split_summary_sources,
    _MAX_SOURCES,
    _MIN_SOURCES,
)
from newsletter_agent.config.schema import TopicConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(state: dict | None = None) -> MagicMock:
    """Create a mock InvocationContext with session state."""
    ctx = MagicMock()
    ctx.session.state = state if state is not None else {}
    return ctx


def _make_topic(name="AI News", search_depth="deep") -> TopicConfig:
    """Create a TopicConfig for testing."""
    return TopicConfig(
        name=name,
        query=f"Latest {name}",
        search_depth=search_depth,
        sources=["google_search", "perplexity"],
    )


def _make_refiner(topic_configs=None, providers=None) -> DeepResearchRefinerAgent:
    """Create a DeepResearchRefinerAgent with sensible defaults."""
    if topic_configs is None:
        topic_configs = [_make_topic()]
    if providers is None:
        providers = ["google"]
    return DeepResearchRefinerAgent(
        name="DeepResearchRefiner",
        topic_count=len(topic_configs),
        providers=providers,
        topic_configs=topic_configs,
    )


def _research_text_with_n_sources(n: int, summary: str = "Analysis of AI trends") -> str:
    """Build research text with exactly n unique markdown source links."""
    sources = "\n".join(
        f"- [Source {i}](https://example.com/article-{i})"
        for i in range(n)
    )
    return f"SUMMARY:\n{summary}\n\nSOURCES:\n{sources}"


def _source_urls(n: int) -> list[str]:
    """Return a list of n URLs matching _research_text_with_n_sources."""
    return [f"https://example.com/article-{i}" for i in range(n)]


def _mock_genai_success(selected_urls: list[str], rationale: str = "Selected best sources"):
    """Create a mock genai response with valid JSON."""
    response = MagicMock()
    response.text = json.dumps({
        "selected_urls": selected_urls,
        "rationale": rationale,
    })
    client = MagicMock()
    client.aio.models.generate_content = AsyncMock(return_value=response)
    return client


def _mock_genai_failure(error_msg="API error"):
    """Create a mock genai client that raises on generate_content."""
    client = MagicMock()
    client.aio.models.generate_content = AsyncMock(side_effect=Exception(error_msg))
    return client


def _mock_genai_invalid_json():
    """Create a mock genai response with invalid JSON."""
    response = MagicMock()
    response.text = "This is not valid JSON at all"
    client = MagicMock()
    client.aio.models.generate_content = AsyncMock(return_value=response)
    return client


def _mock_genai_empty_selection():
    """Create a mock genai response with empty selected_urls."""
    response = MagicMock()
    response.text = json.dumps({"selected_urls": [], "rationale": "None suitable"})
    client = MagicMock()
    client.aio.models.generate_content = AsyncMock(return_value=response)
    return client


# ---------------------------------------------------------------------------
# Test: URL extraction
# ---------------------------------------------------------------------------


class TestExtractSourceUrls:

    def test_extracts_http_urls(self):
        text = "See [Article](http://example.com) and [Other](https://other.com)"
        urls = _extract_source_urls(text)
        assert urls == ["http://example.com", "https://other.com"]

    def test_deduplicates_urls(self):
        text = "- [A](https://a.com)\n- [B](https://a.com)\n- [C](https://b.com)"
        urls = _extract_source_urls(text)
        assert urls == ["https://a.com", "https://b.com"]

    def test_empty_text(self):
        assert _extract_source_urls("") == []

    def test_no_markdown_links(self):
        assert _extract_source_urls("No links here") == []

    def test_excludes_image_links(self):
        text = "![Image](https://img.com/pic.png) [Link](https://link.com)"
        urls = _extract_source_urls(text)
        assert urls == ["https://link.com"]


# ---------------------------------------------------------------------------
# Test: Split summary/sources
# ---------------------------------------------------------------------------


class TestSplitSummarySources:

    def test_splits_standard_format(self):
        text = "SUMMARY:\nAnalysis text\n\nSOURCES:\n- [A](https://a.com)"
        summary, sources = _split_summary_sources(text)
        assert "Analysis text" in summary
        assert "https://a.com" in sources

    def test_no_sources_section(self):
        text = "Just some text without structure"
        summary, sources = _split_summary_sources(text)
        assert summary == text.strip()
        assert sources == ""


# ---------------------------------------------------------------------------
# Test: LLM response parsing
# ---------------------------------------------------------------------------


class TestParseLlmResponse:

    def test_parses_valid_json(self):
        raw = json.dumps({"selected_urls": ["https://a.com", "https://b.com"], "rationale": "Best"})
        result = _parse_llm_response(raw)
        assert result == ["https://a.com", "https://b.com"]

    def test_handles_code_fences(self):
        raw = "```json\n" + json.dumps({"selected_urls": ["https://a.com"]}) + "\n```"
        result = _parse_llm_response(raw)
        assert result == ["https://a.com"]

    def test_returns_none_for_empty(self):
        assert _parse_llm_response("") is None
        assert _parse_llm_response("   ") is None

    def test_returns_none_for_missing_key(self):
        raw = json.dumps({"urls": ["https://a.com"]})
        result = _parse_llm_response(raw)
        assert result is None

    def test_returns_none_for_non_string_urls(self):
        raw = json.dumps({"selected_urls": [1, 2, 3]})
        result = _parse_llm_response(raw)
        assert result is None


# ---------------------------------------------------------------------------
# Test: Filter sources in text
# ---------------------------------------------------------------------------


class TestFilterSourcesInText:

    def test_keeps_selected_sources_only(self):
        text = _research_text_with_n_sources(5)
        selected = _source_urls(5)[:3]
        result = _filter_sources_in_text(text, selected)
        result_urls = _extract_source_urls(result)
        assert set(result_urls) == set(selected)

    def test_preserves_summary(self):
        text = _research_text_with_n_sources(5)
        selected = _source_urls(5)[:3]
        result = _filter_sources_in_text(text, selected)
        assert "SUMMARY:" in result
        assert "Analysis of AI trends" in result

    def test_no_sources_section_returns_unchanged(self):
        text = "Just some text without SOURCES header"
        result = _filter_sources_in_text(text, ["https://a.com"])
        assert result == text


# ---------------------------------------------------------------------------
# Test: No-op for standard-mode topics (FR-REF-006)
# ---------------------------------------------------------------------------


class TestNoOpStandardMode:

    @pytest.mark.asyncio
    async def test_standard_mode_unchanged(self):
        """Standard-mode topic sources remain unchanged."""
        topic = _make_topic(search_depth="standard")
        refiner = _make_refiner(topic_configs=[topic])
        state = {"research_0_google": _research_text_with_n_sources(20)}
        ctx = _make_ctx(state)

        events = []
        async for event in refiner._run_async_impl(ctx):
            events.append(event)

        # State should be unchanged
        assert ctx.session.state["research_0_google"] == _research_text_with_n_sources(20)
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_mixed_topics_only_deep_refined(self):
        """Only deep-mode topics are refined, standard topics untouched."""
        deep_topic = _make_topic(name="Deep Topic", search_depth="deep")
        std_topic = _make_topic(name="Standard Topic", search_depth="standard")

        selected = _source_urls(20)[:8]
        client = _mock_genai_success(selected)

        refiner = _make_refiner(
            topic_configs=[deep_topic, std_topic],
            providers=["google"],
        )

        deep_text = _research_text_with_n_sources(20)
        std_text = _research_text_with_n_sources(15)
        state = {
            "research_0_google": deep_text,
            "research_1_google": std_text,
        }
        ctx = _make_ctx(state)

        with patch("newsletter_agent.tools.deep_research_refiner.genai") as mock_genai:
            mock_genai.Client.return_value = client
            events = []
            async for event in refiner._run_async_impl(ctx):
                events.append(event)

        # Standard topic unchanged
        assert ctx.session.state["research_1_google"] == std_text
        # Deep topic was refined
        assert ctx.session.state["research_0_google"] != deep_text


# ---------------------------------------------------------------------------
# Test: Source count thresholds (FR-REF-005, Section 8.3)
# ---------------------------------------------------------------------------


class TestSourceCountThresholds:

    @pytest.mark.asyncio
    async def test_fewer_than_5_keeps_all(self):
        """Pool < 5: keep all sources, no LLM call."""
        refiner = _make_refiner()
        state = {"research_0_google": _research_text_with_n_sources(3)}
        ctx = _make_ctx(state)

        with patch("newsletter_agent.tools.deep_research_refiner.genai") as mock_genai:
            events = []
            async for event in refiner._run_async_impl(ctx):
                events.append(event)

            # No LLM call should be made
            mock_genai.Client.assert_not_called()

        # All 3 sources still present
        result_urls = _extract_source_urls(ctx.session.state["research_0_google"])
        assert len(result_urls) == 3

    @pytest.mark.asyncio
    async def test_5_to_10_keeps_all_no_llm(self):
        """Pool 5-10: already in range, skip refinement."""
        refiner = _make_refiner()
        state = {"research_0_google": _research_text_with_n_sources(8)}
        ctx = _make_ctx(state)

        with patch("newsletter_agent.tools.deep_research_refiner.genai") as mock_genai:
            events = []
            async for event in refiner._run_async_impl(ctx):
                events.append(event)

            mock_genai.Client.assert_not_called()

        result_urls = _extract_source_urls(ctx.session.state["research_0_google"])
        assert len(result_urls) == 8

    @pytest.mark.asyncio
    async def test_exactly_10_keeps_all(self):
        """Pool == 10: at boundary, skip refinement."""
        refiner = _make_refiner()
        state = {"research_0_google": _research_text_with_n_sources(10)}
        ctx = _make_ctx(state)

        with patch("newsletter_agent.tools.deep_research_refiner.genai") as mock_genai:
            events = []
            async for event in refiner._run_async_impl(ctx):
                events.append(event)

            mock_genai.Client.assert_not_called()

    @pytest.mark.asyncio
    async def test_more_than_10_triggers_llm(self):
        """Pool > 10: triggers LLM refinement."""
        selected = _source_urls(20)[:8]
        client = _mock_genai_success(selected)
        refiner = _make_refiner()

        state = {"research_0_google": _research_text_with_n_sources(20)}
        ctx = _make_ctx(state)

        with patch("newsletter_agent.tools.deep_research_refiner.genai") as mock_genai:
            mock_genai.Client.return_value = client
            events = []
            async for event in refiner._run_async_impl(ctx):
                events.append(event)

            mock_genai.Client.assert_called_once()

        result_urls = _extract_source_urls(ctx.session.state["research_0_google"])
        assert len(result_urls) == 8


# ---------------------------------------------------------------------------
# Test: LLM refinement success (FR-REF-002, FR-REF-003)
# ---------------------------------------------------------------------------


class TestLlmRefinement:

    @pytest.mark.asyncio
    async def test_selects_valid_urls(self):
        """LLM returns valid selection within range."""
        selected = _source_urls(20)[:7]
        client = _mock_genai_success(selected)
        refiner = _make_refiner()

        state = {"research_0_google": _research_text_with_n_sources(20)}
        ctx = _make_ctx(state)

        with patch("newsletter_agent.tools.deep_research_refiner.genai") as mock_genai:
            mock_genai.Client.return_value = client
            async for _ in refiner._run_async_impl(ctx):
                pass

        result_urls = _extract_source_urls(ctx.session.state["research_0_google"])
        assert len(result_urls) == 7
        assert set(result_urls) == set(selected)

    @pytest.mark.asyncio
    async def test_state_updated_in_place(self):
        """State key is updated with refined text."""
        original = _research_text_with_n_sources(20)
        selected = _source_urls(20)[:8]
        client = _mock_genai_success(selected)
        refiner = _make_refiner()

        state = {"research_0_google": original}
        ctx = _make_ctx(state)

        with patch("newsletter_agent.tools.deep_research_refiner.genai") as mock_genai:
            mock_genai.Client.return_value = client
            async for _ in refiner._run_async_impl(ctx):
                pass

        # State was updated (not the same as original since sources were filtered)
        assert ctx.session.state["research_0_google"] != original
        # Summary preserved
        assert "Analysis of AI trends" in ctx.session.state["research_0_google"]


# ---------------------------------------------------------------------------
# Test: Error handling (spec error behavior)
# ---------------------------------------------------------------------------


class TestErrorHandling:

    @pytest.mark.asyncio
    async def test_llm_api_failure_keeps_all(self):
        """LLM call fails: keep all sources, log warning."""
        client = _mock_genai_failure("Connection error")
        refiner = _make_refiner()
        original = _research_text_with_n_sources(20)
        state = {"research_0_google": original}
        ctx = _make_ctx(state)

        with patch("newsletter_agent.tools.deep_research_refiner.genai") as mock_genai:
            mock_genai.Client.return_value = client
            async for _ in refiner._run_async_impl(ctx):
                pass

        # State unchanged
        assert ctx.session.state["research_0_google"] == original

    @pytest.mark.asyncio
    async def test_invalid_json_keeps_all(self):
        """LLM returns invalid JSON: keep all sources."""
        client = _mock_genai_invalid_json()
        refiner = _make_refiner()
        original = _research_text_with_n_sources(20)
        state = {"research_0_google": original}
        ctx = _make_ctx(state)

        with patch("newsletter_agent.tools.deep_research_refiner.genai") as mock_genai:
            mock_genai.Client.return_value = client
            async for _ in refiner._run_async_impl(ctx):
                pass

        assert ctx.session.state["research_0_google"] == original

    @pytest.mark.asyncio
    async def test_empty_selection_keeps_all(self):
        """LLM returns empty selection: keep all sources."""
        client = _mock_genai_empty_selection()
        refiner = _make_refiner()
        original = _research_text_with_n_sources(20)
        state = {"research_0_google": original}
        ctx = _make_ctx(state)

        with patch("newsletter_agent.tools.deep_research_refiner.genai") as mock_genai:
            mock_genai.Client.return_value = client
            async for _ in refiner._run_async_impl(ctx):
                pass

        assert ctx.session.state["research_0_google"] == original


# ---------------------------------------------------------------------------
# Test: Clamping (FR-REF-005)
# ---------------------------------------------------------------------------


class TestClamping:

    @pytest.mark.asyncio
    async def test_llm_selects_more_than_10_clamped(self):
        """LLM selects > 10 URLs: only first 10 kept."""
        selected = _source_urls(20)[:15]  # LLM claims 15 are relevant
        client = _mock_genai_success(selected)
        refiner = _make_refiner()

        state = {"research_0_google": _research_text_with_n_sources(20)}
        ctx = _make_ctx(state)

        with patch("newsletter_agent.tools.deep_research_refiner.genai") as mock_genai:
            mock_genai.Client.return_value = client
            async for _ in refiner._run_async_impl(ctx):
                pass

        result_urls = _extract_source_urls(ctx.session.state["research_0_google"])
        assert len(result_urls) <= _MAX_SOURCES

    @pytest.mark.asyncio
    async def test_llm_selects_fewer_than_5_keeps_all(self):
        """LLM selects < 5 valid URLs: keep all original sources."""
        selected = _source_urls(20)[:3]  # Only 3 valid
        client = _mock_genai_success(selected)
        refiner = _make_refiner()
        original = _research_text_with_n_sources(20)

        state = {"research_0_google": original}
        ctx = _make_ctx(state)

        with patch("newsletter_agent.tools.deep_research_refiner.genai") as mock_genai:
            mock_genai.Client.return_value = client
            async for _ in refiner._run_async_impl(ctx):
                pass

        # Should keep all original sources since LLM returned < 5
        assert ctx.session.state["research_0_google"] == original

    @pytest.mark.asyncio
    async def test_llm_returns_urls_not_in_source_list(self):
        """LLM returns URLs not in original list: filtered out."""
        # 5 valid + 5 invalid URLs
        valid = _source_urls(20)[:5]
        invalid = [f"https://notreal.com/{i}" for i in range(5)]
        client = _mock_genai_success(valid + invalid)
        refiner = _make_refiner()

        state = {"research_0_google": _research_text_with_n_sources(20)}
        ctx = _make_ctx(state)

        with patch("newsletter_agent.tools.deep_research_refiner.genai") as mock_genai:
            mock_genai.Client.return_value = client
            async for _ in refiner._run_async_impl(ctx):
                pass

        result_urls = _extract_source_urls(ctx.session.state["research_0_google"])
        assert len(result_urls) == 5
        assert set(result_urls) == set(valid)


# ---------------------------------------------------------------------------
# Test: Logging (FR-REF-007)
# ---------------------------------------------------------------------------


class TestLogging:

    @pytest.mark.asyncio
    async def test_logs_source_counts(self, caplog):
        """Logs before -> after source counts."""
        selected = _source_urls(20)[:8]
        client = _mock_genai_success(selected)
        refiner = _make_refiner()

        state = {"research_0_google": _research_text_with_n_sources(20)}
        ctx = _make_ctx(state)

        with caplog.at_level(logging.INFO):
            with patch("newsletter_agent.tools.deep_research_refiner.genai") as mock_genai:
                mock_genai.Client.return_value = client
                async for _ in refiner._run_async_impl(ctx):
                    pass

        # Check for before/after log line
        refined_logs = [r for r in caplog.records if "Refined topic" in r.message]
        assert len(refined_logs) == 1
        assert "20 -> 8 sources" in refined_logs[0].message

    @pytest.mark.asyncio
    async def test_logs_skip_reason_below_minimum(self, caplog):
        """Logs skip reason when below minimum."""
        refiner = _make_refiner()
        state = {"research_0_google": _research_text_with_n_sources(3)}
        ctx = _make_ctx(state)

        with caplog.at_level(logging.INFO):
            async for _ in refiner._run_async_impl(ctx):
                pass

        skip_logs = [r for r in caplog.records if "below minimum" in r.message]
        assert len(skip_logs) == 1

    @pytest.mark.asyncio
    async def test_logs_skip_already_in_range(self, caplog):
        """Logs skip reason when already in range."""
        refiner = _make_refiner()
        state = {"research_0_google": _research_text_with_n_sources(8)}
        ctx = _make_ctx(state)

        with caplog.at_level(logging.INFO):
            async for _ in refiner._run_async_impl(ctx):
                pass

        skip_logs = [r for r in caplog.records if "already in range" in r.message]
        assert len(skip_logs) == 1


# ---------------------------------------------------------------------------
# Test: Class instantiation and properties (T13-02)
# ---------------------------------------------------------------------------


class TestRefinerInstantiation:

    def test_creates_with_required_fields(self):
        refiner = _make_refiner()
        assert refiner.topic_count == 1
        assert refiner.providers == ["google"]
        assert len(refiner.topic_configs) == 1

    def test_is_base_agent(self):
        from google.adk.agents import BaseAgent
        refiner = _make_refiner()
        assert isinstance(refiner, BaseAgent)

    def test_multiple_providers(self):
        refiner = _make_refiner(providers=["google", "perplexity"])
        assert refiner.providers == ["google", "perplexity"]


# ---------------------------------------------------------------------------
# Test: Pipeline position (T13-06)
# ---------------------------------------------------------------------------


class TestPipelinePosition:

    def test_refiner_at_position_5(self):
        """DeepResearchRefiner is at position [5] in pipeline."""
        from newsletter_agent.agent import build_pipeline
        from newsletter_agent.config.schema import (
            AppSettings, NewsletterConfig, NewsletterSettings, TopicConfig,
        )

        config = NewsletterConfig(
            newsletter=NewsletterSettings(
                title="Test", schedule="0 0 * * 0", recipient_email="a@b.com"
            ),
            settings=AppSettings(),
            topics=[TopicConfig(name="AI", query="AI", sources=["google_search"])],
        )
        pipeline = build_pipeline(config)
        assert isinstance(pipeline.sub_agents[5], DeepResearchRefinerAgent)
        assert pipeline.sub_agents[5].name == "DeepResearchRefiner"

    def test_refiner_receives_topic_configs(self):
        """Refiner receives topic_configs from build_pipeline."""
        from newsletter_agent.agent import build_pipeline
        from newsletter_agent.config.schema import (
            AppSettings, NewsletterConfig, NewsletterSettings, TopicConfig,
        )

        topics = [
            TopicConfig(name="AI", query="AI", search_depth="deep", sources=["google_search"]),
            TopicConfig(name="Cloud", query="Cloud", sources=["google_search"]),
        ]
        config = NewsletterConfig(
            newsletter=NewsletterSettings(
                title="Test", schedule="0 0 * * 0", recipient_email="a@b.com"
            ),
            settings=AppSettings(),
            topics=topics,
        )
        pipeline = build_pipeline(config)
        refiner = pipeline.sub_agents[5]
        assert isinstance(refiner, DeepResearchRefinerAgent)
        assert refiner.topic_count == 2
        assert len(refiner.topic_configs) == 2
