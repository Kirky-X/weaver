# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit test conftest - lightweight, no heavy resources.

This conftest provides:
- Mock fixtures for unit testing
- Sample data factories
- No real database/ML model connections

Memory footprint: ~200MB per xdist worker
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

# ────────────────────────────────────────────────────────────
# Mock service fixtures
# ────────────────────────────────────────────────────────────


@pytest.fixture
def mock_settings():
    """Create standard mock settings for unit tests."""
    settings = MagicMock()
    settings.api.api_key = "test-api-key"
    settings.llm.model = "gpt-4"
    settings.llm.provider = "openai"
    settings.llm.providers = {
        "openai": MagicMock(api_key="test-key", base_url=None),
    }
    settings.redis.url = "redis://localhost:6379"
    settings.postgres.dsn = "postgresql+asyncpg://user:pass@localhost:5432/weaver"
    settings.postgres.url = "postgresql://localhost/weaver"
    settings.neo4j.uri = "bolt://localhost:7687"
    settings.neo4j.user = "neo4j"
    settings.neo4j.password = "password"
    return settings


@pytest.fixture
def mock_llm():
    """Create standard mock LLM client for unit tests."""
    llm = AsyncMock()
    llm.call = AsyncMock(return_value='{"result": "success"}')
    llm.call_with_fallback = AsyncMock(return_value='{"result": "success"}')
    llm.embed = AsyncMock(return_value=[0.1] * 1536)
    return llm


@pytest.fixture
def mock_llm_client():
    """Mock LLM client for testing (alias for compatibility)."""
    llm = MagicMock()
    llm.call = AsyncMock(return_value='{"result": "success"}')
    llm.call_with_fallback = AsyncMock(return_value='{"result": "success"}')
    llm.embed = AsyncMock(return_value=[0.1] * 1536)
    return llm


@pytest.fixture
def mock_redis():
    """Create standard mock Redis client for unit tests."""
    from tests.helpers import create_mock_cache_client

    return create_mock_cache_client()


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


@pytest.fixture
def mock_postgres_session():
    """Create standard mock PostgreSQL session for unit tests."""
    from tests.helpers import create_mock_postgres_session

    return create_mock_postgres_session()


@pytest.fixture(scope="module")
def mock_graph_pool():
    """Mock graph database pool for testing - module scoped for performance."""
    pool = MagicMock()
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.run = AsyncMock()
    pool.session = MagicMock(return_value=session)
    pool.execute_query = AsyncMock(return_value=[])
    return pool


@pytest.fixture
def mock_graph_session():
    """Create standard mock Neo4j/graph session for unit tests."""
    from tests.helpers import create_mock_neo4j_session

    return create_mock_neo4j_session()


@pytest.fixture
def mock_circuit_breaker():
    """Create standard mock circuit breaker for unit tests."""
    from core.resilience import CBState, CircuitBreaker

    cb = MagicMock(spec=CircuitBreaker)
    cb.state = CBState.CLOSED
    cb.can_execute = MagicMock(return_value=True)
    cb.record_success = MagicMock()
    cb.record_failure = MagicMock()
    return cb


@pytest.fixture
def mock_rate_limiter():
    """Mock rate limiter for testing (aiolimiter AsyncLimiter)."""
    from aiolimiter import AsyncLimiter

    limiter = MagicMock(spec=AsyncLimiter)
    limiter.consume = AsyncMock(return_value=0.0)
    limiter.acquire = AsyncMock(return_value=None)
    return limiter


@pytest.fixture
def mock_token_budget_manager():
    """Mock token budget manager for testing."""
    from core.llm.config.token_budget import TokenBudgetManager

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


# ────────────────────────────────────────────────────────────
# Sample data fixtures
# ────────────────────────────────────────────────────────────


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
    from modules.ingestion.domain.models import RawArticle

    return RawArticle(
        url="https://example.com/article",
        title="Test Title",
        body="Test body content",
        source="test",
        source_host="example.com",
    )


@pytest.fixture
def sample_article():
    """Sample Article model for testing."""
    from core.db import Article

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
    from modules.ingestion.domain.models import RawArticle
    from modules.processing.pipeline.state import PipelineState

    raw = RawArticle(
        url="https://example.com/pipeline-test",
        title="Pipeline Test Article",
        body="Content for pipeline testing",
        source="test_source",
        publish_time=datetime.now(UTC),
        source_host="example.com",
    )
    return PipelineState(raw=raw)


# ────────────────────────────────────────────────────────────
# Helper functions
# ────────────────────────────────────────────────────────────


def create_settings_with_llm_provider(
    provider: str = "openai",
    model: str = "gpt-4",
    base_url: str | None = None,
) -> MagicMock:
    """Helper to create settings with specific LLM provider configuration."""
    settings = MagicMock()
    settings.llm.provider = provider
    settings.llm.model = model
    settings.llm.providers = {
        provider: MagicMock(api_key="test-key", base_url=base_url),
    }
    return settings
