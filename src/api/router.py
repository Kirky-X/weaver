# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unified API router."""

from __future__ import annotations

from fastapi import APIRouter

from api.endpoints import (
    admin,
    articles,
    communities,
    graph,
    graph_metrics,
    graph_visualization,
    metrics,
    pipeline,
    search,
    sources,
)

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(sources.router)
api_router.include_router(pipeline.router)
api_router.include_router(articles.router)
api_router.include_router(search.router)
api_router.include_router(graph.router)
api_router.include_router(graph_metrics.router)
api_router.include_router(graph_visualization.router)
api_router.include_router(admin.router)
api_router.include_router(metrics.router)
api_router.include_router(communities.router)
api_router.include_router(communities.graph_router)
