"""Pytest configuration and fixtures."""

import pytest
import asyncio
from typing import Generator


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_redis():
    """Mock Redis client for testing."""
    from unittest.mock import AsyncMock, MagicMock

    redis = MagicMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.lpush = AsyncMock(return_value=1)
    redis.llen = AsyncMock(return_value=0)
    return redis


@pytest.fixture
def mock_postgres_pool():
    """Mock PostgreSQL pool for testing."""
    from unittest.mock import MagicMock, AsyncMock

    pool = MagicMock()
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    pool.session = MagicMock(return_value=session)
    return pool


@pytest.fixture
def mock_neo4j_pool():
    """Mock Neo4j pool for testing."""
    from unittest.mock import MagicMock, AsyncMock

    pool = MagicMock()
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    pool.session = MagicMock(return_value=session)
    return pool


@pytest.fixture
def sample_source_config():
    """Sample source config for testing."""
    from modules.source.models import SourceConfig

    return SourceConfig(
        id="test_source",
        name="Test Source",
        url="https://example.com/feed.xml",
        source_type="rss",
        enabled=True,
        interval_minutes=30,
    )


@pytest.fixture
def sample_news_item():
    """Sample news item for testing."""
    from modules.source.models import NewsItem

    return NewsItem(
        url="https://example.com/article1",
        title="Test Article",
        source="test_source",
        source_host="example.com",
    )


@pytest.fixture
def sample_article_raw():
    """Sample article raw data for testing."""
    from modules.collector.models import ArticleRaw

    return ArticleRaw(
        url="https://example.com/article",
        title="Test Title",
        body="Test body content",
        source="test",
        source_host="example.com",
    )
