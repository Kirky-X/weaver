# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Shared fixtures for integration tests with service fallback.

Supports three modes:
1. Real services available: Use real connections (PostgreSQL, Neo4j, Redis)
2. Services unavailable: Fall back to embedded databases (DuckDB, LadybugDB)
3. Redis unavailable: Skip tests that require Redis

All fixtures use real databases - no mocks. DuckDB and LadybugDB are real
embedded databases that can run without external services.
"""

import os
import tempfile
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
# Fallback fixtures: Use embedded databases when external services unavailable
# These are REAL databases, not mocks - fully compliant with integration test rules
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
async def relational_pool():
    """Create a relational database pool with automatic fallback.

    Tries PostgreSQL first, falls back to DuckDB if unavailable.
    DuckDB is a real embedded database - no mocks.

    Returns:
        tuple: (pool, database_type) where database_type is "postgresql" or "duckdb"
    """
    # Try PostgreSQL first
    if await check_postgres_available():
        from core.db.postgres import PostgresPool

        dsn = get_postgres_dsn()
        pool = PostgresPool(dsn)
        await pool.startup()
        yield pool, "postgresql"
        await pool.shutdown()
    else:
        # Fallback to DuckDB (real embedded database)
        from core.db.duckdb_pool import DuckDBPool
        from modules.storage.duckdb.schema import initialize_duckdb_schema

        # Use temp file path for test isolation (DuckDB will create the file)
        with tempfile.NamedTemporaryFile(suffix=".duckdb", delete=True) as f:
            db_path = f.name  # Get the path

        # File is now deleted, DuckDB will create a fresh database
        try:
            pool = DuckDBPool(db_path=db_path)
            await pool.startup()
            await initialize_duckdb_schema(pool)
            yield pool, "duckdb"
            await pool.shutdown()
        finally:
            # Cleanup temp file
            if os.path.exists(db_path):
                os.unlink(db_path)


@pytest.fixture
async def graph_pool():
    """Create a graph database pool with automatic fallback.

    Tries Neo4j first, falls back to LadybugDB if unavailable.
    LadybugDB is a real embedded graph database - no mocks.

    Returns:
        tuple: (pool, database_type) where database_type is "neo4j" or "ladybug"
    """
    # Try Neo4j first
    if await check_neo4j_available():
        from core.db.neo4j import Neo4jPool

        uri, auth = get_neo4j_config()
        pool = Neo4jPool(uri, auth)
        await pool.startup()
        yield pool, "neo4j"
        await pool.shutdown()
    else:
        # Fallback to LadybugDB (real embedded graph database)
        from core.db.ladybug_pool import LadybugPool
        from modules.storage.ladybug.schema import initialize_ladybug_schema

        # Use temp file path for test isolation (LadybugDB will create the file)
        with tempfile.NamedTemporaryFile(suffix=".ladybug", delete=True) as f:
            db_path = f.name  # Get the path

        # File is now deleted, LadybugDB will create a fresh database
        try:
            pool = LadybugPool(db_path=db_path)
            await pool.startup()
            await initialize_ladybug_schema(pool)
            yield pool, "ladybug"
            await pool.shutdown()
        finally:
            # Cleanup temp file
            if os.path.exists(db_path):
                os.unlink(db_path)


@pytest.fixture
async def cache_pool():
    """Create a cache pool with automatic fallback.

    Tries Redis first, falls back to CashewsRedisFallback (in-memory) if unavailable.
    CashewsRedisFallback is a real in-memory cache - no mocks.

    Returns:
        tuple: (pool, cache_type) where cache_type is "redis" or "cashews"
    """
    # Try Redis first
    if await check_redis_available():
        from core.cache import RedisClient

        url = get_redis_url()
        client = RedisClient(url)
        await client.startup()
        yield client, "redis"
        await client.shutdown()
    else:
        # Fallback to CashewsRedisFallback (real in-memory cache)
        from core.cache import CashewsRedisFallback

        client = CashewsRedisFallback()
        await client.startup()
        yield client, "cashews"
        await client.shutdown()


@pytest.fixture
async def database_strategy(relational_pool, graph_pool):
    """Create a DatabaseStrategy using fallback databases.

    Uses the relational_pool and graph_pool fixtures which automatically
    fall back to embedded databases when external services are unavailable.
    """
    from core.db.strategy import DatabaseStrategy

    rel_pool, rel_type = relational_pool
    g_pool, g_type = graph_pool

    yield DatabaseStrategy(
        relational_pool=rel_pool,
        graph_pool=g_pool,
        relational_type=rel_type,
        graph_type=g_type,
    )


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
