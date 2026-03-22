"""Unit tests for telemetry initialization, shutdown, get_tracer, is_enabled,
and traced_generate.

Spec refs: FR-101 through FR-106, FR-301, FR-303, FR-402,
FR-602, FR-603, FR-604, SC-004, SC-007, Section 11.1.
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import newsletter_agent.telemetry as tel
from newsletter_agent.cost_tracker import (
    ModelPricing,
    get_cost_tracker,
    init_cost_tracker,
    reset_cost_tracker,
)


@pytest.fixture(autouse=True)
def reset_telemetry():
    """Reset telemetry global state before and after each test."""
    tel._initialized = False
    # Reset OTel global provider to allow re-initialization per test
    trace._TRACER_PROVIDER = None
    trace._TRACER_PROVIDER_SET_ONCE._done = False
    trace._PROXY_TRACER_PROVIDER._real_tracer_provider = None
    yield
    tel._initialized = False
    trace._TRACER_PROVIDER = None
    trace._TRACER_PROVIDER_SET_ONCE._done = False
    trace._PROXY_TRACER_PROVIDER._real_tracer_provider = None


class TestInitTelemetry:

    def test_default_init_succeeds(self, monkeypatch):
        """init_telemetry() with defaults configures a real TracerProvider."""
        monkeypatch.delenv("OTEL_ENABLED", raising=False)
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("K_SERVICE", raising=False)
        tel.init_telemetry()
        assert tel.is_enabled() is True
        provider = trace.get_tracer_provider()
        # Should be a real SDK TracerProvider, not NoOp
        assert isinstance(provider, TracerProvider)

    def test_disabled_via_env(self, monkeypatch):
        """OTEL_ENABLED=false sets NoOpTracerProvider and is_enabled=False (SC-007)."""
        monkeypatch.setenv("OTEL_ENABLED", "false")
        tel.init_telemetry()
        assert tel.is_enabled() is False
        provider = trace.get_tracer_provider()
        assert isinstance(provider, trace.NoOpTracerProvider)

    def test_disabled_case_insensitive(self, monkeypatch):
        """OTEL_ENABLED=False (mixed case) also disables telemetry."""
        monkeypatch.setenv("OTEL_ENABLED", "False")
        tel.init_telemetry()
        assert tel.is_enabled() is False

    def test_idempotent(self, monkeypatch):
        """Second call to init_telemetry() is a no-op."""
        monkeypatch.delenv("OTEL_ENABLED", raising=False)
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("K_SERVICE", raising=False)
        tel.init_telemetry()
        assert tel.is_enabled() is True
        provider_first = trace.get_tracer_provider()
        # Second call should not change anything
        tel.init_telemetry()
        assert tel.is_enabled() is True
        provider_second = trace.get_tracer_provider()
        assert provider_first is provider_second

    def test_console_exporter_when_no_otlp_endpoint(self, monkeypatch):
        """Without OTLP endpoint, configures ConsoleSpanExporter (FR-603)."""
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("K_SERVICE", raising=False)
        tel.init_telemetry()
        provider = trace.get_tracer_provider()
        assert isinstance(provider, TracerProvider)
        # Check span processors contain ConsoleSpanExporter
        processors = provider._active_span_processor._span_processors
        assert len(processors) >= 1
        exporter = processors[0].span_exporter
        assert isinstance(exporter, ConsoleSpanExporter)

    def test_otlp_exporter_when_endpoint_set(self, monkeypatch):
        """With OTLP endpoint, configures OTLPSpanExporter (SC-004)."""
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
        monkeypatch.delenv("K_SERVICE", raising=False)
        tel.init_telemetry()
        provider = trace.get_tracer_provider()
        assert isinstance(provider, TracerProvider)
        processors = provider._active_span_processor._span_processors
        # In dev mode with OTLP: should have BatchSpanProcessor(OTLP) + SimpleSpanProcessor(Console)
        assert len(processors) == 2
        assert isinstance(processors[0].span_exporter, OTLPSpanExporter)
        assert isinstance(processors[1], SimpleSpanProcessor)
        assert isinstance(processors[1].span_exporter, ConsoleSpanExporter)

    def test_production_otlp_no_console(self, monkeypatch):
        """In production with OTLP endpoint, only OTLP exporter (no console) (FR-604)."""
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")
        monkeypatch.setenv("K_SERVICE", "newsletter-agent")
        tel.init_telemetry()
        provider = trace.get_tracer_provider()
        processors = provider._active_span_processor._span_processors
        assert len(processors) == 1
        assert isinstance(processors[0].span_exporter, OTLPSpanExporter)

    def test_otlp_with_headers(self, monkeypatch):
        """OTLP exporter passes parsed headers from OTEL_EXPORTER_OTLP_HEADERS."""
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "Authorization=Bearer token,X-Custom=value")
        monkeypatch.delenv("K_SERVICE", raising=False)
        tel.init_telemetry()
        assert tel.is_enabled() is True

    def test_resource_attributes_development(self, monkeypatch):
        """Resource has correct attributes in development mode."""
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("K_SERVICE", raising=False)
        monkeypatch.setenv("OTEL_SERVICE_NAME", "test-service")
        tel.init_telemetry()
        provider = trace.get_tracer_provider()
        attrs = dict(provider.resource.attributes)
        assert attrs["service.name"] == "test-service"
        assert attrs["service.version"] == "0.1.0"
        assert attrs["deployment.environment"] == "development"

    def test_resource_attributes_production(self, monkeypatch):
        """deployment.environment is 'production' when K_SERVICE is set."""
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.setenv("K_SERVICE", "my-cloud-run-service")
        tel.init_telemetry()
        provider = trace.get_tracer_provider()
        attrs = dict(provider.resource.attributes)
        assert attrs["deployment.environment"] == "production"

    def test_default_service_name(self, monkeypatch):
        """Default service name is 'newsletter-agent'."""
        monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("K_SERVICE", raising=False)
        tel.init_telemetry()
        provider = trace.get_tracer_provider()
        attrs = dict(provider.resource.attributes)
        assert attrs["service.name"] == "newsletter-agent"

    def test_import_error_logs_warning(self, monkeypatch, caplog):
        """If OTel SDK import fails, logs WARNING and is_enabled=False."""
        monkeypatch.delenv("OTEL_ENABLED", raising=False)
        with patch.dict("sys.modules", {"opentelemetry": None, "opentelemetry.trace": None}):
            # Need to force re-import failure
            with patch("newsletter_agent.telemetry.init_telemetry.__module__", tel.__name__):
                pass
        # Simulate ImportError by patching the import inside init_telemetry
        original_init = tel.init_telemetry.__code__
        with caplog.at_level(logging.WARNING):
            # Monkey-patch the import to raise ImportError
            import builtins
            real_import = builtins.__import__

            def mock_import(name, *args, **kwargs):
                if name == "opentelemetry" or name.startswith("opentelemetry."):
                    raise ImportError("mocked OTel unavailable")
                return real_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                tel.init_telemetry()

        assert tel.is_enabled() is False
        assert "OpenTelemetry SDK not available" in caplog.text

    def test_general_exception_logs_warning(self, monkeypatch, caplog):
        """On any other exception during init, logs WARNING and is_enabled=False."""
        monkeypatch.delenv("OTEL_ENABLED", raising=False)
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("K_SERVICE", raising=False)
        # Force an exception by making Resource.create raise
        with caplog.at_level(logging.WARNING):
            with patch("opentelemetry.sdk.resources.Resource.create", side_effect=RuntimeError("boom")):
                tel.init_telemetry()
        assert tel.is_enabled() is False
        assert "Failed to initialize OpenTelemetry" in caplog.text


class TestShutdownTelemetry:

    def test_shutdown_after_init(self, monkeypatch):
        """shutdown_telemetry() does not raise after successful init."""
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("K_SERVICE", raising=False)
        tel.init_telemetry()
        tel.shutdown_telemetry()  # Should not raise

    def test_shutdown_when_not_initialized(self):
        """shutdown_telemetry() does not raise when not initialized."""
        tel.shutdown_telemetry()  # Should not raise

    def test_shutdown_uses_force_flush_timeout_and_no_arg_shutdown(self):
        """shutdown_telemetry() uses a timed force_flush and SDK-compatible shutdown call."""

        class _ProviderWithUntimedShutdown:
            def __init__(self):
                self.force_flush_calls = []
                self.shutdown_calls = 0

            def force_flush(self, timeout_millis=30000):
                self.force_flush_calls.append(timeout_millis)
                return True

            def shutdown(self):
                self.shutdown_calls += 1

        provider = _ProviderWithUntimedShutdown()

        with patch("opentelemetry.trace.get_tracer_provider", return_value=provider):
            tel.shutdown_telemetry()

        assert provider.force_flush_calls == [5000]
        assert provider.shutdown_calls == 1

    def test_shutdown_on_exception(self, caplog):
        """shutdown_telemetry() logs warning but does not raise on error."""
        with caplog.at_level(logging.WARNING):
            with patch("opentelemetry.trace.get_tracer_provider") as mock_prov:
                mock_prov.return_value.shutdown.side_effect = RuntimeError("timeout")
                tel.shutdown_telemetry()
        assert "Telemetry shutdown error" in caplog.text

    def test_shutdown_falls_back_when_shutdown_supports_timeout(self):
        """shutdown_telemetry() still passes timeout_millis when the provider accepts it."""

        class _ProviderWithTimedShutdown:
            def __init__(self):
                self.force_flush_calls = []
                self.shutdown_calls = []

            def force_flush(self, timeout_millis=30000):
                self.force_flush_calls.append(timeout_millis)
                return True

            def shutdown(self, timeout_millis=30000):
                self.shutdown_calls.append(timeout_millis)

        provider = _ProviderWithTimedShutdown()

        with patch("opentelemetry.trace.get_tracer_provider", return_value=provider):
            tel.shutdown_telemetry()

        assert provider.force_flush_calls == [5000]
        assert provider.shutdown_calls == [5000]


class TestGetTracer:

    def test_returns_tracer_after_init(self, monkeypatch):
        """get_tracer() returns a valid tracer after initialization."""
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("K_SERVICE", raising=False)
        tel.init_telemetry()
        tracer = tel.get_tracer("test.module")
        assert tracer is not None
        # Should be able to start a span
        with tracer.start_as_current_span("test-span") as span:
            assert span is not None

    def test_returns_noop_when_not_initialized(self):
        """get_tracer() returns NoOp tracer when not initialized."""
        tracer = tel.get_tracer("test.module")
        assert tracer is not None


class TestIsEnabled:

    def test_false_initially(self):
        """is_enabled() is False before init."""
        assert tel.is_enabled() is False

    def test_true_after_init(self, monkeypatch):
        """is_enabled() is True after successful init."""
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("K_SERVICE", raising=False)
        tel.init_telemetry()
        assert tel.is_enabled() is True

    def test_false_when_disabled(self, monkeypatch):
        """is_enabled() is False when OTEL_ENABLED=false."""
        monkeypatch.setenv("OTEL_ENABLED", "false")
        tel.init_telemetry()
        assert tel.is_enabled() is False


# ---------------------------------------------------------------------------
# T20-09: traced_generate() tests
# ---------------------------------------------------------------------------

def _setup_otel_with_memory_exporter():
    """Set up a TracerProvider with InMemorySpanExporter and return the exporter."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    tel._initialized = True
    return exporter


def _mock_genai_response(
    prompt_tokens=1000,
    candidates_tokens=500,
    thoughts_tokens=200,
    total_tokens=1700,
):
    """Create a mock genai response with usage_metadata."""
    response = MagicMock()
    response.usage_metadata.prompt_token_count = prompt_tokens
    response.usage_metadata.candidates_token_count = candidates_tokens
    response.usage_metadata.thoughts_token_count = thoughts_tokens
    response.usage_metadata.total_token_count = total_tokens
    response.text = "Generated text"
    return response


class TestTracedGenerate:

    _GENAI_CLIENT = "google.genai.Client"

    @pytest.fixture(autouse=True)
    def _setup_cost_tracker(self):
        """Initialize cost tracker for each test."""
        init_cost_tracker(
            {
                "gemini-2.5-pro": ModelPricing(input_per_million=1.25, output_per_million=10.0),
                "gemini-2.5-flash": ModelPricing(input_per_million=0.15, output_per_million=0.60),
            },
            cost_budget_usd=100.0,
        )
        yield
        reset_cost_tracker()

    @pytest.mark.asyncio
    async def test_creates_span_with_correct_name(self, monkeypatch):
        """Span named 'llm.generate:{model}' with correct attributes."""
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("K_SERVICE", raising=False)
        exporter = _setup_otel_with_memory_exporter()

        mock_response = _mock_genai_response()
        with patch(self._GENAI_CLIENT) as mock_cls:
            mock_cls.return_value.aio.models.generate_content = AsyncMock(
                return_value=mock_response
            )
            result = await tel.traced_generate(
                model="gemini-2.5-pro",
                contents="test prompt",
                agent_name="PerTopicSynthesizer",
                phase="synthesis",
                topic_name="AI News",
                topic_index=0,
            )

        assert result is mock_response
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "llm.generate:gemini-2.5-pro"

    @pytest.mark.asyncio
    async def test_sets_span_attributes(self, monkeypatch):
        """Span has gen_ai.*, newsletter.* attributes set correctly."""
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("K_SERVICE", raising=False)
        exporter = _setup_otel_with_memory_exporter()

        mock_response = _mock_genai_response()
        with patch(self._GENAI_CLIENT) as mock_cls:
            mock_cls.return_value.aio.models.generate_content = AsyncMock(
                return_value=mock_response
            )
            await tel.traced_generate(
                model="gemini-2.5-pro",
                contents="test",
                agent_name="PerTopicSynthesizer",
                phase="synthesis",
                topic_name="AI News",
                topic_index=0,
            )

        spans = exporter.get_finished_spans()
        attrs = dict(spans[0].attributes)
        assert attrs["gen_ai.system"] == "google_genai"
        assert attrs["gen_ai.request.model"] == "gemini-2.5-pro"
        assert attrs["gen_ai.usage.input_tokens"] == 1000
        assert attrs["gen_ai.usage.output_tokens"] == 500
        assert attrs["gen_ai.usage.thinking_tokens"] == 200
        assert attrs["gen_ai.usage.total_tokens"] == 1700
        assert attrs["newsletter.agent.name"] == "PerTopicSynthesizer"
        assert attrs["newsletter.phase"] == "synthesis"
        assert attrs["newsletter.topic.name"] == "AI News"
        assert attrs["newsletter.topic.index"] == 0

    @pytest.mark.asyncio
    async def test_sets_cost_attributes(self, monkeypatch):
        """Span has newsletter.cost.* attributes from CostTracker."""
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("K_SERVICE", raising=False)
        exporter = _setup_otel_with_memory_exporter()

        mock_response = _mock_genai_response(
            prompt_tokens=10000, candidates_tokens=2000, thoughts_tokens=500
        )
        with patch(self._GENAI_CLIENT) as mock_cls:
            mock_cls.return_value.aio.models.generate_content = AsyncMock(
                return_value=mock_response
            )
            await tel.traced_generate(
                model="gemini-2.5-pro",
                contents="test",
                agent_name="test",
                phase="synthesis",
            )

        spans = exporter.get_finished_spans()
        attrs = dict(spans[0].attributes)
        assert attrs["newsletter.cost.input_usd"] == pytest.approx(0.0125)
        assert attrs["newsletter.cost.output_usd"] == pytest.approx(0.025)
        assert attrs["newsletter.cost.total_usd"] == pytest.approx(0.0375)

    @pytest.mark.asyncio
    async def test_records_cost_in_tracker(self, monkeypatch):
        """traced_generate records the call in CostTracker."""
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("K_SERVICE", raising=False)
        _setup_otel_with_memory_exporter()

        mock_response = _mock_genai_response()
        with patch(self._GENAI_CLIENT) as mock_cls:
            mock_cls.return_value.aio.models.generate_content = AsyncMock(
                return_value=mock_response
            )
            await tel.traced_generate(
                model="gemini-2.5-pro",
                contents="test",
                agent_name="PerTopicSynthesizer",
                phase="synthesis",
                topic_name="AI News",
                topic_index=0,
            )

        tracker = get_cost_tracker()
        summary = tracker.get_summary()
        assert summary.call_count == 1
        assert summary.total_input_tokens == 1000
        assert summary.total_output_tokens == 500
        assert summary.total_thinking_tokens == 200

    @pytest.mark.asyncio
    async def test_missing_usage_metadata(self, monkeypatch, caplog):
        """FR-303: usage_metadata is None -> tokens default to 0, WARNING logged."""
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("K_SERVICE", raising=False)
        exporter = _setup_otel_with_memory_exporter()

        mock_response = MagicMock()
        mock_response.usage_metadata = None
        mock_response.text = "ok"

        with caplog.at_level(logging.WARNING):
            with patch(self._GENAI_CLIENT) as mock_cls:
                mock_cls.return_value.aio.models.generate_content = AsyncMock(
                    return_value=mock_response
                )
                await tel.traced_generate(
                    model="gemini-2.5-pro",
                    contents="test",
                    agent_name="test",
                    phase="synthesis",
                )

        assert "usage_metadata missing" in caplog.text
        spans = exporter.get_finished_spans()
        attrs = dict(spans[0].attributes)
        assert attrs["gen_ai.usage.input_tokens"] == 0
        assert attrs["gen_ai.usage.output_tokens"] == 0
        assert attrs["gen_ai.usage.thinking_tokens"] == 0

    @pytest.mark.asyncio
    async def test_individual_missing_fields_default_to_zero(self, monkeypatch):
        """Individual None usage fields default to 0."""
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("K_SERVICE", raising=False)
        exporter = _setup_otel_with_memory_exporter()

        mock_response = MagicMock()
        mock_response.usage_metadata.prompt_token_count = 500
        mock_response.usage_metadata.candidates_token_count = None
        mock_response.usage_metadata.thoughts_token_count = None
        mock_response.text = "ok"

        with patch(self._GENAI_CLIENT) as mock_cls:
            mock_cls.return_value.aio.models.generate_content = AsyncMock(
                return_value=mock_response
            )
            await tel.traced_generate(
                model="gemini-2.5-pro",
                contents="test",
                agent_name="test",
                phase="synthesis",
            )

        spans = exporter.get_finished_spans()
        attrs = dict(spans[0].attributes)
        assert attrs["gen_ai.usage.input_tokens"] == 500
        assert attrs["gen_ai.usage.output_tokens"] == 0
        assert attrs["gen_ai.usage.thinking_tokens"] == 0

    @pytest.mark.asyncio
    async def test_api_exception_sets_error_and_reraises(self, monkeypatch):
        """On API exception: span status = ERROR, exception recorded, re-raised."""
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("K_SERVICE", raising=False)
        exporter = _setup_otel_with_memory_exporter()

        with patch(self._GENAI_CLIENT) as mock_cls:
            mock_cls.return_value.aio.models.generate_content = AsyncMock(
                side_effect=RuntimeError("API timeout")
            )
            with pytest.raises(RuntimeError, match="API timeout"):
                await tel.traced_generate(
                    model="gemini-2.5-pro",
                    contents="test",
                    agent_name="test",
                    phase="synthesis",
                )

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        from opentelemetry.trace import StatusCode
        assert spans[0].status.status_code == StatusCode.ERROR
        events = spans[0].events
        assert any("API timeout" in str(e.attributes) for e in events)

    @pytest.mark.asyncio
    async def test_disabled_calls_llm_without_span(self, monkeypatch):
        """When is_enabled() == False: calls LLM directly, no span."""
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("K_SERVICE", raising=False)
        tel._initialized = False

        mock_response = _mock_genai_response()
        with patch(self._GENAI_CLIENT) as mock_cls:
            mock_cls.return_value.aio.models.generate_content = AsyncMock(
                return_value=mock_response
            )
            result = await tel.traced_generate(
                model="gemini-2.5-pro",
                contents="test",
                agent_name="test",
                phase="synthesis",
            )

        assert result is mock_response
        mock_cls.return_value.aio.models.generate_content.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_optional_topic_attributes_omitted_when_none(self, monkeypatch):
        """topic_name and topic_index not set on span when None."""
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("K_SERVICE", raising=False)
        exporter = _setup_otel_with_memory_exporter()

        mock_response = _mock_genai_response()
        with patch(self._GENAI_CLIENT) as mock_cls:
            mock_cls.return_value.aio.models.generate_content = AsyncMock(
                return_value=mock_response
            )
            await tel.traced_generate(
                model="gemini-2.5-pro",
                contents="test",
                agent_name="test",
                phase="synthesis",
                topic_name=None,
                topic_index=None,
            )

        spans = exporter.get_finished_spans()
        attrs = dict(spans[0].attributes)
        assert "newsletter.topic.name" not in attrs
        assert "newsletter.topic.index" not in attrs

    @pytest.mark.asyncio
    async def test_returns_response_unchanged(self, monkeypatch):
        """Returns the original GenerateContentResponse unchanged."""
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("K_SERVICE", raising=False)
        _setup_otel_with_memory_exporter()

        mock_response = _mock_genai_response()
        mock_response.text = "Original response text"
        with patch(self._GENAI_CLIENT) as mock_cls:
            mock_cls.return_value.aio.models.generate_content = AsyncMock(
                return_value=mock_response
            )
            result = await tel.traced_generate(
                model="gemini-2.5-pro",
                contents="test",
                agent_name="test",
                phase="synthesis",
            )

        assert result.text == "Original response text"

    @pytest.mark.asyncio
    async def test_pricing_missing_attribute_for_unknown_model(self, monkeypatch):
        """FR-404: Sets newsletter.cost.pricing_missing=True when model not in pricing."""
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("K_SERVICE", raising=False)
        exporter = _setup_otel_with_memory_exporter()

        mock_response = _mock_genai_response()
        with patch(self._GENAI_CLIENT) as mock_cls:
            mock_cls.return_value.aio.models.generate_content = AsyncMock(
                return_value=mock_response
            )
            await tel.traced_generate(
                model="unknown-model-xyz",
                contents="test",
                agent_name="test",
                phase="synthesis",
            )

        spans = exporter.get_finished_spans()
        attrs = dict(spans[0].attributes)
        assert attrs["newsletter.cost.pricing_missing"] is True
        # Cost should be zero for unknown model
        assert attrs["newsletter.cost.total_usd"] == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_pricing_missing_not_set_for_known_model(self, monkeypatch):
        """Known model should NOT have newsletter.cost.pricing_missing attribute."""
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("K_SERVICE", raising=False)
        exporter = _setup_otel_with_memory_exporter()

        mock_response = _mock_genai_response()
        with patch(self._GENAI_CLIENT) as mock_cls:
            mock_cls.return_value.aio.models.generate_content = AsyncMock(
                return_value=mock_response
            )
            await tel.traced_generate(
                model="gemini-2.5-pro",
                contents="test",
                agent_name="test",
                phase="synthesis",
            )

        spans = exporter.get_finished_spans()
        attrs = dict(spans[0].attributes)
        assert "newsletter.cost.pricing_missing" not in attrs
