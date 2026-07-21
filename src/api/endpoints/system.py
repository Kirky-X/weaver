# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""System endpoints — health, status, config, and metrics.

These endpoints were previously inlined in ``src/main.py`` and are extracted
here to reduce ``create_app()`` responsibility.
"""

from __future__ import annotations

import tomllib
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from api.dependencies import (
    get_cache_client_optional,
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

    Returns ONLY the overall status (``healthy``/``unhealthy``) without
    per-dependency details — the unauthenticated ``/health`` endpoint
    must not disclose internal topology (CWE-200 fix). Callers needing
    per-dependency detail must use the admin-authenticated
    ``/api/v1/system/health/dependencies`` endpoint.
    """
    result = await health_check()
    # Expose only overall status; per-dependency checks contain error
    # messages that may leak driver / version info to unauthenticated
    # callers. The ``checks`` dict is intentionally omitted here.
    return success_response({"status": result.status})


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


# ── Enhanced Operations Endpoints ─────────────────────────────


@system_router.get(
    "/health/dependencies",
    response_model=APIResponse[dict],
)
async def health_dependencies(
    _: str = Depends(verify_admin_api_key),
) -> APIResponse[dict]:
    """Detailed dependency health check (requires admin API key).

    Returns per-dependency status with latency, version, and connection details.
    Covers: relational DB, graph DB, cache, LLM provider, spaCy, BM25 index.
    """
    from container import get_container

    details: dict[str, Any] = {}

    try:
        container = get_container()
    except RuntimeError:
        container = None

    # Relational DB
    if container is not None:
        try:
            pool = container.relational_pool()
            pool_type = container.relational_pool_type
            import time

            start = time.monotonic()
            async with pool.session_context() as session:
                await session.execute(text("SELECT 1"))
            latency_ms = (time.monotonic() - start) * 1000
            details["relational"] = {
                "type": pool_type,
                "status": "ok",
                "latency_ms": round(latency_ms, 2),
            }
        except Exception as e:
            # CWE-200: log full error server-side, expose only type to
            # admin callers (admin endpoint, but still minimize leakage).
            log.warning(
                "system_health_relational_error",
                error=str(e),
                exc_type=type(e).__name__,
            )
            details["relational"] = {
                "status": "error",
                "error_type": type(e).__name__,
            }

        # Graph DB
        try:
            gpool = container.graph_pool()
            gtype = container.graph_pool_type
            import time

            start = time.monotonic()
            await gpool.execute_query("RETURN 1")
            latency_ms = (time.monotonic() - start) * 1000
            details["graph"] = {
                "type": gtype,
                "status": "ok",
                "latency_ms": round(latency_ms, 2),
            }
        except Exception as e:
            log.warning(
                "system_health_graph_error",
                error=str(e),
                exc_type=type(e).__name__,
            )
            details["graph"] = {
                "status": "error",
                "error_type": type(e).__name__,
            }

        # Cache
        try:
            cache = container.cache_client()
            cache_type = getattr(cache, "cache_type", "unknown")
            import time

            start = time.monotonic()
            await cache.ping()
            latency_ms = (time.monotonic() - start) * 1000
            details["cache"] = {
                "type": cache_type,
                "status": "ok",
                "latency_ms": round(latency_ms, 2),
            }
        except Exception as e:
            log.warning(
                "system_health_cache_error",
                error=str(e),
                exc_type=type(e).__name__,
            )
            details["cache"] = {
                "status": "error",
                "error_type": type(e).__name__,
            }

        # LLM
        try:
            llm = container.llm_client()
            providers = getattr(llm, "_providers", {})
            details["llm"] = {
                "status": "ok",
                "providers": list(providers.keys()),
                "provider_count": len(providers),
            }
        except Exception as e:
            log.warning(
                "system_health_llm_error",
                error=str(e),
                exc_type=type(e).__name__,
            )
            details["llm"] = {
                "status": "error",
                "error_type": type(e).__name__,
            }

    overall_healthy = all(v.get("status") == "ok" for v in details.values() if isinstance(v, dict))
    return success_response(
        {
            "status": "healthy" if overall_healthy else "degraded",
            "dependencies": details,
        }
    )


@system_router.post(
    "/admin/cache/clear",
    response_model=APIResponse[dict],
)
async def clear_cache(
    pattern: str = "*",
    _: str = Depends(verify_admin_api_key),
    cache_client: Any = Depends(get_cache_client_optional),
) -> APIResponse[dict]:
    """Clear cache entries matching pattern (requires admin API key).

    Args:
        pattern: Key pattern to match (default "*" = all keys).
        cache_client: Cache pool instance.

    """
    if cache_client is None:
        raise HTTPException(status_code=503, detail="Cache pool not initialized")

    deleted = 0
    async for key in cache_client.scan_iter(pattern=pattern, count=500):
        await cache_client.delete(key)
        deleted += 1

    log.info("cache_cleared", pattern=pattern, deleted=deleted)
    return success_response(
        {
            "pattern": pattern,
            "deleted": deleted,
            "status": "completed",
        }
    )


@system_router.post(
    "/admin/config/reload",
    response_model=APIResponse[dict],
)
async def reload_config(
    _: str = Depends(verify_admin_api_key),
) -> APIResponse[dict]:
    """Reload LLM live configuration from config/llm.toml (requires admin API key).

    Triggers LiveConfig.reload() which re-reads the TOML file and updates
    the LLM settings in-place. No server restart required.
    """
    from container import get_container

    try:
        container = get_container()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Container not initialized") from exc

    live_config = getattr(container, "_live_config", None)
    if live_config is None:
        raise HTTPException(status_code=503, detail="Live config not initialized")

    try:
        settings = live_config.reload()
        provider_count = len(getattr(settings, "providers", {}))
        log.info("config_reloaded", providers=provider_count)
        return success_response(
            {
                "status": "reloaded",
                "providers": provider_count,
                "config_path": str(getattr(live_config, "_config_path", "unknown")),
            }
        )
    except Exception as exc:
        log.error("config_reload_failed", error=str(exc), exc_type=type(exc).__name__)
        raise HTTPException(status_code=500, detail="Configuration reload failed") from exc
