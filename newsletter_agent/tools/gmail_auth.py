"""
Gmail OAuth2 authentication and token management.

Spec refs: FR-028, FR-041, Section 9.5, Section 10.2.
"""

import logging
import os

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

logger = logging.getLogger(__name__)

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
_TOKEN_URI = "https://oauth2.googleapis.com/token"


class GmailAuthError(Exception):
    """Raised when Gmail OAuth2 authentication fails."""


class GmailSendError(Exception):
    """Raised when Gmail API send operation fails."""


def get_gmail_credentials() -> Credentials:
    """Load and validate Gmail OAuth2 credentials from environment.

    Returns:
        Valid google.oauth2.credentials.Credentials object.

    Raises:
        GmailAuthError: If credentials are missing or refresh fails.
    """
    client_id = os.environ.get("GMAIL_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET", "").strip()
    refresh_token = os.environ.get("GMAIL_REFRESH_TOKEN", "").strip()

    missing = []
    if not client_id:
        missing.append("GMAIL_CLIENT_ID")
    if not client_secret:
        missing.append("GMAIL_CLIENT_SECRET")
    if not refresh_token:
        missing.append("GMAIL_REFRESH_TOKEN")

    if missing:
        raise GmailAuthError(
            f"Missing Gmail OAuth2 credentials: {', '.join(missing)}. "
            "Run 'python setup_gmail_oauth.py' to configure Gmail access."
        )

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=_TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=GMAIL_SCOPES,
    )

    try:
        creds.refresh(Request())
        logger.info("Gmail credentials refreshed successfully")
    except RefreshError as e:
        raise GmailAuthError(
            f"Gmail refresh token is invalid or revoked: {e}. "
            "Run 'python setup_gmail_oauth.py' to re-authorize."
        ) from e
    except Exception as e:
        raise GmailAuthError(
            f"Failed to refresh Gmail credentials: {e}"
        ) from e

    return creds
