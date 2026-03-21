"""Unit tests for TraceContextFilter and log format updates.

Spec refs: FR-701, FR-702, FR-703, FR-704, Section 11.1 (test_logging_trace.py).
"""

import json
import logging
from unittest.mock import patch

import pytest
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import newsletter_agent.logging_config as lc
from newsletter_agent.logging_config import (
    TraceContextFilter,
    _CloudJsonFormatter,
    setup_logging,
)


@pytest.fixture(autouse=True)
def _reset_logging():
    """Reset logging state before each test."""
    lc._configured = False
    logger = logging.getLogger("newsletter_agent")
    logger.handlers.clear()
    logger.filters.clear()
    logger.setLevel(logging.NOTSET)
    yield
    lc._configured = False
    logger = logging.getLogger("newsletter_agent")
    logger.handlers.clear()
    logger.filters.clear()
    logger.setLevel(logging.NOTSET)


@pytest.fixture()
def otel_provider():
    """Set up a real TracerProvider for testing trace context."""
    exporter = InMemorySpanExporter()
    resource = Resource.create({"service.name": "test"})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    # Reset global state so test provider can be set
    trace._TRACER_PROVIDER = None
    trace._TRACER_PROVIDER_SET_ONCE._done = False
    trace.set_tracer_provider(provider)

    yield provider

    provider.shutdown()
    trace._TRACER_PROVIDER = None
    trace._TRACER_PROVIDER_SET_ONCE._done = False


def _make_record(msg="Test message"):
    return logging.LogRecord(
        name="newsletter_agent.test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg=msg,
        args=None,
        exc_info=None,
    )


class TestTraceContextFilter:
    """FR-701: filter injects trace_id/span_id from active span."""

    def test_sets_ids_from_active_span(self, otel_provider):
        tracer = trace.get_tracer("test")
        f = TraceContextFilter()
        with tracer.start_as_current_span("test-span") as span:
            record = _make_record()
            result = f.filter(record)
            assert result is True
            ctx = span.get_span_context()
            assert record.trace_id == format(ctx.trace_id, "032x")
            assert record.span_id == format(ctx.span_id, "016x")
            assert len(record.trace_id) == 32
            assert len(record.span_id) == 16

    def test_sets_zero_ids_when_no_span(self):
        f = TraceContextFilter()
        record = _make_record()
        result = f.filter(record)
        assert result is True
        assert record.trace_id == "0" * 32
        assert record.span_id == "0" * 16

    def test_sets_zero_ids_on_import_error(self):
        """FR-704: backwards-compat when OTel not importable."""
        f = TraceContextFilter()
        record = _make_record()
        with patch.dict("sys.modules", {"opentelemetry": None, "opentelemetry.trace": None}):
            # Force re-import to fail
            import sys
            saved = sys.modules.get("opentelemetry")
            sys.modules["opentelemetry"] = None
            try:
                result = f.filter(record)
                assert result is True
                assert record.trace_id == "0" * 32
                assert record.span_id == "0" * 16
            finally:
                if saved is not None:
                    sys.modules["opentelemetry"] = saved

    def test_always_returns_true(self, otel_provider):
        f = TraceContextFilter()
        record = _make_record()
        assert f.filter(record) is True

    def test_trace_id_is_32_hex_chars(self, otel_provider):
        tracer = trace.get_tracer("test")
        f = TraceContextFilter()
        with tracer.start_as_current_span("hex-check"):
            record = _make_record()
            f.filter(record)
            assert len(record.trace_id) == 32
            int(record.trace_id, 16)  # should not raise


class TestTextLogFormat:
    """FR-702: text format includes trace/span IDs."""

    def test_text_format_contains_trace_span(self):
        setup_logging()
        logger = logging.getLogger("newsletter_agent")
        handler = logger.handlers[0]
        record = _make_record()
        # Apply filter
        for f in logger.filters:
            f.filter(record)
        formatted = handler.formatter.format(record)
        assert "[trace=" in formatted
        assert "span=" in formatted
        assert "0" * 32 in formatted  # zero trace ID (no active span)
        assert "0" * 16 in formatted  # zero span ID

    def test_text_format_with_active_span(self, otel_provider):
        setup_logging()
        logger = logging.getLogger("newsletter_agent")
        tracer = trace.get_tracer("test")
        with tracer.start_as_current_span("fmt-test") as span:
            record = _make_record()
            for f in logger.filters:
                f.filter(record)
            handler = logger.handlers[0]
            formatted = handler.formatter.format(record)
            ctx = span.get_span_context()
            expected_trace = format(ctx.trace_id, "032x")
            assert expected_trace in formatted

    def test_existing_format_fields_preserved(self):
        """Existing fields (timestamp, level, name, message) still present."""
        setup_logging()
        logger = logging.getLogger("newsletter_agent")
        record = _make_record("Hello world")
        for f in logger.filters:
            f.filter(record)
        formatted = logger.handlers[0].formatter.format(record)
        assert "INFO" in formatted
        assert "newsletter_agent.test" in formatted
        assert "Hello world" in formatted


class TestJsonLogFormat:
    """FR-703: JSON format includes trace_id and span_id fields."""

    def test_json_includes_trace_fields(self):
        formatter = _CloudJsonFormatter()
        record = _make_record()
        # Apply filter manually
        f = TraceContextFilter()
        f.filter(record)
        output = formatter.format(record)
        data = json.loads(output)
        assert "trace_id" in data
        assert "span_id" in data
        assert data["trace_id"] == "0" * 32
        assert data["span_id"] == "0" * 16

    def test_json_with_active_span(self, otel_provider):
        formatter = _CloudJsonFormatter()
        f = TraceContextFilter()
        tracer = trace.get_tracer("test")
        with tracer.start_as_current_span("json-test") as span:
            record = _make_record()
            f.filter(record)
            output = formatter.format(record)
            data = json.loads(output)
            ctx = span.get_span_context()
            assert data["trace_id"] == format(ctx.trace_id, "032x")
            assert data["span_id"] == format(ctx.span_id, "016x")

    def test_json_without_filter_uses_defaults(self):
        """If filter not applied, getattr defaults to zero IDs."""
        formatter = _CloudJsonFormatter()
        record = _make_record()
        output = formatter.format(record)
        data = json.loads(output)
        assert data["trace_id"] == "0" * 32
        assert data["span_id"] == "0" * 16


class TestOtelDisabledLogs:
    """FR-704: when OTEL_ENABLED=false, filter outputs zero IDs."""

    def test_zero_ids_when_otel_disabled(self, monkeypatch):
        monkeypatch.setenv("OTEL_ENABLED", "false")
        f = TraceContextFilter()
        record = _make_record()
        f.filter(record)
        assert record.trace_id == "0" * 32
        assert record.span_id == "0" * 16
