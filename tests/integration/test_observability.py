"""Integration tests: OTel end-to-end, cost pipeline, config loading.

Spec refs: Section 11.3 (integration tests).

Tests verify end-to-end observability pipelines with mocked LLM calls:
1. OTel span tree structure from before/after callbacks
2. Cost pipeline from traced_generate through to cost summary
3. Config loading with pricing section
"""

import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from newsletter_agent.cost_tracker import (
    CostTracker,
    ModelPricing,
    get_cost_tracker,
    init_cost_tracker,
    reset_cost_tracker,
)
from newsletter_agent.telemetry import is_enabled
from newsletter_agent.timing import (
    _active_spans,
    _phase_starts,
    after_agent_callback,
    before_agent_callback,
)


@pytest.fixture()
def otel_exporter():
    """Set up InMemorySpanExporter with SimpleSpanProcessor for integration tests."""
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
    _active_spans.clear()
    _phase_starts.clear()


@pytest.fixture(autouse=True)
def _reset_cost():
    yield
    reset_cost_tracker()


def _make_callback_ctx(agent_name, invocation_id="inv-1", state=None):
    """Create a mock callback context for before/after callbacks."""
    ctx = SimpleNamespace()
    ctx.agent_name = agent_name
    ctx.invocation_id = invocation_id
    ctx.state = state if state is not None else {}
    return ctx


class TestOtelEndToEnd:
    """Integration: Full OTel span tree from callback simulation."""

    def test_full_pipeline_span_tree(self, otel_exporter):
        """Simulate a 2-topic pipeline and verify the span hierarchy.

        Nesting: NewsletterPipeline > ResearchPhase > Topic0Research
                                    > Topic1Research
                                    > SynthesisPhase
        """
        state = {"config_topic_count": 2, "config_topics": ["AI", "Cloud"]}

        with patch("newsletter_agent.timing.is_enabled", return_value=True):
            # Root span
            root_ctx = _make_callback_ctx("NewsletterPipeline", state=state)
            before_agent_callback(root_ctx)

            # ResearchPhase
            research_ctx = _make_callback_ctx(
                "ResearchPhase", state=state
            )
            before_agent_callback(research_ctx)

            # Topic0Research
            t0_ctx = _make_callback_ctx("Topic0Research", state=state)
            before_agent_callback(t0_ctx)
            after_agent_callback(t0_ctx)

            # Topic1Research
            t1_ctx = _make_callback_ctx("Topic1Research", state=state)
            before_agent_callback(t1_ctx)
            after_agent_callback(t1_ctx)

            # End ResearchPhase
            after_agent_callback(research_ctx)

            # SynthesisPhase
            synth_ctx = _make_callback_ctx("SynthesisPhase", state=state)
            before_agent_callback(synth_ctx)
            after_agent_callback(synth_ctx)

            # End root
            after_agent_callback(root_ctx)

        spans = otel_exporter.get_finished_spans()
        span_map = {s.name: s for s in spans}

        # All expected spans present
        expected = [
            "NewsletterPipeline",
            "ResearchPhase",
            "Topic0Research",
            "Topic1Research",
            "SynthesisPhase",
        ]
        for name in expected:
            assert name in span_map, f"Missing span: {name}"

        # Root has no parent
        root_span = span_map["NewsletterPipeline"]
        assert root_span.parent is None

        # ResearchPhase parent is root
        research_span = span_map["ResearchPhase"]
        assert (
            research_span.parent.span_id == root_span.context.span_id
        )

        # Topics are children of ResearchPhase
        for topic_name in ("Topic0Research", "Topic1Research"):
            topic_span = span_map[topic_name]
            assert (
                topic_span.parent.span_id == research_span.context.span_id
            )

        # Topic attributes
        t0 = span_map["Topic0Research"]
        assert dict(t0.attributes)["newsletter.topic.index"] == 0
        assert dict(t0.attributes)["newsletter.topic.name"] == "AI"

        t1 = span_map["Topic1Research"]
        assert dict(t1.attributes)["newsletter.topic.index"] == 1
        assert dict(t1.attributes)["newsletter.topic.name"] == "Cloud"

    def test_root_span_has_pipeline_attributes(self, otel_exporter):
        """Root span should have pipeline_start_time and topic_count."""
        state = {"config_topic_count": 3, "config_dry_run": True}

        with patch("newsletter_agent.timing.is_enabled", return_value=True):
            ctx = _make_callback_ctx("NewsletterPipeline", state=state)
            before_agent_callback(ctx)
            after_agent_callback(ctx)

        spans = otel_exporter.get_finished_spans()
        root = [s for s in spans if s.name == "NewsletterPipeline"][0]
        attrs = dict(root.attributes)

        assert attrs["newsletter.topic_count"] == 3
        assert attrs["newsletter.dry_run"] is True
        assert "newsletter.pipeline_start_time" in attrs
        assert "newsletter.duration_seconds" in attrs


class TestCostPipelineIntegration:
    """Integration: Cost tracking through traced_generate to cost summary."""

    @pytest.mark.asyncio
    async def test_traced_generate_records_cost_and_tokens(self, otel_exporter):
        """traced_generate should create an LLM span with token+cost attrs
        and record cost in the global CostTracker."""
        from newsletter_agent.telemetry import traced_generate

        # Init cost tracker with known pricing
        init_cost_tracker(
            pricing={"gemini-2.5-pro": ModelPricing(1.25, 10.00)},
        )

        # Build mock response
        usage = SimpleNamespace(
            prompt_token_count=5000,
            candidates_token_count=1000,
            thoughts_token_count=200,
        )
        response = MagicMock()
        response.usage_metadata = usage

        mock_client = MagicMock()
        mock_client.return_value.aio.models.generate_content = AsyncMock(
            return_value=response
        )

        with patch("newsletter_agent.telemetry._initialized", True):
            with patch("google.genai.Client", mock_client):
                result = await traced_generate(
                    model="gemini-2.5-pro",
                    contents="Summarize AI news",
                    agent_name="PerTopicSynthesizer_0",
                    topic_name="AI",
                    topic_index=0,
                    phase="synthesis",
                )

        assert result is response

        # Verify span
        spans = otel_exporter.get_finished_spans()
        llm_spans = [s for s in spans if s.name.startswith("llm.generate")]
        assert len(llm_spans) == 1
        attrs = dict(llm_spans[0].attributes)

        assert attrs["gen_ai.usage.input_tokens"] == 5000
        assert attrs["gen_ai.usage.output_tokens"] == 1000
        assert attrs["gen_ai.usage.thinking_tokens"] == 200
        assert attrs["newsletter.cost.total_usd"] == pytest.approx(0.01825)

        # Verify cost tracker state
        tracker = get_cost_tracker()
        summary = tracker.get_summary()
        assert summary.call_count == 1
        assert summary.total_cost_usd == pytest.approx(0.01825)

    def test_cost_summary_on_root_agent_end(self, otel_exporter, caplog):
        """When root agent ends, cost summary should be logged and added to state."""
        init_cost_tracker(
            pricing={"gemini-2.5-pro": ModelPricing(1.25, 10.00)},
        )

        # Simulate two LLM calls
        tracker = get_cost_tracker()
        tracker.record_llm_call(
            model="gemini-2.5-pro",
            agent_name="PerTopicSynthesizer_0",
            phase="synthesis",
            topic_name="AI",
            prompt_tokens=5000,
            completion_tokens=1000,
        )
        tracker.record_llm_call(
            model="gemini-2.5-pro",
            agent_name="PerTopicSynthesizer_1",
            phase="synthesis",
            topic_name="Cloud",
            prompt_tokens=3000,
            completion_tokens=800,
        )

        state = {}

        with patch("newsletter_agent.timing.is_enabled", return_value=True):
            with caplog.at_level(logging.INFO, logger="newsletter_agent.timing"):
                ctx = _make_callback_ctx("NewsletterPipeline", state=state)
                before_agent_callback(ctx)
                after_agent_callback(ctx)

        # State should have cost summary
        assert "run_cost_usd" in state
        assert state["run_cost_usd"] == pytest.approx(
            tracker.get_summary().total_cost_usd
        )
        assert "cost_summary" in state

        # Log should contain JSON cost summary
        cost_logs = [
            r for r in caplog.records
            if "pipeline_cost_summary" in r.getMessage()
        ]
        assert len(cost_logs) >= 1
        cost_data = json.loads(cost_logs[0].getMessage())
        assert cost_data["call_count"] == 2
        assert cost_data["total_cost_usd"] == pytest.approx(
            state["run_cost_usd"]
        )

        # Span should have cost_summary event
        spans = otel_exporter.get_finished_spans()
        root = [s for s in spans if s.name == "NewsletterPipeline"][0]
        events = [e for e in root.events if e.name == "cost_summary"]
        assert len(events) == 1
        assert events[0].attributes["call_count"] == 2


class TestConfigLoadingIntegration:
    """Integration: Config loading with pricing section."""

    def test_pricing_config_parsed_from_yaml(self, tmp_path):
        """Load a YAML config with pricing and verify it creates valid pricing."""
        from newsletter_agent.config.schema import (
            AppSettings,
            NewsletterConfig,
        )

        config_data = {
            "newsletter": {
                "title": "Test Newsletter",
                "schedule": "0 8 * * 0",
                "recipient_email": "test@example.com",
            },
            "settings": {
                "dry_run": True,
                "output_dir": str(tmp_path),
                "pricing": {
                    "models": {
                        "gemini-2.5-pro": {
                            "input_per_million": 1.25,
                            "output_per_million": 10.00,
                        },
                        "gemini-2.5-flash": {
                            "input_per_million": 0.30,
                            "output_per_million": 2.50,
                        },
                    },
                    "cost_budget_usd": 0.50,
                },
            },
            "topics": [
                {"name": "AI", "query": "AI news"},
            ],
        }

        config = NewsletterConfig(**config_data)

        # Verify pricing parsed correctly
        pricing = config.settings.pricing
        assert "gemini-2.5-pro" in pricing.models
        assert pricing.models["gemini-2.5-pro"].input_per_million == 1.25
        assert pricing.models["gemini-2.5-pro"].output_per_million == 10.00
        assert pricing.cost_budget_usd == 0.50

        # Verify CostTracker can be initialized from parsed pricing
        pricing_dict = {
            name: ModelPricing(m.input_per_million, m.output_per_million)
            for name, m in pricing.models.items()
        }
        init_cost_tracker(pricing_dict, pricing.cost_budget_usd)
        tracker = get_cost_tracker()

        record = tracker.record_llm_call(
            model="gemini-2.5-pro",
            agent_name="TestAgent",
            phase="test",
            prompt_tokens=1000,
            completion_tokens=500,
        )
        assert record.total_cost_usd == pytest.approx(
            1000 * 1.25 / 1_000_000 + 500 * 10.00 / 1_000_000
        )

    def test_default_pricing_without_explicit_config(self):
        """AppSettings without explicit pricing should have default models."""
        from newsletter_agent.config.schema import AppSettings

        settings = AppSettings(dry_run=True)
        assert "gemini-2.5-pro" in settings.pricing.models
        assert "gemini-2.5-flash" in settings.pricing.models
        assert settings.pricing.cost_budget_usd is None
