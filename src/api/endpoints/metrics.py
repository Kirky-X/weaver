# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Prometheus metrics endpoint."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from core.observability.metrics import MetricsCollector

router = APIRouter(tags=["metrics"])

# Export metrics instance for use in other modules
metrics = MetricsCollector()


@router.get("/metrics")
async def get_metrics() -> PlainTextResponse:
    """Prometheus metrics endpoint.

    Returns:
        Prometheus-formatted metrics.
    """
    return PlainTextResponse(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
