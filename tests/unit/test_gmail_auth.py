"""
Unit tests for Gmail OAuth2 authentication.

Spec refs: Section 11.1, FR-028, FR-041.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from newsletter_agent.tools.gmail_auth import (
    GMAIL_SCOPES,
    GmailAuthError,
    get_gmail_credentials,
)

_VALID_ENV = {
    "GMAIL_CLIENT_ID": "test-client-id",
    "GMAIL_CLIENT_SECRET": "test-client-secret",
    "GMAIL_REFRESH_TOKEN": "test-refresh-token",
}


class TestValidCredentials:
    @patch("newsletter_agent.tools.gmail_auth.Request")
    @patch("newsletter_agent.tools.gmail_auth.Credentials")
    @patch.dict(os.environ, _VALID_ENV, clear=False)
    def test_returns_credentials_with_valid_env(self, mock_creds_cls, mock_request):
        mock_creds = MagicMock()
        mock_creds_cls.return_value = mock_creds
        result = get_gmail_credentials()
        assert result is mock_creds

    @patch("newsletter_agent.tools.gmail_auth.Request")
    @patch("newsletter_agent.tools.gmail_auth.Credentials")
    @patch.dict(os.environ, _VALID_ENV, clear=False)
    def test_calls_refresh(self, mock_creds_cls, mock_request):
        mock_creds = MagicMock()
        mock_creds_cls.return_value = mock_creds
        get_gmail_credentials()
        mock_creds.refresh.assert_called_once()

    @patch("newsletter_agent.tools.gmail_auth.Request")
    @patch("newsletter_agent.tools.gmail_auth.Credentials")
    @patch.dict(os.environ, _VALID_ENV, clear=False)
    def test_uses_correct_scope(self, mock_creds_cls, mock_request):
        mock_creds = MagicMock()
        mock_creds_cls.return_value = mock_creds
        get_gmail_credentials()
        call_kwargs = mock_creds_cls.call_args
        assert call_kwargs.kwargs["scopes"] == GMAIL_SCOPES


class TestMissingCredentials:
    @patch.dict(os.environ, {"GMAIL_CLIENT_SECRET": "s", "GMAIL_REFRESH_TOKEN": "r"}, clear=True)
    def test_missing_client_id_raises(self):
        with pytest.raises(GmailAuthError, match="GMAIL_CLIENT_ID"):
            get_gmail_credentials()

    @patch.dict(os.environ, {"GMAIL_CLIENT_ID": "i", "GMAIL_REFRESH_TOKEN": "r"}, clear=True)
    def test_missing_client_secret_raises(self):
        with pytest.raises(GmailAuthError, match="GMAIL_CLIENT_SECRET"):
            get_gmail_credentials()

    @patch.dict(os.environ, {"GMAIL_CLIENT_ID": "i", "GMAIL_CLIENT_SECRET": "s"}, clear=True)
    def test_missing_refresh_token_raises(self):
        with pytest.raises(GmailAuthError, match="GMAIL_REFRESH_TOKEN"):
            get_gmail_credentials()

    @patch.dict(os.environ, {}, clear=True)
    def test_all_missing_raises(self):
        with pytest.raises(GmailAuthError, match="Missing Gmail OAuth2 credentials"):
            get_gmail_credentials()


class TestWhitespaceStripping:
    @patch("newsletter_agent.tools.gmail_auth.Request")
    @patch("newsletter_agent.tools.gmail_auth.Credentials")
    @patch.dict(
        os.environ,
        {
            "GMAIL_CLIENT_ID": "  id  ",
            "GMAIL_CLIENT_SECRET": "  secret  ",
            "GMAIL_REFRESH_TOKEN": "  token  ",
        },
        clear=False,
    )
    def test_strips_whitespace(self, mock_creds_cls, mock_request):
        mock_creds = MagicMock()
        mock_creds_cls.return_value = mock_creds
        get_gmail_credentials()
        call_kwargs = mock_creds_cls.call_args.kwargs
        assert call_kwargs["client_id"] == "id"
        assert call_kwargs["client_secret"] == "secret"
        assert call_kwargs["refresh_token"] == "token"


class TestRefreshFailure:
    @patch("newsletter_agent.tools.gmail_auth.Request")
    @patch("newsletter_agent.tools.gmail_auth.Credentials")
    @patch.dict(os.environ, _VALID_ENV, clear=False)
    def test_revoked_token_raises_auth_error(self, mock_creds_cls, mock_request):
        from google.auth.exceptions import RefreshError

        mock_creds = MagicMock()
        mock_creds.refresh.side_effect = RefreshError("Token revoked")
        mock_creds_cls.return_value = mock_creds
        with pytest.raises(GmailAuthError, match="invalid or revoked"):
            get_gmail_credentials()

    @patch("newsletter_agent.tools.gmail_auth.Request")
    @patch("newsletter_agent.tools.gmail_auth.Credentials")
    @patch.dict(os.environ, _VALID_ENV, clear=False)
    def test_general_refresh_error_raises(self, mock_creds_cls, mock_request):
        mock_creds = MagicMock()
        mock_creds.refresh.side_effect = Exception("Network error")
        mock_creds_cls.return_value = mock_creds
        with pytest.raises(GmailAuthError, match="Failed to refresh"):
            get_gmail_credentials()
