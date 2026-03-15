"""
Cloud Run HTTP trigger handler for the Newsletter Agent.

Provides a POST /run endpoint that Cloud Scheduler calls to trigger
newsletter generation, and a GET / health check for Cloud Run probes.

Spec refs: FR-037, Section 8.1.
"""

import asyncio
import logging
import time
from datetime import date

from dotenv import load_dotenv

load_dotenv()  # Load .env for local dev; no-op on Cloud Run (vars injected)

from newsletter_agent.logging_config import setup_logging

setup_logging()

from flask import Flask, jsonify, request

logger = logging.getLogger("newsletter_agent.http")

app = Flask(__name__)


async def _execute_pipeline() -> dict:
    """Execute the ADK pipeline programmatically and return final session state."""
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
        user_id="scheduler",
    )

    async for event in runner.run_async(
        session_id=session.id,
        user_id="scheduler",
        new_message=types.Content(
            parts=[types.Part(text="Generate newsletter")]
        ),
    ):
        if hasattr(event, "author"):
            logger.info("Event from %s", event.author)

    updated_session = await session_service.get_session(
        app_name="newsletter_agent",
        user_id="scheduler",
        session_id=session.id,
    )
    return dict(updated_session.state) if updated_session else {}


@app.route("/", methods=["GET"])
def health():
    """Health check endpoint for Cloud Run startup/liveness probes."""
    return jsonify({"status": "healthy"}), 200


@app.route("/run", methods=["POST"])
def run_pipeline():
    """Trigger a full newsletter generation cycle.

    Returns JSON with generation result on success (200) or error details (500).
    """
    logger.info(
        "Pipeline triggered via HTTP POST /run (source: %s)",
        request.headers.get("User-Agent", "unknown"),
    )
    start = time.monotonic()

    try:
        state = asyncio.run(_execute_pipeline())

        elapsed = time.monotonic() - start
        delivery = state.get("delivery_status", {})
        metadata = state.get("newsletter_metadata", {})

        response = {
            "status": "success",
            "newsletter_date": date.today().isoformat(),
            "topics_processed": metadata.get("topic_count", 0),
            "email_sent": delivery.get("status") == "sent",
            "elapsed_seconds": round(elapsed, 1),
        }

        if delivery.get("status") == "dry_run":
            response["output_file"] = delivery.get("output_file", "")

        logger.info("Pipeline completed in %.1fs: %s", elapsed, response)
        return jsonify(response), 200

    except BaseException as e:
        elapsed = time.monotonic() - start
        error_msg = f"{type(e).__name__}: {e}"
        logger.error("Pipeline failed after %.1fs: %s", elapsed, error_msg)

        if isinstance(e, BaseExceptionGroup):
            for i, sub in enumerate(e.exceptions):
                logger.error("  Sub-exception %d: %s: %s", i + 1, type(sub).__name__, sub)

        return jsonify({"status": "error", "message": error_msg, "elapsed_seconds": round(elapsed, 1)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
