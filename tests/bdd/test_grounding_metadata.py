"""
BDD-style acceptance tests for grounding metadata extraction.

Uses Given/When/Then structure to verify spec Section 11.2 scenarios.
Spec refs: Section 11.2 Feature: Grounding Metadata Extraction,
           specs/004-grounding-metadata-extraction.spec.md.
"""

import json
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from newsletter_agent.tools.deep_research import DeepResearchOrchestrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_orchestrator(**overrides) -> DeepResearchOrchestrator:
    defaults = dict(
        name="DeepResearch_0_google",
        topic_idx=0,
        provider="google",
        query="AI news latest developments",
        topic_name="Artificial Intelligence",
        timeframe_instruction=None,
        max_rounds=1,
        search_depth="deep",
        model="gemini-2.5-flash",
        tools=[],
    )
    defaults.update(overrides)
    return DeepResearchOrchestrator(**defaults)


def _make_ctx(state=None):
    ctx = MagicMock()
    ctx.session.state = state if state is not None else {}
    return ctx


def _research_text(urls, summary="Some findings"):
    sources = "\n".join(f"- [{t}]({u})" for t, u in urls)
    return f"SUMMARY:\n{summary}\n\nSOURCES:\n{sources}"


def _grounding_raw(chunks, supports=None, queries=None):
    """Build a raw grounding dict as the callback would produce."""
    return {
        "grounding_chunks": [
            {"web": {"uri": c[0], "title": c[1]}} for c in chunks
        ],
        "grounding_supports": supports or [],
        "web_search_queries": queries or [],
    }


# ---------------------------------------------------------------------------
# Scenario 1: Google search round captures grounding metadata
# ---------------------------------------------------------------------------


class TestGoogleSearchCapturesGroundingMetadata:
    """
    Feature: Grounding Metadata Extraction
    Scenario: Google search round captures grounding metadata

    Given a topic configured with google_search provider
    And the Gemini API returns groundingMetadata with 5 groundingChunks
    When the search round completes
    Then the system extracts 5 source URIs from grounding metadata
    And stores them in the grounding_sources state key
    And logs the grounding chunk count at INFO level
    """

    @pytest.mark.asyncio
    async def test_captures_5_sources_from_grounding_metadata(self, caplog):
        # Given: topic configured with google_search provider
        orch = _make_orchestrator(max_rounds=1, provider="google")
        ctx = _make_ctx()

        round_output = _research_text(
            [("Old", "https://old.com")], "LLM text"
        )

        # And: Gemini API returns groundingMetadata with 5 groundingChunks
        chunks = [
            (f"https://source{i}.com/article", f"Source {i}")
            for i in range(5)
        ]
        raw = _grounding_raw(chunks, queries=["AI news"])

        with patch.object(orch, "_make_search_agent") as mock_make:
            mock_agent = MagicMock()

            async def fake_run_async(run_ctx):
                run_ctx.session.state["deep_research_latest_0_google"] = round_output
                run_ctx.session.state["_grounding_raw_0_google_round_0"] = raw
                return
                yield

            mock_agent.run_async = fake_run_async
            mock_make.return_value = mock_agent

            # When: the search round completes
            with caplog.at_level("INFO"):
                async for _ in orch._run_async_impl(ctx):
                    pass

        # Then: system extracts 5 source URIs from grounding metadata
        merged = ctx.session.state["research_0_google"]
        sources_section = merged.split("SOURCES:")[1]
        for i in range(5):
            assert f"https://source{i}.com/article" in sources_section

        # And: logs the grounding chunk count at INFO level
        grounding_logs = [
            r for r in caplog.records
            if "[Grounding]" in r.message and "extracted" in r.message
        ]
        assert len(grounding_logs) == 1
        assert grounding_logs[0].levelname == "INFO"
        assert "5 sources" in grounding_logs[0].message


# ---------------------------------------------------------------------------
# Scenario 2: Google search round without grounding metadata falls back
# ---------------------------------------------------------------------------


class TestGoogleSearchFallsBackWithoutGrounding:
    """
    Scenario: Google search round without grounding metadata falls back

    Given a topic configured with google_search provider
    And the Gemini API returns a response without groundingMetadata
    When the search round completes
    Then the system falls back to regex-based URL extraction
    And logs a WARNING about missing grounding metadata
    """

    @pytest.mark.asyncio
    async def test_falls_back_to_regex_and_logs_warning(self, caplog):
        # Given: topic with google_search, no grounding metadata
        orch = _make_orchestrator(max_rounds=1, provider="google")
        ctx = _make_ctx()

        round_output = _research_text(
            [("Regex Source", "https://regex.com/article")],
            "Text findings",
        )

        with patch.object(orch, "_make_search_agent") as mock_make:
            mock_agent = MagicMock()

            async def fake_run_async(run_ctx):
                run_ctx.session.state["deep_research_latest_0_google"] = round_output
                # No _grounding_raw key -- simulates no grounding metadata
                return
                yield

            mock_agent.run_async = fake_run_async
            mock_make.return_value = mock_agent

            # When: the search round completes
            with caplog.at_level("WARNING"):
                async for _ in orch._run_async_impl(ctx):
                    pass

        # Then: falls back to regex-based URL extraction
        merged = ctx.session.state["research_0_google"]
        assert "https://regex.com/article" in merged

        # And: logs a WARNING about missing grounding metadata
        fallback_logs = [
            r for r in caplog.records
            if "falling back" in r.message and r.levelname == "WARNING"
        ]
        assert len(fallback_logs) >= 1


# ---------------------------------------------------------------------------
# Scenario 3: Multi-round merge uses grounding sources
# ---------------------------------------------------------------------------


class TestMultiRoundMergeUsesGroundingSources:
    """
    Scenario: Multi-round merge uses grounding sources

    Given a Google topic that completed 3 research rounds
    And rounds 1 and 2 had grounding metadata with 4 and 3 sources respectively
    And round 3 had no grounding metadata
    When rounds are merged
    Then the SOURCES section contains deduplicated sources from grounding
    """

    def test_merge_deduplicates_grounding_sources_across_rounds(self):
        # Given: 3 rounds, rounds 0 and 1 have grounding, round 2 does not
        orch = _make_orchestrator()
        state = {}

        # Round 0: 4 grounding sources
        state["research_0_google_round_0"] = "SUMMARY:\nRound 0\n\nSOURCES:\n"
        state["grounding_sources_0_google_round_0"] = [
            {"uri": "https://a.com", "title": "A"},
            {"uri": "https://b.com", "title": "B"},
            {"uri": "https://c.com", "title": "C"},
            {"uri": "https://d.com", "title": "D"},
        ]

        # Round 1: 3 grounding sources (1 overlapping with round 0)
        state["research_0_google_round_1"] = "SUMMARY:\nRound 1\n\nSOURCES:\n"
        state["grounding_sources_0_google_round_1"] = [
            {"uri": "https://a.com", "title": "A (round 1)"},  # dup, first wins
            {"uri": "https://e.com", "title": "E"},
            {"uri": "https://f.com", "title": "F"},
        ]

        # Round 2: no grounding (text only)
        state["research_0_google_round_2"] = _research_text(
            [("G", "https://g.com")], "Round 2"
        )

        # When: rounds are merged
        result = orch._merge_rounds_with_grounding(state, 3)

        # Then: SOURCES from grounding metadata (deduplicated, first title wins)
        sources_section = result.split("SOURCES:")[1]
        assert "https://a.com" in sources_section
        assert "https://b.com" in sources_section
        assert "https://c.com" in sources_section
        assert "https://d.com" in sources_section
        assert "https://e.com" in sources_section
        assert "https://f.com" in sources_section
        # First title wins for https://a.com
        assert "[A]" in sources_section
        assert "[A (round 1)]" not in sources_section


# ---------------------------------------------------------------------------
# Scenario 4: Perplexity provider is unaffected
# ---------------------------------------------------------------------------


class TestPerplexityProviderUnaffected:
    """
    Scenario: Perplexity provider is unaffected

    Given a topic configured with perplexity provider
    When the search round completes
    Then no grounding metadata extraction is attempted
    And source extraction uses the existing regex-based approach
    """

    @pytest.mark.asyncio
    async def test_perplexity_uses_regex_no_grounding(self):
        # Given: topic configured with perplexity provider
        orch = _make_orchestrator(
            name="DeepResearch_0_perplexity",
            provider="perplexity",
            max_rounds=1,
        )
        ctx = _make_ctx()

        round_output = _research_text(
            [("Perp Source", "https://perplexity-source.com")],
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

            # When: the search round completes
            async for _ in orch._run_async_impl(ctx):
                pass

        # Then: no grounding metadata extraction attempted
        assert not any(
            k.startswith("grounding_") or k.startswith("_grounding_")
            for k in ctx.session.state
        )

        # And: regex-based extraction used -- source present in merged output
        merged = ctx.session.state["research_0_perplexity"]
        assert "https://perplexity-source.com" in merged


# ---------------------------------------------------------------------------
# Scenario 5: Broken grounding URL is cleaned up
# ---------------------------------------------------------------------------


class TestBrokenGroundingUrlCleanedUp:
    """
    Scenario: Broken grounding URL is cleaned up

    Given a Google search round with grounding metadata containing 5 sources
    And link verification determines 2 of those URLs are broken
    When cleanup runs
    Then the grounding sources state contains only 3 sources
    And the broken URLs are removed from the LLM text output
    """

    @pytest.mark.asyncio
    async def test_broken_urls_removed_from_grounding_and_text(self):
        from newsletter_agent.tools.link_verifier import LinkCheckResult

        # Given: Google search round with 5 grounding sources
        orch = _make_orchestrator(max_rounds=1, provider="google")
        ctx = _make_ctx({"config_verify_links": True})

        # LLM text mentions all 5 URLs
        all_urls = [
            ("A", "https://a.com"),
            ("B", "https://b.com"),
            ("C", "https://c.com"),
            ("Broken1", "https://broken1.com"),
            ("Broken2", "https://broken2.com"),
        ]
        round_output = _research_text(all_urls, "Findings with broken links")

        raw = _grounding_raw(
            [(u, t) for t, u in all_urls],
            queries=["test"],
        )

        # And: link verification determines 2 are broken
        check_results = {
            "https://a.com": LinkCheckResult(url="https://a.com", status="valid"),
            "https://b.com": LinkCheckResult(url="https://b.com", status="valid"),
            "https://c.com": LinkCheckResult(url="https://c.com", status="valid"),
            "https://broken1.com": LinkCheckResult(
                url="https://broken1.com", status="broken", error="404"
            ),
            "https://broken2.com": LinkCheckResult(
                url="https://broken2.com", status="broken", error="timeout"
            ),
        }

        with patch.object(orch, "_make_search_agent") as mock_make, \
             patch("newsletter_agent.tools.deep_research.verify_urls",
                   new_callable=AsyncMock) as mock_verify:

            mock_verify.return_value = check_results
            mock_agent = MagicMock()

            async def fake_run_async(run_ctx):
                run_ctx.session.state["deep_research_latest_0_google"] = round_output
                run_ctx.session.state["_grounding_raw_0_google_round_0"] = raw
                return
                yield

            mock_agent.run_async = fake_run_async
            mock_make.return_value = mock_agent

            # When: round runs (cleanup happens during verification)
            async for _ in orch._run_async_impl(ctx):
                pass

        # Then: merged SOURCES has only 3 valid URLs
        merged = ctx.session.state["research_0_google"]
        sources_section = merged.split("SOURCES:")[1]
        assert "https://a.com" in sources_section
        assert "https://b.com" in sources_section
        assert "https://c.com" in sources_section
        assert "https://broken1.com" not in sources_section
        assert "https://broken2.com" not in sources_section
