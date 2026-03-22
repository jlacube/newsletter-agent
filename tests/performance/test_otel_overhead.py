"""Performance tests: OTel instrumentation overhead.

Spec refs: Section 11.5, SC-006, Section 10.1.

Verifies that OTel tracing overhead is less than 5% of pipeline execution
time, and that span count stays below 500 per run.
"""

import logging
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from newsletter_agent.cost_tracker import (
    ModelPricing,
    init_cost_tracker,
    reset_cost_tracker,
)
from newsletter_agent.timing import (
    _active_spans,
    _phase_starts,
    after_agent_callback,
    before_agent_callback,
)


def _make_ctx(agent_name, invocation_id="perf-inv", state=None):
    ctx = SimpleNamespace()
    ctx.agent_name = agent_name
    ctx.invocation_id = invocation_id
    ctx.state = state if state is not None else {}
    return ctx


def _simulate_mock_llm_work(duration_seconds=0.01):
    """Burn a small, deterministic amount of wall-clock time.

    This approximates mocked downstream work so the benchmark measures
    observability overhead relative to a representative pipeline run rather
    than a near-empty callback microbenchmark.
    """
    deadline = time.perf_counter() + duration_seconds
    while time.perf_counter() < deadline:
        pass


def _run_simulated_pipeline(n_topics=5, deep=True):
    """Simulate a multi-topic pipeline via before/after callbacks.

    Creates span tree:
      NewsletterPipeline > ResearchPhase > Topic{i}Research (x n_topics)
                                        > SynthesisPhase
    For deep mode, each topic gets additional sub-agents.
    """
    state = {
        "config_topic_count": n_topics,
        "config_topics": [f"Topic{i}" for i in range(n_topics)],
    }

    root = _make_ctx("NewsletterPipeline", state=state)
    before_agent_callback(root)

    # Research phase
    research = _make_ctx("ResearchPhase", state=state)
    before_agent_callback(research)

    for i in range(n_topics):
        topic = _make_ctx(f"Topic{i}Research", state=state)
        before_agent_callback(topic)

        if deep:
            # Simulate deep research sub-agents
            for round_idx in range(3):
                searcher = _make_ctx(
                    f"DeepSearchRound_{i}_{round_idx}", state=state
                )
                before_agent_callback(searcher)
                _simulate_mock_llm_work()
                after_agent_callback(searcher)

            analyzer = _make_ctx(f"AdaptiveAnalyzer_{i}", state=state)
            before_agent_callback(analyzer)
            _simulate_mock_llm_work()
            after_agent_callback(analyzer)

        after_agent_callback(topic)

    after_agent_callback(research)

    # Synthesis phase
    synth = _make_ctx("SynthesisPhase", state=state)
    before_agent_callback(synth)

    for i in range(n_topics):
        synthesizer = _make_ctx(f"PerTopicSynthesizer_{i}", state=state)
        before_agent_callback(synthesizer)
        _simulate_mock_llm_work()
        after_agent_callback(synthesizer)

    after_agent_callback(synth)
    after_agent_callback(root)


@pytest.fixture(autouse=True)
def _reset_state():
    yield
    _active_spans.clear()
    _phase_starts.clear()
    reset_cost_tracker()


@pytest.fixture()
def otel_exporter():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(
        BatchSpanProcessor(
            exporter,
            schedule_delay_millis=1,
            max_export_batch_size=512,
            max_queue_size=2048,
        )
    )

    trace._TRACER_PROVIDER = None
    trace._TRACER_PROVIDER_SET_ONCE._done = False
    trace.set_tracer_provider(provider)

    yield exporter

    provider.shutdown()
    trace._TRACER_PROVIDER = None
    trace._TRACER_PROVIDER_SET_ONCE._done = False


@pytest.mark.performance
class TestOtelOverhead:
    """Performance: OTel tracing overhead < 5%."""

    def test_otel_overhead_below_5_percent(self, otel_exporter):
        """Compare wall-clock time with OTel enabled vs disabled.

        SC-006: Instrumentation adds < 5% overhead.
        """
        init_cost_tracker(
            pricing={"gemini-2.5-pro": ModelPricing(1.25, 10.00)},
        )
        iterations = 10
        logger = logging.getLogger("newsletter_agent.timing")

        # Warm up
        with patch("newsletter_agent.timing.is_enabled", return_value=True), patch.object(
            logger, "info"
        ):
            _run_simulated_pipeline(n_topics=5, deep=True)
        otel_exporter.clear()
        _active_spans.clear()
        _phase_starts.clear()

        # Median-of-3 runs to reduce scheduling noise.
        overhead_samples = []
        for _ in range(3):
            # Benchmark with OTel enabled
            with patch("newsletter_agent.timing.is_enabled", return_value=True), patch.object(
                logger, "info"
            ):
                start = time.perf_counter()
                for _ in range(iterations):
                    _run_simulated_pipeline(n_topics=5, deep=True)
                enabled_time = (time.perf_counter() - start) / iterations

            otel_exporter.clear()
            _active_spans.clear()
            _phase_starts.clear()

            # Benchmark with OTel disabled
            with patch("newsletter_agent.timing.is_enabled", return_value=False), patch.object(
                logger, "info"
            ):
                start = time.perf_counter()
                for _ in range(iterations):
                    _run_simulated_pipeline(n_topics=5, deep=True)
                disabled_time = (time.perf_counter() - start) / iterations

            _active_spans.clear()
            _phase_starts.clear()

            if disabled_time > 1e-9:
                overhead_samples.append(
                    (enabled_time - disabled_time) / disabled_time
                )

        if not overhead_samples:
            pytest.skip("Disabled time too small for meaningful comparison")

        overhead_samples.sort()
        median_overhead = overhead_samples[len(overhead_samples) // 2]

        assert median_overhead < 0.05, (
            f"OTel overhead {median_overhead:.2%} exceeds 5% threshold"
        )

    def test_span_count_below_500_for_5_topic_deep(self, otel_exporter):
        """A 5-topic deep-research run should produce fewer than 500 spans."""
        init_cost_tracker(
            pricing={"gemini-2.5-pro": ModelPricing(1.25, 10.00)},
        )
        logger = logging.getLogger("newsletter_agent.timing")

        with patch("newsletter_agent.timing.is_enabled", return_value=True), patch.object(
            logger, "info"
        ):
            _run_simulated_pipeline(n_topics=5, deep=True)

        trace.get_tracer_provider().force_flush()
        span_count = len(otel_exporter.get_finished_spans())
        assert span_count < 500, (
            f"Span count {span_count} exceeds 500 limit"
        )
        # Sanity: should have at least the expected spans
        # Root + research + 5 topics + 5*(3 searchers + 1 analyzer) + synth + 5 synthesizers
        # = 1 + 1 + 5 + 20 + 1 + 5 = 33
        assert span_count >= 30
