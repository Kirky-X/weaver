# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unified API router."""

from __future__ import annotations

from fastapi import APIRouter

from api.endpoints import (
    admin_router,
    articles_router,
    causal_router,
    communities_monitoring_router,
    communities_router,
    graph_monitoring_router,
    graph_router,
    llm_router,
    memory_router,
    pipeline_router,
    search_router,
    sources_router,
    visualization_router,
)

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(sources_router)
api_router.include_router(pipeline_router)
api_router.include_router(articles_router)
api_router.include_router(search_router)
api_router.include_router(graph_router)
api_router.include_router(visualization_router)
api_router.include_router(admin_router)
api_router.include_router(communities_router)

# Monitoring endpoints (read-only observation)
api_router.include_router(llm_router)
api_router.include_router(memory_router)
api_router.include_router(causal_router)
api_router.include_router(graph_monitoring_router)
api_router.include_router(communities_monitoring_router)
