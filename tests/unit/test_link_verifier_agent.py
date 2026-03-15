"""Unit tests for LinkVerifierAgent.

Mocks verify_urls() to return predetermined results and tests agent behavior
for disabled verification, all-valid, some-broken, and failure scenarios.
Tests verify the pre-synthesis mode where the agent reads research state keys.

Spec refs: Section 11.1 (LinkVerifierAgent unit tests), FR-PSV-003 through FR-PSV-006.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from newsletter_agent.tools.link_verifier import LinkCheckResult
from newsletter_agent.tools.link_verifier_agent import LinkVerifierAgent


def _make_ctx(state: dict) -> MagicMock:
    """Create a mock InvocationContext with the given session state."""
    ctx = MagicMock()
    ctx.session.state = state
    return ctx


def _research_text(links: list[tuple[str, str]]) -> str:
    """Build research text with markdown links.

    Args:
        links: list of (title, url) tuples.
    """
    parts = [f"[{title}]({url})" for title, url in links]
    return "Research findings: " + ", ".join(parts) + "."


class TestLinkVerifierAgentDisabled:
    @pytest.mark.asyncio
    async def test_no_op_when_verify_links_false(self):
        research_text = _research_text([("A", "http://a.com")])
        state = {
            "config_verify_links": False,
            "research_0_google": research_text,
        }
        agent = LinkVerifierAgent(
            name="LinkVerifier", topic_count=1, providers=["google"],
        )
        ctx = _make_ctx(state)

        events = []
        async for event in agent._run_async_impl(ctx):
            events.append(event)

        # State unchanged
        assert state["research_0_google"] == research_text
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_no_op_when_verify_links_missing(self):
        state = {"research_0_google": "Some text"}
        agent = LinkVerifierAgent(
            name="LinkVerifier", topic_count=1, providers=["google"],
        )
        ctx = _make_ctx(state)

        events = []
        async for event in agent._run_async_impl(ctx):
            events.append(event)

        assert len(events) == 1


class TestLinkVerifierAgentAllValid:
    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_all_links_valid_state_unchanged(self, mock_verify):
        mock_verify.return_value = {
            "http://a.com": LinkCheckResult(url="http://a.com", status="valid", http_status=200),
            "http://b.com": LinkCheckResult(url="http://b.com", status="valid", http_status=200),
        }
        research_text = _research_text([("A", "http://a.com"), ("B", "http://b.com")])
        state = {
            "config_verify_links": True,
            "research_0_google": research_text,
        }
        agent = LinkVerifierAgent(
            name="LinkVerifier", topic_count=1, providers=["google"],
        )
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        # Text unchanged
        assert state["research_0_google"] == research_text


class TestLinkVerifierAgentSomeBroken:
    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_broken_links_removed_from_research_text(self, mock_verify):
        mock_verify.return_value = {
            "http://a.com": LinkCheckResult(url="http://a.com", status="valid", http_status=200),
            "http://b.com": LinkCheckResult(url="http://b.com", status="broken", http_status=404, error="status_404"),
            "http://c.com": LinkCheckResult(url="http://c.com", status="valid", http_status=200),
        }
        research_text = (
            "Read [A](http://a.com), [B](http://b.com), and [C](http://c.com)."
        )
        state = {
            "config_verify_links": True,
            "research_0_google": research_text,
        }
        agent = LinkVerifierAgent(
            name="LinkVerifier", topic_count=1, providers=["google"],
        )
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        cleaned = state["research_0_google"]
        # Broken link removed, title text preserved
        assert "[B](http://b.com)" not in cleaned
        assert "B" in cleaned
        # Valid links preserved
        assert "[A](http://a.com)" in cleaned
        assert "[C](http://c.com)" in cleaned

    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_cleans_both_providers(self, mock_verify):
        mock_verify.return_value = {
            "http://a.com": LinkCheckResult(url="http://a.com", status="valid", http_status=200),
            "http://bad.com": LinkCheckResult(url="http://bad.com", status="broken", http_status=404, error="status_404"),
        }
        state = {
            "config_verify_links": True,
            "research_0_google": "See [A](http://a.com) and [Bad](http://bad.com).",
            "research_0_perplexity": "Found [Bad](http://bad.com) info.",
        }
        agent = LinkVerifierAgent(
            name="LinkVerifier", topic_count=1, providers=["google", "perplexity"],
        )
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        assert "[Bad](http://bad.com)" not in state["research_0_google"]
        assert "[Bad](http://bad.com)" not in state["research_0_perplexity"]
        assert "[A](http://a.com)" in state["research_0_google"]


class TestLinkVerifierAgentAllBroken:
    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_all_broken_links_cleaned(self, mock_verify):
        mock_verify.return_value = {
            "http://a.com": LinkCheckResult(url="http://a.com", status="broken", http_status=404, error="status_404"),
            "http://b.com": LinkCheckResult(url="http://b.com", status="broken", http_status=500, error="status_500"),
        }
        state = {
            "config_verify_links": True,
            "research_0_google": "Read [A](http://a.com) and [B](http://b.com).",
        }
        agent = LinkVerifierAgent(
            name="LinkVerifier", topic_count=1, providers=["google"],
        )
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        cleaned = state["research_0_google"]
        assert "[A](http://a.com)" not in cleaned
        assert "[B](http://b.com)" not in cleaned
        assert "A" in cleaned
        assert "B" in cleaned


class TestLinkVerifierAgentFailure:
    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_total_failure_state_unchanged(self, mock_verify):
        """If verify_urls raises, agent logs warning and proceeds."""
        mock_verify.side_effect = Exception("network completely down")
        original_text = "See [A](http://a.com)."
        state = {
            "config_verify_links": True,
            "research_0_google": original_text,
        }
        agent = LinkVerifierAgent(
            name="LinkVerifier", topic_count=1, providers=["google"],
        )
        ctx = _make_ctx(state)

        events = []
        async for event in agent._run_async_impl(ctx):
            events.append(event)

        # State unchanged
        assert state["research_0_google"] == original_text
        assert len(events) == 1


class TestLinkVerifierAgentMultipleTopics:
    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_processes_topics_independently(self, mock_verify):
        mock_verify.return_value = {
            "http://a.com": LinkCheckResult(url="http://a.com", status="valid", http_status=200),
            "http://b.com": LinkCheckResult(url="http://b.com", status="broken", http_status=404, error="status_404"),
            "http://c.com": LinkCheckResult(url="http://c.com", status="broken", http_status=500, error="status_500"),
        }
        state = {
            "config_verify_links": True,
            "research_0_google": "See [A](http://a.com) and [B](http://b.com).",
            "research_1_google": "Read [C](http://c.com).",
        }
        agent = LinkVerifierAgent(
            name="LinkVerifier", topic_count=2, providers=["google"],
        )
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        # Topic 0: A valid, B broken
        assert "[A](http://a.com)" in state["research_0_google"]
        assert "[B](http://b.com)" not in state["research_0_google"]

        # Topic 1: C broken
        assert "[C](http://c.com)" not in state["research_1_google"]
        assert "C" in state["research_1_google"]

    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_deduplicates_urls_across_topics(self, mock_verify):
        """Same URL in multiple topics should be verified once."""
        mock_verify.return_value = {
            "http://shared.com": LinkCheckResult(
                url="http://shared.com", status="valid", http_status=200
            ),
        }
        state = {
            "config_verify_links": True,
            "research_0_google": "[Shared](http://shared.com) info.",
            "research_1_google": "[Shared](http://shared.com) more.",
        }
        agent = LinkVerifierAgent(
            name="LinkVerifier", topic_count=2, providers=["google"],
        )
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        # verify_urls called with deduplicated list
        call_args = mock_verify.call_args[0][0]
        assert len(call_args) == 1

    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_no_urls_skips_verification(self, mock_verify):
        state = {
            "config_verify_links": True,
            "research_0_google": "No links here.",
        }
        agent = LinkVerifierAgent(
            name="LinkVerifier", topic_count=1, providers=["google"],
        )
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        mock_verify.assert_not_called()

    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_skips_non_string_research_keys(self, mock_verify):
        """Dict values (error results) should be skipped gracefully."""
        state = {
            "config_verify_links": True,
            "research_0_google": {"error": True, "message": "API failure"},
        }
        agent = LinkVerifierAgent(
            name="LinkVerifier", topic_count=1, providers=["google"],
        )
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        mock_verify.assert_not_called()
