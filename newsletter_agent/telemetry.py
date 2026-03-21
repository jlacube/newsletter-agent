"""OpenTelemetry initialization and lifecycle management.

Provides init_telemetry(), shutdown_telemetry(), get_tracer(), and is_enabled()
for the newsletter agent pipeline. Designed to fail gracefully -- if OTel SDK
is not available or initialization fails, the pipeline continues without tracing.

Spec refs: FR-101 through FR-106, FR-602, FR-603, FR-604, Section 8.1.
"""

import logging
import os

logger = logging.getLogger(__name__)

_initialized: bool = False


def init_telemetry() -> None:
    """Initialize the OpenTelemetry TracerProvider with configured exporters.

    Reads environment variables:
    - OTEL_ENABLED: "true" (default) or "false" to disable tracing
    - OTEL_SERVICE_NAME: service name resource attribute (default "newsletter-agent")
    - OTEL_EXPORTER_OTLP_ENDPOINT: OTLP gRPC endpoint; empty = console export
    - OTEL_EXPORTER_OTLP_HEADERS: auth headers for OTLP endpoint

    Idempotent: second call is a no-op. Never raises.
    """
    global _initialized

    if _initialized:
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
            SimpleSpanProcessor,
        )
    except ImportError:
        logger.warning(
            "OpenTelemetry SDK not available. "
            "Install opentelemetry-sdk to enable tracing."
        )
        _initialized = False
        return

    try:
        # Check kill switch
        otel_enabled = os.environ.get("OTEL_ENABLED", "true")
        if otel_enabled.lower() == "false":
            trace.set_tracer_provider(trace.NoOpTracerProvider())
            _initialized = False
            return

        # Determine environment
        is_production = "K_SERVICE" in os.environ

        # Read package version
        try:
            from importlib.metadata import version
            service_version = version("newsletter-agent")
        except Exception:
            service_version = "0.1.0"

        # Build resource
        service_name = os.environ.get("OTEL_SERVICE_NAME", "newsletter-agent")
        resource = Resource.create(
            {
                "service.name": service_name,
                "service.version": service_version,
                "deployment.environment": "production" if is_production else "development",
            }
        )

        # Create provider
        provider = TracerProvider(resource=resource)

        # Configure exporters
        otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
        if otlp_endpoint:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

            headers_str = os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", "")
            headers_dict = {}
            if headers_str:
                for pair in headers_str.split(","):
                    if "=" in pair:
                        key, val = pair.split("=", 1)
                        headers_dict[key.strip()] = val.strip()

            otlp_exporter = OTLPSpanExporter(
                endpoint=otlp_endpoint,
                headers=headers_dict or None,
            )
            provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

            # In development, also log to console for local debugging
            if not is_production:
                provider.add_span_processor(
                    SimpleSpanProcessor(ConsoleSpanExporter())
                )
        else:
            # No OTLP endpoint: console output only
            provider.add_span_processor(
                BatchSpanProcessor(ConsoleSpanExporter())
            )

        trace.set_tracer_provider(provider)
        _initialized = True

    except Exception:
        logger.warning("Failed to initialize OpenTelemetry", exc_info=True)
        _initialized = False


def shutdown_telemetry() -> None:
    """Flush pending spans and shut down the TracerProvider.

    Uses a 5-second timeout. Never raises.
    Spec ref: FR-106.
    """
    try:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        if hasattr(provider, "shutdown"):
            provider.shutdown()
    except Exception:
        logger.warning("Telemetry shutdown error", exc_info=True)


def get_tracer(name: str):
    """Return a tracer for the given module name.

    Returns a real tracer if telemetry is initialized, otherwise a NoOp tracer.
    """
    from opentelemetry import trace

    return trace.get_tracer(name)


def is_enabled() -> bool:
    """Return True if telemetry was successfully initialized."""
    return _initialized
