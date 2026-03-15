"""
Unit tests for the DeliveryAgent.

Spec refs: Section 11.1, FR-027, FR-031, FR-032.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from newsletter_agent.tools.delivery import DeliveryAgent


def _make_state(dry_run=False, has_html=True, recipient="test@gmail.com"):
    state = {
        "config_dry_run": dry_run,
        "config_output_dir": "/tmp/output",
        "config_recipient_email": recipient,
        "config_recipient_emails": [recipient] if recipient else [],
        "newsletter_metadata": {
            "title": "Test Newsletter",
            "date": "2026-03-14",
            "topic_count": 3,
            "generation_time_seconds": 60.0,
        },
    }
    if has_html:
        state["newsletter_html"] = "<h1>Test Newsletter</h1>"
    else:
        state["newsletter_html"] = ""
    return state


def _make_ctx(state):
    ctx = MagicMock()
    ctx.session.state = state
    return ctx


class TestDryRunMode:
    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.delivery.save_newsletter_html", return_value="/tmp/output/2026-03-14-newsletter.html")
    async def test_dry_run_saves_html(self, mock_save):
        agent = DeliveryAgent(name="TestDelivery")
        state = _make_state(dry_run=True)
        ctx = _make_ctx(state)

        events = []
        async for event in agent._run_async_impl(ctx):
            events.append(event)

        mock_save.assert_called_once()
        assert state["delivery_status"]["status"] == "dry_run"
        assert "output_file" in state["delivery_status"]

    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.delivery.save_newsletter_html", return_value="/tmp/out.html")
    @patch("newsletter_agent.tools.delivery.send_newsletter_email")
    async def test_dry_run_does_not_send_email(self, mock_send, mock_save):
        agent = DeliveryAgent(name="TestDelivery")
        state = _make_state(dry_run=True)
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        mock_send.assert_not_called()


class TestSuccessfulSend:
    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.delivery.send_newsletter_email", return_value={"status": "sent", "recipients": [{"email": "test@gmail.com", "status": "sent", "message_id": "msg-123"}]})
    async def test_sends_email(self, mock_send):
        agent = DeliveryAgent(name="TestDelivery")
        state = _make_state(dry_run=False)
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        mock_send.assert_called_once()
        assert state["delivery_status"]["status"] == "sent"
        assert state["delivery_status"]["recipients"][0]["message_id"] == "msg-123"

    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.delivery.send_newsletter_email", return_value={"status": "sent", "recipients": [{"email": "test@gmail.com", "status": "sent", "message_id": "x"}]})
    async def test_correct_subject_format(self, mock_send):
        agent = DeliveryAgent(name="TestDelivery")
        state = _make_state(dry_run=False)
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        call_args = mock_send.call_args
        subject = call_args[0][2]
        assert subject == "Test Newsletter - 2026-03-14"


class TestEmailFailureFallback:
    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.delivery.save_newsletter_html", return_value="/tmp/fallback.html")
    @patch("newsletter_agent.tools.delivery.send_newsletter_email", return_value={"status": "failed", "recipients": [{"email": "test@gmail.com", "status": "error", "error": "Auth failed"}]})
    async def test_fallback_on_failure(self, mock_send, mock_save):
        agent = DeliveryAgent(name="TestDelivery")
        state = _make_state(dry_run=False)
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        mock_save.assert_called_once()
        assert state["delivery_status"]["status"] == "failed"
        assert "fallback_file" in state["delivery_status"]
        assert "error" in state["delivery_status"]


class TestNoRecipient:
    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.delivery.save_newsletter_html", return_value="/tmp/fallback.html")
    async def test_no_recipient_saves_fallback(self, mock_save):
        agent = DeliveryAgent(name="TestDelivery")
        state = _make_state(dry_run=False, recipient="")
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        mock_save.assert_called_once()
        assert state["delivery_status"]["status"] == "failed"
        assert "No recipient" in state["delivery_status"]["error"]


class TestEmptyHtml:
    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.delivery.save_newsletter_html", return_value="/tmp/out.html")
    async def test_dry_run_with_empty_html(self, mock_save):
        agent = DeliveryAgent(name="TestDelivery")
        state = _make_state(dry_run=True, has_html=False)
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        # Should still save (even empty content)
        mock_save.assert_called_once()


class TestMissingHtmlKey:
    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.delivery.save_newsletter_html", return_value="/tmp/out.html")
    async def test_missing_newsletter_html_key_uses_empty_string(self, mock_save):
        """When newsletter_html key is absent from state, agent should default to empty."""
        agent = DeliveryAgent(name="TestDelivery")
        state = _make_state(dry_run=True)
        del state["newsletter_html"]  # Remove the key entirely
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        # Should still save with empty default
        mock_save.assert_called_once()
        assert state["delivery_status"]["status"] == "dry_run"
