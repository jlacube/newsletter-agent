"""
Unit tests for multi-recipient email delivery.

Covers: FR-MR-001 through FR-MR-012, Spec Section 5.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError

from newsletter_agent.config.schema import (
    ConfigValidationError,
    NewsletterConfig,
    NewsletterSettings,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _newsletter_settings(**overrides):
    base = {"title": "Test Newsletter", "schedule": "0 8 * * 0"}
    base.update(overrides)
    return NewsletterSettings(**base)


def _make_config(newsletter_overrides=None, topics=None):
    newsletter = {
        "title": "Test Newsletter",
        "schedule": "0 8 * * 0",
        "recipient_emails": ["a@example.com"],
    }
    if newsletter_overrides:
        newsletter.update(newsletter_overrides)
    return {
        "newsletter": newsletter,
        "topics": topics or [{"name": "Topic 1", "query": "Query 1"}],
    }


# ===========================================================================
# FB-01: Schema validation tests for multi-recipient
# ===========================================================================


class TestRecipientEmailsList:
    """FR-MR-001: recipient_emails list field accepts 1-10 items."""

    def test_accepts_single_email_list(self):
        s = _newsletter_settings(recipient_emails=["one@example.com"])
        assert s.recipient_emails == ["one@example.com"]

    def test_accepts_ten_email_list(self):
        emails = [f"user{i}@example.com" for i in range(1, 11)]
        s = _newsletter_settings(recipient_emails=emails)
        assert len(s.recipient_emails) == 10

    def test_accepts_two_emails(self):
        emails = ["a@example.com", "b@example.com"]
        s = _newsletter_settings(recipient_emails=emails)
        assert s.recipient_emails == emails

    def test_rejects_empty_list(self):
        """FR-MR-005: empty list rejected."""
        with pytest.raises(ValidationError, match="at least 1"):
            _newsletter_settings(recipient_emails=[])

    def test_rejects_more_than_ten(self):
        """FR-MR-001: >10 emails rejected."""
        emails = [f"user{i}@example.com" for i in range(11)]
        with pytest.raises(ValidationError, match="at most 10"):
            _newsletter_settings(recipient_emails=emails)

    def test_rejects_duplicate_emails(self):
        """FR-MR-004: duplicate emails rejected."""
        with pytest.raises(ValidationError, match="[Dd]uplicate"):
            _newsletter_settings(recipient_emails=["a@example.com", "a@example.com"])

    def test_rejects_case_insensitive_duplicates(self):
        """FR-MR-004: case-insensitive duplicate detection."""
        with pytest.raises(ValidationError, match="[Dd]uplicate"):
            _newsletter_settings(
                recipient_emails=["User@Example.com", "user@example.com"]
            )

    def test_rejects_invalid_email_in_list(self):
        """FR-MR-004: each email validated."""
        with pytest.raises(ValidationError, match="not a valid email"):
            _newsletter_settings(recipient_emails=["not-an-email"])


class TestBothFieldsPresent:
    """FR-MR-003: both fields present raises error."""

    def test_rejects_both_singular_and_plural(self):
        with pytest.raises(ValidationError, match="Cannot specify both"):
            _newsletter_settings(
                recipient_email="a@example.com",
                recipient_emails=["b@example.com"],
            )


class TestSingularFieldBackwardCompat:
    """FR-MR-002: singular recipient_email accepted and normalized to list."""

    def test_singular_email_accepted(self):
        s = _newsletter_settings(recipient_email="solo@example.com")
        assert s.recipient_email == "solo@example.com"
        assert s.recipient_emails == ["solo@example.com"]

    def test_singular_populates_plural(self):
        s = _newsletter_settings(recipient_email="one@example.com")
        assert s.recipient_emails == ["one@example.com"]

    def test_plural_populates_singular(self):
        """First email in list becomes the singular field."""
        s = _newsletter_settings(
            recipient_emails=["first@example.com", "second@example.com"]
        )
        assert s.recipient_email == "first@example.com"

    def test_neither_field_raises_error(self):
        with pytest.raises(ValidationError, match="must be provided"):
            _newsletter_settings()


# ===========================================================================
# FB-02: send_newsletter_email multi-recipient tests
# ===========================================================================


class TestSendMultiRecipient:
    """FR-MR-008, FR-MR-009, FR-MR-010: send_newsletter_email with list input."""

    @patch("newsletter_agent.tools.gmail_send.build")
    @patch("newsletter_agent.tools.gmail_send.get_gmail_credentials")
    def test_list_input_returns_per_recipient_breakdown(self, mock_creds, mock_build):
        from newsletter_agent.tools.gmail_send import send_newsletter_email

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.users().messages().send().execute.return_value = {"id": "msg-1"}

        result = send_newsletter_email(
            "<h1>Hi</h1>",
            ["a@example.com", "b@example.com"],
            "Subject",
        )
        assert result["status"] == "sent"
        assert len(result["recipients"]) == 2
        assert result["recipients"][0]["email"] == "a@example.com"
        assert result["recipients"][0]["status"] == "sent"
        assert result["recipients"][1]["email"] == "b@example.com"

    @patch("newsletter_agent.tools.gmail_send.build")
    @patch("newsletter_agent.tools.gmail_send.get_gmail_credentials")
    def test_partial_failure(self, mock_creds, mock_build):
        """FR-MR-011: some succeed, some fail -> status 'partial'."""
        from googleapiclient.errors import HttpError
        from newsletter_agent.tools.gmail_send import send_newsletter_email

        mock_service = MagicMock()
        mock_build.return_value = mock_service

        resp = MagicMock()
        resp.status = 500
        resp.reason = "Internal"
        call_count = 0

        def send_side_effect(**kwargs):
            nonlocal call_count
            m = MagicMock()
            if call_count == 0:
                m.execute.return_value = {"id": "msg-ok"}
            else:
                m.execute.side_effect = HttpError(resp, b"Internal")
            call_count += 1
            return m

        mock_service.users().messages().send = send_side_effect

        result = send_newsletter_email(
            "<h1>Hi</h1>",
            ["ok@example.com", "fail@example.com"],
            "Subject",
        )
        assert result["status"] == "partial"
        assert len(result["recipients"]) == 2
        ok = [r for r in result["recipients"] if r["status"] == "sent"]
        err = [r for r in result["recipients"] if r["status"] == "error"]
        assert len(ok) == 1
        assert len(err) == 1

    @patch("newsletter_agent.tools.gmail_send.build")
    @patch("newsletter_agent.tools.gmail_send.get_gmail_credentials")
    def test_full_failure(self, mock_creds, mock_build):
        """All recipients fail -> status 'failed'."""
        from googleapiclient.errors import HttpError
        from newsletter_agent.tools.gmail_send import send_newsletter_email

        mock_service = MagicMock()
        mock_build.return_value = mock_service

        resp = MagicMock()
        resp.status = 403
        resp.reason = "Forbidden"
        mock_service.users().messages().send().execute.side_effect = HttpError(
            resp, b"Forbidden"
        )

        result = send_newsletter_email(
            "<h1>Hi</h1>",
            ["a@example.com", "b@example.com"],
            "Subject",
        )
        assert result["status"] == "failed"
        assert len(result["recipients"]) == 2
        assert all(r["status"] == "error" for r in result["recipients"])


# ===========================================================================
# FB-03: DeliveryAgent multi-recipient tests
# ===========================================================================


def _make_delivery_state(recipient_emails=None, recipient_email=None, dry_run=False):
    state = {
        "config_dry_run": dry_run,
        "config_output_dir": "/tmp/output",
        "newsletter_html": "<h1>Newsletter</h1>",
        "newsletter_metadata": {
            "title": "Test Newsletter",
            "date": "2026-03-15",
            "topic_count": 2,
            "generation_time_seconds": 30.0,
        },
    }
    if recipient_emails is not None:
        state["config_recipient_emails"] = recipient_emails
    if recipient_email is not None:
        state["config_recipient_email"] = recipient_email
    return state


def _make_ctx(state):
    ctx = MagicMock()
    ctx.session.state = state
    return ctx


class TestDeliveryAgentMultiRecipient:
    """FR-MR-012: DeliveryAgent reads config_recipient_emails from state."""

    @pytest.mark.asyncio
    @patch(
        "newsletter_agent.tools.delivery.send_newsletter_email",
        return_value={
            "status": "sent",
            "recipients": [
                {"email": "a@example.com", "status": "sent", "message_id": "m1"},
                {"email": "b@example.com", "status": "sent", "message_id": "m2"},
            ],
        },
    )
    async def test_reads_config_recipient_emails(self, mock_send):
        from newsletter_agent.tools.delivery import DeliveryAgent

        agent = DeliveryAgent(name="TestDelivery")
        state = _make_delivery_state(
            recipient_emails=["a@example.com", "b@example.com"]
        )
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        mock_send.assert_called_once()
        call_args = mock_send.call_args[0]
        assert call_args[1] == ["a@example.com", "b@example.com"]
        assert state["delivery_status"]["status"] == "sent"

    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.delivery.save_newsletter_html", return_value="/tmp/fallback.html")
    @patch(
        "newsletter_agent.tools.delivery.send_newsletter_email",
        return_value={
            "status": "partial",
            "recipients": [
                {"email": "a@example.com", "status": "sent", "message_id": "m1"},
                {"email": "b@example.com", "status": "error", "error": "Bounce"},
            ],
        },
    )
    async def test_partial_delivery_saves_fallback_and_sets_partial(self, mock_send, mock_save):
        """FR-MR-011: partial delivery saves fallback and sets status='partial'."""
        from newsletter_agent.tools.delivery import DeliveryAgent

        agent = DeliveryAgent(name="TestDelivery")
        state = _make_delivery_state(
            recipient_emails=["a@example.com", "b@example.com"]
        )
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        mock_save.assert_called_once()
        assert state["delivery_status"]["status"] == "partial"
        assert "fallback_file" in state["delivery_status"]
        assert len(state["delivery_status"]["recipients"]) == 2

    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.delivery.save_newsletter_html", return_value="/tmp/fallback.html")
    @patch(
        "newsletter_agent.tools.delivery.send_newsletter_email",
        return_value={
            "status": "failed",
            "recipients": [
                {"email": "a@example.com", "status": "error", "error": "Auth failed"},
                {"email": "b@example.com", "status": "error", "error": "Auth failed"},
            ],
        },
    )
    async def test_full_failure_saves_fallback(self, mock_send, mock_save):
        from newsletter_agent.tools.delivery import DeliveryAgent

        agent = DeliveryAgent(name="TestDelivery")
        state = _make_delivery_state(
            recipient_emails=["a@example.com", "b@example.com"]
        )
        ctx = _make_ctx(state)

        async for _ in agent._run_async_impl(ctx):
            pass

        mock_save.assert_called_once()
        assert state["delivery_status"]["status"] == "failed"
        assert "fallback_file" in state["delivery_status"]
        assert "recipients" in state["delivery_status"]
