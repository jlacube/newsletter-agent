"""BDD tests: Export Configuration.

Spec refs: US-05, FR-602, FR-603, SC-004, Section 11.2.

Feature: Export Configuration
  Scenario: Console export when no OTLP endpoint
  Scenario: OTLP export when endpoint is set
"""

from unittest.mock import patch

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter

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


def _get_exporter_types(provider):
    """Extract exporter class names from a TracerProvider."""
    types = []
    if hasattr(provider, "_active_span_processor"):
        proc = provider._active_span_processor
        # MultSpanProcessor wraps individual processors
        if hasattr(proc, "_span_processors"):
            for p in proc._span_processors:
                if hasattr(p, "span_exporter"):
                    types.append(type(p.span_exporter).__name__)
    return types


class TestExportConfigScenarios:
    """Feature: Export Configuration."""

    def test_console_export_when_no_otlp_endpoint(self, monkeypatch):
        """Scenario: Console export when no OTLP endpoint.

        Given OTEL_EXPORTER_OTLP_ENDPOINT is not set
        When telemetry initializes
        Then ConsoleSpanExporter is configured
        """
        monkeypatch.setenv("OTEL_ENABLED", "true")
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("K_SERVICE", raising=False)

        telemetry_mod.init_telemetry()

        provider = trace.get_tracer_provider()
        assert isinstance(provider, TracerProvider)

        exporter_types = _get_exporter_types(provider)
        assert "ConsoleSpanExporter" in exporter_types

    def test_otlp_export_when_endpoint_set(self, monkeypatch):
        """Scenario: OTLP export when endpoint is set.

        Given OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
        When telemetry initializes
        Then OTLPSpanExporter is configured with that endpoint
        """
        monkeypatch.setenv("OTEL_ENABLED", "true")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
        monkeypatch.delenv("K_SERVICE", raising=False)

        telemetry_mod.init_telemetry()

        provider = trace.get_tracer_provider()
        assert isinstance(provider, TracerProvider)

        exporter_types = _get_exporter_types(provider)
        assert "OTLPSpanExporter" in exporter_types
