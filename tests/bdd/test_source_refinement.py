"""
BDD-style acceptance tests for deep research source refinement.

Uses Given/When/Then structure to verify spec Section 11.2 scenarios.
Spec refs: Section 11.2 Feature: Deep Research Source Refinement, US-04.
"""

import json
import logging

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from newsletter_agent.tools.deep_research_refiner import (
    DeepResearchRefinerAgent,
    _extract_source_urls,
)
from newsletter_agent.config.schema import TopicConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_topic(name="AI News", search_depth="deep"):
    return TopicConfig(
        name=name,
        query=f"Latest {name}",
        search_depth=search_depth,
        sources=["google_search", "perplexity"],
    )


def _make_refiner(topic_configs, providers=None):
    if providers is None:
        providers = ["google"]
    return DeepResearchRefinerAgent(
        name="DeepResearchRefiner",
        topic_count=len(topic_configs),
        providers=providers,
        topic_configs=topic_configs,
    )


def _make_ctx(state=None):
    ctx = MagicMock()
    ctx.session.state = state if state is not None else {}
    return ctx


def _research_text(n_sources, summary="Deep research findings on AI"):
    sources = "\n".join(
        f"- [Source {i} Title](https://example.com/source-{i})"
        for i in range(n_sources)
    )
    return f"SUMMARY:\n{summary}\n\nSOURCES:\n{sources}"


def _source_urls(n):
    return [f"https://example.com/source-{i}" for i in range(n)]


def _mock_llm_selecting(urls, rationale="Selected most relevant"):
    response = MagicMock()
    response.text = json.dumps({"selected_urls": urls, "rationale": rationale})
    client = MagicMock()
    client.aio.models.generate_content = AsyncMock(return_value=response)
    return client


# ---------------------------------------------------------------------------
# Scenario: Sources refined to 5-10 per provider
# ---------------------------------------------------------------------------


class TestSourcesRefinedTo5to10:
    """
    Given a deep-mode topic with 20 verified Google sources
    When the refinement agent runs
    Then between 5 and 10 Google sources remain
    """

    @pytest.mark.asyncio
    async def test_given_deep_20_sources_when_refines_then_5_to_10_remain(self):
        # Given: a deep-mode topic with 20 verified Google sources
        topic = _make_topic(search_depth="deep")
        refiner = _make_refiner(topic_configs=[topic])
        state = {"research_0_google": _research_text(20)}
        ctx = _make_ctx(state)

        # Mock LLM to return 8 selected sources
        selected = _source_urls(20)[:8]
        client = _mock_llm_selecting(selected)

        # When: the refinement agent runs
        with patch("newsletter_agent.tools.deep_research_refiner.genai") as mock_genai:
            mock_genai.Client.return_value = client
            events = []
            async for event in refiner._run_async_impl(ctx):
                events.append(event)

        # Then: between 5 and 10 Google sources remain
        result_urls = _extract_source_urls(ctx.session.state["research_0_google"])
        assert 5 <= len(result_urls) <= 10
        assert len(result_urls) == 8
        assert set(result_urls) == set(selected)

    @pytest.mark.asyncio
    async def test_summary_text_preserved_after_refinement(self):
        # Given: a deep-mode topic with 20 sources and a specific summary
        topic = _make_topic(search_depth="deep")
        refiner = _make_refiner(topic_configs=[topic])
        state = {"research_0_google": _research_text(20, summary="Critical AI breakthrough")}
        ctx = _make_ctx(state)

        selected = _source_urls(20)[:7]
        client = _mock_llm_selecting(selected)

        # When: refinement runs
        with patch("newsletter_agent.tools.deep_research_refiner.genai") as mock_genai:
            mock_genai.Client.return_value = client
            async for _ in refiner._run_async_impl(ctx):
                pass

        # Then: summary text is preserved
        assert "Critical AI breakthrough" in ctx.session.state["research_0_google"]

    @pytest.mark.asyncio
    async def test_refinement_logs_before_after(self, caplog):
        # Given: a deep-mode topic with 20 sources
        topic = _make_topic(search_depth="deep")
        refiner = _make_refiner(topic_configs=[topic])
        state = {"research_0_google": _research_text(20)}
        ctx = _make_ctx(state)

        selected = _source_urls(20)[:8]
        client = _mock_llm_selecting(selected)

        # When: refinement runs
        with caplog.at_level(logging.INFO):
            with patch("newsletter_agent.tools.deep_research_refiner.genai") as mock_genai:
                mock_genai.Client.return_value = client
                async for _ in refiner._run_async_impl(ctx):
                    pass

        # Then: log contains before -> after counts
        log_msgs = [r.message for r in caplog.records]
        assert any("20 -> 8 sources" in msg for msg in log_msgs)


# ---------------------------------------------------------------------------
# Scenario: Few sources kept without filtering
# ---------------------------------------------------------------------------


class TestFewSourcesKeptWithoutFiltering:
    """
    Given a deep-mode topic with 3 verified sources
    When the refinement agent runs
    Then all 3 sources are kept
    """

    @pytest.mark.asyncio
    async def test_given_deep_3_sources_when_refines_then_all_kept(self):
        # Given: a deep-mode topic with 3 verified sources
        topic = _make_topic(search_depth="deep")
        refiner = _make_refiner(topic_configs=[topic])
        original = _research_text(3)
        state = {"research_0_google": original}
        ctx = _make_ctx(state)

        # When: the refinement agent runs
        with patch("newsletter_agent.tools.deep_research_refiner.genai") as mock_genai:
            events = []
            async for event in refiner._run_async_impl(ctx):
                events.append(event)

            # Then: no LLM call was made
            mock_genai.Client.assert_not_called()

        # And: all 3 sources are kept
        result_urls = _extract_source_urls(ctx.session.state["research_0_google"])
        assert len(result_urls) == 3

        # And: text is unchanged
        assert ctx.session.state["research_0_google"] == original

    @pytest.mark.asyncio
    async def test_given_deep_4_sources_all_kept(self):
        # Edge case: 4 sources (below minimum of 5)
        topic = _make_topic(search_depth="deep")
        refiner = _make_refiner(topic_configs=[topic])
        state = {"research_0_google": _research_text(4)}
        ctx = _make_ctx(state)

        with patch("newsletter_agent.tools.deep_research_refiner.genai") as mock_genai:
            async for _ in refiner._run_async_impl(ctx):
                pass
            mock_genai.Client.assert_not_called()

        result_urls = _extract_source_urls(ctx.session.state["research_0_google"])
        assert len(result_urls) == 4


# ---------------------------------------------------------------------------
# Scenario: Refinement no-op for standard mode
# ---------------------------------------------------------------------------


class TestRefinementNoOpForStandardMode:
    """
    Given a standard-mode topic with 5 sources
    When the refinement agent runs
    Then all 5 sources remain unchanged
    """

    @pytest.mark.asyncio
    async def test_given_standard_5_sources_when_refines_then_unchanged(self):
        # Given: a standard-mode topic with 5 sources
        topic = _make_topic(search_depth="standard")
        refiner = _make_refiner(topic_configs=[topic])
        original = _research_text(5)
        state = {"research_0_google": original}
        ctx = _make_ctx(state)

        # When: the refinement agent runs
        with patch("newsletter_agent.tools.deep_research_refiner.genai") as mock_genai:
            events = []
            async for event in refiner._run_async_impl(ctx):
                events.append(event)

            # Then: no LLM call
            mock_genai.Client.assert_not_called()

        # And: all 5 sources remain unchanged
        assert ctx.session.state["research_0_google"] == original

    @pytest.mark.asyncio
    async def test_standard_mode_yields_skip_event(self):
        # Given: standard-mode only
        topic = _make_topic(search_depth="standard")
        refiner = _make_refiner(topic_configs=[topic])
        state = {"research_0_google": _research_text(20)}
        ctx = _make_ctx(state)

        # When/Then: event indicates refinement skipped
        events = []
        async for event in refiner._run_async_impl(ctx):
            events.append(event)

        assert len(events) == 1
        assert "skipped" in events[0].content.parts[0].text.lower() or \
               "standard" in events[0].content.parts[0].text.lower()


# ---------------------------------------------------------------------------
# Scenario: Graceful degradation on LLM failure
# ---------------------------------------------------------------------------


class TestGracefulDegradationOnLlmFailure:
    """
    Given a deep-mode topic with 20 verified sources
    And the refinement LLM call fails
    When the refinement agent runs
    Then all 20 sources are kept
    And a warning is logged
    """

    @pytest.mark.asyncio
    async def test_given_llm_fails_when_refines_then_all_kept_and_warning_logged(self, caplog):
        # Given: a deep-mode topic with 20 verified sources
        topic = _make_topic(search_depth="deep")
        refiner = _make_refiner(topic_configs=[topic])
        original = _research_text(20)
        state = {"research_0_google": original}
        ctx = _make_ctx(state)

        # And: the refinement LLM call fails
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(
            side_effect=Exception("API unavailable")
        )

        # When: the refinement agent runs
        with caplog.at_level(logging.WARNING):
            with patch("newsletter_agent.tools.deep_research_refiner.genai") as mock_genai:
                mock_genai.Client.return_value = client
                events = []
                async for event in refiner._run_async_impl(ctx):
                    events.append(event)

        # Then: all 20 sources are kept
        assert ctx.session.state["research_0_google"] == original
        result_urls = _extract_source_urls(ctx.session.state["research_0_google"])
        assert len(result_urls) == 20

        # And: a warning is logged
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warnings) >= 1
        assert any("LLM call failed" in w.message for w in warnings)

    @pytest.mark.asyncio
    async def test_invalid_json_keeps_all_and_warns(self, caplog):
        # Given: LLM returns invalid JSON
        topic = _make_topic(search_depth="deep")
        refiner = _make_refiner(topic_configs=[topic])
        original = _research_text(20)
        state = {"research_0_google": original}
        ctx = _make_ctx(state)

        response = MagicMock()
        response.text = "not json {"
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(return_value=response)

        with caplog.at_level(logging.WARNING):
            with patch("newsletter_agent.tools.deep_research_refiner.genai") as mock_genai:
                mock_genai.Client.return_value = client
                async for _ in refiner._run_async_impl(ctx):
                    pass

        # All sources kept
        assert ctx.session.state["research_0_google"] == original

        # Warning logged
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("Invalid JSON" in w.message for w in warnings)
