"""Health check endpoints for monitoring service dependencies."""

import asyncio
import time
from typing import Any

from sqlalchemy import text

from core.cache.redis import RedisClient
from core.db.neo4j import Neo4jPool
from core.db.postgres import PostgresPool

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
    except asyncio.TimeoutError:
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
    except asyncio.TimeoutError:
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
    except asyncio.TimeoutError:
        latency_ms = (time.monotonic() - start) * 1000
        return {"status": "timeout", "latency_ms": latency_ms}
    except Exception as e:
        latency_ms = (time.monotonic() - start) * 1000
        return {"status": "error", "latency_ms": latency_ms, "error": str(e)}


async def health_check() -> dict[str, Any]:
    """Aggregated health check for all dependencies.

    Returns:
        dict with overall status and individual check results.
        Returns 200 if all healthy, 503 if any unhealthy.
    """
    checks = {}
    all_healthy = True

    # Check PostgreSQL
    if _postgres_pool:
        checks["postgres"] = await check_postgres_health(_postgres_pool)
        if checks["postgres"]["status"] != "ok":
            all_healthy = False
    else:
        checks["postgres"] = {"status": "unavailable", "error": "Pool not initialized"}
        all_healthy = False

    # Check Neo4j
    if _neo4j_pool:
        checks["neo4j"] = await check_neo4j_health(_neo4j_pool)
        if checks["neo4j"]["status"] != "ok":
            all_healthy = False
    else:
        checks["neo4j"] = {"status": "unavailable", "error": "Pool not initialized"}
        all_healthy = False

    # Check Redis
    if _redis_client:
        checks["redis"] = await check_redis_health(_redis_client)
        if checks["redis"]["status"] != "ok":
            all_healthy = False
    else:
        checks["redis"] = {"status": "unavailable", "error": "Client not initialized"}
        all_healthy = False

    return {
        "status": "healthy" if all_healthy else "unhealthy",
        "checks": checks
    }