"""
Cloud Run HTTP trigger handler for the Newsletter Agent.

Provides a POST /run endpoint that Cloud Scheduler calls to trigger
newsletter generation. Uses ADK's Runner for programmatic execution.

Spec refs: FR-037, Section 8.1.
"""

import asyncio
import logging
from datetime import date

from flask import Flask, jsonify

logger = logging.getLogger("newsletter_agent.http")

app = Flask(__name__)


async def _execute_pipeline():
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

    async for _event in runner.run_async(
        session_id=session.id,
        user_id="scheduler",
        new_message=types.Content(
            parts=[types.Part(text="Generate newsletter")]
        ),
    ):
        pass  # consume all events

    updated_session = await session_service.get_session(
        app_name="newsletter_agent",
        user_id="scheduler",
        session_id=session.id,
    )
    return dict(updated_session.state) if updated_session else {}


@app.route("/run", methods=["POST"])
def run_pipeline():
    """Trigger a full newsletter generation cycle.

    Returns JSON with generation result on success (200) or error details (500).
    """
    logger.info("Pipeline triggered via HTTP POST /run")

    try:
        state = asyncio.run(_execute_pipeline())

        delivery = state.get("delivery_status", {})
        metadata = state.get("newsletter_metadata", {})

        response = {
            "status": "success",
            "newsletter_date": date.today().isoformat(),
            "topics_processed": metadata.get("topic_count", 0),
            "email_sent": delivery.get("status") == "sent",
        }

        if delivery.get("status") == "dry_run":
            response["output_file"] = delivery.get("output_file", "")

        logger.info("Pipeline completed successfully: %s", response)
        return jsonify(response), 200

    except Exception as e:
        error_msg = f"Pipeline failed: {type(e).__name__}: {e}"
        logger.error(error_msg)
        return jsonify({"status": "error", "message": error_msg}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
