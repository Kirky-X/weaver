# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Shared fixtures for integration tests - NO MOCKS.

All fixtures use real service connections (PostgreSQL, Neo4j, Redis, EventBus).
"""

import os
import uuid

import pytest


def get_postgres_dsn():
    """Get PostgreSQL DSN with three-level fallback."""
    return (
        os.getenv("WEAVER_POSTGRES__DSN")
        or os.getenv("POSTGRES_DSN")
        or "postgresql+asyncpg://weaver:weaver@localhost:5432/weaver"
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


@pytest.fixture
def unique_id():
    """Generate unique test ID to avoid conflicts."""
    return str(uuid.uuid4())


@pytest.fixture
async def postgres_pool():
    """Create a real PostgreSQL pool for integration tests."""
    from core.db.postgres import PostgresPool

    dsn = get_postgres_dsn()
    pool = PostgresPool(dsn)
    await pool.startup()
    yield pool
    await pool.shutdown()


@pytest.fixture
async def neo4j_pool():
    """Create a real Neo4j pool for integration tests."""
    from core.db.neo4j import Neo4jPool

    uri, auth = get_neo4j_config()
    pool = Neo4jPool(uri, auth)
    await pool.startup()
    yield pool
    await pool.shutdown()


@pytest.fixture
async def redis_client():
    """Create a real Redis client for integration tests."""
    from redis import asyncio as aioredis

    url = get_redis_url()
    client = aioredis.from_url(url)
    yield client
    await client.aclose()


@pytest.fixture
def event_bus():
    """Create a real EventBus for integration tests."""
    from core.event.bus import EventBus

    return EventBus()
