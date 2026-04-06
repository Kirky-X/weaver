# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Shared fixtures for integration tests with service fallback.

Supports three modes:
1. Real services available: Use real connections
2. Services unavailable: Skip tests gracefully
3. Mock mode: Use mocks for isolated testing

All fixtures use real service connections (PostgreSQL, Neo4j, Redis, EventBus)
when available, or skip tests when services are not running.
"""

import os
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest


def get_postgres_dsn():
    """Get PostgreSQL DSN from environment variables."""
    return (
        os.getenv("WEAVER_POSTGRES__DSN")
        or os.getenv("POSTGRES_DSN")
        or f"postgresql+asyncpg://{os.getenv('POSTGRES_USER', 'postgres')}:{os.getenv('POSTGRES_PASSWORD', 'invalid')}@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}/{os.getenv('POSTGRES_DATABASE', 'weaver')}"
    )


def get_neo4j_config():
    """Get Neo4j connection config."""
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "password")
    return uri, (user, password)


def get_redis_url():
    """Get Redis URL."""
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


async def check_postgres_available() -> bool:
    """Check if PostgreSQL is available."""
    try:
        from core.db.postgres import PostgresPool

        dsn = get_postgres_dsn()
        pool = PostgresPool(dsn)
        await pool.startup()
        await pool.shutdown()
        return True
    except Exception:
        return False


async def check_neo4j_available() -> bool:
    """Check if Neo4j is available."""
    try:
        from core.db.neo4j import Neo4jPool

        uri, auth = get_neo4j_config()
        pool = Neo4jPool(uri, auth)
        await pool.startup()
        await pool.shutdown()
        return True
    except Exception:
        return False


async def check_redis_available() -> bool:
    """Check if Redis is available."""
    try:
        from redis import asyncio as aioredis

        url = get_redis_url()
        client = aioredis.from_url(url)
        await client.ping()
        await client.aclose()
        return True
    except Exception:
        return False


@pytest.fixture
def unique_id():
    """Generate unique test ID to avoid conflicts."""
    return str(uuid.uuid4())


@pytest.fixture
async def postgres_pool():
    """Create a real PostgreSQL pool for integration tests.

    Skips tests if PostgreSQL is not available.
    """
    from core.db.postgres import PostgresPool

    if not await check_postgres_available():
        pytest.skip("PostgreSQL not available")

    dsn = get_postgres_dsn()
    pool = PostgresPool(dsn)
    await pool.startup()
    yield pool
    await pool.shutdown()


@pytest.fixture
async def neo4j_pool():
    """Create a real Neo4j pool for integration tests.

    Skips tests if Neo4j is not available.
    """
    from core.db.neo4j import Neo4jPool

    if not await check_neo4j_available():
        pytest.skip("Neo4j not available")

    uri, auth = get_neo4j_config()
    pool = Neo4jPool(uri, auth)
    await pool.startup()
    yield pool
    await pool.shutdown()


@pytest.fixture
async def redis_client():
    """Create a real Redis client for integration tests.

    Skips tests if Redis is not available.
    """
    from redis import asyncio as aioredis

    if not await check_redis_available():
        pytest.skip("Redis not available")

    url = get_redis_url()
    client = aioredis.from_url(url)
    yield client
    await client.aclose()


@pytest.fixture
def event_bus():
    """Create a real EventBus for integration tests."""
    from core.event.bus import EventBus

    return EventBus()


# ─────────────────────────────────────────────────────────────────────────────
# Optional fixtures for tests that can work with or without services
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
async def optional_postgres_pool():
    """Optional PostgreSQL pool - returns None if not available."""
    from core.db.postgres import PostgresPool

    if not await check_postgres_available():
        yield None
        return

    dsn = get_postgres_dsn()
    pool = PostgresPool(dsn)
    await pool.startup()
    yield pool
    await pool.shutdown()


@pytest.fixture
async def optional_neo4j_pool():
    """Optional Neo4j pool - returns None if not available."""
    from core.db.neo4j import Neo4jPool

    if not await check_neo4j_available():
        yield None
        return

    uri, auth = get_neo4j_config()
    pool = Neo4jPool(uri, auth)
    await pool.startup()
    yield pool
    await pool.shutdown()


@pytest.fixture
async def optional_redis_client():
    """Optional Redis client - returns None if not available."""
    from redis import asyncio as aioredis

    if not await check_redis_available():
        yield None
        return

    url = get_redis_url()
    client = aioredis.from_url(url)
    yield client
    await client.aclose()


# ─────────────────────────────────────────────────────────────────────────────
# Mock Detection: Integration tests MUST use real services
# ─────────────────────────────────────────────────────────────────────────────


def pytest_collection_modifyitems(config, items):
    """Detect mock usage in integration tests and raise error.

    Integration tests MUST use real services (PostgreSQL, Neo4j, Redis).
    If a test needs mock, move it to tests/unit/ directory.
    """
    import inspect

    forbidden_patterns = [
        "MagicMock",
        "AsyncMock",
        "patch(",
        "@patch",
        "unittest.mock",
    ]

    for item in items:
        # Only check test functions, not fixtures
        if not hasattr(item, "function"):
            continue

        try:
            source = inspect.getsource(item.function)
        except (TypeError, OSError):
            continue

        for pattern in forbidden_patterns:
            if pattern in source:
                raise AssertionError(
                    f"\n"
                    f"╔════════════════════════════════════════════════════════════╗\n"
                    f"║  ❌ 集成测试禁止使用 mock!                                  ║\n"
                    f"╠════════════════════════════════════════════════════════════╣\n"
                    f"║  测试: {item.name:<50} ║\n"
                    f"║  文件: {item.fspath!s:<50} ║\n"
                    f"║  检测到: {pattern:<48} ║\n"
                    f"╠════════════════════════════════════════════════════════════╣\n"
                    f"║  集成测试必须使用真实服务。                                 ║\n"
                    f"║  如需 mock，请将测试移至 tests/unit/ 目录。                 ║\n"
                    f"╚════════════════════════════════════════════════════════════╝\n"
                )
