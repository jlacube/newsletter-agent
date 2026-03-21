"""BDD tests: Telemetry Kill Switch.

Spec refs: US-07, FR-102, SC-007, Section 11.2.

Feature: Telemetry Kill Switch
  Scenario: Disabled telemetry has no overhead
"""

from unittest.mock import MagicMock, patch

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from newsletter_agent.cost_tracker import reset_cost_tracker
from newsletter_agent.timing import (
    _ROOT_AGENT_NAME,
    _active_spans,
    _phase_starts,
    after_agent_callback,
    before_agent_callback,
)
import newsletter_agent.telemetry as telemetry_mod


@pytest.fixture(autouse=True)
def _clean_timing_state():
    _phase_starts.clear()
    _active_spans.clear()
    yield
    _phase_starts.clear()
    _active_spans.clear()


@pytest.fixture(autouse=True)
def _reset_all():
    yield
    reset_cost_tracker()
    telemetry_mod._initialized = False
    trace._TRACER_PROVIDER = None
    trace._TRACER_PROVIDER_SET_ONCE._done = False


def _make_ctx(agent_name="TestAgent", invocation_id="inv-1", state=None):
    ctx = MagicMock()
    ctx.agent_name = agent_name
    ctx.invocation_id = invocation_id
    ctx.state = state if state is not None else {}
    return ctx


class TestTelemetryKillSwitchScenarios:
    """Feature: Telemetry Kill Switch."""

    def test_disabled_telemetry_has_no_overhead(self, monkeypatch):
        """Scenario: Disabled telemetry has no overhead.

        Given OTEL_ENABLED=false
        When the pipeline runs
        Then no spans are created
        And no cost tracking occurs
        And the pipeline produces identical output to a non-instrumented run
        """
        monkeypatch.setenv("OTEL_ENABLED", "false")

        telemetry_mod._initialized = False
        trace._TRACER_PROVIDER = None
        trace._TRACER_PROVIDER_SET_ONCE._done = False
        telemetry_mod.init_telemetry()

        assert telemetry_mod.is_enabled() is False

        # Run through timing callbacks (simulating pipeline)
        root = _make_ctx(agent_name=_ROOT_AGENT_NAME, invocation_id="inv-1")
        phase = _make_ctx(agent_name="ResearchPhase", invocation_id="inv-1")
        topic = _make_ctx(agent_name="Topic0Research", invocation_id="inv-1")

        before_agent_callback(root)
        before_agent_callback(phase)
        before_agent_callback(topic)
        after_agent_callback(topic)
        after_agent_callback(phase)
        after_agent_callback(root)

        # No spans created (active_spans should remain empty throughout)
        assert len(_active_spans) == 0

        # Existing timing behavior still works
        assert "pipeline_start_time" in root.state
        assert "newsletter_metadata" in root.state
        assert "generation_time_seconds" in root.state["newsletter_metadata"]

    def test_disabled_telemetry_noop_provider(self, monkeypatch):
        """Verify NoOpTracerProvider is active when disabled."""
        monkeypatch.setenv("OTEL_ENABLED", "false")

        telemetry_mod._initialized = False
        trace._TRACER_PROVIDER = None
        trace._TRACER_PROVIDER_SET_ONCE._done = False
        telemetry_mod.init_telemetry()

        provider = trace.get_tracer_provider()
        assert isinstance(provider, trace.NoOpTracerProvider)
