"""BDD tests: Token Tracking on LLM Calls.

Spec refs: US-01 Scenarios 1-2, SC-001, Section 11.2.

Feature: Token Tracking on LLM Calls
  Scenario: Successful synthesis records token counts
  Scenario: Missing usage_metadata defaults to zero
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from opentelemetry import context, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from newsletter_agent.cost_tracker import (
    ModelPricing,
    init_cost_tracker,
    reset_cost_tracker,
)
from newsletter_agent.telemetry import traced_generate


@pytest.fixture()
def otel_exporter():
    """Set up InMemorySpanExporter with fresh TracerProvider."""
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
def _setup_cost_tracker():
    """Initialize cost tracker with known pricing for each test."""
    pricing = {
        "gemini-2.5-pro": ModelPricing(1.25, 10.00),
        "gemini-2.5-flash": ModelPricing(0.30, 2.50),
    }
    init_cost_tracker(pricing)
    yield
    reset_cost_tracker()


def _mock_response(prompt_tokens=1000, candidates_tokens=500, thinking_tokens=200):
    """Create a mock LLM response with usage_metadata."""
    usage = MagicMock()
    usage.prompt_token_count = prompt_tokens
    usage.candidates_token_count = candidates_tokens
    usage.thoughts_token_count = thinking_tokens

    response = MagicMock()
    response.usage_metadata = usage
    return response


class TestTokenTrackingScenarios:
    """Feature: Token Tracking on LLM Calls."""

    @pytest.mark.asyncio
    async def test_successful_synthesis_records_token_counts(self, otel_exporter):
        """Scenario: Successful synthesis records token counts.

        Given a pipeline configuration with 1 topic in deep mode
        And the LLM mock returns usage_metadata with
            prompt_token_count=1000, candidates_token_count=500, thoughts_token_count=200
        When the PerTopicSynthesizer agent completes
        Then the span "llm.generate:gemini-2.5-pro" has attribute
            gen_ai.usage.input_tokens = 1000
        And the span has attribute gen_ai.usage.output_tokens = 500
        And the span has attribute gen_ai.usage.thinking_tokens = 200
        """
        mock_resp = _mock_response(
            prompt_tokens=1000, candidates_tokens=500, thinking_tokens=200
        )
        mock_client = MagicMock()
        mock_client.return_value.aio.models.generate_content = AsyncMock(
            return_value=mock_resp
        )

        with patch("newsletter_agent.telemetry._initialized", True):
            with patch("google.genai.Client", mock_client):
                await traced_generate(
                    model="gemini-2.5-pro",
                    contents="Synthesize research on AI Frameworks",
                    agent_name="PerTopicSynthesizer_0",
                    topic_name="AI Frameworks",
                    topic_index=0,
                    phase="synthesis",
                )

        spans = otel_exporter.get_finished_spans()
        llm_spans = [s for s in spans if s.name.startswith("llm.generate")]
        assert len(llm_spans) == 1

        attrs = dict(llm_spans[0].attributes)
        assert attrs["gen_ai.usage.input_tokens"] == 1000
        assert attrs["gen_ai.usage.output_tokens"] == 500
        assert attrs["gen_ai.usage.thinking_tokens"] == 200

    @pytest.mark.asyncio
    async def test_missing_usage_metadata_defaults_to_zero(
        self, otel_exporter, caplog
    ):
        """Scenario: Missing usage_metadata defaults to zero.

        Given a pipeline configuration with 1 topic
        And the LLM mock returns a response with usage_metadata = None
        When the PerTopicSynthesizer agent completes
        Then the span "llm.generate:gemini-2.5-pro" has attribute
            gen_ai.usage.input_tokens = 0
        And a WARNING log contains "usage_metadata missing"
        """
        response = MagicMock()
        response.usage_metadata = None

        mock_client = MagicMock()
        mock_client.return_value.aio.models.generate_content = AsyncMock(
            return_value=response
        )

        with patch("newsletter_agent.telemetry._initialized", True):
            with patch("google.genai.Client", mock_client):
                with caplog.at_level(logging.WARNING):
                    await traced_generate(
                        model="gemini-2.5-pro",
                        contents="Synthesize",
                        agent_name="PerTopicSynthesizer_0",
                        phase="synthesis",
                    )

        spans = otel_exporter.get_finished_spans()
        llm_spans = [s for s in spans if s.name.startswith("llm.generate")]
        assert len(llm_spans) == 1

        attrs = dict(llm_spans[0].attributes)
        assert attrs["gen_ai.usage.input_tokens"] == 0
        assert attrs["gen_ai.usage.output_tokens"] == 0
        assert attrs["gen_ai.usage.thinking_tokens"] == 0
        assert "usage_metadata missing" in caplog.text
