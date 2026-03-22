"""Performance tests: OTel instrumentation overhead.

Spec refs: Section 11.5, SC-006, Section 10.1.

Benchmarks a mocked deep-research pipeline path that exercises timing
callbacks, traced LLM calls, and cost tracking rather than a callback-only
simulation.
"""

import asyncio
import logging
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import newsletter_agent.telemetry as telemetry_mod
from newsletter_agent.cost_tracker import ModelPricing, init_cost_tracker, reset_cost_tracker
from newsletter_agent.timing import _active_spans, _phase_starts, after_agent_callback, before_agent_callback


def _make_ctx(agent_name: str, state: dict, invocation_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        agent_name=agent_name,
        invocation_id=invocation_id,
        state=state,
    )


def _build_mock_response() -> SimpleNamespace:
    usage = SimpleNamespace(
        prompt_token_count=1000,
        candidates_token_count=500,
        thoughts_token_count=200,
    )
    return SimpleNamespace(usage_metadata=usage)


async def _mock_generate_content(**kwargs) -> SimpleNamespace:
    await asyncio.sleep(0.075)
    return _build_mock_response()


async def _run_mocked_pipeline(*, n_topics: int = 5) -> None:
    state = {
        "config_topic_count": n_topics,
        "config_topics": [f"Topic{i}" for i in range(n_topics)],
        "config_dry_run": True,
    }

    invocation_id = f"perf-{time.perf_counter_ns()}"
    root = _make_ctx("NewsletterPipeline", state, invocation_id)
    research = _make_ctx("ResearchPhase", state, invocation_id)

    before_agent_callback(root)
    before_agent_callback(research)

    for topic_index in range(n_topics):
        topic = _make_ctx(f"Topic{topic_index}Research", state, invocation_id)
        before_agent_callback(topic)

        for round_index in range(3):
            search_round = _make_ctx(
                f"DeepSearchRound_{topic_index}_{round_index}",
                state,
                invocation_id,
            )
            before_agent_callback(search_round)
            after_agent_callback(search_round)

        synthesizer = _make_ctx(
            f"PerTopicSynthesizer_{topic_index}",
            state,
            invocation_id,
        )
        before_agent_callback(synthesizer)
        await telemetry_mod.traced_generate(
            model="gemini-2.5-pro",
            contents=f"Summarize topic {topic_index}",
            agent_name=f"PerTopicSynthesizer_{topic_index}",
            topic_name=state["config_topics"][topic_index],
            topic_index=topic_index,
            phase="synthesis",
        )
        after_agent_callback(synthesizer)
        after_agent_callback(topic)

    after_agent_callback(research)
    after_agent_callback(root)

    trace.get_tracer_provider().force_flush()


@pytest.fixture(autouse=True)
def _reset_state():
    yield
    _active_spans.clear()
    _phase_starts.clear()
    reset_cost_tracker()
    telemetry_mod._initialized = False
    trace._TRACER_PROVIDER = None
    trace._TRACER_PROVIDER_SET_ONCE._done = False


@pytest.fixture()
def otel_exporter():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    trace._TRACER_PROVIDER = None
    trace._TRACER_PROVIDER_SET_ONCE._done = False
    trace.set_tracer_provider(provider)

    yield exporter

    provider.shutdown()
    trace._TRACER_PROVIDER = None
    trace._TRACER_PROVIDER_SET_ONCE._done = False


async def _average_pipeline_runtime(*, otel_enabled: bool, iterations: int) -> float:
    logger = logging.getLogger("newsletter_agent.timing")

    with patch("google.genai.Client") as mock_client, patch(
        "newsletter_agent.timing.is_enabled", return_value=otel_enabled
    ), patch.object(logger, "info"):
        mock_client.return_value.aio.models.generate_content.side_effect = (
            _mock_generate_content
        )
        telemetry_mod._initialized = otel_enabled

        start = time.perf_counter()
        for _ in range(iterations):
            if otel_enabled:
                init_cost_tracker(
                    pricing={"gemini-2.5-pro": ModelPricing(1.25, 10.00)}
                )
            await _run_mocked_pipeline()
            _active_spans.clear()
            _phase_starts.clear()
            reset_cost_tracker()
        return (time.perf_counter() - start) / iterations


@pytest.mark.performance
class TestOtelOverhead:
    """Performance: OTel tracing overhead < 5%."""

    def test_otel_overhead_below_5_percent(self, otel_exporter):
        """Compare wall-clock time with OTel enabled vs disabled.

        SC-006: Instrumentation adds < 5% overhead.
        """
        iterations = 3

        overhead_samples = []
        for _ in range(3):
            enabled_time = asyncio.run(
                _average_pipeline_runtime(otel_enabled=True, iterations=iterations)
            )
            disabled_time = asyncio.run(
                _average_pipeline_runtime(otel_enabled=False, iterations=iterations)
            )
            overhead_samples.append((enabled_time - disabled_time) / disabled_time)

        overhead_samples.sort()
        overhead = overhead_samples[len(overhead_samples) // 2]
        assert overhead < 0.05, (
            f"OTel overhead {overhead:.2%} exceeds 5% threshold"
        )

    def test_span_count_below_500_for_5_topic_deep(self, otel_exporter):
        """A 5-topic deep-research run should produce fewer than 500 spans."""
        init_cost_tracker(
            pricing={"gemini-2.5-pro": ModelPricing(1.25, 10.00)}
        )

        logger = logging.getLogger("newsletter_agent.timing")

        with patch("google.genai.Client") as mock_client, patch(
            "newsletter_agent.timing.is_enabled", return_value=True
        ), patch.object(logger, "info"):
            mock_client.return_value.aio.models.generate_content.side_effect = (
                _mock_generate_content
            )
            telemetry_mod._initialized = True
            asyncio.run(_run_mocked_pipeline(n_topics=5))

        span_count = len(otel_exporter.get_finished_spans())
        assert span_count < 500, f"Span count {span_count} exceeds 500 limit"
        assert span_count >= 32
