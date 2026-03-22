"""OpenTelemetry initialization and lifecycle management.

Provides init_telemetry(), shutdown_telemetry(), get_tracer(), and is_enabled()
for the newsletter agent pipeline. Designed to fail gracefully -- if OTel SDK
is not available or initialization fails, the pipeline continues without tracing.

Spec refs: FR-101 through FR-106, FR-602, FR-603, FR-604, Section 8.1.
"""

import logging
import os
import sys

logger = logging.getLogger(__name__)

_initialized: bool = False


class _NoOpSpan:
    def set_attribute(self, *args, **kwargs) -> None:
        return None

    def set_status(self, *args, **kwargs) -> None:
        return None

    def record_exception(self, *args, **kwargs) -> None:
        return None

    def add_event(self, *args, **kwargs) -> None:
        return None

    def end(self) -> None:
        return None


class _NoOpSpanContextManager:
    def __enter__(self) -> _NoOpSpan:
        return _NoOpSpan()

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _NoOpTracer:
    def start_span(self, name: str):
        return _NoOpSpan()

    def start_as_current_span(self, name: str):
        return _NoOpSpanContextManager()


_NOOP_TRACER = _NoOpTracer()


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
                    SimpleSpanProcessor(ConsoleSpanExporter(out=sys.__stdout__))
                )
        else:
            # No OTLP endpoint: console output only
            provider.add_span_processor(
                BatchSpanProcessor(ConsoleSpanExporter(out=sys.__stdout__))
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
            provider.shutdown(timeout_millis=5000)
    except Exception:
        logger.warning("Telemetry shutdown error", exc_info=True)


def get_tracer(name: str):
    """Return a tracer for the given module name.

    Returns a real tracer if telemetry is initialized, otherwise a NoOp tracer.
    """
    if not _initialized:
        return _NOOP_TRACER

    try:
        from opentelemetry import trace
    except ImportError:
        return _NOOP_TRACER

    return trace.get_tracer(name)


def is_enabled() -> bool:
    """Return True if telemetry was successfully initialized."""
    return _initialized


async def traced_generate(
    model,
    contents,
    config=None,
    *,
    agent_name: str,
    topic_name: str | None = None,
    topic_index: int | None = None,
    phase: str,
):
    """Wrap genai.Client().aio.models.generate_content() with OTel span and cost tracking.

    When telemetry is disabled, calls the LLM directly without instrumentation.

    Spec refs: FR-301, FR-303, FR-402, Section 4.3, 8.1.
    """
    from google import genai

    if not _initialized:
        client = genai.Client()
        return await client.aio.models.generate_content(
            model=model, contents=contents, config=config
        )

    from opentelemetry.trace import StatusCode

    from newsletter_agent.cost_tracker import get_cost_tracker

    tracer = get_tracer("newsletter_agent.telemetry")
    with tracer.start_as_current_span(f"llm.generate:{model}") as span:
        span.set_attribute("gen_ai.system", "google_genai")
        span.set_attribute("gen_ai.request.model", model)
        span.set_attribute("newsletter.agent.name", agent_name)
        span.set_attribute("newsletter.phase", phase)
        if topic_name is not None:
            span.set_attribute("newsletter.topic.name", topic_name)
        if topic_index is not None:
            span.set_attribute("newsletter.topic.index", topic_index)

        try:
            client = genai.Client()
            response = await client.aio.models.generate_content(
                model=model, contents=contents, config=config
            )

            # Extract token counts from usage_metadata
            usage = getattr(response, "usage_metadata", None)
            if usage is None:
                logger.warning("usage_metadata missing from LLM response")
                prompt_tokens = 0
                completion_tokens = 0
                thinking_tokens = 0
            else:
                prompt_tokens = getattr(usage, "prompt_token_count", 0) or 0
                completion_tokens = getattr(usage, "candidates_token_count", 0) or 0
                thinking_tokens = getattr(usage, "thoughts_token_count", 0) or 0

            total_tokens = prompt_tokens + completion_tokens + thinking_tokens

            span.set_attribute("gen_ai.usage.input_tokens", prompt_tokens)
            span.set_attribute("gen_ai.usage.output_tokens", completion_tokens)
            span.set_attribute("gen_ai.usage.thinking_tokens", thinking_tokens)
            span.set_attribute("gen_ai.usage.total_tokens", total_tokens)

            # Record cost
            tracker = get_cost_tracker()
            record = tracker.record_llm_call(
                model=model,
                agent_name=agent_name,
                phase=phase,
                topic_name=topic_name,
                topic_index=topic_index,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                thinking_tokens=thinking_tokens,
            )

            span.set_attribute("newsletter.cost.input_usd", record.input_cost_usd)
            span.set_attribute("newsletter.cost.output_usd", record.output_cost_usd)
            span.set_attribute("newsletter.cost.total_usd", record.total_cost_usd)

            if not tracker.has_pricing(model):
                span.set_attribute("newsletter.cost.pricing_missing", True)

            return response

        except Exception as e:
            span.set_status(StatusCode.ERROR, str(e))
            span.record_exception(e)
            raise
