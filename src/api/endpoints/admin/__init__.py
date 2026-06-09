"""Admin API endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import APIRouter


def __getattr__(name: str) -> APIRouter:
    """Lazy import routers to avoid circular dependencies."""
    if name == "router":
        from api.endpoints.admin.admin import router

        return router
    if name == "monitoring_router":
        from api.endpoints.admin.monitoring import router as monitoring_router

        return monitoring_router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["router"]
