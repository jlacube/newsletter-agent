"""Security tests: No PII in spans, OTLP headers not logged.

Spec refs: Section 11.6, Section 10.2.

Verifies that:
1. No span attributes contain prompt text, response text, emails, or API keys
2. OTLP auth headers are not logged at any level
3. No API key patterns appear in span data
"""

import logging
import os
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
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
    _active_spans.clear()
    _phase_starts.clear()


@pytest.fixture(autouse=True)
def _reset_cost():
    yield
    reset_cost_tracker()


def _make_ctx(agent_name, invocation_id="sec-inv", state=None):
    ctx = SimpleNamespace()
    ctx.agent_name = agent_name
    ctx.invocation_id = invocation_id
    ctx.state = state if state is not None else {}
    return ctx


# Sensitive data that should NEVER appear in span attributes
_PROMPT_TEXT = "Summarize the latest developments in AI agent frameworks for 2025"
_RESPONSE_TEXT = "The AI landscape has evolved significantly with new frameworks..."
_EMAIL = "user@gmail.com"
_SECRET_TOKEN = "secret-token-12345"


class TestNoPiiInSpans:
    """Security: Span attributes must not contain PII or prompt/response text."""

    @pytest.mark.asyncio
    async def test_no_prompt_or_response_in_span_attrs(self, otel_exporter):
        """Spans from traced_generate should not contain prompt or response text."""
        from newsletter_agent.telemetry import traced_generate

        init_cost_tracker(
            pricing={"gemini-2.5-pro": ModelPricing(1.25, 10.00)},
        )

        usage = SimpleNamespace(
            prompt_token_count=500,
            candidates_token_count=200,
            thoughts_token_count=50,
        )
        response = MagicMock()
        response.usage_metadata = usage
        response.text = _RESPONSE_TEXT

        mock_client = MagicMock()
        mock_client.return_value.aio.models.generate_content = AsyncMock(
            return_value=response
        )

        with patch("newsletter_agent.telemetry._initialized", True):
            with patch("google.genai.Client", mock_client):
                await traced_generate(
                    model="gemini-2.5-pro",
                    contents=_PROMPT_TEXT,
                    agent_name="PerTopicSynthesizer_0",
                    topic_name="AI Frameworks",
                    topic_index=0,
                    phase="synthesis",
                )

        spans = otel_exporter.get_finished_spans()
        for span in spans:
            attrs = dict(span.attributes) if span.attributes else {}
            for key, value in attrs.items():
                str_val = str(value)
                assert _PROMPT_TEXT not in str_val, (
                    f"Prompt text found in span attr '{key}'"
                )
                assert _RESPONSE_TEXT not in str_val, (
                    f"Response text found in span attr '{key}'"
                )
                assert _EMAIL not in str_val, (
                    f"Email address found in span attr '{key}'"
                )

    def test_no_email_in_pipeline_span_attrs(self, otel_exporter):
        """Pipeline spans should not contain email addresses."""
        state = {
            "config_topic_count": 1,
            "config_topics": ["AI"],
            "recipient_email": _EMAIL,
        }

        with patch("newsletter_agent.timing.is_enabled", return_value=True):
            ctx = _make_ctx("NewsletterPipeline", state=state)
            before_agent_callback(ctx)
            after_agent_callback(ctx)

        spans = otel_exporter.get_finished_spans()
        email_pattern = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

        for span in spans:
            attrs = dict(span.attributes) if span.attributes else {}
            for key, value in attrs.items():
                str_val = str(value)
                assert not email_pattern.search(str_val), (
                    f"Email pattern found in span attr '{key}': {str_val}"
                )

    def test_no_api_key_patterns_in_spans(self, otel_exporter):
        """Span attributes should not contain API key patterns."""
        init_cost_tracker(
            pricing={"gemini-2.5-pro": ModelPricing(1.25, 10.00)},
        )

        state = {"config_topic_count": 1, "config_topics": ["AI"]}

        with patch("newsletter_agent.timing.is_enabled", return_value=True):
            ctx = _make_ctx("NewsletterPipeline", state=state)
            before_agent_callback(ctx)
            after_agent_callback(ctx)

        # API key patterns
        api_key_patterns = [
            re.compile(r"AIza[0-9A-Za-z\-_]{35}"),  # Google API key
            re.compile(r"pplx-[a-z0-9]{48}"),  # Perplexity API key
        ]

        spans = otel_exporter.get_finished_spans()
        for span in spans:
            attrs = dict(span.attributes) if span.attributes else {}
            for key, value in attrs.items():
                str_val = str(value)
                for pattern in api_key_patterns:
                    assert not pattern.search(str_val), (
                        f"API key pattern found in span attr '{key}'"
                    )


class TestOtlpHeadersNotLogged:
    """Security: OTLP auth headers must not appear in log output."""

    def test_otlp_headers_not_in_logs(self, otel_exporter, caplog, monkeypatch):
        """Set OTLP headers and verify they don't appear in any log output."""
        monkeypatch.setenv(
            "OTEL_EXPORTER_OTLP_HEADERS",
            f"Authorization=Bearer {_SECRET_TOKEN}",
        )

        init_cost_tracker(
            pricing={"gemini-2.5-pro": ModelPricing(1.25, 10.00)},
        )

        state = {"config_topic_count": 1, "config_topics": ["AI"]}

        with caplog.at_level(logging.DEBUG):
            with patch("newsletter_agent.timing.is_enabled", return_value=True):
                ctx = _make_ctx("NewsletterPipeline", state=state)
                before_agent_callback(ctx)
                after_agent_callback(ctx)

        # Check all log records for the secret token
        full_log = caplog.text
        assert _SECRET_TOKEN not in full_log, (
            "OTLP auth token found in log output"
        )

    def test_env_api_keys_not_in_logs(self, otel_exporter, caplog, monkeypatch):
        """API keys from environment should not appear in logs."""
        fake_google_key = "AIzaTestFakeKey12345678901234567890"
        fake_perplexity_key = "pplx-" + "a" * 48

        monkeypatch.setenv("GOOGLE_API_KEY", fake_google_key)
        monkeypatch.setenv("PERPLEXITY_API_KEY", fake_perplexity_key)

        init_cost_tracker(
            pricing={"gemini-2.5-pro": ModelPricing(1.25, 10.00)},
        )

        state = {"config_topic_count": 1, "config_topics": ["AI"]}

        with caplog.at_level(logging.DEBUG):
            with patch("newsletter_agent.timing.is_enabled", return_value=True):
                ctx = _make_ctx("NewsletterPipeline", state=state)
                before_agent_callback(ctx)
                after_agent_callback(ctx)

        full_log = caplog.text
        assert fake_google_key not in full_log, (
            "Google API key found in log output"
        )
        assert fake_perplexity_key not in full_log, (
            "Perplexity API key found in log output"
        )
