"""Admin API endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import APIRouter


def __getattr__(name: str) -> APIRouter:
    """Lazy import routers to avoid circular dependencies."""
    if name == "router":
        # Composite router aggregating all admin sub-routers. Each sub-router
        # carries its own ``/admin`` prefix, so the composite itself has none
        # to avoid double-prefixing (``/admin/admin/...``).
        from fastapi import APIRouter

        from api.endpoints.admin.api_keys import router as api_keys_router
        from api.endpoints.admin.articles import router as articles_router
        from api.endpoints.admin.authorities import router as authorities_router
        from api.endpoints.admin.llm_monitoring import router as llm_monitoring_router
        from api.endpoints.admin.memory import router as memory_router
        from api.endpoints.admin.monitoring import router as monitoring_router

        composite = APIRouter(tags=["admin"])
        composite.include_router(authorities_router)
        composite.include_router(llm_monitoring_router)
        composite.include_router(articles_router)
        composite.include_router(memory_router)
        composite.include_router(api_keys_router)
        composite.include_router(monitoring_router)
        globals()["router"] = composite
        return composite
    if name == "authorities_router":
        from api.endpoints.admin.authorities import router as authorities_router

        return authorities_router
    if name == "llm_monitoring_router":
        from api.endpoints.admin.llm_monitoring import router as llm_monitoring_router

        return llm_monitoring_router
    if name == "articles_router":
        from api.endpoints.admin.articles import router as articles_router

        return articles_router
    if name == "memory_router":
        from api.endpoints.admin.memory import router as memory_router

        return memory_router
    if name == "api_keys_router":
        from api.endpoints.admin.api_keys import router as api_keys_router

        return api_keys_router
    if name == "monitoring_router":
        from api.endpoints.admin.monitoring import router as monitoring_router

        return monitoring_router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "api_keys_router",
    "articles_router",
    "authorities_router",
    "llm_monitoring_router",
    "memory_router",
    "monitoring_router",
    "router",
]
