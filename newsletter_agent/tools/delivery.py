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
        recipient_email = state.get("config_recipient_email", "")

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

        if not recipient_email:
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

        result = send_newsletter_email(html, recipient_email, subject)
        if result["status"] == "sent":
            state["delivery_status"] = result
            logger.info("Email sent: message_id=%s", result.get("message_id"))
            yield Event(
                author=self.name,
                content=types.Content(
                    parts=[types.Part(text=f"Email sent: {result.get('message_id')}")]
                ),
            )
        else:
            path = save_newsletter_html(html, output_dir, nl_date)
            state["delivery_status"] = {
                "status": "failed",
                "fallback_file": path,
                "error": result.get("error_message", "Unknown error"),
            }
            logger.error(
                "Email delivery failed: %s; saved fallback to %s",
                result.get("error_message"),
                path,
            )
            yield Event(
                author=self.name,
                content=types.Content(
                    parts=[types.Part(text=f"Email failed; saved to {path}")]
                ),
            )
