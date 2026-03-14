"""BDD-style acceptance tests for source link verification.

Uses Given/When/Then structure per spec Section 11.2.
Covers: all valid, some broken, all broken, disabled, network failure.

Spec refs: Section 11.2 Feature: Source Link Verification, US-04, US-05.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from newsletter_agent.tools.link_verifier import LinkCheckResult
from newsletter_agent.tools.link_verifier_agent import LinkVerifierAgent, _ALL_BROKEN_NOTICE


def _make_ctx(state: dict) -> MagicMock:
    ctx = MagicMock()
    ctx.session.state = state
    return ctx


def _synthesis(topic: str, body: str, sources: list[dict]) -> dict:
    return {"topic_name": topic, "body_markdown": body, "sources": sources}


class TestAllLinksValid:
    """Scenario: All links valid

    Given verify_links is true
    And all source URLs return HTTP 200
    When LinkVerifierAgent runs
    Then all sources remain in state
    And body_markdown is unchanged
    """

    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_all_valid_sources_preserved(self, mock_verify):
        # Given verify_links is true and all URLs return 200
        mock_verify.return_value = {
            "https://a.com/1": LinkCheckResult(url="https://a.com/1", status="valid", http_status=200),
            "https://b.com/2": LinkCheckResult(url="https://b.com/2", status="valid", http_status=200),
        }
        body = "See [A](https://a.com/1) and [B](https://b.com/2)."
        sources = [
            {"title": "A", "url": "https://a.com/1"},
            {"title": "B", "url": "https://b.com/2"},
        ]
        state = {
            "config_verify_links": True,
            "config_topic_count": 1,
            "synthesis_0": _synthesis("AI", body, sources),
        }

        # When LinkVerifierAgent runs
        agent = LinkVerifierAgent(name="LinkVerifier")
        async for _ in agent._run_async_impl(_make_ctx(state)):
            pass

        # Then all sources remain
        assert len(state["synthesis_0"]["sources"]) == 2
        # And body_markdown is unchanged
        assert state["synthesis_0"]["body_markdown"] == body


class TestSomeLinksBroken:
    """Scenario: Some links broken

    Given verify_links is true
    And 2 of 5 source URLs return errors (404, timeout)
    When LinkVerifierAgent runs
    Then the 2 broken sources are removed
    And their inline citations are replaced with unlinked text
    And the 3 valid sources remain
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
        body = (
            "See [OK1](https://ok1.com), [Dead](https://dead.com), "
            "[OK2](https://ok2.com), [Slow](https://slow.com), [OK3](https://ok3.com)."
        )
        sources = [
            {"title": "OK1", "url": "https://ok1.com"},
            {"title": "Dead", "url": "https://dead.com"},
            {"title": "OK2", "url": "https://ok2.com"},
            {"title": "Slow", "url": "https://slow.com"},
            {"title": "OK3", "url": "https://ok3.com"},
        ]
        state = {
            "config_verify_links": True,
            "config_topic_count": 1,
            "synthesis_0": _synthesis("AI", body, sources),
        }

        # When LinkVerifierAgent runs
        agent = LinkVerifierAgent(name="LinkVerifier")
        async for _ in agent._run_async_impl(_make_ctx(state)):
            pass

        # Then 2 broken removed, 3 valid remain
        remaining = state["synthesis_0"]["sources"]
        assert len(remaining) == 3
        remaining_urls = {s["url"] for s in remaining}
        assert "https://dead.com" not in remaining_urls
        assert "https://slow.com" not in remaining_urls

        # And citations cleaned
        cleaned = state["synthesis_0"]["body_markdown"]
        assert "[Dead](https://dead.com)" not in cleaned
        assert "[Slow](https://slow.com)" not in cleaned
        assert "[OK1](https://ok1.com)" in cleaned


class TestAllLinksBrokenForTopic:
    """Scenario: All links broken for a topic

    Given verify_links is true
    And all source URLs for a topic return errors
    When LinkVerifierAgent runs
    Then sources list is empty
    And a notice is appended to body_markdown
    """

    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_all_broken_notice_appended(self, mock_verify):
        # Given all URLs broken
        mock_verify.return_value = {
            "https://dead1.com": LinkCheckResult(url="https://dead1.com", status="broken", http_status=404, error="status_404"),
            "https://dead2.com": LinkCheckResult(url="https://dead2.com", status="broken", http_status=500, error="status_500"),
        }
        state = {
            "config_verify_links": True,
            "config_topic_count": 1,
            "synthesis_0": _synthesis(
                "AI",
                "See [D1](https://dead1.com) and [D2](https://dead2.com).",
                [
                    {"title": "D1", "url": "https://dead1.com"},
                    {"title": "D2", "url": "https://dead2.com"},
                ],
            ),
        }

        # When LinkVerifierAgent runs
        agent = LinkVerifierAgent(name="LinkVerifier")
        async for _ in agent._run_async_impl(_make_ctx(state)):
            pass

        # Then sources empty and notice appended
        assert state["synthesis_0"]["sources"] == []
        assert state["synthesis_0"]["body_markdown"].endswith(_ALL_BROKEN_NOTICE)


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
        body = "See [A](https://a.com)."
        sources = [{"title": "A", "url": "https://a.com"}]
        state = {
            "config_verify_links": False,
            "config_topic_count": 1,
            "synthesis_0": _synthesis("AI", body, sources),
        }

        # When LinkVerifierAgent runs
        agent = LinkVerifierAgent(name="LinkVerifier")
        async for _ in agent._run_async_impl(_make_ctx(state)):
            pass

        # Then no HTTP calls made
        mock_verify.assert_not_called()
        # And state unchanged
        assert state["synthesis_0"]["body_markdown"] == body
        assert state["synthesis_0"]["sources"] == sources


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
        body = "See [A](https://a.com)."
        sources = [{"title": "A", "url": "https://a.com"}]
        state = {
            "config_verify_links": True,
            "config_topic_count": 1,
            "synthesis_0": _synthesis("AI", body, list(sources)),
        }

        # When LinkVerifierAgent runs
        agent = LinkVerifierAgent(name="LinkVerifier")
        async for _ in agent._run_async_impl(_make_ctx(state)):
            pass

        # Then state unchanged (graceful degradation)
        assert state["synthesis_0"]["body_markdown"] == body
        assert state["synthesis_0"]["sources"] == sources
