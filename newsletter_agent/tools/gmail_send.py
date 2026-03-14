"""
Gmail API email send function.

Spec refs: FR-027, FR-029, FR-030, Section 8.3.
"""

import base64
import logging
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from newsletter_agent.tools.gmail_auth import GmailAuthError, get_gmail_credentials

logger = logging.getLogger(__name__)


def send_newsletter_email(
    html_content: str,
    recipient_email: str,
    subject: str,
) -> dict:
    """Send an HTML email via Gmail API.

    Args:
        html_content: Complete HTML newsletter string.
        recipient_email: Target email address.
        subject: Email subject line.

    Returns:
        dict with status "sent" and message_id, or status "error" and error_message.
    """
    try:
        creds = get_gmail_credentials()
    except GmailAuthError as e:
        logger.error("Gmail authentication failed: %s", e)
        return {"status": "error", "error_message": str(e)}

    message = MIMEMultipart("alternative")
    message["To"] = recipient_email
    message["From"] = recipient_email  # MVP: operator is also the sender
    message["Subject"] = subject

    plain_text = _strip_html(html_content)
    message.attach(MIMEText(plain_text, "plain", "utf-8"))
    message.attach(MIMEText(html_content, "html", "utf-8"))

    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")

    try:
        service = build("gmail", "v1", credentials=creds)
        result = (
            service.users()
            .messages()
            .send(userId="me", body={"raw": raw_message})
            .execute()
        )
        message_id = result.get("id", "")
        logger.info("Email sent successfully: message_id=%s", message_id)
        return {"status": "sent", "message_id": message_id}
    except HttpError as e:
        logger.error("Gmail API error: %s", e)
        return {"status": "error", "error_message": str(e)}
    except Exception as e:
        logger.error("Email send failed: %s", e)
        return {"status": "error", "error_message": str(e)}


def _strip_html(html: str) -> str:
    """Strip HTML tags for plain-text fallback."""
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</li>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</h[1-6]>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()
