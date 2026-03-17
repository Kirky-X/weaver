"""OpenTelemetry tracing configuration."""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter


def configure_tracing(service_name: str = "weaver") -> None:
    """Configure OpenTelemetry tracing with a console exporter.

    In production, replace ConsoleSpanExporter with an OTLP exporter
    pointing to your collector (e.g. Jaeger, Tempo).

    Args:
        service_name: The service name for tracing resource.
    """
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)


def get_tracer(name: str = "weaver") -> trace.Tracer:
    """Get an OpenTelemetry tracer instance.

    Args:
        name: Tracer scope name.

    Returns:
        An OpenTelemetry Tracer.
    """
    return trace.get_tracer(name)
