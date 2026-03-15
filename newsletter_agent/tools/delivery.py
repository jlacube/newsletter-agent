"""
Delivery agent - sends email via Gmail or saves to disk.

Spec refs: FR-027, FR-031, FR-032, FR-033, Section 9.1.
"""

import logging
from collections.abc import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types

from newsletter_agent.tools.file_output import save_newsletter_html
from newsletter_agent.tools.gmail_send import send_newsletter_email

logger = logging.getLogger(__name__)


class DeliveryAgent(BaseAgent):
    """Custom BaseAgent that delivers the newsletter via email or saves to disk."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        html = state.get("newsletter_html", "")
        metadata = state.get("newsletter_metadata", {})
        dry_run = state.get("config_dry_run", False)
        output_dir = state.get("config_output_dir", "output/")
        recipient_emails = state.get("config_recipient_emails") or []
        # Backward compat: fall back to singular key
        if not recipient_emails:
            single = state.get("config_recipient_email", "")
            if single:
                recipient_emails = [single]

        title = metadata.get("title", "Newsletter")
        nl_date = metadata.get("date", "")
        subject = f"{title} - {nl_date}"

        if dry_run:
            path = save_newsletter_html(html, output_dir, nl_date)
            state["delivery_status"] = {"status": "dry_run", "output_file": path}
            logger.info("Dry run: newsletter saved to %s", path)
            yield Event(
                author=self.name,
                content=types.Content(
                    parts=[types.Part(text=f"Dry run: saved to {path}")]
                ),
            )
            return

        if not recipient_emails:
            path = save_newsletter_html(html, output_dir, nl_date)
            state["delivery_status"] = {
                "status": "failed",
                "fallback_file": path,
                "error": "No recipient email configured",
            }
            logger.error("No recipient email configured; saved fallback to %s", path)
            yield Event(
                author=self.name,
                content=types.Content(
                    parts=[types.Part(text=f"No recipient email; saved to {path}")]
                ),
            )
            return

        result = send_newsletter_email(html, recipient_emails, subject)

        if result["status"] == "sent":
            state["delivery_status"] = result
            sent_count = len(result.get("recipients", []))
            logger.info("Email sent to %d recipient(s)", sent_count)
            yield Event(
                author=self.name,
                content=types.Content(
                    parts=[types.Part(text=f"Email sent to {sent_count} recipient(s)")]
                ),
            )
        elif result["status"] == "partial":
            path = save_newsletter_html(html, output_dir, nl_date)
            result["fallback_file"] = path
            state["delivery_status"] = result
            recipients_info = result.get("recipients", [])
            sent = sum(1 for r in recipients_info if r["status"] == "sent")
            failed = len(recipients_info) - sent
            logger.warning(
                "Partial delivery: %d sent, %d failed; saved fallback to %s",
                sent, failed, path,
            )
            yield Event(
                author=self.name,
                content=types.Content(
                    parts=[types.Part(text=f"Partial delivery: {sent} sent, {failed} failed; saved to {path}")]
                ),
            )
        else:
            path = save_newsletter_html(html, output_dir, nl_date)
            error_msg = result.get("error_message", "")
            if not error_msg and "recipients" in result:
                errors = [r.get("error", "") for r in result["recipients"] if r.get("error")]
                error_msg = "; ".join(errors[:3])
            state["delivery_status"] = {
                "status": "failed",
                "fallback_file": path,
                "error": error_msg or "All recipients failed",
                "recipients": result.get("recipients", []),
            }
            logger.error(
                "Email delivery failed: %s; saved fallback to %s",
                error_msg, path,
            )
            yield Event(
                author=self.name,
                content=types.Content(
                    parts=[types.Part(text=f"Email failed; saved to {path}")]
                ),
            )
