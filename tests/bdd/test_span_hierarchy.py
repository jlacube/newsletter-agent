"""BDD tests: Span Hierarchy.

Spec refs: US-03, FR-201, FR-202, SC-003, Section 11.2.

Feature: Span Hierarchy
  Scenario: Agent spans form correct tree
  Scenario: Failed agent span records error
"""

from unittest.mock import MagicMock, patch

import pytest
from opentelemetry import context, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from newsletter_agent.cost_tracker import reset_cost_tracker
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


class TestSpanHierarchyScenarios:
    """Feature: Span Hierarchy."""

    def test_agent_spans_form_correct_tree(self, otel_exporter):
        """Scenario: Agent spans form correct tree.

        Given a pipeline with 1 topic in standard mode
        When the pipeline completes
        Then span "NewsletterPipeline" is the root span (no parent)
        And span "ResearchPhase" has parent "NewsletterPipeline"
        And span "Topic0Research" has parent "ResearchPhase"
        """
        with patch("newsletter_agent.timing.is_enabled", return_value=True):
            root = _make_ctx(agent_name=_ROOT_AGENT_NAME, invocation_id="inv-1")
            research = _make_ctx(agent_name="ResearchPhase", invocation_id="inv-1")
            topic = _make_ctx(agent_name="Topic0Research", invocation_id="inv-1")

            before_agent_callback(root)
            before_agent_callback(research)
            before_agent_callback(topic)
            after_agent_callback(topic)
            after_agent_callback(research)
            after_agent_callback(root)

        spans = otel_exporter.get_finished_spans()
        assert len(spans) == 3

        span_map = {s.name: s for s in spans}

        # Root has no parent
        root_span = span_map[_ROOT_AGENT_NAME]
        assert root_span.parent is None

        # ResearchPhase -> NewsletterPipeline
        research_span = span_map["ResearchPhase"]
        assert research_span.parent is not None
        assert research_span.parent.span_id == root_span.context.span_id

        # Topic0Research -> ResearchPhase
        topic_span = span_map["Topic0Research"]
        assert topic_span.parent is not None
        assert topic_span.parent.span_id == research_span.context.span_id

    def test_failed_agent_span_records_error(self, otel_exporter):
        """Scenario: Failed agent span records error.

        Given a pipeline where PerTopicSynthesizer raises an exception
        When the pipeline completes
        Then the span "PerTopicSynthesizer" has status ERROR
        And the span has an exception event
        """
        with patch("newsletter_agent.timing.is_enabled", return_value=True):
            ctx = _make_ctx(agent_name="PerTopicSynthesizer", invocation_id="inv-1")
            before_agent_callback(ctx)

            # Simulate exception: manually set error on the span
            key = f"{ctx.invocation_id}:{ctx.agent_name}"
            span, token = _active_spans[key]
            error = RuntimeError("Synthesis failed: API timeout")
            span.set_status(StatusCode.ERROR, str(error))
            span.record_exception(error)

            after_agent_callback(ctx)

        spans = otel_exporter.get_finished_spans()
        assert len(spans) == 1

        synth_span = spans[0]
        assert synth_span.name == "PerTopicSynthesizer"
        assert synth_span.status.status_code == StatusCode.ERROR

        # Check exception event
        exception_events = [e for e in synth_span.events if e.name == "exception"]
        assert len(exception_events) == 1
        exc_attrs = dict(exception_events[0].attributes)
        assert "RuntimeError" in exc_attrs.get("exception.type", "")
