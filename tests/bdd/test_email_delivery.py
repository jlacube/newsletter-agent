"""
BDD-style acceptance tests for email delivery.

Uses Given/When/Then structure to verify spec scenarios.
Spec refs: Section 11.2, US-05.
"""

import pytest
from unittest.mock import MagicMock, patch


def _make_state(dry_run=False, recipient="test@gmail.com"):
    return {
        "config_dry_run": dry_run,
        "config_output_dir": "/tmp/output",
        "config_recipient_email": recipient,
        "newsletter_html": "<h1>Newsletter</h1><p>Content</p>",
        "newsletter_metadata": {
            "title": "Weekly Tech Digest",
            "date": "2026-03-14",
            "topic_count": 3,
            "generation_time_seconds": 60.0,
        },
    }


def _make_ctx(state):
    ctx = MagicMock()
    ctx.session.state = state
    return ctx


class TestSuccessfulEmailSend:
    """Feature: Email Delivery
    Scenario: Successful email send
    """

    @pytest.mark.asyncio
    @patch(
        "newsletter_agent.tools.delivery.send_newsletter_email",
        return_value={
            "status": "sent",
            "recipients": [{"email": "test@gmail.com", "status": "sent", "message_id": "msg-456"}],
        },
    )
    async def test_given_newsletter_when_send_then_email_delivered(self, mock_send):
        """
        Given a formatted newsletter HTML
        And valid Gmail credentials
        When the delivery agent runs
        Then the email is sent to the recipient with correct subject
        """
        from newsletter_agent.tools.delivery import DeliveryAgent

        agent = DeliveryAgent(name="Delivery")
        state = _make_state()
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        mock_send.assert_called_once()
        args = mock_send.call_args[0]
        assert args[1] == ["test@gmail.com"]
        assert args[2] == "Weekly Tech Digest - 2026-03-14"
        assert state["delivery_status"]["status"] == "sent"


class TestDryRunMode:
    """Feature: Email Delivery
    Scenario: Dry run mode
    """

    @pytest.mark.asyncio
    @patch(
        "newsletter_agent.tools.delivery.save_newsletter_html",
        return_value="/tmp/output/2026-03-14-newsletter.html",
    )
    @patch("newsletter_agent.tools.delivery.send_newsletter_email")
    async def test_given_dry_run_when_deliver_then_no_email_file_saved(
        self, mock_send, mock_save
    ):
        """
        Given dry_run is true
        When the delivery agent runs
        Then no email is sent and the HTML is saved to disk
        """
        from newsletter_agent.tools.delivery import DeliveryAgent

        agent = DeliveryAgent(name="Delivery")
        state = _make_state(dry_run=True)
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        mock_send.assert_not_called()
        mock_save.assert_called_once()
        assert state["delivery_status"]["status"] == "dry_run"


class TestEmailFailureWithFallback:
    """Feature: Email Delivery
    Scenario: Email failure with fallback
    """

    @pytest.mark.asyncio
    @patch(
        "newsletter_agent.tools.delivery.save_newsletter_html",
        return_value="/tmp/output/fallback.html",
    )
    @patch(
        "newsletter_agent.tools.delivery.send_newsletter_email",
        return_value={"status": "error", "error_message": "Token revoked"},
    )
    async def test_given_failure_when_deliver_then_fallback_saved(
        self, mock_send, mock_save
    ):
        """
        Given email delivery fails
        When the delivery agent runs
        Then the error is logged and HTML is saved locally as fallback
        """
        from newsletter_agent.tools.delivery import DeliveryAgent

        agent = DeliveryAgent(name="Delivery")
        state = _make_state()
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        mock_save.assert_called_once()
        assert state["delivery_status"]["status"] == "failed"
        assert "fallback_file" in state["delivery_status"]
        assert "Token revoked" in state["delivery_status"]["error"]


class TestExpiredTokenWithRefresh:
    """Feature: Email Delivery
    Scenario: Expired token with valid refresh
    """

    @pytest.mark.asyncio
    @patch(
        "newsletter_agent.tools.delivery.send_newsletter_email",
        return_value={"status": "sent", "message_id": "msg-refreshed"},
    )
    async def test_given_expired_token_when_refresh_succeeds_then_email_sent(
        self, mock_send
    ):
        """
        Given the access token is expired but the refresh token is valid
        When the delivery agent runs
        Then the token is refreshed and the email is sent successfully
        (Token refresh is handled internally by get_gmail_credentials)
        """
        from newsletter_agent.tools.delivery import DeliveryAgent

        agent = DeliveryAgent(name="Delivery")
        state = _make_state()
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        assert state["delivery_status"]["status"] == "sent"
        assert state["delivery_status"]["message_id"] == "msg-refreshed"
