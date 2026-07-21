# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Health check endpoints for monitoring service dependencies."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text

from api.middleware.auth import verify_api_key
from api.schemas.response import APIResponse, success_response
from core.constants import HealthCheckStatus, HealthStatus
from core.observability import get_logger, metrics

log = get_logger(__name__)


class ServiceHealthCheck(BaseModel):
    """Individual service health check result."""

    status: str = Field(description="Service status: ok, timeout, error, or unavailable")
    latency_ms: float | None = Field(default=None, description="Response latency in milliseconds")
    error: bool = Field(
        default=False,
        description="Error flag (true if check failed; details are logged server-side only).",
    )


class HealthCheckResponse(BaseModel):
    """Health check response model."""

    status: str = Field(description="Overall health status: healthy or unhealthy")
    checks: dict[str, ServiceHealthCheck] = Field(
        default_factory=dict, description="Individual service check results"
    )


# Health status code mapping for Prometheus metrics
HEALTH_STATUS_CODES = {
    HealthCheckStatus.OK.value: 1,
    HealthCheckStatus.ERROR.value: 0,
    HealthCheckStatus.TIMEOUT.value: -1,
    HealthCheckStatus.UNAVAILABLE.value: -2,
}


async def check_postgres_health(pool: Any, service_name: str = "postgres") -> dict[str, Any]:
    """Check relational database connectivity (PostgreSQL or DuckDB).

    Args:
        pool: Database connection pool.
        service_name: Service name for Prometheus labels (e.g. "postgres" or "duckdb").

    Returns:
        dict with status, latency_ms, and optional error message.

    """
    start = time.monotonic()
    try:
        async with asyncio.timeout(5):
            async with pool.session_context() as session:
                await session.execute(text("SELECT 1"))
        latency_ms = (time.monotonic() - start) * 1000
        metrics.health_check_status.labels(service=service_name).set(
            HEALTH_STATUS_CODES[HealthCheckStatus.OK.value]
        )
        metrics.health_check_latency.labels(service=service_name).observe(latency_ms / 1000)
        return {"status": HealthCheckStatus.OK.value, "latency_ms": latency_ms}
    except TimeoutError:
        latency_ms = (time.monotonic() - start) * 1000
        metrics.health_check_status.labels(service=service_name).set(
            HEALTH_STATUS_CODES[HealthCheckStatus.TIMEOUT.value]
        )
        metrics.health_check_latency.labels(service=service_name).observe(latency_ms / 1000)
        return {"status": HealthCheckStatus.TIMEOUT.value, "latency_ms": latency_ms}
    except Exception as e:
        latency_ms = (time.monotonic() - start) * 1000
        metrics.health_check_status.labels(service=service_name).set(
            HEALTH_STATUS_CODES[HealthCheckStatus.ERROR.value]
        )
        metrics.health_check_latency.labels(service=service_name).observe(latency_ms / 1000)
        # CWE-200: log full error server-side, expose only boolean flag in
        # the public health response to avoid disclosing topology/version
        # information to unauthenticated callers.
        log.warning(
            "health_check_error",
            service=service_name,
            error=str(e),
            exc_type=type(e).__name__,
        )
        return {"status": HealthCheckStatus.ERROR.value, "latency_ms": latency_ms, "error": True}


async def check_neo4j_health(pool: Any, service_name: str = "neo4j") -> dict[str, Any]:
    """Check graph database connectivity (Neo4j or LadybugDB).

    Args:
        pool: Graph database connection pool.
        service_name: Service name for Prometheus labels (e.g. "neo4j" or "ladybug").

    Returns:
        dict with status, latency_ms, and optional error message.

    """
    start = time.monotonic()
    try:
        async with asyncio.timeout(5):
            await pool.execute_query("RETURN 1")
        latency_ms = (time.monotonic() - start) * 1000
        metrics.health_check_status.labels(service=service_name).set(
            HEALTH_STATUS_CODES[HealthCheckStatus.OK.value]
        )
        metrics.health_check_latency.labels(service=service_name).observe(latency_ms / 1000)
        return {"status": HealthCheckStatus.OK.value, "latency_ms": latency_ms}
    except TimeoutError:
        latency_ms = (time.monotonic() - start) * 1000
        metrics.health_check_status.labels(service=service_name).set(
            HEALTH_STATUS_CODES[HealthCheckStatus.TIMEOUT.value]
        )
        metrics.health_check_latency.labels(service=service_name).observe(latency_ms / 1000)
        return {"status": HealthCheckStatus.TIMEOUT.value, "latency_ms": latency_ms}
    except Exception as e:
        latency_ms = (time.monotonic() - start) * 1000
        metrics.health_check_status.labels(service=service_name).set(
            HEALTH_STATUS_CODES[HealthCheckStatus.ERROR.value]
        )
        metrics.health_check_latency.labels(service=service_name).observe(latency_ms / 1000)
        log.warning(
            "health_check_error",
            service=service_name,
            error=str(e),
            exc_type=type(e).__name__,
        )
        return {"status": HealthCheckStatus.ERROR.value, "latency_ms": latency_ms, "error": True}


async def check_redis_health(client: Any) -> dict[str, Any]:
    """Check Redis connectivity.

    Returns:
        dict with status, latency_ms, and optional error message.

    """
    start = time.monotonic()
    try:
        async with asyncio.timeout(5):
            await client.ping()
        latency_ms = (time.monotonic() - start) * 1000
        metrics.health_check_status.labels(service="redis").set(
            HEALTH_STATUS_CODES[HealthCheckStatus.OK.value]
        )
        metrics.health_check_latency.labels(service="redis").observe(latency_ms / 1000)
        return {"status": HealthCheckStatus.OK.value, "latency_ms": latency_ms}
    except TimeoutError:
        latency_ms = (time.monotonic() - start) * 1000
        metrics.health_check_status.labels(service="redis").set(
            HEALTH_STATUS_CODES[HealthCheckStatus.TIMEOUT.value]
        )
        metrics.health_check_latency.labels(service="redis").observe(latency_ms / 1000)
        return {"status": HealthCheckStatus.TIMEOUT.value, "latency_ms": latency_ms}
    except Exception as e:
        latency_ms = (time.monotonic() - start) * 1000
        metrics.health_check_status.labels(service="redis").set(
            HEALTH_STATUS_CODES[HealthCheckStatus.ERROR.value]
        )
        metrics.health_check_latency.labels(service="redis").observe(latency_ms / 1000)
        log.warning(
            "health_check_error",
            service="redis",
            error=str(e),
            exc_type=type(e).__name__,
        )
        return {"status": HealthCheckStatus.ERROR.value, "latency_ms": latency_ms, "error": True}


async def health_check() -> HealthCheckResponse:
    """Perform aggregated health check for all dependencies.

    Returns:
        HealthCheckResponse with overall status and individual check results.

    """
    from container import get_container

    try:
        container = get_container()
    except RuntimeError:
        container = None

    checks: dict[str, ServiceHealthCheck] = {}
    all_healthy = True

    # Check relational database (PostgreSQL or DuckDB)
    relational_service_name = "postgres"  # default
    pg_pool = None
    if container is not None:
        try:
            pg_pool = container.relational_pool()
            relational_service_name = container.relational_pool_type
        except RuntimeError:
            pg_pool = None
    if pg_pool is not None:
        pg_result = await check_postgres_health(pg_pool, service_name=relational_service_name)
        checks[relational_service_name] = ServiceHealthCheck(**pg_result)
        if pg_result["status"] != HealthCheckStatus.OK.value:
            all_healthy = False
    else:
        checks[relational_service_name] = ServiceHealthCheck(
            status=HealthCheckStatus.UNAVAILABLE.value, error=True
        )
        metrics.health_check_status.labels(service=relational_service_name).set(
            HEALTH_STATUS_CODES[HealthCheckStatus.UNAVAILABLE.value]
        )
        all_healthy = False

    # Check graph database (Neo4j or LadybugDB)
    graph_service_name = "neo4j"  # default
    neo4j_pool = container.graph_pool() if container is not None else None
    if container is not None:
        graph_type = container.graph_pool_type
        if graph_type is not None:
            graph_service_name = graph_type
    if neo4j_pool is not None:
        neo4j_result = await check_neo4j_health(neo4j_pool, service_name=graph_service_name)
        checks[graph_service_name] = ServiceHealthCheck(**neo4j_result)
        if neo4j_result["status"] != HealthCheckStatus.OK.value:
            all_healthy = False
    else:
        checks[graph_service_name] = ServiceHealthCheck(
            status=HealthCheckStatus.UNAVAILABLE.value, error=True
        )
        metrics.health_check_status.labels(service=graph_service_name).set(
            HEALTH_STATUS_CODES[HealthCheckStatus.UNAVAILABLE.value]
        )
        all_healthy = False

    # Check cache (Redis or Cashews fallback)
    cache_client = None
    if container is not None:
        try:
            cache_client = container.cache_client()
        except RuntimeError:
            cache_client = None
    # Use the cache backend type as the service name so the checks key
    # reflects the actual active backend ('redis' or 'cashews').
    cache_service_name = cache_client.cache_type if hasattr(cache_client, "cache_type") else "redis"
    if cache_client is not None:
        redis_result = await check_redis_health(cache_client)
        checks[cache_service_name] = ServiceHealthCheck(**redis_result)
        if redis_result["status"] != HealthCheckStatus.OK.value:
            all_healthy = False
    else:
        checks[cache_service_name] = ServiceHealthCheck(
            status=HealthCheckStatus.UNAVAILABLE.value, error=True
        )
        metrics.health_check_status.labels(service=cache_service_name).set(
            HEALTH_STATUS_CODES[HealthCheckStatus.UNAVAILABLE.value]
        )
        all_healthy = False

    return HealthCheckResponse(
        status=HealthStatus.HEALTHY.value if all_healthy else HealthStatus.UNHEALTHY.value,
        checks=checks,
    )


# ── Health API Router (under /api/v1/health) ─────────────────


health_router = APIRouter(prefix="/health", tags=["health"])


@health_router.get("/dependencies", response_model=APIResponse[dict])
async def health_dependencies(
    _: str = Depends(verify_api_key),
) -> APIResponse[dict]:
    """Return aggregated dependency health check.

    Returns per-dependency status (relational DB, graph DB, cache) with
    latency measurements. This is the public-facing endpoint under
    ``/api/v1/health/dependencies``; the admin-only
    ``/api/v1/system/health/dependencies`` provides additional details
    (LLM providers, spaCy, BM25).
    """
    result = await health_check()
    return success_response(
        {
            "status": result.status,
            "checks": {name: check.model_dump() for name, check in result.checks.items()},
        }
    )
