"""
Pipeline timing instrumentation via ADK agent callbacks.

Records pipeline start time in session state and logs per-phase
and total execution time at INFO level.

Spec refs: FR-042, Section 7.6, Section 10.1.
"""

import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger("newsletter_agent.timing")

_ROOT_AGENT_NAME = "NewsletterPipeline"

# Module-level dict to track phase start times (keyed by invocation_id + agent_name)
_phase_starts: dict[str, float] = {}


def _phase_key(callback_context) -> str:
    return f"{callback_context.invocation_id}:{callback_context.agent_name}"


def before_agent_callback(callback_context) -> None:
    """Record phase start time and pipeline_start_time in session state."""
    key = _phase_key(callback_context)
    _phase_starts[key] = time.monotonic()

    agent_name = callback_context.agent_name
    if agent_name == _ROOT_AGENT_NAME:
        # Root agent - record pipeline start time in state for the formatter
        callback_context.state["pipeline_start_time"] = (
            datetime.now(timezone.utc).isoformat()
        )
        logger.info("Pipeline started")
    else:
        logger.info("%s started", agent_name)

    return None


def after_agent_callback(callback_context) -> None:
    """Log phase elapsed time and total pipeline time."""
    key = _phase_key(callback_context)
    start = _phase_starts.pop(key, None)

    agent_name = callback_context.agent_name
    if start is not None:
        elapsed = time.monotonic() - start
        if agent_name == _ROOT_AGENT_NAME:
            logger.info("Pipeline completed in %.1fs", elapsed)
            callback_context.state.setdefault("newsletter_metadata", {})
            callback_context.state["newsletter_metadata"][
                "generation_time_seconds"
            ] = elapsed
        else:
            logger.info("%s completed in %.1fs", agent_name, elapsed)

    return None
