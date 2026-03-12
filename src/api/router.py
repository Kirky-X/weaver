"""Unified API router."""

from __future__ import annotations

from fastapi import APIRouter

from api.endpoints import (
    sources,
    pipeline,
    articles,
    graph,
    admin,
    metrics,
)

# Create main API router
api_router = APIRouter(prefix="/api/v1")

# Include all endpoint routers
api_router.include_router(sources.router)
api_router.include_router(pipeline.router)
api_router.include_router(articles.router)
api_router.include_router(graph.router)
api_router.include_router(admin.router)
api_router.include_router(metrics.router)
