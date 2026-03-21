"""BDD tests: Cost Summary at Pipeline End.

Spec refs: US-02, FR-501, FR-502, FR-503, FR-504, Section 11.2.

Feature: Cost Summary at Pipeline End
  Scenario: Summary includes per-topic breakdown
  Scenario: Empty run produces zero summary
"""

import json
import logging
from unittest.mock import MagicMock, patch

import pytest
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from newsletter_agent.cost_tracker import (
    ModelPricing,
    init_cost_tracker,
    get_cost_tracker,
    reset_cost_tracker,
)
from newsletter_agent.timing import (
    _ROOT_AGENT_NAME,
    _active_spans,
    _phase_starts,
    after_agent_callback,
    before_agent_callback,
)


@pytest.fixture(autouse=True)
def _clean_timing_state():
    _phase_starts.clear()
    _active_spans.clear()
    yield
    _phase_starts.clear()
    _active_spans.clear()


@pytest.fixture()
def otel_exporter():
    exporter = InMemorySpanExporter()
    resource = Resource.create({"service.name": "test"})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    trace._TRACER_PROVIDER = None
    trace._TRACER_PROVIDER_SET_ONCE._done = False
    trace.set_tracer_provider(provider)

    yield exporter

    provider.shutdown()
    trace._TRACER_PROVIDER = None
    trace._TRACER_PROVIDER_SET_ONCE._done = False


@pytest.fixture(autouse=True)
def _reset_cost():
    yield
    reset_cost_tracker()


def _make_ctx(agent_name="TestAgent", invocation_id="inv-1", state=None):
    ctx = MagicMock()
    ctx.agent_name = agent_name
    ctx.invocation_id = invocation_id
    ctx.state = state if state is not None else {}
    return ctx


class TestCostSummaryScenarios:
    """Feature: Cost Summary at Pipeline End."""

    def test_summary_includes_per_topic_breakdown(self, otel_exporter, caplog):
        """Scenario: Summary includes per-topic breakdown.

        Given a pipeline run with topics "AI Frameworks" and "Cloud Native"
        And 2 synthesis calls (one per topic) complete with tracked costs
        When the pipeline finishes
        Then the cost summary log contains per_topic with keys
            "AI Frameworks" and "Cloud Native"
        And total_cost_usd equals the sum of both topic costs
        """
        pricing = {"gemini-2.5-pro": ModelPricing(1.25, 10.00)}
        init_cost_tracker(pricing)
        tracker = get_cost_tracker()

        tracker.record_llm_call(
            model="gemini-2.5-pro",
            agent_name="Synthesizer_0",
            phase="synthesis",
            topic_name="AI Frameworks",
            topic_index=0,
            prompt_tokens=10000,
            completion_tokens=2000,
            thinking_tokens=500,
        )
        tracker.record_llm_call(
            model="gemini-2.5-pro",
            agent_name="Synthesizer_1",
            phase="synthesis",
            topic_name="Cloud Native",
            topic_index=1,
            prompt_tokens=8000,
            completion_tokens=1500,
            thinking_tokens=300,
        )

        with patch("newsletter_agent.timing.is_enabled", return_value=True):
            ctx = _make_ctx(agent_name=_ROOT_AGENT_NAME)
            with caplog.at_level(logging.INFO, logger="newsletter_agent.timing"):
                before_agent_callback(ctx)
                after_agent_callback(ctx)

        # Find cost summary log
        cost_logs = [
            r for r in caplog.records
            if "pipeline_cost_summary" in r.getMessage()
        ]
        assert len(cost_logs) == 1
        cost_data = json.loads(cost_logs[0].getMessage())

        assert "AI Frameworks" in cost_data["per_topic"]
        assert "Cloud Native" in cost_data["per_topic"]

        ai_cost = cost_data["per_topic"]["AI Frameworks"]
        cloud_cost = cost_data["per_topic"]["Cloud Native"]
        assert cost_data["total_cost_usd"] == pytest.approx(ai_cost + cloud_cost)

        # Verify state is populated (FR-503, FR-504)
        assert "run_cost_usd" in ctx.state
        assert isinstance(ctx.state["run_cost_usd"], float)
        assert "cost_summary" in ctx.state
        assert isinstance(ctx.state["cost_summary"], dict)

    def test_empty_run_produces_zero_summary(self, otel_exporter, caplog):
        """Scenario: Empty run produces zero summary.

        Given a pipeline run where no LLM calls succeed
        When the pipeline finishes
        Then the cost summary log contains total_cost_usd = 0.0
            and call_count = 0
        """
        # No cost tracker init needed - the no-op tracker returns zeros

        with patch("newsletter_agent.timing.is_enabled", return_value=True):
            ctx = _make_ctx(agent_name=_ROOT_AGENT_NAME)
            with caplog.at_level(logging.INFO, logger="newsletter_agent.timing"):
                before_agent_callback(ctx)
                after_agent_callback(ctx)

        cost_logs = [
            r for r in caplog.records
            if "pipeline_cost_summary" in r.getMessage()
        ]
        assert len(cost_logs) == 1
        cost_data = json.loads(cost_logs[0].getMessage())
        assert cost_data["total_cost_usd"] == 0.0
        assert cost_data["call_count"] == 0
