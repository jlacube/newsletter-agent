"""BDD-style acceptance tests for source link verification.

Uses Given/When/Then structure per spec Section 11.2.
Covers: all valid, some broken, all broken, disabled, network failure.

The LinkVerifierAgent reads research_{idx}_{provider} state entries
(markdown text with source URLs) after research and cleans broken links
before refinement and synthesis.

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


def _research_text(body_links):
    """Build a research state entry (markdown string) for testing."""
    parts = [f"[{t}]({u})" for t, u in body_links]
    body = "See " + ", ".join(parts) + "."
    sources = "\n".join(f"- [{t}]({u})" for t, u in body_links)
    return f"SUMMARY:\n{body}\n\nSOURCES:\n{sources}"


class TestAllLinksValid:
    """Scenario: All links valid

    Given verify_links is true
    And all source URLs return HTTP 200
    When LinkVerifierAgent runs
    Then research text is unchanged
    """

    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_all_valid_sources_preserved(self, mock_verify):
        mock_verify.return_value = {
            "https://a.com/1": LinkCheckResult(url="https://a.com/1", status="valid", http_status=200),
            "https://b.com/2": LinkCheckResult(url="https://b.com/2", status="valid", http_status=200),
        }
        text = _research_text([("A", "https://a.com/1"), ("B", "https://b.com/2")])
        state = {
            "config_verify_links": True,
            "research_0_google": text,
        }

        agent = LinkVerifierAgent(name="LinkVerifier", topic_count=1, providers=["google"])
        async for _ in agent._run_async_impl(_make_ctx(state)):
            pass

        assert state["research_0_google"] == text


class TestSomeLinksBroken:
    """Scenario: Some links broken

    Given verify_links is true
    And 2 of 5 source URLs return errors (404, timeout)
    When LinkVerifierAgent runs
    Then broken links removed from research text
    And valid links remain
    """

    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_broken_removed_valid_kept(self, mock_verify):
        mock_verify.return_value = {
            "https://ok1.com": LinkCheckResult(url="https://ok1.com", status="valid", http_status=200),
            "https://dead.com": LinkCheckResult(url="https://dead.com", status="broken", http_status=404, error="status_404"),
            "https://ok2.com": LinkCheckResult(url="https://ok2.com", status="valid", http_status=200),
            "https://slow.com": LinkCheckResult(url="https://slow.com", status="broken", http_status=None, error="timeout"),
            "https://ok3.com": LinkCheckResult(url="https://ok3.com", status="valid", http_status=200),
        }
        text = _research_text([
            ("OK1", "https://ok1.com"), ("Dead", "https://dead.com"),
            ("OK2", "https://ok2.com"), ("Slow", "https://slow.com"),
            ("OK3", "https://ok3.com"),
        ])
        state = {
            "config_verify_links": True,
            "research_0_google": text,
        }

        agent = LinkVerifierAgent(name="LinkVerifier", topic_count=1, providers=["google"])
        async for _ in agent._run_async_impl(_make_ctx(state)):
            pass

        result = state["research_0_google"]
        # Broken links removed
        assert "https://dead.com" not in result
        assert "https://slow.com" not in result
        # Valid links remain
        assert "[OK1](https://ok1.com)" in result
        assert "[OK2](https://ok2.com)" in result
        assert "[OK3](https://ok3.com)" in result


class TestAllLinksBrokenForTopic:
    """Scenario: All links broken for a topic

    Given verify_links is true
    And all source URLs for a topic return errors
    When LinkVerifierAgent runs
    Then all broken links cleaned from research text
    """

    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_all_broken_links_cleaned(self, mock_verify):
        mock_verify.return_value = {
            "https://dead1.com": LinkCheckResult(url="https://dead1.com", status="broken", http_status=404, error="status_404"),
            "https://dead2.com": LinkCheckResult(url="https://dead2.com", status="broken", http_status=500, error="status_500"),
        }
        text = _research_text([("D1", "https://dead1.com"), ("D2", "https://dead2.com")])
        state = {
            "config_verify_links": True,
            "research_0_google": text,
        }

        agent = LinkVerifierAgent(name="LinkVerifier", topic_count=1, providers=["google"])
        async for _ in agent._run_async_impl(_make_ctx(state)):
            pass

        result = state["research_0_google"]
        assert "https://dead1.com" not in result
        assert "https://dead2.com" not in result
        # Title text preserved (clean_broken_links_from_markdown keeps title)
        assert "D1" in result
        assert "D2" in result


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
        text = _research_text([("A", "https://a.com")])
        state = {
            "config_verify_links": False,
            "research_0_google": text,
        }

        agent = LinkVerifierAgent(name="LinkVerifier", topic_count=1, providers=["google"])
        async for _ in agent._run_async_impl(_make_ctx(state)):
            pass

        mock_verify.assert_not_called()
        assert state["research_0_google"] == text


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
        mock_verify.side_effect = Exception("network unreachable")
        text = _research_text([("A", "https://a.com")])
        state = {
            "config_verify_links": True,
            "research_0_google": text,
        }

        agent = LinkVerifierAgent(name="LinkVerifier", topic_count=1, providers=["google"])
        async for _ in agent._run_async_impl(_make_ctx(state)):
            pass

        assert state["research_0_google"] == text
