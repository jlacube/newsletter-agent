"""Integration test: LinkVerifier + research state flow.

Verifies that LinkVerifierAgent correctly processes research state keys,
removes broken links from research text before synthesis.

Spec refs: FR-PSV-003 through FR-PSV-006, Section 11.3.
"""

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
        """Broken URLs removed from research text; valid ones stay."""
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
        agent = LinkVerifierAgent(
            name="LinkVerifier", topic_count=2, providers=["google"],
        )
        ctx = _make_ctx(state)
        async for _ in agent._run_async_impl(ctx):
            pass

        # Topic 0: broken link cleaned, valid links preserved
        r0 = state["research_0_google"]
        assert "[Broken Link](https://broken.example.com/gone)" not in r0
        assert "[Good Link](https://good.example.com/ai)" in r0
        assert "[Another Good](https://good2.example.com)" in r0

        # Topic 1: broken link cleaned, valid link preserved
        r1 = state["research_1_google"]
        assert "[Dead Page](https://dead.example.com/404)" not in r1
        assert "[Cloud Doc](https://cloud.example.com)" in r1

    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_cleaned_state_valid_for_formatter(
        self, mock_verify, synthesis_state_with_mixed_urls
    ):
        """Post-verification research state has no broken link markdown."""
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
        agent = LinkVerifierAgent(
            name="LinkVerifier", topic_count=2, providers=["google"],
        )
        ctx = _make_ctx(state)
        async for _ in agent._run_async_impl(ctx):
            pass

        # Broken link markdown should not appear in any research key
        for key in ["research_0_google", "research_1_google"]:
            assert "[Broken Link](https://broken.example.com/gone)" not in state[key]
            assert "[Dead Page](https://dead.example.com/404)" not in state[key]
