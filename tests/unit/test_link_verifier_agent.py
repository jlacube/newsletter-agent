"""Unit tests for LinkVerifierAgent.

Mocks verify_urls() to return predetermined results and tests agent behavior
for disabled verification, all-valid, some-broken, all-broken, and failure
scenarios. Tests verify the post-research mode where the agent reads
research_{idx}_{provider} state entries (markdown text).

Spec refs: Section 11.1, FR-016 through FR-024.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from newsletter_agent.tools.link_verifier import LinkCheckResult
from newsletter_agent.tools.link_verifier_agent import LinkVerifierAgent, SynthesisLinkVerifierAgent


def _make_ctx(state: dict) -> MagicMock:
    """Create a mock InvocationContext with the given session state."""
    ctx = MagicMock()
    ctx.session.state = state
    return ctx


def _research_entry(body_links: list[tuple[str, str]]) -> str:
    """Build a research state entry (markdown string).

    Args:
        body_links: list of (title, url) for markdown links.
    """
    body_parts = [f"[{t}]({u})" for t, u in body_links]
    body = "Analysis: " + ", ".join(body_parts) + "."
    sources = "\n".join(f"- [{t}]({u})" for t, u in body_links)
    return f"SUMMARY:\n{body}\n\nSOURCES:\n{sources}"


class TestLinkVerifierAgentDisabled:
    @pytest.mark.asyncio
    async def test_no_op_when_verify_links_false(self):
        text = _research_entry([("A", "http://a.com")])
        state = {
            "config_verify_links": False,
            "research_0_google": text,
        }
        agent = LinkVerifierAgent(name="LinkVerifier", topic_count=1, providers=["google"])
        ctx = _make_ctx(state)

        events = []
        async for event in agent._run_async_impl(ctx):
            events.append(event)

        # State unchanged
        assert state["research_0_google"] == text
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_no_op_when_verify_links_missing(self):
        text = _research_entry([("A", "http://a.com")])
        state = {"research_0_google": text}
        agent = LinkVerifierAgent(name="LinkVerifier", topic_count=1, providers=["google"])
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
        text = _research_entry([("A", "http://a.com"), ("B", "http://b.com")])
        state = {
            "config_verify_links": True,
            "research_0_google": text,
        }
        agent = LinkVerifierAgent(name="LinkVerifier", topic_count=1, providers=["google"])
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        # Text unchanged (no broken links to remove)
        assert state["research_0_google"] == text


class TestLinkVerifierAgentSomeBroken:
    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_broken_links_removed(self, mock_verify):
        mock_verify.return_value = {
            "http://a.com": LinkCheckResult(url="http://a.com", status="valid", http_status=200),
            "http://b.com": LinkCheckResult(url="http://b.com", status="broken", http_status=404, error="status_404"),
            "http://c.com": LinkCheckResult(url="http://c.com", status="valid", http_status=200),
        }
        text = _research_entry(
            [("A", "http://a.com"), ("B", "http://b.com"), ("C", "http://c.com")],
        )
        state = {
            "config_verify_links": True,
            "research_0_google": text,
        }
        agent = LinkVerifierAgent(name="LinkVerifier", topic_count=1, providers=["google"])
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        result = state["research_0_google"]
        # Broken link removed, title text preserved
        assert "http://b.com" not in result
        assert "B" in result
        # Valid links preserved
        assert "[A](http://a.com)" in result
        assert "[C](http://c.com)" in result


class TestLinkVerifierAgentAllBroken:
    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_all_broken_links_cleaned(self, mock_verify):
        mock_verify.return_value = {
            "http://a.com": LinkCheckResult(url="http://a.com", status="broken", http_status=404, error="status_404"),
            "http://b.com": LinkCheckResult(url="http://b.com", status="broken", http_status=500, error="status_500"),
        }
        text = _research_entry(
            [("A", "http://a.com"), ("B", "http://b.com")],
        )
        state = {
            "config_verify_links": True,
            "research_0_google": text,
        }
        agent = LinkVerifierAgent(name="LinkVerifier", topic_count=1, providers=["google"])
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        result = state["research_0_google"]
        # Links removed
        assert "http://a.com" not in result
        assert "http://b.com" not in result
        # Title text preserved
        assert "A" in result
        assert "B" in result


class TestLinkVerifierAgentFailure:
    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_total_failure_state_unchanged(self, mock_verify):
        """If verify_urls raises, agent logs warning and proceeds."""
        mock_verify.side_effect = Exception("network completely down")
        text = _research_entry([("A", "http://a.com")])
        state = {
            "config_verify_links": True,
            "research_0_google": text,
        }
        agent = LinkVerifierAgent(name="LinkVerifier", topic_count=1, providers=["google"])
        ctx = _make_ctx(state)

        events = []
        async for event in agent._run_async_impl(ctx):
            events.append(event)

        # State unchanged
        assert state["research_0_google"] == text
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
            "research_0_google": _research_entry(
                [("A", "http://a.com"), ("B", "http://b.com")]
            ),
            "research_1_google": _research_entry(
                [("C", "http://c.com")]
            ),
        }
        agent = LinkVerifierAgent(name="LinkVerifier", topic_count=2, providers=["google"])
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        # Topic 0: A valid, B broken
        assert "[A](http://a.com)" in state["research_0_google"]
        assert "http://b.com" not in state["research_0_google"]

        # Topic 1: C broken
        assert "http://c.com" not in state["research_1_google"]
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
            "research_0_google": _research_entry([("Shared", "http://shared.com")]),
            "research_1_google": _research_entry([("Shared", "http://shared.com")]),
        }
        agent = LinkVerifierAgent(name="LinkVerifier", topic_count=2, providers=["google"])
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
            "research_0_google": "SUMMARY:\nNo links.\n\nSOURCES:\n(none)",
        }
        agent = LinkVerifierAgent(name="LinkVerifier", topic_count=1, providers=["google"])
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        mock_verify.assert_not_called()

    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_skips_missing_research_entries(self, mock_verify):
        """Missing research entries should be skipped gracefully."""
        state = {
            "config_verify_links": True,
            # research_0_google missing
        }
        agent = LinkVerifierAgent(name="LinkVerifier", topic_count=1, providers=["google"])
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        mock_verify.assert_not_called()


# ---------------------------------------------------------------------------
# SynthesisLinkVerifierAgent tests
# ---------------------------------------------------------------------------

def _synthesis_entry(
    title: str,
    body_links: list[tuple[str, str]],
    source_links: list[tuple[str, str]] | None = None,
) -> dict:
    """Build a synthesis state entry (dict with body_markdown, sources, title)."""
    body_parts = [f"[{t}]({u})" for t, u in body_links]
    body = "Analysis: " + ", ".join(body_parts) + "."
    if source_links is None:
        source_links = body_links
    sources = [{"title": t, "url": u} for t, u in source_links]
    return {"title": title, "body_markdown": body, "sources": sources}


class TestSynthesisLinkVerifierDisabled:
    @pytest.mark.asyncio
    async def test_no_op_when_verify_links_false(self):
        section = _synthesis_entry("AI", [("A", "http://a.com")])
        state = {
            "config_verify_links": False,
            "synthesis_0": section,
        }
        agent = SynthesisLinkVerifierAgent(
            name="SynthesisLinkVerifier", topic_count=1
        )
        ctx = _make_ctx(state)

        events = []
        async for event in agent._run_async_impl(ctx):
            events.append(event)

        assert state["synthesis_0"] == section
        assert len(events) == 1


class TestSynthesisLinkVerifierAllValid:
    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_all_valid_state_unchanged(self, mock_verify):
        mock_verify.return_value = {
            "http://a.com": LinkCheckResult(url="http://a.com", status="valid", http_status=200),
            "http://b.com": LinkCheckResult(url="http://b.com", status="valid", http_status=200),
        }
        section = _synthesis_entry(
            "AI", [("A", "http://a.com"), ("B", "http://b.com")]
        )
        state = {
            "config_verify_links": True,
            "synthesis_0": section,
        }
        agent = SynthesisLinkVerifierAgent(
            name="SynthesisLinkVerifier", topic_count=1
        )
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        assert "[A](http://a.com)" in state["synthesis_0"]["body_markdown"]
        assert len(state["synthesis_0"]["sources"]) == 2


class TestSynthesisLinkVerifierBroken:
    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_broken_links_removed_from_body_and_sources(self, mock_verify):
        mock_verify.return_value = {
            "http://a.com": LinkCheckResult(url="http://a.com", status="valid", http_status=200),
            "http://broken.com": LinkCheckResult(
                url="http://broken.com", status="broken", http_status=404, error="status_404"
            ),
        }
        section = _synthesis_entry(
            "AI",
            [("A", "http://a.com"), ("Broken", "http://broken.com")],
        )
        state = {
            "config_verify_links": True,
            "synthesis_0": section,
        }
        agent = SynthesisLinkVerifierAgent(
            name="SynthesisLinkVerifier", topic_count=1
        )
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        # Body: broken link removed (converted to plain text)
        assert "[A](http://a.com)" in state["synthesis_0"]["body_markdown"]
        assert "http://broken.com" not in state["synthesis_0"]["body_markdown"]
        assert "Broken" in state["synthesis_0"]["body_markdown"]

        # Sources: broken URL removed
        source_urls = [s["url"] for s in state["synthesis_0"]["sources"]]
        assert "http://a.com" in source_urls
        assert "http://broken.com" not in source_urls

    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_multiple_topics_processed(self, mock_verify):
        mock_verify.return_value = {
            "http://a.com": LinkCheckResult(url="http://a.com", status="valid", http_status=200),
            "http://bad1.com": LinkCheckResult(
                url="http://bad1.com", status="broken", error="dns_error"
            ),
            "http://bad2.com": LinkCheckResult(
                url="http://bad2.com", status="broken", error="soft_404"
            ),
        }
        state = {
            "config_verify_links": True,
            "synthesis_0": _synthesis_entry("AI", [("A", "http://a.com"), ("Bad", "http://bad1.com")]),
            "synthesis_1": _synthesis_entry("Cloud", [("Bad2", "http://bad2.com")]),
        }
        agent = SynthesisLinkVerifierAgent(
            name="SynthesisLinkVerifier", topic_count=2
        )
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        assert "[A](http://a.com)" in state["synthesis_0"]["body_markdown"]
        assert "http://bad1.com" not in state["synthesis_0"]["body_markdown"]
        assert "http://bad2.com" not in state["synthesis_1"]["body_markdown"]
        assert len(state["synthesis_1"]["sources"]) == 0


class TestSynthesisLinkVerifierNoUrls:
    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_no_urls_skips_verification(self, mock_verify):
        state = {
            "config_verify_links": True,
            "synthesis_0": {"title": "AI", "body_markdown": "No links here.", "sources": []},
        }
        agent = SynthesisLinkVerifierAgent(
            name="SynthesisLinkVerifier", topic_count=1
        )
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        mock_verify.assert_not_called()


class TestSynthesisLinkVerifierFailure:
    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_exception_gracefully_handled(self, mock_verify):
        mock_verify.side_effect = RuntimeError("network failure")
        section = _synthesis_entry("AI", [("A", "http://a.com")])
        original_body = section["body_markdown"]
        state = {
            "config_verify_links": True,
            "synthesis_0": section,
        }
        agent = SynthesisLinkVerifierAgent(
            name="SynthesisLinkVerifier", topic_count=1
        )
        ctx = _make_ctx(state)

        events = []
        async for event in agent._run_async_impl(ctx):
            events.append(event)

        # State unchanged on failure
        assert state["synthesis_0"]["body_markdown"] == original_body
        assert len(events) == 1
