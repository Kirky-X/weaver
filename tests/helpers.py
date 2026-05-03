# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Test helper utilities."""

import random
import string
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock


def generate_random_string(length: int = 10) -> str:
    """Generate a random string of specified length."""
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


def generate_random_url(domain: str = "example.com") -> str:
    """Generate a random URL."""
    return f"https://{domain}/{generate_random_string(8)}"


def generate_random_uuid() -> str:
    """Generate a random UUID string."""
    return str(uuid.uuid4())


def create_mock_cache_client() -> MagicMock:
    """Create a mock Redis client with all common methods."""
    redis = MagicMock()
    redis.client = MagicMock()
    redis.client.get = AsyncMock(return_value=None)
    redis.client.set = AsyncMock(return_value=True)
    redis.client.lpush = AsyncMock(return_value=1)
    redis.client.rpush = AsyncMock(return_value=1)
    redis.client.llen = AsyncMock(return_value=0)
    redis.client.lpop = AsyncMock(return_value=None)
    redis.client.rpop = AsyncMock(return_value=None)
    redis.client.lrange = AsyncMock(return_value=[])
    redis.client.hset = AsyncMock(return_value=1)
    redis.client.hget = AsyncMock(return_value=None)
    redis.client.hgetall = AsyncMock(return_value={})
    redis.client.hdel = AsyncMock(return_value=1)
    redis.client.delete = AsyncMock(return_value=1)
    redis.client.expire = AsyncMock(return_value=True)
    redis.client.ttl = AsyncMock(return_value=-1)
    redis.client.incr = AsyncMock(return_value=1)
    redis.client.decr = AsyncMock(return_value=0)
    redis.client.zadd = AsyncMock(return_value=1)
    redis.client.zrange = AsyncMock(return_value=[])
    redis.client.zrem = AsyncMock(return_value=1)
    redis.client.zscore = AsyncMock(return_value=None)
    redis.client.eval = AsyncMock(return_value=1)
    redis.client.ping = AsyncMock(return_value=True)
    return redis


def create_mock_postgres_session() -> MagicMock:
    """Create a mock PostgreSQL session with all common methods."""
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    session.delete = MagicMock()
    session.flush = AsyncMock()
    session.close = AsyncMock()
    return session


def create_mock_neo4j_session() -> MagicMock:
    """Create a mock Neo4j session with all common methods."""
    session = MagicMock()
    session.run = AsyncMock()
    session.close = AsyncMock()
    return session


def assert_api_response(
    response,
    expected_status: int = 200,
    has_data: bool = True,
    expected_code: int | None = None,
) -> dict[str, Any]:
    """Standardized API response assertion helper.

    Args:
        response: FastAPI TestClient response
        expected_status: Expected HTTP status code
        has_data: Whether response should contain 'data' field (False for errors)
        expected_code: Expected business logic code (optional)

    Returns:
        Parsed JSON response data
    """
    assert (
        response.status_code == expected_status
    ), f"Expected status {expected_status}, got {response.status_code}: {response.text}"
    data = response.json()

    if expected_status >= 400:
        assert "detail" in data, f"Error response missing 'detail' field: {data}"
    elif has_data:
        assert "data" in data, f"Response missing 'data' field: {data}"

    if expected_code is not None:
        assert (
            data.get("code") == expected_code
        ), f"Expected code {expected_code}, got {data.get('code')}"
    return data


class AsyncContextManagerMock:
    """Mock for async context managers."""

    def __init__(self, return_value: Any = None):
        self.return_value = return_value

    async def __aenter__(self):
        return self.return_value

    async def __aexit__(self, *args):
        return None


class AsyncIteratorMock:
    """Mock for async iterators."""

    def __init__(self, items: list[Any]):
        self.items = items
        self.index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index >= len(self.items):
            raise StopAsyncIteration
        item = self.items[self.index]
        self.index += 1
        return item


def create_migration_request_data(
    source_db: str = "postgres",
    target_db: str = "duckdb",
    batch_size: int = 5000,
    **kwargs,
) -> dict:
    """Create migration request test data with validation.

    Args:
        source_db: Source database type (default: 'postgres')
        target_db: Target database type (default: 'duckdb')
        batch_size: Batch size for migration (default: 5000)
        **kwargs: Additional fields to include in request data

    Returns:
        Dictionary with migration request data
    """
    data = {
        "source_db": source_db,
        "target_db": target_db,
        "batch_size": batch_size,
    }
    data.update(kwargs)
    return data
