"""CLI entry point for autonomous newsletter generation.

Enables execution via: python -m newsletter_agent

Runs the full ADK pipeline programmatically without interactive input,
logs progress, prints a JSON summary, and exits with 0 (success) or 1 (failure).

Spec refs: FR-CLI-001 through FR-CLI-005, Section 8.1, US-01.
"""

import asyncio
import json
import logging
import sys
import time
from datetime import date

from dotenv import load_dotenv

load_dotenv()  # Load .env before importing agent (which reads GOOGLE_API_KEY)

from newsletter_agent.logging_config import setup_logging

logger = logging.getLogger("newsletter_agent.cli")


async def run_pipeline() -> dict:
    """Execute the ADK pipeline and return the final session state."""
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    from newsletter_agent.agent import root_agent

    session_service = InMemorySessionService()
    runner = Runner(
        agent=root_agent,
        app_name="newsletter_agent",
        session_service=session_service,
    )

    session = await session_service.create_session(
        app_name="newsletter_agent",
        user_id="cli",
    )

    async for event in runner.run_async(
        session_id=session.id,
        user_id="cli",
        new_message=types.Content(
            parts=[types.Part(text="Generate newsletter")]
        ),
    ):
        if hasattr(event, "author") and hasattr(event, "content"):
            logger.info("[CLI] Event from %s", event.author)

    updated_session = await session_service.get_session(
        app_name="newsletter_agent",
        user_id="cli",
        session_id=session.id,
    )
    return dict(updated_session.state) if updated_session else {}


def main() -> int:
    """Run the newsletter pipeline and return an exit code.

    Returns:
        0 on success, 1 on failure.
    """
    setup_logging()
    logger.info("[CLI] Pipeline starting...")
    start = time.monotonic()

    try:
        state = asyncio.run(run_pipeline())

        elapsed = time.monotonic() - start
        logger.info("[CLI] Pipeline completed in %.1fs", elapsed)

        delivery = state.get("delivery_status", {})
        metadata = state.get("newsletter_metadata", {})

        summary = {
            "status": "success",
            "newsletter_date": date.today().isoformat(),
            "topics_processed": metadata.get("topic_count", 0),
            "email_sent": delivery.get("status") == "sent",
        }

        if delivery.get("status") == "dry_run":
            summary["output_file"] = delivery.get("output_file", "")

        print(json.dumps(summary))
        return 0

    except BaseException as e:
        elapsed = time.monotonic() - start
        logger.error("[CLI] Pipeline failed after %.1fs: %s: %s", elapsed, type(e).__name__, e)

        # Log sub-exceptions from ExceptionGroup (e.g. ParallelAgent failures)
        if isinstance(e, BaseExceptionGroup):
            for i, sub in enumerate(e.exceptions):
                logger.error("[CLI]   Sub-exception %d: %s: %s", i + 1, type(sub).__name__, sub)

        summary = {
            "status": "error",
            "message": f"{type(e).__name__}: {e}",
        }
        print(json.dumps(summary))
        return 1


if __name__ == "__main__":
    sys.exit(main())
