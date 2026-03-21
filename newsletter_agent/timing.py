"""
Pipeline timing instrumentation via ADK agent callbacks.

Records pipeline start time in session state and logs per-phase
and total execution time at INFO level. When OTel is enabled,
creates spans with parent-child hierarchy, agent attributes, and
cost summary events.

Spec refs: FR-042, FR-201 through FR-208, FR-501 through FR-504,
           Section 4.2, 7.6, 7.7, 8.3, 10.1.
"""

import json
import logging
import re
import time
from datetime import datetime, timezone

from newsletter_agent.telemetry import get_tracer, is_enabled

logger = logging.getLogger("newsletter_agent.timing")

_ROOT_AGENT_NAME = "NewsletterPipeline"

# Known LlmAgent name prefixes (FR-304) - no token tracking in P1
_LLMAGENT_PREFIXES = frozenset({
    "GoogleSearcher",
    "PerplexitySearcher",
    "AdaptivePlanner",
    "DeepSearchRound",
    "AdaptiveAnalyzer",
})

# Regex for extracting topic index from agent name (FR-206)
# Matches both Topic{N}Research (e.g. Topic0Research) and _N_ / _N$ patterns
# (e.g. GoogleSearcher_0, DeepResearch_2_google)
_TOPIC_INDEX_RE = re.compile(r"(?:^Topic|_)(\d+)(?:_|$|[A-Z])")

# Module-level dict to track phase start times (keyed by invocation_id + agent_name)
_phase_starts: dict[str, float] = {}

# Module-level dict to track active OTel spans (FR-204)
_active_spans: dict[str, tuple] = {}


def _phase_key(callback_context) -> str:
    return f"{callback_context.invocation_id}:{callback_context.agent_name}"


def before_agent_callback(callback_context) -> None:
    """Record phase start time, pipeline_start_time, and create OTel span."""
    key = _phase_key(callback_context)
    _phase_starts[key] = time.monotonic()

    agent_name = callback_context.agent_name
    if agent_name == _ROOT_AGENT_NAME:
        callback_context.state["pipeline_start_time"] = (
            datetime.now(timezone.utc).isoformat()
        )
        logger.info("Pipeline started")
    else:
        logger.info("%s started", agent_name)

    # OTel span creation (FR-201, FR-202)
    if is_enabled():
        from opentelemetry import context, trace

        tracer = get_tracer("newsletter_agent.timing")
        span = tracer.start_span(name=agent_name)
        span.set_attribute("newsletter.agent.name", agent_name)
        span.set_attribute(
            "newsletter.invocation_id", callback_context.invocation_id
        )

        # Root agent attributes (FR-205)
        if agent_name == _ROOT_AGENT_NAME:
            span.set_attribute(
                "newsletter.pipeline_start_time",
                callback_context.state.get("pipeline_start_time", ""),
            )
            topic_count = callback_context.state.get("config_topic_count")
            if topic_count is not None:
                span.set_attribute("newsletter.topic_count", topic_count)
            dry_run = callback_context.state.get("config_dry_run")
            if dry_run is not None:
                span.set_attribute("newsletter.dry_run", dry_run)

        # Topic-scoped attributes (FR-206)
        match = _TOPIC_INDEX_RE.search(agent_name)
        if match:
            topic_idx = int(match.group(1))
            span.set_attribute("newsletter.topic.index", topic_idx)
            topics = callback_context.state.get("config_topics")
            if topics and 0 <= topic_idx < len(topics):
                try:
                    topic_name = topics[topic_idx]
                    if isinstance(topic_name, str):
                        span.set_attribute("newsletter.topic.name", topic_name)
                except (IndexError, TypeError):
                    pass

        # LlmAgent marker (FR-304)
        if any(agent_name.startswith(p) for p in _LLMAGENT_PREFIXES):
            span.set_attribute("gen_ai.tokens_available", False)

        token = context.attach(trace.set_span_in_context(span))
        _active_spans[key] = (span, token)

    return None


def after_agent_callback(callback_context) -> None:
    """Log phase elapsed time, end OTel span, and record cost summary."""
    key = _phase_key(callback_context)
    start = _phase_starts.pop(key, None)

    agent_name = callback_context.agent_name
    elapsed = None
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

    # OTel span finalization (FR-203, FR-204)
    if is_enabled():
        from opentelemetry import context

        span_data = _active_spans.pop(key, None)
        if span_data is not None:
            span, token = span_data
            try:
                if elapsed is not None:
                    span.set_attribute(
                        "newsletter.duration_seconds", elapsed
                    )

                # Cost summary on root agent completion (FR-501 - FR-504)
                if agent_name == _ROOT_AGENT_NAME:
                    _record_cost_summary(span, callback_context)

                span.end()
            finally:
                context.detach(token)
        else:
            logger.warning("Span not found for key %s", key)

    return None


def _record_cost_summary(span, callback_context) -> None:
    """Log cost summary and record as span event on root agent completion."""
    from newsletter_agent.cost_tracker import get_cost_tracker

    try:
        summary = get_cost_tracker().get_summary()

        cost_dict = {
            "event": "pipeline_cost_summary",
            "total_cost_usd": summary.total_cost_usd,
            "total_input_tokens": summary.total_input_tokens,
            "total_output_tokens": summary.total_output_tokens,
            "total_thinking_tokens": summary.total_thinking_tokens,
            "call_count": summary.call_count,
            "per_model": {
                model_name: {
                    "cost_usd": detail["cost_usd"],
                    "call_count": detail["call_count"],
                }
                for model_name, detail in summary.per_model.items()
            },
            "per_topic": dict(summary.per_topic),
            "per_phase": dict(summary.per_phase),
        }
        logger.info(json.dumps(cost_dict))

        # Record span event (FR-502) - flat primitive attributes only
        span.add_event(
            "cost_summary",
            attributes={
                "total_cost_usd": summary.total_cost_usd,
                "total_input_tokens": summary.total_input_tokens,
                "total_output_tokens": summary.total_output_tokens,
                "call_count": summary.call_count,
            },
        )

        # Store in session state (FR-503, FR-504)
        callback_context.state["run_cost_usd"] = summary.total_cost_usd

        # Full summary as a spec-aligned dict for state storage
        callback_context.state["cost_summary"] = {
            "total_cost_usd": summary.total_cost_usd,
            "total_input_tokens": summary.total_input_tokens,
            "total_output_tokens": summary.total_output_tokens,
            "total_thinking_tokens": summary.total_thinking_tokens,
            "call_count": summary.call_count,
            "per_model": dict(summary.per_model),
            "per_topic": dict(summary.per_topic),
            "per_phase": dict(summary.per_phase),
        }

    except Exception:
        logger.warning("Failed to record cost summary", exc_info=True)
