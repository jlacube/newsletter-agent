"""Unit tests for telemetry initialization, shutdown, get_tracer, and is_enabled.

Spec refs: FR-101 through FR-106, FR-602, FR-603, FR-604, SC-004, SC-007, Section 11.1.
"""

import logging
from unittest.mock import patch

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

import newsletter_agent.telemetry as tel


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

    def test_shutdown_on_exception(self, caplog):
        """shutdown_telemetry() logs warning but does not raise on error."""
        with caplog.at_level(logging.WARNING):
            with patch("opentelemetry.trace.get_tracer_provider") as mock_prov:
                mock_prov.return_value.shutdown.side_effect = RuntimeError("timeout")
                tel.shutdown_telemetry()
        assert "Telemetry shutdown error" in caplog.text


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
