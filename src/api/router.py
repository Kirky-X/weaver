# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unified API router."""

from __future__ import annotations

from fastapi import APIRouter

from api.endpoints import (
    admin_router,
    alerts_router,
    analytics_router,
    articles_router,
    briefings_router,
    causal_router,
    communities_monitoring_router,
    communities_router,
    graph_metrics_router,
    graph_monitoring_router,
    graph_router,
    health_router,
    llm_router,
    memory_router,
    pipeline_router,
    saga_router,
    search_router,
    sources_router,
    system_router,
    visualization_router,
)

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(sources_router)
api_router.include_router(pipeline_router)
api_router.include_router(articles_router)
api_router.include_router(search_router)
api_router.include_router(graph_router)
api_router.include_router(graph_metrics_router)
api_router.include_router(visualization_router)
api_router.include_router(admin_router)
api_router.include_router(communities_router)

# System endpoints (status, config)
api_router.include_router(system_router)

# Health endpoints (dependency checks)
api_router.include_router(health_router)

# Saga management endpoints
api_router.include_router(saga_router)

# Analytics endpoints
api_router.include_router(analytics_router)

# Briefings endpoints (T009 / R-briefing-004, R-briefing-005)
api_router.include_router(briefings_router)

# Monitoring endpoints (read-only observation)
api_router.include_router(alerts_router)
api_router.include_router(llm_router)
api_router.include_router(memory_router)
api_router.include_router(causal_router)
api_router.include_router(graph_monitoring_router)
api_router.include_router(communities_monitoring_router)
