"""OpenTelemetry tracing configuration."""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def configure_tracing(service_name: str = "weaver", endpoint: str | None = None) -> None:
    """Configure OpenTelemetry tracing with OTLP exporter.

    Args:
        service_name: The service name for tracing resource.
        endpoint: OTLP collector endpoint (e.g. http://localhost:4317).
                  If None, defaults to http://localhost:4317.
    """
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    # Use OTLP exporter with configurable endpoint
    otlp_endpoint = endpoint or "http://localhost:4317"
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))

    trace.set_tracer_provider(provider)


def get_tracer(name: str = "weaver") -> trace.Tracer:
    """Get an OpenTelemetry tracer instance.

    Args:
        name: Tracer scope name.

    Returns:
        An OpenTelemetry Tracer.
    """
    return trace.get_tracer(name)
