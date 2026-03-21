"""BDD tests: Log-Trace Correlation.

Spec refs: US-04, FR-701, FR-704, SC-005, Section 11.2.

Feature: Log-Trace Correlation
  Scenario: Log lines include trace context
  Scenario: Disabled telemetry produces zero trace IDs
"""

import logging
import re

import pytest
from opentelemetry import context, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from newsletter_agent.logging_config import TraceContextFilter


@pytest.fixture()
def otel_exporter():
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


class TestLogTraceCorrelationScenarios:
    """Feature: Log-Trace Correlation."""

    def test_log_lines_include_trace_context(self, otel_exporter):
        """Scenario: Log lines include trace context.

        Given OTEL_ENABLED=true and a pipeline is running
        When a log message is emitted from the newsletter_agent namespace
        Then the log line contains a 32-character hex trace_id
            matching the root span
        """
        trace_filter = TraceContextFilter()
        test_logger = logging.getLogger("newsletter_agent.test_correlation")
        test_logger.addFilter(trace_filter)
        handler = logging.StreamHandler()
        fmt = logging.Formatter(
            "%(message)s [trace=%(trace_id)s span=%(span_id)s]"
        )
        handler.setFormatter(fmt)
        test_logger.addHandler(handler)
        test_logger.setLevel(logging.DEBUG)

        try:
            tracer = trace.get_tracer("test")
            with tracer.start_as_current_span("TestRootSpan") as span:
                expected_trace_id = format(
                    span.get_span_context().trace_id, "032x"
                )
                expected_span_id = format(
                    span.get_span_context().span_id, "016x"
                )

                record = logging.LogRecord(
                    name="newsletter_agent.test",
                    level=logging.INFO,
                    pathname="",
                    lineno=0,
                    msg="Test log message",
                    args=(),
                    exc_info=None,
                )
                trace_filter.filter(record)

                assert record.trace_id == expected_trace_id
                assert record.span_id == expected_span_id
                assert len(record.trace_id) == 32
                assert re.match(r"^[0-9a-f]{32}$", record.trace_id)
        finally:
            test_logger.removeFilter(trace_filter)
            test_logger.removeHandler(handler)

    def test_disabled_telemetry_produces_zero_trace_ids(self):
        """Scenario: Disabled telemetry produces zero trace IDs.

        Given OTEL_ENABLED=false
        When a log message is emitted
        Then the log line contains trace=00000000000000000000000000000000
        """
        # Reset OTel to NoOp
        trace._TRACER_PROVIDER = None
        trace._TRACER_PROVIDER_SET_ONCE._done = False
        trace.set_tracer_provider(trace.NoOpTracerProvider())

        try:
            trace_filter = TraceContextFilter()
            record = logging.LogRecord(
                name="newsletter_agent.test",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg="Test disabled message",
                args=(),
                exc_info=None,
            )
            trace_filter.filter(record)

            assert record.trace_id == "0" * 32
            assert record.span_id == "0" * 16
        finally:
            trace._TRACER_PROVIDER = None
            trace._TRACER_PROVIDER_SET_ONCE._done = False
