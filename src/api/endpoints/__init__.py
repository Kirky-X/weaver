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
from api.endpoints.articles import router as articles_router
from api.endpoints.graph import router as graph_router
from api.endpoints.graph_metrics import router as graph_metrics_router
from api.endpoints.graph_visualization import router as graph_visualization_router
from api.endpoints.metrics import router as metrics_router
from api.endpoints.pipeline import router as pipeline_router
from api.endpoints.sources import router as sources_router

__all__ = [
    "admin_router",
    "articles_router",
    "graph_metrics_router",
    "graph_router",
    "graph_visualization_router",
    "metrics_router",
    "pipeline_router",
    "sources_router",
]
