"""BDD tests: Export Configuration.

Spec refs: US-05, FR-602, FR-603, SC-004, Section 11.2.

Feature: Export Configuration
  Scenario: Console export when no OTLP endpoint
  Scenario: OTLP export when endpoint is set
"""

import io
from unittest.mock import patch

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

import newsletter_agent.telemetry as telemetry_mod


@pytest.fixture(autouse=True)
def _reset_telemetry():
    """Reset telemetry module state before/after each test."""
    telemetry_mod._initialized = False
    trace._TRACER_PROVIDER = None
    trace._TRACER_PROVIDER_SET_ONCE._done = False
    yield
    telemetry_mod._initialized = False
    trace._TRACER_PROVIDER = None
    trace._TRACER_PROVIDER_SET_ONCE._done = False


class TestExportConfigScenarios:
    """Feature: Export Configuration."""

    def test_console_export_when_no_otlp_endpoint(self, monkeypatch):
        """Scenario: Console export when no OTLP endpoint.

        Given OTEL_EXPORTER_OTLP_ENDPOINT is not set
        When telemetry initializes
        Then span output is written to stdout by the console exporter
        """
        monkeypatch.setenv("OTEL_ENABLED", "true")
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("K_SERVICE", raising=False)
        capture_stream = io.StringIO()
        monkeypatch.setattr(telemetry_mod.sys, "__stdout__", capture_stream)

        telemetry_mod.init_telemetry()

        provider = trace.get_tracer_provider()
        assert isinstance(provider, TracerProvider)

        tracer = telemetry_mod.get_tracer("test.export_config")
        with tracer.start_as_current_span("ConsoleExportSpan"):
            pass

        provider.force_flush()
        captured = capture_stream.getvalue()

        assert "ConsoleExportSpan" in captured
        assert '"name": "ConsoleExportSpan"' in captured

    def test_otlp_export_when_endpoint_set(self, monkeypatch):
        """Scenario: OTLP export when endpoint is set.

        Given OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
        When telemetry initializes
        Then OTLPSpanExporter is configured with that endpoint
        """
        monkeypatch.setenv("OTEL_ENABLED", "true")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
        monkeypatch.delenv("K_SERVICE", raising=False)

        with patch(
            "opentelemetry.exporter.otlp.proto.grpc.trace_exporter.OTLPSpanExporter"
        ) as mock_exporter:
            telemetry_mod.init_telemetry()

        provider = trace.get_tracer_provider()
        assert isinstance(provider, TracerProvider)

        mock_exporter.assert_called_once_with(
            endpoint="http://localhost:4317",
            headers=None,
        )
