"""
Unit tests for Gmail send function.

Spec refs: Section 11.1, FR-027, FR-029, FR-030.
"""

import base64
from unittest.mock import MagicMock, patch

import pytest

from newsletter_agent.tools.gmail_send import _strip_html, send_newsletter_email


class TestSuccessfulSend:
    @patch("newsletter_agent.tools.gmail_send.build")
    @patch("newsletter_agent.tools.gmail_send.get_gmail_credentials")
    def test_returns_sent_with_message_id(self, mock_creds, mock_build):
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.users().messages().send().execute.return_value = {"id": "msg-123"}

        result = send_newsletter_email("<h1>Test</h1>", "test@gmail.com", "Subject")
        assert result["status"] == "sent"
        assert result["message_id"] == "msg-123"

    @patch("newsletter_agent.tools.gmail_send.build")
    @patch("newsletter_agent.tools.gmail_send.get_gmail_credentials")
    def test_builds_gmail_service(self, mock_creds, mock_build):
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.users().messages().send().execute.return_value = {"id": "x"}

        send_newsletter_email("<h1>Hi</h1>", "a@b.com", "S")
        mock_build.assert_called_once_with("gmail", "v1", credentials=mock_creds.return_value)


class TestMimeMessage:
    @patch("newsletter_agent.tools.gmail_send.build")
    @patch("newsletter_agent.tools.gmail_send.get_gmail_credentials")
    def test_sends_base64_raw_message(self, mock_creds, mock_build):
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.users().messages().send().execute.return_value = {"id": "x"}

        send_newsletter_email("<h1>Hi</h1>", "a@b.com", "Test Subject")

        call_args = mock_service.users().messages().send.call_args
        body = call_args.kwargs.get("body") or call_args[1].get("body")
        assert "raw" in body
        # Should be valid base64
        decoded = base64.urlsafe_b64decode(body["raw"])
        assert b"Test Subject" in decoded

    @patch("newsletter_agent.tools.gmail_send.build")
    @patch("newsletter_agent.tools.gmail_send.get_gmail_credentials")
    def test_mime_has_html_and_plain_parts(self, mock_creds, mock_build):
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.users().messages().send().execute.return_value = {"id": "x"}

        send_newsletter_email("<h1>Hi</h1>", "a@b.com", "S")

        call_args = mock_service.users().messages().send.call_args
        body = call_args.kwargs.get("body") or call_args[1].get("body")
        decoded = base64.urlsafe_b64decode(body["raw"])
        assert b"text/plain" in decoded
        assert b"text/html" in decoded


class TestAuthFailure:
    @patch("newsletter_agent.tools.gmail_send.get_gmail_credentials")
    def test_auth_error_returns_error_dict(self, mock_creds):
        from newsletter_agent.tools.gmail_auth import GmailAuthError

        mock_creds.side_effect = GmailAuthError("Missing credentials")

        result = send_newsletter_email("<h1>Hi</h1>", "a@b.com", "S")
        assert result["status"] == "error"
        assert "Missing credentials" in result["error_message"]


class TestApiErrors:
    @patch("newsletter_agent.tools.gmail_send.build")
    @patch("newsletter_agent.tools.gmail_send.get_gmail_credentials")
    def test_http_error_returns_error_dict(self, mock_creds, mock_build):
        from googleapiclient.errors import HttpError

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        resp = MagicMock()
        resp.status = 403
        resp.reason = "Forbidden"
        mock_service.users().messages().send().execute.side_effect = HttpError(
            resp, b"Forbidden"
        )

        result = send_newsletter_email("<h1>Hi</h1>", "a@b.com", "S")
        assert result["status"] == "error"
        assert result["error_message"]

    @patch("newsletter_agent.tools.gmail_send.build")
    @patch("newsletter_agent.tools.gmail_send.get_gmail_credentials")
    def test_network_error_returns_error_dict(self, mock_creds, mock_build):
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.users().messages().send().execute.side_effect = ConnectionError("Offline")

        result = send_newsletter_email("<h1>Hi</h1>", "a@b.com", "S")
        assert result["status"] == "error"
        assert "Offline" in result["error_message"]


class TestStripHtml:
    def test_strips_tags(self):
        assert "Hello" in _strip_html("<p>Hello</p>")
        assert "<p>" not in _strip_html("<p>Hello</p>")

    def test_br_to_newline(self):
        result = _strip_html("Line1<br>Line2")
        assert "Line1\nLine2" in result

    def test_large_html(self):
        html = "<h1>Title</h1>" + "<p>Paragraph</p>" * 100
        result = _strip_html(html)
        assert "Title" in result
        assert "<" not in result

    def test_heading_tags_add_double_newline(self):
        result = _strip_html("<h2>Section</h2><p>Content</p>")
        assert "Section\n\n" in result

    def test_list_items_add_newline(self):
        result = _strip_html("<ul><li>Item 1</li><li>Item 2</li></ul>")
        assert "Item 1\n" in result
        assert "Item 2" in result

    def test_case_insensitive_tags(self):
        result = _strip_html("<P>Hello</P><BR>World")
        assert "Hello" in result
        assert "World" in result
        assert "<" not in result

    def test_horizontal_whitespace_compressed(self):
        result = _strip_html("<p>Hello    World</p>")
        assert "Hello World" in result
        assert "    " not in result


class TestSpecialCharacters:
    @patch("newsletter_agent.tools.gmail_send.build")
    @patch("newsletter_agent.tools.gmail_send.get_gmail_credentials")
    def test_html_with_unicode(self, mock_creds, mock_build):
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.users().messages().send().execute.return_value = {"id": "x"}

        result = send_newsletter_email(
            "<p>Cafe with umlauts: Munchen</p>", "a@b.com", "S"
        )
        assert result["status"] == "sent"
