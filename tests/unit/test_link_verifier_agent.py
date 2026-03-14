"""Unit tests for LinkVerifierAgent.

Mocks verify_urls() to return predetermined results and tests agent behavior
for disabled verification, all-valid, some-broken, all-broken, and failure.

Spec refs: Section 11.1 (LinkVerifierAgent unit tests).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from newsletter_agent.tools.link_verifier import LinkCheckResult
from newsletter_agent.tools.link_verifier_agent import LinkVerifierAgent, _ALL_BROKEN_NOTICE


def _make_ctx(state: dict) -> MagicMock:
    """Create a mock InvocationContext with the given session state."""
    ctx = MagicMock()
    ctx.session.state = state
    return ctx


def _synthesis_entry(topic_name: str, body: str, sources: list[dict]) -> dict:
    return {
        "topic_name": topic_name,
        "body_markdown": body,
        "sources": sources,
    }


class TestLinkVerifierAgentDisabled:
    @pytest.mark.asyncio
    async def test_no_op_when_verify_links_false(self):
        state = {
            "config_verify_links": False,
            "config_topic_count": 1,
            "synthesis_0": _synthesis_entry(
                "AI",
                "See [A](http://a.com).",
                [{"title": "A", "url": "http://a.com"}],
            ),
        }
        agent = LinkVerifierAgent(name="LinkVerifier")
        ctx = _make_ctx(state)

        events = []
        async for event in agent._run_async_impl(ctx):
            events.append(event)

        # State unchanged
        assert len(state["synthesis_0"]["sources"]) == 1
        assert state["synthesis_0"]["body_markdown"] == "See [A](http://a.com)."
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_no_op_when_verify_links_missing(self):
        state = {"config_topic_count": 1}
        agent = LinkVerifierAgent(name="LinkVerifier")
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
        body = "See [A](http://a.com) and [B](http://b.com)."
        sources = [
            {"title": "A", "url": "http://a.com"},
            {"title": "B", "url": "http://b.com"},
        ]
        state = {
            "config_verify_links": True,
            "config_topic_count": 1,
            "synthesis_0": _synthesis_entry("AI", body, sources),
        }
        agent = LinkVerifierAgent(name="LinkVerifier")
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        # Body and sources unchanged
        assert state["synthesis_0"]["body_markdown"] == body
        assert len(state["synthesis_0"]["sources"]) == 2


class TestLinkVerifierAgentSomeBroken:
    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_broken_links_removed(self, mock_verify):
        mock_verify.return_value = {
            "http://a.com": LinkCheckResult(url="http://a.com", status="valid", http_status=200),
            "http://b.com": LinkCheckResult(url="http://b.com", status="broken", http_status=404, error="status_404"),
            "http://c.com": LinkCheckResult(url="http://c.com", status="valid", http_status=200),
            "http://d.com": LinkCheckResult(url="http://d.com", status="broken", http_status=None, error="timeout"),
            "http://e.com": LinkCheckResult(url="http://e.com", status="valid", http_status=200),
        }
        body = (
            "Read [A](http://a.com), [B](http://b.com), "
            "[C](http://c.com), [D](http://d.com), and [E](http://e.com)."
        )
        sources = [
            {"title": "A", "url": "http://a.com"},
            {"title": "B", "url": "http://b.com"},
            {"title": "C", "url": "http://c.com"},
            {"title": "D", "url": "http://d.com"},
            {"title": "E", "url": "http://e.com"},
        ]
        state = {
            "config_verify_links": True,
            "config_topic_count": 1,
            "synthesis_0": _synthesis_entry("AI", body, sources),
        }
        agent = LinkVerifierAgent(name="LinkVerifier")
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        # 2 broken removed, 3 remain
        assert len(state["synthesis_0"]["sources"]) == 3
        remaining_urls = [s["url"] for s in state["synthesis_0"]["sources"]]
        assert "http://b.com" not in remaining_urls
        assert "http://d.com" not in remaining_urls

        # Markdown citations cleaned
        cleaned_body = state["synthesis_0"]["body_markdown"]
        assert "[B](http://b.com)" not in cleaned_body
        assert "[D](http://d.com)" not in cleaned_body
        assert "B" in cleaned_body  # Title text preserved
        assert "D" in cleaned_body
        assert "[A](http://a.com)" in cleaned_body  # Valid links preserved

    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_no_all_broken_notice_when_some_valid(self, mock_verify):
        mock_verify.return_value = {
            "http://a.com": LinkCheckResult(url="http://a.com", status="valid", http_status=200),
            "http://b.com": LinkCheckResult(url="http://b.com", status="broken", http_status=404, error="status_404"),
        }
        state = {
            "config_verify_links": True,
            "config_topic_count": 1,
            "synthesis_0": _synthesis_entry(
                "AI",
                "[A](http://a.com) and [B](http://b.com)",
                [
                    {"title": "A", "url": "http://a.com"},
                    {"title": "B", "url": "http://b.com"},
                ],
            ),
        }
        agent = LinkVerifierAgent(name="LinkVerifier")
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        assert _ALL_BROKEN_NOTICE not in state["synthesis_0"]["body_markdown"]


class TestLinkVerifierAgentAllBroken:
    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_all_broken_notice_appended(self, mock_verify):
        mock_verify.return_value = {
            "http://a.com": LinkCheckResult(url="http://a.com", status="broken", http_status=404, error="status_404"),
            "http://b.com": LinkCheckResult(url="http://b.com", status="broken", http_status=500, error="status_500"),
        }
        state = {
            "config_verify_links": True,
            "config_topic_count": 1,
            "synthesis_0": _synthesis_entry(
                "AI",
                "Read [A](http://a.com) and [B](http://b.com).",
                [
                    {"title": "A", "url": "http://a.com"},
                    {"title": "B", "url": "http://b.com"},
                ],
            ),
        }
        agent = LinkVerifierAgent(name="LinkVerifier")
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        assert state["synthesis_0"]["sources"] == []
        assert state["synthesis_0"]["body_markdown"].endswith(_ALL_BROKEN_NOTICE)


class TestLinkVerifierAgentFailure:
    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_total_failure_state_unchanged(self, mock_verify):
        """If verify_urls raises, agent logs warning and proceeds."""
        mock_verify.side_effect = Exception("network completely down")
        original_body = "See [A](http://a.com)."
        original_sources = [{"title": "A", "url": "http://a.com"}]
        state = {
            "config_verify_links": True,
            "config_topic_count": 1,
            "synthesis_0": _synthesis_entry("AI", original_body, list(original_sources)),
        }
        agent = LinkVerifierAgent(name="LinkVerifier")
        ctx = _make_ctx(state)

        events = []
        async for event in agent._run_async_impl(ctx):
            events.append(event)

        # State unchanged
        assert state["synthesis_0"]["body_markdown"] == original_body
        assert state["synthesis_0"]["sources"] == original_sources
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
            "config_topic_count": 2,
            "synthesis_0": _synthesis_entry(
                "Topic0",
                "See [A](http://a.com) and [B](http://b.com).",
                [
                    {"title": "A", "url": "http://a.com"},
                    {"title": "B", "url": "http://b.com"},
                ],
            ),
            "synthesis_1": _synthesis_entry(
                "Topic1",
                "Read [C](http://c.com).",
                [{"title": "C", "url": "http://c.com"}],
            ),
        }
        agent = LinkVerifierAgent(name="LinkVerifier")
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        # Topic 0: A valid, B broken
        assert len(state["synthesis_0"]["sources"]) == 1
        assert state["synthesis_0"]["sources"][0]["url"] == "http://a.com"
        assert "[B](http://b.com)" not in state["synthesis_0"]["body_markdown"]
        assert _ALL_BROKEN_NOTICE not in state["synthesis_0"]["body_markdown"]

        # Topic 1: C broken (all broken)
        assert state["synthesis_1"]["sources"] == []
        assert state["synthesis_1"]["body_markdown"].endswith(_ALL_BROKEN_NOTICE)

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
            "config_topic_count": 2,
            "synthesis_0": _synthesis_entry(
                "T0",
                "[Shared](http://shared.com)",
                [{"title": "Shared", "url": "http://shared.com"}],
            ),
            "synthesis_1": _synthesis_entry(
                "T1",
                "[Shared](http://shared.com)",
                [{"title": "Shared", "url": "http://shared.com"}],
            ),
        }
        agent = LinkVerifierAgent(name="LinkVerifier")
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
            "config_topic_count": 1,
            "synthesis_0": _synthesis_entry("AI", "No links here.", []),
        }
        agent = LinkVerifierAgent(name="LinkVerifier")
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        mock_verify.assert_not_called()
