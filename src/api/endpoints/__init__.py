# Copyright (c) 2026 KirkyX. All Rights Reserved
"""API endpoints module - FastAPI route handlers.

This module contains all API endpoint routers:
- articles: Article CRUD operations
- sources: Data source management
- pipeline: Pipeline control endpoints
- graph: Graph operations
- admin: Administrative endpoints
- monitoring: Monitoring and observation endpoints
"""

from api.endpoints.admin import router as admin_router
from api.endpoints.communities import router as communities_router
from api.endpoints.content.articles import router as articles_router
from api.endpoints.content.pipeline import router as pipeline_router
from api.endpoints.content.search import router as search_router
from api.endpoints.content.sources import router as sources_router
from api.endpoints.graph import router as graph_router, visualization_router
from api.endpoints.monitoring import (
    causal_router,
    communities_monitoring_router,
    graph_monitoring_router,
    llm_router,
    memory_router,
)

__all__ = [
    "admin_router",
    "articles_router",
    "causal_router",
    "communities_monitoring_router",
    "communities_router",
    "graph_monitoring_router",
    "graph_router",
    "llm_router",
    "memory_router",
    "pipeline_router",
    "search_router",
    "sources_router",
    "visualization_router",
]
