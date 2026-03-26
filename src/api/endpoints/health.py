# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Health check endpoints for monitoring service dependencies."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import text

from core.cache.redis import RedisClient
from core.constants import HealthStatus
from core.db.neo4j import Neo4jPool
from core.db.postgres import PostgresPool


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


# Global references to database pools/clients (set during startup)
_postgres_pool: PostgresPool | None = None
_neo4j_pool: Neo4jPool | None = None
_redis_client: RedisClient | None = None


def set_postgres_pool(pool: PostgresPool) -> None:
    """Set the PostgreSQL pool reference."""
    global _postgres_pool
    _postgres_pool = pool


def set_neo4j_pool(pool: Neo4jPool) -> None:
    """Set the Neo4j pool reference."""
    global _neo4j_pool
    _neo4j_pool = pool


def set_redis_client(client: RedisClient) -> None:
    """Set the Redis client reference."""
    global _redis_client
    _redis_client = client


async def check_postgres_health(pool: PostgresPool) -> dict[str, Any]:
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
        return {"status": "ok", "latency_ms": latency_ms}
    except TimeoutError:
        latency_ms = (time.monotonic() - start) * 1000
        return {"status": "timeout", "latency_ms": latency_ms}
    except Exception as e:
        latency_ms = (time.monotonic() - start) * 1000
        return {"status": "error", "latency_ms": latency_ms, "error": str(e)}


async def check_neo4j_health(pool: Neo4jPool) -> dict[str, Any]:
    """Check Neo4j connectivity.

    Returns:
        dict with status, latency_ms, and optional error message.
    """
    start = time.monotonic()
    try:
        async with asyncio.timeout(5):
            await pool.execute_query("RETURN 1")
        latency_ms = (time.monotonic() - start) * 1000
        return {"status": "ok", "latency_ms": latency_ms}
    except TimeoutError:
        latency_ms = (time.monotonic() - start) * 1000
        return {"status": "timeout", "latency_ms": latency_ms}
    except Exception as e:
        latency_ms = (time.monotonic() - start) * 1000
        return {"status": "error", "latency_ms": latency_ms, "error": str(e)}


async def check_redis_health(client: RedisClient) -> dict[str, Any]:
    """Check Redis connectivity.

    Returns:
        dict with status, latency_ms, and optional error message.
    """
    start = time.monotonic()
    try:
        async with asyncio.timeout(5):
            await client.client.ping()
        latency_ms = (time.monotonic() - start) * 1000
        return {"status": "ok", "latency_ms": latency_ms}
    except TimeoutError:
        latency_ms = (time.monotonic() - start) * 1000
        return {"status": "timeout", "latency_ms": latency_ms}
    except Exception as e:
        latency_ms = (time.monotonic() - start) * 1000
        return {"status": "error", "latency_ms": latency_ms, "error": str(e)}


async def health_check() -> HealthCheckResponse:
    """Aggregated health check for all dependencies.

    Returns:
        HealthCheckResponse with overall status and individual check results.
    """
    checks: dict[str, ServiceHealthCheck] = {}
    all_healthy = True

    # Check PostgreSQL
    if _postgres_pool:
        pg_result = await check_postgres_health(_postgres_pool)
        checks["postgres"] = ServiceHealthCheck(**pg_result)
        if pg_result["status"] != "ok":
            all_healthy = False
    else:
        checks["postgres"] = ServiceHealthCheck(status="unavailable", error="Pool not initialized")
        all_healthy = False

    # Check Neo4j
    if _neo4j_pool:
        neo4j_result = await check_neo4j_health(_neo4j_pool)
        checks["neo4j"] = ServiceHealthCheck(**neo4j_result)
        if neo4j_result["status"] != "ok":
            all_healthy = False
    else:
        checks["neo4j"] = ServiceHealthCheck(status="unavailable", error="Pool not initialized")
        all_healthy = False

    # Check Redis
    if _redis_client:
        redis_result = await check_redis_health(_redis_client)
        checks["redis"] = ServiceHealthCheck(**redis_result)
        if redis_result["status"] != "ok":
            all_healthy = False
    else:
        checks["redis"] = ServiceHealthCheck(status="unavailable", error="Client not initialized")
        all_healthy = False

    return HealthCheckResponse(
        status=HealthStatus.HEALTHY.value if all_healthy else HealthStatus.UNHEALTHY.value,
        checks=checks,
    )
