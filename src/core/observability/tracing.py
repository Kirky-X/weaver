# Copyright (c) 2026 KirkyX. All Rights Reserved
"""OpenTelemetry tracing configuration."""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter


def configure_tracing(
    service_name: str = "weaver",
    endpoint: str | None = None,
    console_export: bool = False,
) -> None:
    """Configure OpenTelemetry tracing with OTLP exporter.

    Args:
        service_name: The service name for tracing resource.
        endpoint: OTLP collector endpoint (e.g. http://localhost:4317).
                  If None, defaults to http://localhost:4317.
        console_export: If True, also export traces to console for debugging.
    """
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    # Use OTLP exporter with configurable endpoint
    otlp_endpoint = endpoint or "http://localhost:4317"
    if otlp_endpoint:  # Only add if endpoint is provided
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))

    # Optional console exporter for debugging
    if console_export:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)


def instrument_fastapi(app) -> None:
    """Instrument FastAPI application for OpenTelemetry tracing.

    Args:
        app: The FastAPI application instance to instrument.
    """
    FastAPIInstrumentor.instrument_app(app)


def get_tracer(name: str = "weaver") -> trace.Tracer:
    """Get an OpenTelemetry tracer instance.

    Args:
        name: Tracer scope name.

    Returns:
        An OpenTelemetry Tracer.
    """
    return trace.get_tracer(name)
