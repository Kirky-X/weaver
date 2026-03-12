"""Test helper utilities."""

import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from typing import Any
from unittest.mock import MagicMock, AsyncMock


def generate_random_string(length: int = 10) -> str:
    """Generate a random string of specified length."""
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


def generate_random_url(domain: str = "example.com") -> str:
    """Generate a random URL."""
    return f"https://{domain}/{generate_random_string(8)}"


def generate_random_uuid() -> str:
    """Generate a random UUID string."""
    return str(uuid.uuid4())


def generate_random_embedding(dimensions: int = 1536) -> list[float]:
    """Generate a random embedding vector."""
    return [random.random() for _ in range(dimensions)]


def create_mock_article(
    id: uuid.UUID | None = None,
    title: str | None = None,
    body: str | None = None,
    url: str | None = None,
    **kwargs,
) -> MagicMock:
    """Create a mock Article object with default values."""
    article = MagicMock()
    article.id = id or uuid.uuid4()
    article.title = title or f"Test Article {generate_random_string(6)}"
    article.body = body or "Test article body content"
    article.source_url = url or generate_random_url()
    article.source_host = kwargs.get("source_host", "example.com")
    article.is_news = kwargs.get("is_news", True)
    article.category = kwargs.get("category")
    article.language = kwargs.get("language", "zh")
    article.region = kwargs.get("region")
    article.summary = kwargs.get("summary")
    article.event_time = kwargs.get("event_time")
    article.subjects = kwargs.get("subjects")
    article.key_data = kwargs.get("key_data")
    article.impact = kwargs.get("impact")
    article.score = kwargs.get("score")
    article.sentiment = kwargs.get("sentiment")
    article.sentiment_score = kwargs.get("sentiment_score")
    article.primary_emotion = kwargs.get("primary_emotion")
    article.credibility_score = kwargs.get("credibility_score")
    article.source_credibility = kwargs.get("source_credibility")
    article.cross_verification = kwargs.get("cross_verification")
    article.content_check_score = kwargs.get("content_check_score")
    article.publish_time = kwargs.get("publish_time")
    article.created_at = kwargs.get("created_at", datetime.now(timezone.utc))
    article.updated_at = kwargs.get("updated_at", datetime.now(timezone.utc))
    return article


def create_mock_entity(
    canonical_name: str | None = None,
    entity_type: str | None = None,
    neo4j_id: str | None = None,
    **kwargs,
) -> MagicMock:
    """Create a mock Entity object with default values."""
    entity = MagicMock()
    entity.neo4j_id = neo4j_id or generate_random_uuid()
    entity.canonical_name = canonical_name or f"Entity {generate_random_string(6)}"
    entity.type = entity_type or "PERSON"
    entity.aliases = kwargs.get("aliases", [])
    entity.description = kwargs.get("description")
    entity.created_at = kwargs.get("created_at", datetime.now(timezone.utc))
    entity.updated_at = kwargs.get("updated_at", datetime.now(timezone.utc))
    return entity


def create_mock_source_config(
    source_id: str | None = None,
    name: str | None = None,
    url: str | None = None,
    **kwargs,
) -> MagicMock:
    """Create a mock SourceConfig object with default values."""
    config = MagicMock()
    config.id = source_id or f"source_{generate_random_string(4)}"
    config.name = name or f"Test Source {generate_random_string(4)}"
    config.url = url or generate_random_url("feeds.example.com")
    config.source_type = kwargs.get("source_type", "rss")
    config.enabled = kwargs.get("enabled", True)
    config.interval_minutes = kwargs.get("interval_minutes", 30)
    config.per_host_concurrency = kwargs.get("per_host_concurrency", 2)
    config.last_crawl_time = kwargs.get("last_crawl_time")
    return config


def create_mock_llm_response(data: dict[str, Any]) -> str:
    """Create a mock LLM JSON response."""
    import json
    return json.dumps(data)


def create_mock_redis_client() -> MagicMock:
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


def assert_dict_contains(expected: dict[str, Any], actual: dict[str, Any]) -> None:
    """Assert that actual dict contains all keys from expected with matching values."""
    for key, value in expected.items():
        assert key in actual, f"Key '{key}' not found in actual dict"
        assert actual[key] == value, f"Value mismatch for key '{key}': expected {value}, got {actual[key]}"


def assert_datetime_close(
    dt1: datetime,
    dt2: datetime,
    tolerance_seconds: float = 1.0,
) -> None:
    """Assert that two datetimes are within tolerance of each other."""
    diff = abs((dt1 - dt2).total_seconds())
    assert diff <= tolerance_seconds, f"Datetimes differ by {diff} seconds (tolerance: {tolerance_seconds})"


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
