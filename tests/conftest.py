# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Pytest configuration and fixtures."""

import asyncio
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from dotenv import load_dotenv

# Load environment variables from .env file before any tests run
_env_file = Path(__file__).parent.parent / ".env"
if _env_file.exists():
    load_dotenv(_env_file, override=True)

from core.observability.logging import get_logger

log = get_logger(__name__)


async def cancel_all_tasks() -> None:
    """Cancel all pending asyncio tasks from the current event loop.

    Retrieves all tasks, cancels each one, waits for cancellation to complete,
    and suppresses CancelledError exceptions. Includes timeout handling for
    tasks that don't respond to cancellation.
    """
    loop = asyncio.get_running_loop()
    tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task()]

    if not tasks:
        log.debug("no_pending_tasks_to_cancel")
        return

    log.info("cancelling_tasks", count=len(tasks))

    # Cancel all tasks
    for task in tasks:
        task.cancel()

    # Wait for all cancellations to complete with timeout
    try:
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=5.0)
        log.info("all_tasks_cancelled", count=len(tasks))
    except TimeoutError:
        log.warning(
            "task_cancellation_timeout",
            message="Some tasks did not respond to cancellation within timeout",
        )
    except Exception as exc:
        log.warning(
            "task_cancellation_error",
            error=str(exc),
            message="Errors occurred during task cancellation but continuing",
        )


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test case.

    This is required for session-scoped async fixtures to work with pytest-asyncio.
    """
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def postgres_pool():
    """Create PostgreSQL pool for integration tests."""
    from core.db.postgres import PostgresPool

    dsn = os.getenv("POSTGRES_DSN", "postgresql+asyncpg://postgres:postgres@localhost:5432/weaver")
    pool = PostgresPool(dsn)

    await pool.startup()
    yield pool
    await pool.shutdown()


@pytest.fixture(scope="module")
def mock_redis():
    """Mock Redis client for testing - module scoped for performance."""
    redis = MagicMock()
    redis.client = MagicMock()
    redis.client.get = AsyncMock(return_value=None)
    redis.client.set = AsyncMock(return_value=True)
    redis.client.lpush = AsyncMock(return_value=1)
    redis.client.llen = AsyncMock(return_value=0)
    redis.client.hset = AsyncMock(return_value=1)
    redis.client.hget = AsyncMock(return_value=None)
    redis.client.hgetall = AsyncMock(return_value={})
    redis.client.hdel = AsyncMock(return_value=1)
    redis.client.delete = AsyncMock(return_value=1)
    redis.client.expire = AsyncMock(return_value=True)
    redis.client.incr = AsyncMock(return_value=1)
    redis.client.decr = AsyncMock(return_value=0)
    redis.client.zadd = AsyncMock(return_value=1)
    redis.client.zrange = AsyncMock(return_value=[])
    redis.client.zrem = AsyncMock(return_value=1)
    redis.client.eval = AsyncMock(return_value=1)
    redis.client.ping = AsyncMock(return_value=True)
    return redis


@pytest.fixture(scope="module")
def mock_postgres_pool():
    """Mock PostgreSQL pool for testing - module scoped for performance."""
    pool = MagicMock()
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    session.delete = MagicMock()
    pool.session = MagicMock(return_value=session)
    return pool


@pytest.fixture(scope="module")
def mock_neo4j_pool():
    """Mock Neo4j pool for testing - module scoped for performance."""
    pool = MagicMock()
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.run = AsyncMock()
    pool.session = MagicMock(return_value=session)
    pool.execute_query = AsyncMock(return_value=[])
    return pool


@pytest.fixture(scope="session")
def sample_source_config():
    """Sample source config for testing - session scoped for immutability."""
    from modules.ingestion.domain.models import SourceConfig

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
    from modules.ingestion.domain.models import NewsItem

    return NewsItem(
        url="https://example.com/article1",
        title="Test Article",
        source="test_source",
        source_host="example.com",
    )


@pytest.fixture
def sample_article_raw():
    """Sample article raw data for testing."""
    from modules.ingestion.domain.models import ArticleRaw

    return ArticleRaw(
        url="https://example.com/article",
        title="Test Title",
        body="Test body content",
        source="test",
        source_host="example.com",
    )


@pytest.fixture
def sample_article():
    """Sample Article model for testing."""
    from core.db.models import Article

    article = MagicMock(spec=Article)
    article.id = uuid.uuid4()
    article.source_url = "https://example.com/article"
    article.source_host = "example.com"
    article.is_news = True
    article.title = "Test Article Title"
    article.body = "Test article body content"
    article.category = None
    article.language = "zh"
    article.region = None
    article.summary = None
    article.event_time = None
    article.subjects = None
    article.key_data = None
    article.impact = None
    article.score = None
    article.sentiment = None
    article.sentiment_score = None
    article.primary_emotion = None
    article.credibility_score = None
    article.source_credibility = None
    article.cross_verification = None
    article.content_check_score = None
    article.publish_time = None
    article.created_at = datetime.now(UTC)
    article.updated_at = datetime.now(UTC)
    return article


@pytest.fixture
def sample_pipeline_state():
    """Sample pipeline state for testing."""
    from modules.ingestion.domain.models import ArticleRaw
    from modules.processing.pipeline.state import PipelineState

    raw = ArticleRaw(
        url="https://example.com/pipeline-test",
        title="Pipeline Test Article",
        body="Content for pipeline testing",
        source="test_source",
        publish_time=datetime.now(UTC),
        source_host="example.com",
    )
    return PipelineState(raw=raw)


@pytest.fixture
def mock_llm_client():
    """Mock LLM client for testing."""
    llm = MagicMock()
    llm.call = AsyncMock(return_value='{"result": "success"}')
    llm.call_with_fallback = AsyncMock(return_value='{"result": "success"}')
    llm.embed = AsyncMock(return_value=[0.1] * 1536)
    return llm


@pytest.fixture(scope="module")
def mock_settings():
    """Mock settings for testing - module scoped for performance."""
    settings = MagicMock()
    settings.api.api_key = "test-api-key"
    settings.llm.model = "gpt-4"
    settings.llm.provider = "openai"
    settings.redis.url = "redis://localhost:6379"
    settings.postgres.url = "postgresql://localhost/weaver"
    settings.neo4j.uri = "bolt://localhost:7687"
    return settings


@pytest.fixture
def mock_circuit_breaker():
    """Mock circuit breaker for testing."""
    from core.resilience.circuit_breaker import CBState, CircuitBreaker

    cb = MagicMock(spec=CircuitBreaker)
    cb.state = CBState.CLOSED
    cb.can_execute = MagicMock(return_value=True)
    cb.record_success = MagicMock()
    cb.record_failure = MagicMock()
    return cb


@pytest.fixture
def mock_rate_limiter():
    """Mock rate limiter for testing."""
    from core.resilience.rate_limiter import RedisTokenBucket

    limiter = MagicMock(spec=RedisTokenBucket)
    limiter.consume = AsyncMock(return_value=True)
    limiter.get_tokens = AsyncMock(return_value=100)
    return limiter


@pytest.fixture
def mock_token_budget_manager():
    """Mock token budget manager for testing."""
    from core.llm.token_budget import TokenBudgetManager

    manager = MagicMock(spec=TokenBudgetManager)
    manager.count_tokens = MagicMock(return_value=100)
    manager.truncate_text = MagicMock(return_value="truncated text")
    manager.build_messages = MagicMock(
        return_value=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "user"},
        ]
    )
    return manager


@pytest.fixture
def mock_spacy_extractor():
    """Mock spaCy extractor for testing."""
    extractor = MagicMock()
    extractor.extract = MagicMock(
        return_value=[
            {"text": "OpenAI", "label": "ORG", "start": 0, "end": 6},
            {"text": "GPT-4", "label": "PRODUCT", "start": 10, "end": 15},
        ]
    )
    return extractor


@pytest.fixture(scope="module")
def mock_embedder():
    """Mock embedder for testing - module scoped for performance."""
    embedder = MagicMock()
    embedder.embed = AsyncMock(return_value=[0.1] * 1536)
    embedder.embed_batch = AsyncMock(return_value=[[0.1] * 1536 for _ in range(5)])
    return embedder


def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line("markers", "asyncio: mark test as async")
    config.addinivalue_line("markers", "unit: mark test as unit test")
    config.addinivalue_line("markers", "integration: mark test as integration test")
    config.addinivalue_line("markers", "e2e: mark test as end-to-end test")
    config.addinivalue_line("markers", "slow: mark test as slow running")
    config.addinivalue_line(
        "markers", "no_parallel: mark test as not suitable for parallel execution"
    )
    config.addinivalue_line("markers", "describe: mark test class as describing a feature")
    config.addinivalue_line("markers", "it: mark test method as a specific behavior")


def pytest_collection_modifyitems(config, items):
    """Add markers to tests based on file location."""
    for item in items:
        if "unit" in str(item.fspath):
            item.add_marker(pytest.mark.unit)
        elif "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        elif "e2e" in str(item.fspath):
            item.add_marker(pytest.mark.e2e)


def pytest_sessionfinish(session, exitstatus):
    """Global cleanup hook that runs after all tests complete.

    Ensures all background asyncio tasks are cancelled before pytest exits.
    This hook runs even when tests fail.
    """
    log.info("session_cleanup_starting", exit_status=exitstatus)

    # Get the current event loop if one exists
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If loop is still running, schedule cleanup
            asyncio.run_coroutine_threadsafe(cancel_all_tasks(), loop).result(timeout=10)
        else:
            # If loop is not running, run cleanup directly
            loop.run_until_complete(cancel_all_tasks())
        log.info("session_cleanup_complete")
    except RuntimeError as e:
        # No event loop exists, which is fine
        log.debug("no_event_loop_during_cleanup", error=str(e))
    except Exception as e:
        log.warning(
            "session_cleanup_error",
            error=str(e),
            message="Cleanup encountered errors but continuing shutdown",
        )
