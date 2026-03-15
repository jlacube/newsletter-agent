"""BDD-style acceptance tests for source link verification.

Uses Given/When/Then structure per spec Section 11.2.
Covers: all valid, some broken, all broken, disabled, network failure.

The LinkVerifierAgent reads research_N_{provider} state keys (plain markdown
strings) and cleans broken links from research text before synthesis.

Spec refs: Section 11.2 Feature: Source Link Verification, US-04, US-05.
"""

import pytest
from unittest.mock import MagicMock, patch

from newsletter_agent.tools.link_verifier import LinkCheckResult
from newsletter_agent.tools.link_verifier_agent import LinkVerifierAgent


def _make_ctx(state: dict) -> MagicMock:
    ctx = MagicMock()
    ctx.session.state = state
    return ctx


class TestAllLinksValid:
    """Scenario: All links valid

    Given verify_links is true
    And all source URLs return HTTP 200
    When LinkVerifierAgent runs
    Then research text is unchanged (all links preserved)
    """

    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_all_valid_sources_preserved(self, mock_verify):
        # Given verify_links is true and all URLs return 200
        mock_verify.return_value = {
            "https://a.com/1": LinkCheckResult(url="https://a.com/1", status="valid", http_status=200),
            "https://b.com/2": LinkCheckResult(url="https://b.com/2", status="valid", http_status=200),
        }
        research = "See [A](https://a.com/1) and [B](https://b.com/2)."
        state = {
            "config_verify_links": True,
            "research_0_google": research,
        }

        # When LinkVerifierAgent runs
        agent = LinkVerifierAgent(
            name="LinkVerifier", topic_count=1, providers=["google"],
        )
        async for _ in agent._run_async_impl(_make_ctx(state)):
            pass

        # Then research text is unchanged
        assert state["research_0_google"] == research


class TestSomeLinksBroken:
    """Scenario: Some links broken

    Given verify_links is true
    And 2 of 5 source URLs return errors (404, timeout)
    When LinkVerifierAgent runs
    Then broken link references are cleaned from research text
    And valid link references remain
    """

    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_broken_removed_valid_kept(self, mock_verify):
        # Given 2 of 5 URLs are broken
        mock_verify.return_value = {
            "https://ok1.com": LinkCheckResult(url="https://ok1.com", status="valid", http_status=200),
            "https://dead.com": LinkCheckResult(url="https://dead.com", status="broken", http_status=404, error="status_404"),
            "https://ok2.com": LinkCheckResult(url="https://ok2.com", status="valid", http_status=200),
            "https://slow.com": LinkCheckResult(url="https://slow.com", status="broken", http_status=None, error="timeout"),
            "https://ok3.com": LinkCheckResult(url="https://ok3.com", status="valid", http_status=200),
        }
        research = (
            "See [OK1](https://ok1.com), [Dead](https://dead.com), "
            "[OK2](https://ok2.com), [Slow](https://slow.com), [OK3](https://ok3.com)."
        )
        state = {
            "config_verify_links": True,
            "research_0_google": research,
        }

        # When LinkVerifierAgent runs
        agent = LinkVerifierAgent(
            name="LinkVerifier", topic_count=1, providers=["google"],
        )
        async for _ in agent._run_async_impl(_make_ctx(state)):
            pass

        # Then broken links cleaned from research text
        cleaned = state["research_0_google"]
        assert "[Dead](https://dead.com)" not in cleaned
        assert "[Slow](https://slow.com)" not in cleaned
        # And valid links remain
        assert "[OK1](https://ok1.com)" in cleaned
        assert "[OK2](https://ok2.com)" in cleaned
        assert "[OK3](https://ok3.com)" in cleaned


class TestAllLinksBrokenForTopic:
    """Scenario: All links broken for a topic

    Given verify_links is true
    And all source URLs for a topic return errors
    When LinkVerifierAgent runs
    Then all broken link references are cleaned from research text
    """

    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_all_broken_links_cleaned(self, mock_verify):
        # Given all URLs broken
        mock_verify.return_value = {
            "https://dead1.com": LinkCheckResult(url="https://dead1.com", status="broken", http_status=404, error="status_404"),
            "https://dead2.com": LinkCheckResult(url="https://dead2.com", status="broken", http_status=500, error="status_500"),
        }
        research = "See [D1](https://dead1.com) and [D2](https://dead2.com)."
        state = {
            "config_verify_links": True,
            "research_0_google": research,
        }

        # When LinkVerifierAgent runs
        agent = LinkVerifierAgent(
            name="LinkVerifier", topic_count=1, providers=["google"],
        )
        async for _ in agent._run_async_impl(_make_ctx(state)):
            pass

        # Then all broken links cleaned
        cleaned = state["research_0_google"]
        assert "[D1](https://dead1.com)" not in cleaned
        assert "[D2](https://dead2.com)" not in cleaned
        # Title text preserved as unlinked text
        assert "D1" in cleaned
        assert "D2" in cleaned


class TestLinkVerificationDisabled:
    """Scenario: Link verification disabled

    Given verify_links is false
    When LinkVerifierAgent runs
    Then no HTTP requests are made
    And session state is unchanged
    """

    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_disabled_no_verification(self, mock_verify):
        # Given verify_links is false
        research = "See [A](https://a.com)."
        state = {
            "config_verify_links": False,
            "research_0_google": research,
        }

        # When LinkVerifierAgent runs
        agent = LinkVerifierAgent(
            name="LinkVerifier", topic_count=1, providers=["google"],
        )
        async for _ in agent._run_async_impl(_make_ctx(state)):
            pass

        # Then no HTTP calls made
        mock_verify.assert_not_called()
        # And state unchanged
        assert state["research_0_google"] == research


class TestLinkVerificationNetworkFailure:
    """Scenario: Link verification network failure

    Given verify_links is true
    And the network is completely down (verify_urls raises)
    When LinkVerifierAgent runs
    Then the agent logs a warning
    And session state is unchanged (graceful degradation)
    """

    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_network_failure_graceful_degradation(self, mock_verify):
        # Given network completely down
        mock_verify.side_effect = Exception("network unreachable")
        research = "See [A](https://a.com)."
        state = {
            "config_verify_links": True,
            "research_0_google": research,
        }

        # When LinkVerifierAgent runs
        agent = LinkVerifierAgent(
            name="LinkVerifier", topic_count=1, providers=["google"],
        )
        async for _ in agent._run_async_impl(_make_ctx(state)):
            pass

        # Then state unchanged (graceful degradation)
        assert state["research_0_google"] == research
