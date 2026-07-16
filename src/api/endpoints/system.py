# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""System endpoints — health, status, config, and metrics.

These endpoints were previously inlined in ``src/main.py`` and are extracted
here to reduce ``create_app()`` responsibility.
"""

from __future__ import annotations

import tomllib

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from api.dependencies import (
    get_cache_type as get_cache_type_dep,
    get_graph_type as get_graph_type_dep,
    get_relational_type as get_relational_type_dep,
)
from api.endpoints.health import health_check
from api.middleware.auth import verify_admin_api_key, verify_api_key, verify_api_key_optional
from api.schemas.response import APIResponse, success_response
from core.observability import get_logger

log = get_logger(__name__)

# Router for endpoints under /api/v1 prefix (no additional prefix — paths are
# /api/v1/status and /api/v1/config when included in the top-level api_router)
system_router = APIRouter(tags=["system"])


@system_router.get("/status", response_model=APIResponse[dict])
async def system_status(
    _: str = Depends(verify_api_key),
    relational_type: str = Depends(get_relational_type_dep),
    graph_type: str = Depends(get_graph_type_dep),
    cache_type: str = Depends(get_cache_type_dep),
) -> APIResponse[dict]:
    """System status endpoint (requires authentication).

    Returns overall system status including database types and processing stats.
    """
    version = "unknown"
    try:
        with open("pyproject.toml", "rb") as f:
            pyproject = tomllib.load(f)
        version = pyproject.get("project", {}).get("version", "unknown")
    except OSError as exc:
        log.warning("read_version_failed", error=str(exc))

    return success_response(
        {
            "status": "running",
            "version": version,
            "database": {
                "relational": relational_type,
                "graph": graph_type,
                "cache": cache_type,
            },
        }
    )


@system_router.get("/config", response_model=APIResponse[dict])
async def system_config(
    _: str = Depends(verify_admin_api_key),
    relational_type: str = Depends(get_relational_type_dep),
    graph_type: str = Depends(get_graph_type_dep),
) -> APIResponse[dict]:
    """System configuration endpoint (requires admin authentication).

    Returns current configuration including available features.
    This endpoint contains sensitive information and requires admin API key.
    """
    from container import get_container

    try:
        container = get_container()
        llm_enabled = getattr(container, "_llm_client", None) is not None
        search_enabled = getattr(container, "_local_search_engine", None) is not None
        graph_available = container.graph_pool() is not None
    except RuntimeError:
        llm_enabled = False
        search_enabled = False
        graph_available = False

    return success_response(
        {
            "relational_pool_type": relational_type,
            "graph_pool_type": graph_type,
            "llm_enabled": llm_enabled,
            "search_enabled": search_enabled,
            "graph_available": graph_available,
        }
    )


async def health_endpoint() -> APIResponse[dict]:
    """Health check endpoint for load balancers.

    Returns health status wrapped in APIResponse format.
    Detailed health info requires authentication via /api/v1/system/status.
    """
    result = await health_check()
    return success_response({"status": result.status, "checks": result.checks})


async def metrics_endpoint(
    _: str | None = Depends(verify_api_key_optional),
) -> PlainTextResponse:
    """Prometheus metrics endpoint (optional authentication).

    Authentication required if WEAVER__API__REQUIRE_AUTH_FOR_METRICS=true.
    """
    return PlainTextResponse(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
