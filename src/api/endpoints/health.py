# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Health check endpoints for monitoring service dependencies."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import text

from core.constants import HealthCheckStatus, HealthStatus
from core.observability import metrics


class ServiceHealthCheck(BaseModel):
    """Individual service health check result."""

    status: str = Field(description="Service status: ok, timeout, error, or unavailable")
    latency_ms: float | None = Field(default=None, description="Response latency in milliseconds")
    error: str | None = Field(default=None, description="Error message if any")


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


async def check_postgres_health(pool: Any) -> dict[str, Any]:
    """Check PostgreSQL connectivity.

    Returns:
        dict with status, latency_ms, and optional error message.

    """
    start = time.monotonic()
    try:
        async with asyncio.timeout(5):
            async with pool.session_context() as session:
                await session.execute(text("SELECT 1"))
        latency_ms = (time.monotonic() - start) * 1000
        metrics.health_check_status.labels(service="postgres").set(
            HEALTH_STATUS_CODES[HealthCheckStatus.OK.value]
        )
        metrics.health_check_latency.labels(service="postgres").observe(latency_ms / 1000)
        return {"status": HealthCheckStatus.OK.value, "latency_ms": latency_ms}
    except TimeoutError:
        latency_ms = (time.monotonic() - start) * 1000
        metrics.health_check_status.labels(service="postgres").set(
            HEALTH_STATUS_CODES[HealthCheckStatus.TIMEOUT.value]
        )
        metrics.health_check_latency.labels(service="postgres").observe(latency_ms / 1000)
        return {"status": HealthCheckStatus.TIMEOUT.value, "latency_ms": latency_ms}
    except Exception as e:
        latency_ms = (time.monotonic() - start) * 1000
        metrics.health_check_status.labels(service="postgres").set(
            HEALTH_STATUS_CODES[HealthCheckStatus.ERROR.value]
        )
        metrics.health_check_latency.labels(service="postgres").observe(latency_ms / 1000)
        return {
            "status": HealthCheckStatus.ERROR.value,
            "latency_ms": latency_ms,
            HealthCheckStatus.ERROR.value: str(e),
        }


async def check_neo4j_health(pool: Any) -> dict[str, Any]:
    """Check Neo4j connectivity.

    Returns:
        dict with status, latency_ms, and optional error message.

    """
    start = time.monotonic()
    try:
        async with asyncio.timeout(5):
            await pool.execute_query("RETURN 1")
        latency_ms = (time.monotonic() - start) * 1000
        metrics.health_check_status.labels(service="neo4j").set(
            HEALTH_STATUS_CODES[HealthCheckStatus.OK.value]
        )
        metrics.health_check_latency.labels(service="neo4j").observe(latency_ms / 1000)
        return {"status": HealthCheckStatus.OK.value, "latency_ms": latency_ms}
    except TimeoutError:
        latency_ms = (time.monotonic() - start) * 1000
        metrics.health_check_status.labels(service="neo4j").set(
            HEALTH_STATUS_CODES[HealthCheckStatus.TIMEOUT.value]
        )
        metrics.health_check_latency.labels(service="neo4j").observe(latency_ms / 1000)
        return {"status": HealthCheckStatus.TIMEOUT.value, "latency_ms": latency_ms}
    except Exception as e:
        latency_ms = (time.monotonic() - start) * 1000
        metrics.health_check_status.labels(service="neo4j").set(
            HEALTH_STATUS_CODES[HealthCheckStatus.ERROR.value]
        )
        metrics.health_check_latency.labels(service="neo4j").observe(latency_ms / 1000)
        return {
            "status": HealthCheckStatus.ERROR.value,
            "latency_ms": latency_ms,
            HealthCheckStatus.ERROR.value: str(e),
        }


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
        return {
            "status": HealthCheckStatus.ERROR.value,
            "latency_ms": latency_ms,
            HealthCheckStatus.ERROR.value: str(e),
        }


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

    # Check PostgreSQL
    pg_pool = None
    if container is not None:
        try:
            pg_pool = container.relational_pool()
        except RuntimeError:
            pg_pool = None
    if pg_pool is not None:
        pg_result = await check_postgres_health(pg_pool)
        checks["postgres"] = ServiceHealthCheck(**pg_result)
        if pg_result["status"] != HealthCheckStatus.OK.value:
            all_healthy = False
    else:
        checks["postgres"] = ServiceHealthCheck(
            status=HealthCheckStatus.UNAVAILABLE.value, error="Pool not initialized"
        )
        metrics.health_check_status.labels(service="postgres").set(
            HEALTH_STATUS_CODES[HealthCheckStatus.UNAVAILABLE.value]
        )
        all_healthy = False

    # Check Neo4j
    neo4j_pool = container.graph_pool() if container is not None else None
    if neo4j_pool is not None:
        neo4j_result = await check_neo4j_health(neo4j_pool)
        checks["neo4j"] = ServiceHealthCheck(**neo4j_result)
        if neo4j_result["status"] != HealthCheckStatus.OK.value:
            all_healthy = False
    else:
        checks["neo4j"] = ServiceHealthCheck(
            status=HealthCheckStatus.UNAVAILABLE.value, error="Pool not initialized"
        )
        metrics.health_check_status.labels(service="neo4j").set(
            HEALTH_STATUS_CODES[HealthCheckStatus.UNAVAILABLE.value]
        )
        all_healthy = False

    # Check Redis
    cache_client = None
    if container is not None:
        try:
            cache_client = container.cache_client()
        except RuntimeError:
            cache_client = None
    if cache_client is not None:
        redis_result = await check_redis_health(cache_client)
        checks["redis"] = ServiceHealthCheck(**redis_result)
        if redis_result["status"] != HealthCheckStatus.OK.value:
            all_healthy = False
    else:
        checks["redis"] = ServiceHealthCheck(
            status=HealthCheckStatus.UNAVAILABLE.value, error="Client not initialized"
        )
        metrics.health_check_status.labels(service="redis").set(
            HEALTH_STATUS_CODES[HealthCheckStatus.UNAVAILABLE.value]
        )
        all_healthy = False

    return HealthCheckResponse(
        status=HealthStatus.HEALTHY.value if all_healthy else HealthStatus.UNHEALTHY.value,
        checks=checks,
    )
