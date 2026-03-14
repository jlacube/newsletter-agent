"""Integration test: Synthesis + LinkVerifier Flow.

Verifies that LinkVerifierAgent correctly processes synthesis state,
removes broken links, and produces output consumable by the formatter.

Spec refs: FR-014, FR-015, FR-020, FR-025, Section 11.3.
"""

import httpx
import pytest
from unittest.mock import MagicMock, patch

from newsletter_agent.tools.link_verifier import LinkCheckResult
from newsletter_agent.tools.link_verifier_agent import LinkVerifierAgent


def _make_ctx(state: dict) -> MagicMock:
    ctx = MagicMock()
    ctx.session.state = state
    return ctx


class TestSynthesisLinkVerificationIntegration:
    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_broken_links_removed_valid_preserved(
        self, mock_verify, synthesis_state_with_mixed_urls
    ):
        """Broken URLs removed from sources and citations; valid ones stay."""
        mock_verify.return_value = {
            "https://good.example.com/ai": LinkCheckResult(
                url="https://good.example.com/ai", status="valid", http_status=200
            ),
            "https://broken.example.com/gone": LinkCheckResult(
                url="https://broken.example.com/gone",
                status="broken",
                http_status=404,
                error="status_404",
            ),
            "https://good2.example.com": LinkCheckResult(
                url="https://good2.example.com", status="valid", http_status=200
            ),
            "https://cloud.example.com": LinkCheckResult(
                url="https://cloud.example.com", status="valid", http_status=200
            ),
            "https://dead.example.com/404": LinkCheckResult(
                url="https://dead.example.com/404",
                status="broken",
                http_status=404,
                error="status_404",
            ),
        }

        state = synthesis_state_with_mixed_urls
        agent = LinkVerifierAgent(name="LinkVerifier")
        ctx = _make_ctx(state)
        async for _ in agent._run_async_impl(ctx):
            pass

        # Topic 0: 2 of 3 valid
        s0 = state["synthesis_0"]
        assert len(s0["sources"]) == 2
        urls_0 = {s["url"] for s in s0["sources"]}
        assert "https://broken.example.com/gone" not in urls_0
        assert "https://good.example.com/ai" in urls_0
        assert "[Broken Link](https://broken.example.com/gone)" not in s0["body_markdown"]
        assert "[Good Link](https://good.example.com/ai)" in s0["body_markdown"]

        # Topic 1: 1 of 2 valid
        s1 = state["synthesis_1"]
        assert len(s1["sources"]) == 1
        assert s1["sources"][0]["url"] == "https://cloud.example.com"
        assert "[Dead Page](https://dead.example.com/404)" not in s1["body_markdown"]

    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_cleaned_state_valid_for_formatter(
        self, mock_verify, synthesis_state_with_mixed_urls
    ):
        """Post-verification state can be consumed by render_newsletter()."""
        mock_verify.return_value = {
            "https://good.example.com/ai": LinkCheckResult(
                url="https://good.example.com/ai", status="valid", http_status=200
            ),
            "https://broken.example.com/gone": LinkCheckResult(
                url="https://broken.example.com/gone",
                status="broken",
                http_status=404,
                error="status_404",
            ),
            "https://good2.example.com": LinkCheckResult(
                url="https://good2.example.com", status="valid", http_status=200
            ),
            "https://cloud.example.com": LinkCheckResult(
                url="https://cloud.example.com", status="valid", http_status=200
            ),
            "https://dead.example.com/404": LinkCheckResult(
                url="https://dead.example.com/404",
                status="broken",
                http_status=404,
                error="status_404",
            ),
        }

        state = synthesis_state_with_mixed_urls
        state["config_newsletter_title"] = "Test Newsletter"
        state["pipeline_start_time"] = "2025-01-01T08:00:00+00:00"
        state["executive_summary"] = ["AI is evolving.", "Cloud is growing."]
        state["generation_time_seconds"] = 5.0

        agent = LinkVerifierAgent(name="LinkVerifier")
        ctx = _make_ctx(state)
        async for _ in agent._run_async_impl(ctx):
            pass

        # Verify the formatter can consume this state
        from newsletter_agent.tools.formatter import render_newsletter

        html = render_newsletter(state)
        assert "<html" in html.lower() or "<!doctype" in html.lower() or "<div" in html.lower()
        # Broken link markdown should not appear in HTML
        assert "[Broken Link](https://broken.example.com/gone)" not in html
        assert "[Dead Page](https://dead.example.com/404)" not in html
