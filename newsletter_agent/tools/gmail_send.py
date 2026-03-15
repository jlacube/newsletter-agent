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
    recipient_email: str | list[str],
    subject: str,
) -> dict:
    """Send an HTML email via Gmail API.

    Args:
        html_content: Complete HTML newsletter string.
        recipient_email: Target email address or list of addresses.
        subject: Email subject line.

    Returns:
        dict with status and per-recipient breakdown when given a list,
        or simple status/message_id when given a single string.
    """
    # Normalize to list
    if isinstance(recipient_email, str):
        recipients = [recipient_email]
        single_mode = True
    else:
        recipients = list(recipient_email)
        single_mode = False

    try:
        creds = get_gmail_credentials()
    except GmailAuthError as e:
        logger.error("Gmail authentication failed: %s", e)
        if single_mode:
            return {"status": "error", "error_message": str(e)}
        return {
            "status": "failed",
            "recipients": [
                {"email": r, "status": "error", "error": str(e)} for r in recipients
            ],
        }

    plain_text = _strip_html(html_content)

    try:
        service = build("gmail", "v1", credentials=creds)
    except Exception as e:
        logger.error("Failed to build Gmail service: %s", e)
        if single_mode:
            return {"status": "error", "error_message": str(e)}
        return {
            "status": "failed",
            "recipients": [
                {"email": r, "status": "error", "error": str(e)} for r in recipients
            ],
        }

    if single_mode:
        return _send_single(service, html_content, plain_text, recipients[0], subject)

    # Multi-recipient: send individually and collect results
    results = []
    for addr in recipients:
        result = _send_single(service, html_content, plain_text, addr, subject)
        if result["status"] == "sent":
            results.append({"email": addr, "status": "sent", "message_id": result["message_id"]})
        else:
            results.append({"email": addr, "status": "error", "error": result.get("error_message", "Unknown error")})

    sent_count = sum(1 for r in results if r["status"] == "sent")
    if sent_count == len(results):
        overall = "sent"
    elif sent_count == 0:
        overall = "failed"
    else:
        overall = "partial"

    return {"status": overall, "recipients": results}


def _send_single(service, html_content: str, plain_text: str, recipient: str, subject: str) -> dict:
    """Send a single email to one recipient. Returns status dict."""
    message = MIMEMultipart("alternative")
    message["To"] = recipient
    message["From"] = recipient  # MVP: operator is also the sender
    message["Subject"] = subject

    message.attach(MIMEText(plain_text, "plain", "utf-8"))
    message.attach(MIMEText(html_content, "html", "utf-8"))

    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")

    try:
        result = (
            service.users()
            .messages()
            .send(userId="me", body={"raw": raw_message})
            .execute()
        )
        message_id = result.get("id", "")
        logger.info("Email sent to %s: message_id=%s", recipient, message_id)
        return {"status": "sent", "message_id": message_id}
    except HttpError as e:
        logger.error("Gmail API error for %s: %s", recipient, e)
        return {"status": "error", "error_message": str(e)}
    except Exception as e:
        logger.error("Email send failed for %s: %s", recipient, e)
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
