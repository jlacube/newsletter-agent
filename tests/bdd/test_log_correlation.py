"""BDD tests: Log-Trace Correlation.

Spec refs: US-04, FR-701, FR-704, SC-005, Section 11.2.

Feature: Log-Trace Correlation
  Scenario: Log lines include trace context
  Scenario: Disabled telemetry produces zero trace IDs
"""

import io
import logging
import re

import pytest
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider

from newsletter_agent.logging_config import TraceContextFilter


@pytest.fixture()
def tracer_provider():
    resource = Resource.create({"service.name": "test"})
    provider = TracerProvider(resource=resource)

    trace._TRACER_PROVIDER = None
    trace._TRACER_PROVIDER_SET_ONCE._done = False
    trace.set_tracer_provider(provider)

    yield provider

    provider.shutdown()
    trace._TRACER_PROVIDER = None
    trace._TRACER_PROVIDER_SET_ONCE._done = False


def _capture_log_line(logger_name: str, message: str) -> str:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        logging.Formatter(
            "%(levelname)s %(name)s [trace=%(trace_id)s span=%(span_id)s] %(message)s"
        )
    )
    handler.addFilter(TraceContextFilter())

    logger = logging.getLogger(logger_name)
    original_handlers = list(logger.handlers)
    original_filters = list(logger.filters)
    original_level = logger.level
    original_propagate = logger.propagate

    logger.handlers = [handler]
    logger.filters = []
    logger.setLevel(logging.INFO)
    logger.propagate = False

    try:
        logger.info(message)
    finally:
        handler.flush()
        logger.handlers = original_handlers
        logger.filters = original_filters
        logger.setLevel(original_level)
        logger.propagate = original_propagate
        handler.close()

    return stream.getvalue().strip()


class TestLogTraceCorrelationScenarios:
    """Feature: Log-Trace Correlation."""

    def test_log_lines_include_trace_context(self, tracer_provider):
        """Scenario: Log lines include trace context.

        Given OTEL_ENABLED=true and a pipeline is running
        When a log message is emitted from the newsletter_agent namespace
        Then the log line contains a 32-character hex trace_id
            matching the root span
        """
        tracer = trace.get_tracer("test")
        with tracer.start_as_current_span("TestRootSpan") as span:
            expected_trace_id = format(
                span.get_span_context().trace_id, "032x"
            )
            expected_span_id = format(
                span.get_span_context().span_id, "016x"
            )
            log_line = _capture_log_line(
                "newsletter_agent.test_correlation",
                "Test log message",
            )

        match = re.search(
            r"\[trace=([0-9a-f]{32}) span=([0-9a-f]{16})\]",
            log_line,
        )

        assert "INFO newsletter_agent.test_correlation" in log_line
        assert "Test log message" in log_line
        assert match is not None
        assert match.group(1) == expected_trace_id
        assert match.group(2) == expected_span_id

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
            log_line = _capture_log_line(
                "newsletter_agent.test_correlation",
                "Test disabled message",
            )

            assert "trace=00000000000000000000000000000000" in log_line
            assert "span=0000000000000000" in log_line
            assert log_line.endswith("Test disabled message")
        finally:
            trace._TRACER_PROVIDER = None
            trace._TRACER_PROVIDER_SET_ONCE._done = False
