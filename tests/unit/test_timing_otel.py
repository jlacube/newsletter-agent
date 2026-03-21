"""Unit tests for timing.py OTel span creation and hierarchy.

Spec refs: FR-201 through FR-208, FR-304, FR-501 through FR-504,
           Section 11.1 (test_timing_otel.py requirements).
"""

import json
import logging
import time
from unittest.mock import MagicMock, patch

import pytest
from opentelemetry import context, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from newsletter_agent.cost_tracker import (
    CostSummary,
    CostTracker,
    ModelCostDetail,
    ModelPricing,
    get_cost_tracker,
    init_cost_tracker,
    reset_cost_tracker,
)
from newsletter_agent.timing import (
    _ROOT_AGENT_NAME,
    _TOPIC_INDEX_RE,
    _active_spans,
    _phase_starts,
    after_agent_callback,
    before_agent_callback,
)


@pytest.fixture(autouse=True)
def _clean_timing_state():
    """Clear module-level dicts before/after each test."""
    _phase_starts.clear()
    _active_spans.clear()
    yield
    _phase_starts.clear()
    _active_spans.clear()


@pytest.fixture()
def otel_exporter():
    """Set up an InMemorySpanExporter and TracerProvider for test capture.

    Resets the global OTel state to allow setting a fresh provider, then
    restores it after the test.
    """
    exporter = InMemorySpanExporter()
    resource = Resource.create({"service.name": "test"})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    # Reset global OTel state so we can set our test provider
    trace._TRACER_PROVIDER = None
    trace._TRACER_PROVIDER_SET_ONCE._done = False
    trace.set_tracer_provider(provider)

    yield exporter

    provider.shutdown()
    # Reset again so other tests aren't affected
    trace._TRACER_PROVIDER = None
    trace._TRACER_PROVIDER_SET_ONCE._done = False


@pytest.fixture(autouse=True)
def _reset_cost():
    """Reset cost tracker between tests."""
    yield
    reset_cost_tracker()


def _make_ctx(agent_name="TestAgent", invocation_id="inv-1", state=None):
    ctx = MagicMock()
    ctx.agent_name = agent_name
    ctx.invocation_id = invocation_id
    ctx.state = state if state is not None else {}
    return ctx


class TestBeforeCallbackSpanCreation:
    """FR-201: before_agent_callback creates OTel span when enabled."""

    def test_creates_span_when_enabled(self, otel_exporter):
        with patch("newsletter_agent.timing.is_enabled", return_value=True):
            ctx = _make_ctx(agent_name="ResearchPhase")
            before_agent_callback(ctx)
            # Span stored but not yet ended
            key = f"{ctx.invocation_id}:{ctx.agent_name}"
            assert key in _active_spans
            span, token = _active_spans[key]
            assert span.name == "ResearchPhase"
            # Clean up
            span.end()
            context.detach(token)
            _active_spans.pop(key)

        spans = otel_exporter.get_finished_spans()
        assert len(spans) == 1
        attrs = dict(spans[0].attributes)
        assert attrs["newsletter.agent.name"] == "ResearchPhase"
        assert attrs["newsletter.invocation_id"] == "inv-1"

    def test_skips_span_when_disabled(self, otel_exporter):
        with patch("newsletter_agent.timing.is_enabled", return_value=False):
            ctx = _make_ctx(agent_name="ResearchPhase")
            before_agent_callback(ctx)
            key = f"{ctx.invocation_id}:{ctx.agent_name}"
            assert key not in _active_spans

        assert len(otel_exporter.get_finished_spans()) == 0

    def test_preserves_start_time_recording(self, otel_exporter):
        with patch("newsletter_agent.timing.is_enabled", return_value=True):
            ctx = _make_ctx()
            before_agent_callback(ctx)
            key = f"{ctx.invocation_id}:{ctx.agent_name}"
            assert key in _phase_starts
            # Cleanup span
            span, token = _active_spans.pop(key)
            span.end()
            context.detach(token)


class TestAfterCallbackSpanEnd:
    """FR-203, FR-204: after_agent_callback ends span and detaches context."""

    def test_ends_span_with_duration(self, otel_exporter):
        with patch("newsletter_agent.timing.is_enabled", return_value=True):
            ctx = _make_ctx(agent_name="ResearchPhase")
            before_agent_callback(ctx)
            time.sleep(0.01)
            after_agent_callback(ctx)

        spans = otel_exporter.get_finished_spans()
        assert len(spans) == 1
        attrs = dict(spans[0].attributes)
        assert "newsletter.duration_seconds" in attrs
        assert attrs["newsletter.duration_seconds"] >= 0.01

    def test_handles_missing_span_gracefully(self, otel_exporter, caplog):
        """FR-204 error: missing span logs WARNING."""
        with patch("newsletter_agent.timing.is_enabled", return_value=True):
            ctx = _make_ctx(agent_name="Orphan")
            # Don't call before_callback - simulate missing span
            _phase_starts[f"{ctx.invocation_id}:{ctx.agent_name}"] = time.monotonic()
            with caplog.at_level(logging.WARNING, logger="newsletter_agent.timing"):
                after_agent_callback(ctx)
            assert "Span not found for key" in caplog.text

    def test_preserves_timing_log(self, otel_exporter, caplog):
        """FR-207: existing timing behavior preserved."""
        with patch("newsletter_agent.timing.is_enabled", return_value=True):
            ctx = _make_ctx(agent_name="ConfigLoader")
            with caplog.at_level(logging.INFO, logger="newsletter_agent.timing"):
                before_agent_callback(ctx)
                after_agent_callback(ctx)
            assert "ConfigLoader completed in" in caplog.text

    def test_preserves_pipeline_metadata(self, otel_exporter):
        """FR-207: generation_time_seconds still set in state."""
        with patch("newsletter_agent.timing.is_enabled", return_value=True):
            ctx = _make_ctx(agent_name=_ROOT_AGENT_NAME)
            before_agent_callback(ctx)
            after_agent_callback(ctx)
            assert "newsletter_metadata" in ctx.state
            assert "generation_time_seconds" in ctx.state["newsletter_metadata"]


class TestSpanHierarchy:
    """FR-202: parent-child relationships via context attach/detach."""

    def test_parent_child_spans(self, otel_exporter):
        with patch("newsletter_agent.timing.is_enabled", return_value=True):
            parent = _make_ctx(agent_name="ResearchPhase", invocation_id="inv-1")
            child = _make_ctx(agent_name="Topic0Research", invocation_id="inv-1")

            before_agent_callback(parent)
            before_agent_callback(child)
            after_agent_callback(child)
            after_agent_callback(parent)

        spans = otel_exporter.get_finished_spans()
        assert len(spans) == 2

        child_span = next(s for s in spans if s.name == "Topic0Research")
        parent_span = next(s for s in spans if s.name == "ResearchPhase")

        # Child's parent should be the parent span
        assert child_span.parent is not None
        assert child_span.parent.span_id == parent_span.context.span_id

    def test_three_level_hierarchy(self, otel_exporter):
        """SC-003: pipeline > phase > agent."""
        with patch("newsletter_agent.timing.is_enabled", return_value=True):
            root = _make_ctx(agent_name=_ROOT_AGENT_NAME, invocation_id="inv-1")
            phase = _make_ctx(agent_name="ResearchPhase", invocation_id="inv-1")
            agent = _make_ctx(agent_name="Topic0Research", invocation_id="inv-1")

            before_agent_callback(root)
            before_agent_callback(phase)
            before_agent_callback(agent)
            after_agent_callback(agent)
            after_agent_callback(phase)
            after_agent_callback(root)

        spans = otel_exporter.get_finished_spans()
        assert len(spans) == 3

        root_span = next(s for s in spans if s.name == _ROOT_AGENT_NAME)
        phase_span = next(s for s in spans if s.name == "ResearchPhase")
        agent_span = next(s for s in spans if s.name == "Topic0Research")

        assert phase_span.parent.span_id == root_span.context.span_id
        assert agent_span.parent.span_id == phase_span.context.span_id


class TestRootAgentAttributes:
    """FR-205: Root agent span has topic_count, dry_run, pipeline_start_time."""

    def test_root_span_attributes_from_state(self, otel_exporter):
        state = {
            "config_topic_count": 5,
            "config_dry_run": True,
        }
        with patch("newsletter_agent.timing.is_enabled", return_value=True):
            ctx = _make_ctx(agent_name=_ROOT_AGENT_NAME, state=state)
            before_agent_callback(ctx)
            after_agent_callback(ctx)

        spans = otel_exporter.get_finished_spans()
        assert len(spans) == 1
        attrs = dict(spans[0].attributes)
        assert attrs["newsletter.topic_count"] == 5
        assert attrs["newsletter.dry_run"] is True
        assert "newsletter.pipeline_start_time" in attrs
        assert len(attrs["newsletter.pipeline_start_time"]) > 0

    def test_root_span_omits_missing_state(self, otel_exporter):
        """If state keys not populated, attributes omitted gracefully."""
        with patch("newsletter_agent.timing.is_enabled", return_value=True):
            ctx = _make_ctx(agent_name=_ROOT_AGENT_NAME)
            before_agent_callback(ctx)
            after_agent_callback(ctx)

        spans = otel_exporter.get_finished_spans()
        attrs = dict(spans[0].attributes)
        # pipeline_start_time is always set from before_callback
        assert "newsletter.pipeline_start_time" in attrs
        # topic_count and dry_run should NOT be present
        assert "newsletter.topic_count" not in attrs
        assert "newsletter.dry_run" not in attrs


class TestTopicScopedAttributes:
    """FR-206: topic index extracted from agent name via regex."""

    @pytest.mark.parametrize(
        "agent_name,expected_idx",
        [
            ("GoogleSearcher_0", 0),
            ("DeepResearch_2_google", 2),
            ("Topic0Research", 0),
            ("Topic3Research", 3),
        ],
    )
    def test_topic_index_regex(self, agent_name, expected_idx):
        match = _TOPIC_INDEX_RE.search(agent_name)
        assert match is not None
        assert int(match.group(1)) == expected_idx

    def test_no_match_for_non_topic_agent(self):
        assert _TOPIC_INDEX_RE.search("ConfigLoader") is None

    def test_topic_attributes_on_span(self, otel_exporter):
        state = {"config_topics": ["AI Frameworks", "Cloud Native", "Security"]}
        with patch("newsletter_agent.timing.is_enabled", return_value=True):
            ctx = _make_ctx(
                agent_name="GoogleSearcher_1", invocation_id="inv-1", state=state
            )
            before_agent_callback(ctx)
            after_agent_callback(ctx)

        spans = otel_exporter.get_finished_spans()
        attrs = dict(spans[0].attributes)
        assert attrs["newsletter.topic.index"] == 1
        assert attrs["newsletter.topic.name"] == "Cloud Native"

    def test_topic_research_callback_sets_attributes(self, otel_exporter):
        """FB-03: TopicNResearch names get topic attributes through full callback."""
        state = {"config_topics": ["AI Frameworks", "Cloud Native", "Security"]}
        with patch("newsletter_agent.timing.is_enabled", return_value=True):
            ctx = _make_ctx(
                agent_name="Topic0Research", invocation_id="inv-1", state=state
            )
            before_agent_callback(ctx)
            after_agent_callback(ctx)

        spans = otel_exporter.get_finished_spans()
        assert len(spans) == 1
        attrs = dict(spans[0].attributes)
        assert attrs["newsletter.topic.index"] == 0
        assert attrs["newsletter.topic.name"] == "AI Frameworks"

    def test_topic_index_without_names(self, otel_exporter):
        """Topic index set even if topic names not in state."""
        with patch("newsletter_agent.timing.is_enabled", return_value=True):
            ctx = _make_ctx(agent_name="GoogleSearcher_0")
            before_agent_callback(ctx)
            after_agent_callback(ctx)

        spans = otel_exporter.get_finished_spans()
        attrs = dict(spans[0].attributes)
        assert attrs["newsletter.topic.index"] == 0
        assert "newsletter.topic.name" not in attrs


class TestLlmAgentMarker:
    """FR-304: LlmAgent spans have gen_ai.tokens_available: false."""

    @pytest.mark.parametrize(
        "agent_name",
        [
            "GoogleSearcher_0",
            "PerplexitySearcher_1",
            "AdaptivePlanner_0_google",
            "DeepSearchRound_2_google_r0",
            "AdaptiveAnalyzer_0_google_r0",
        ],
    )
    def test_llm_agent_has_marker(self, agent_name, otel_exporter):
        with patch("newsletter_agent.timing.is_enabled", return_value=True):
            ctx = _make_ctx(agent_name=agent_name)
            before_agent_callback(ctx)
            after_agent_callback(ctx)

        spans = otel_exporter.get_finished_spans()
        attrs = dict(spans[0].attributes)
        assert attrs["gen_ai.tokens_available"] is False

    @pytest.mark.parametrize(
        "agent_name",
        ["ConfigLoader", "ResearchPhase", "FormatterAgent", "DeliveryAgent"],
    )
    def test_non_llm_agent_no_marker(self, agent_name, otel_exporter):
        with patch("newsletter_agent.timing.is_enabled", return_value=True):
            ctx = _make_ctx(agent_name=agent_name)
            before_agent_callback(ctx)
            after_agent_callback(ctx)

        spans = otel_exporter.get_finished_spans()
        attrs = dict(spans[0].attributes)
        assert "gen_ai.tokens_available" not in attrs


class TestCostSummary:
    """FR-501 through FR-504: cost summary logging and span events."""

    def test_cost_summary_logged_on_root_completion(self, otel_exporter, caplog):
        """FR-501: structured cost summary logged at INFO."""
        pricing = {"gemini-2.5-flash": ModelPricing(0.30, 2.50)}
        init_cost_tracker(pricing)
        tracker = get_cost_tracker()
        tracker.record_llm_call(
            model="gemini-2.5-flash",
            agent_name="TestAgent",
            phase="refinement",
            prompt_tokens=1000,
            completion_tokens=500,
            thinking_tokens=100,
        )

        with patch("newsletter_agent.timing.is_enabled", return_value=True):
            ctx = _make_ctx(agent_name=_ROOT_AGENT_NAME)
            with caplog.at_level(logging.INFO, logger="newsletter_agent.timing"):
                before_agent_callback(ctx)
                after_agent_callback(ctx)

        # Verify JSON log line
        cost_logs = [
            r for r in caplog.records
            if "pipeline_cost_summary" in r.getMessage()
        ]
        assert len(cost_logs) == 1
        cost_data = json.loads(cost_logs[0].getMessage())
        assert cost_data["event"] == "pipeline_cost_summary"
        assert cost_data["total_input_tokens"] == 1000
        assert cost_data["total_output_tokens"] == 500
        assert cost_data["total_thinking_tokens"] == 100
        assert cost_data["call_count"] == 1
        assert cost_data["total_cost_usd"] > 0

    def test_cost_summary_span_event(self, otel_exporter):
        """FR-502: cost_summary event on root span."""
        pricing = {"gemini-2.5-flash": ModelPricing(0.30, 2.50)}
        init_cost_tracker(pricing)
        tracker = get_cost_tracker()
        tracker.record_llm_call(
            model="gemini-2.5-flash",
            agent_name="TestAgent",
            phase="synthesis",
            prompt_tokens=100,
            completion_tokens=50,
            thinking_tokens=0,
        )

        with patch("newsletter_agent.timing.is_enabled", return_value=True):
            ctx = _make_ctx(agent_name=_ROOT_AGENT_NAME)
            before_agent_callback(ctx)
            after_agent_callback(ctx)

        spans = otel_exporter.get_finished_spans()
        root_span = next(s for s in spans if s.name == _ROOT_AGENT_NAME)
        events = root_span.events
        assert len(events) == 1
        assert events[0].name == "cost_summary"
        event_attrs = dict(events[0].attributes)
        assert "total_cost_usd" in event_attrs
        assert "total_input_tokens" in event_attrs
        assert "total_output_tokens" in event_attrs
        assert "call_count" in event_attrs

    def test_state_set_on_root_completion(self, otel_exporter):
        """FR-503, FR-504: run_cost_usd and cost_summary in state."""
        pricing = {"gemini-2.5-flash": ModelPricing(0.30, 2.50)}
        init_cost_tracker(pricing)

        with patch("newsletter_agent.timing.is_enabled", return_value=True):
            ctx = _make_ctx(agent_name=_ROOT_AGENT_NAME)
            before_agent_callback(ctx)
            after_agent_callback(ctx)

        assert "run_cost_usd" in ctx.state
        assert isinstance(ctx.state["run_cost_usd"], float)
        assert "cost_summary" in ctx.state
        assert isinstance(ctx.state["cost_summary"], dict)

    def test_zero_summary_does_not_error(self, otel_exporter, caplog):
        """Empty cost tracker produces zeros, no error."""
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

    def test_non_root_agent_no_cost_summary(self, otel_exporter, caplog):
        """Cost summary only at root agent, not child agents."""
        with patch("newsletter_agent.timing.is_enabled", return_value=True):
            ctx = _make_ctx(agent_name="ResearchPhase")
            with caplog.at_level(logging.INFO, logger="newsletter_agent.timing"):
                before_agent_callback(ctx)
                after_agent_callback(ctx)

        assert "pipeline_cost_summary" not in caplog.text
