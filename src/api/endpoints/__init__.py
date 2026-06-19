# Copyright (c) 2026 KirkyX. All Rights Reserved
"""API endpoints module - FastAPI route handlers.

This module contains all API endpoint routers:
- articles: Article CRUD operations
- sources: Data source management
- pipeline: Pipeline control endpoints
- graph: Graph operations
- admin: Administrative endpoints
- monitoring: Monitoring and observation endpoints

NOTE: Uses lazy imports to avoid circular dependencies with api.dependencies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import APIRouter


def __getattr__(name: str) -> APIRouter:
    """Lazy import routers to avoid circular dependencies."""
    router_map = {
        "admin_router": ("api.endpoints.admin", "router"),
        "alerts_router": ("api.endpoints.monitoring", "alerts_router"),
        "analytics_router": ("api.endpoints.analytics", "router"),
        "articles_router": ("api.endpoints.content.articles", "router"),
        "causal_router": ("api.endpoints.monitoring", "causal_router"),
        "communities_monitoring_router": (
            "api.endpoints.monitoring",
            "communities_monitoring_router",
        ),
        "communities_router": ("api.endpoints.communities", "router"),
        "graph_monitoring_router": ("api.endpoints.monitoring", "graph_monitoring_router"),
        "graph_router": ("api.endpoints.graph", "router"),
        "llm_router": ("api.endpoints.monitoring", "llm_router"),
        "memory_router": ("api.endpoints.monitoring", "memory_router"),
        "pipeline_router": ("api.endpoints.content.pipeline", "router"),
        "saga_router": ("api.endpoints.saga", "router"),
        "search_router": ("api.endpoints.content.search", "router"),
        "sources_router": ("api.endpoints.content.sources", "router"),
        "system_router": ("api.endpoints.system", "system_router"),
        "visualization_router": ("api.endpoints.graph", "visualization_router"),
    }
    if name in router_map:
        module_path, attr = router_map[name]
        import importlib

        module = importlib.import_module(module_path)
        return getattr(module, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "admin_router",
    "alerts_router",
    "analytics_router",
    "articles_router",
    "causal_router",
    "communities_monitoring_router",
    "communities_router",
    "graph_monitoring_router",
    "graph_router",
    "llm_router",
    "memory_router",
    "pipeline_router",
    "saga_router",
    "search_router",
    "sources_router",
    "system_router",
    "visualization_router",
]
