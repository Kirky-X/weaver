# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""OpenTelemetry tracing configuration."""

from __future__ import annotations

from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from core.observability import get_logger

log = get_logger(__name__)


def configure_tracing(
    service_name: str = "weaver",
    endpoint: str | None = None,
    console_export: bool = False,
) -> None:
    """Configure OpenTelemetry tracing with OTLP exporter.

    Args:
        service_name: The service name for tracing resource.
        endpoint: OTLP collector endpoint (e.g. http://localhost:4317).
                  If None or empty, tracing export is disabled.
        console_export: If True, also export traces to console for debugging.
    """
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    # Use OTLP exporter with configurable endpoint
    otlp_endpoint = endpoint or ""
    if otlp_endpoint:  # Only add if endpoint is provided and non-empty
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


def instrument_dependencies(
    engine: Any | None = None,
    redis_client: Any | None = None,
) -> None:
    """Register OTel auto-instrumentation for SQLAlchemy, Redis, and httpx.

    Must be called after ``configure_tracing`` so the tracer provider is set.
    Each instrumentor is wrapped in a try/except so a missing optional
    dependency does not prevent the others from loading.

    Args:
        engine: SQLAlchemy engine instance to instrument. If ``None``,
                SQLAlchemy instrumentation is skipped.
        redis_client: Redis client instance to instrument. If ``None``,
                      Redis instrumentation is skipped.
    """
    # ── SQLAlchemy ──────────────────────────────────────────────
    if engine is not None:
        try:
            from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

            SQLAlchemyInstrumentor().instrument(engine=engine)
            log.info("otel_instrumentor_registered", instrumentor="sqlalchemy")
        except Exception as exc:
            log.warning(
                "otel_instrumentor_failed",
                instrumentor="sqlalchemy",
                error=str(exc),
                exc_type=type(exc).__name__,
            )

    # ── Redis ───────────────────────────────────────────────────
    if redis_client is not None:
        try:
            from opentelemetry.instrumentation.redis import RedisInstrumentor

            RedisInstrumentor().instrument()
            log.info("otel_instrumentor_registered", instrumentor="redis")
        except Exception as exc:
            log.warning(
                "otel_instrumentor_failed",
                instrumentor="redis",
                error=str(exc),
                exc_type=type(exc).__name__,
            )

    # ── httpx ───────────────────────────────────────────────────
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
        log.info("otel_instrumentor_registered", instrumentor="httpx")
    except Exception as exc:
        log.warning(
            "otel_instrumentor_failed",
            instrumentor="httpx",
            error=str(exc),
            exc_type=type(exc).__name__,
        )


def get_tracer(name: str = "weaver") -> trace.Tracer:
    """Get an OpenTelemetry tracer instance.

    Args:
        name: Tracer scope name.

    Returns:
        An OpenTelemetry Tracer.
    """
    return trace.get_tracer(name)
