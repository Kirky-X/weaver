# Copyright (c) 2026 KirkyX. All Rights Reserved
"""API endpoints module - FastAPI route handlers.

This module contains all API endpoint routers:
- articles: Article CRUD operations
- sources: Data source management
- pipeline: Pipeline control endpoints
- graph: Graph operations
- graph_metrics: Graph metrics endpoints
- graph_visualization: Graph visualization endpoints
- admin: Administrative endpoints
- metrics: Prometheus metrics endpoint

Example usage:
    from api.endpoints import articles, sources
    app.include_router(articles.router)
"""

from api.endpoints.admin import router as admin_router
from api.endpoints.communities import router as communities_router
from api.endpoints.content.articles import router as articles_router
from api.endpoints.content.pipeline import router as pipeline_router
from api.endpoints.content.search import router as search_router
from api.endpoints.content.sources import router as sources_router
from api.endpoints.graph import router as graph_router
from api.endpoints.graph.graph_metrics import router as graph_metrics_router
from api.endpoints.graph.graph_visualization import router as graph_visualization_router

__all__ = [
    "admin_router",
    "articles_router",
    "communities_router",
    "graph_metrics_router",
    "graph_router",
    "graph_visualization_router",
    "pipeline_router",
    "search_router",
    "sources_router",
]
