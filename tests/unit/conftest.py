# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Pytest configuration and shared fixtures for unit tests.

This conftest.py provides common fixtures available to all unit tests,
reducing duplication across test files.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_settings():
    """Create standard mock settings for unit tests.

    Provides a fully configured MagicMock with common settings sections:
    - api: API configuration
    - llm: LLM provider configuration
    - redis: Redis connection settings
    - postgres: PostgreSQL connection settings
    - neo4j: Neo4j connection settings

    Usage:
        def test_something(mock_settings):
            # Use mock_settings in your test
            pass
    """
    settings = MagicMock()
    settings.api.api_key = "test-api-key"
    settings.llm.model = "gpt-4"
    settings.llm.provider = "openai"
    settings.llm.providers = {
        "openai": MagicMock(api_key="test-key", base_url=None),
    }
    settings.redis.url = "redis://localhost:6379"
    settings.postgres.dsn = "postgresql+asyncpg://user:pass@localhost:5432/weaver"
    settings.neo4j.uri = "bolt://localhost:7687"
    settings.neo4j.user = "neo4j"
    settings.neo4j.password = "password"
    return settings


@pytest.fixture
def mock_llm():
    """Create standard mock LLM client for unit tests.

    Provides AsyncMock with common LLM methods:
    - call: Standard LLM call
    - call_with_fallback: LLM call with fallback
    - embed: Embedding generation

    Usage:
        @pytest.mark.asyncio
        async def test_llm_call(mock_llm):
            mock_llm.call.return_value = '{"result": "success"}'
            # Use mock_llm in your test
            pass
    """
    llm = AsyncMock()
    llm.call = AsyncMock(return_value='{"result": "success"}')
    llm.call_with_fallback = AsyncMock(return_value='{"result": "success"}')
    llm.embed = AsyncMock(return_value=[0.1] * 1536)
    return llm


@pytest.fixture
def mock_redis():
    """Create standard mock Redis client for unit tests.

    Delegates to tests.helpers.create_mock_redis_client() for consistency.

    Usage:
        def test_redis_ops(mock_redis):
            # Use mock_redis.client.get(), mock_redis.client.set(), etc.
            pass
    """
    from tests.helpers import create_mock_redis_client

    return create_mock_redis_client()


@pytest.fixture
def mock_postgres_session():
    """Create standard mock PostgreSQL session for unit tests.

    Provides AsyncMock with common session methods:
    - execute: Execute SQL queries
    - commit: Commit transaction
    - rollback: Rollback transaction
    - refresh: Refresh object state

    Usage:
        @pytest.mark.asyncio
        async def test_db_ops(mock_postgres_session):
            mock_postgres_session.execute.return_value = []
            # Use mock_postgres_session in your test
            pass
    """
    from tests.helpers import create_mock_postgres_session

    return create_mock_postgres_session()


@pytest.fixture
def mock_graph_session():
    """Create standard mock Neo4j/graph session for unit tests.

    Provides AsyncMock with common graph database methods:
    - run: Execute Cypher queries
    - close: Close session

    Usage:
        @pytest.mark.asyncio
        async def test_graph_query(mock_graph_session):
            mock_graph_session.run.return_value = []
            # Use mock_graph_session in your test
            pass
    """
    from tests.helpers import create_mock_neo4j_session

    return create_mock_neo4j_session()


@pytest.fixture
def mock_circuit_breaker():
    """Create standard mock circuit breaker for unit tests.

    Provides MagicMock configured with:
    - state: CLOSED (normal operation)
    - can_execute: Returns True
    - record_success/failure: No-op mocks

    Usage:
        def test_cb_logic(mock_circuit_breaker):
            # Use mock_circuit_breaker in your test
            pass
    """
    from core.resilience import CBState, CircuitBreaker

    cb = MagicMock(spec=CircuitBreaker)
    cb.state = CBState.CLOSED
    cb.can_execute = MagicMock(return_value=True)
    cb.record_success = MagicMock()
    cb.record_failure = MagicMock()
    return cb


# ────────────────────────────────────────────────────────────
# Helper functions for creating parameterized settings
# ────────────────────────────────────────────────────────────


def create_settings_with_llm_provider(
    provider: str = "openai",
    model: str = "gpt-4",
    base_url: str | None = None,
) -> MagicMock:
    """Helper to create settings with specific LLM provider configuration.

    Use this in parameterized tests to test multiple provider configurations.

    Args:
        provider: LLM provider name (openai, ollama, anthropic, etc.)
        model: Model name
        base_url: Optional base URL for the provider

    Returns:
        MagicMock configured with the specified provider

    Example:
        @pytest.mark.parametrize("provider", ["openai", "ollama", "anthropic"])
        def test_multiple_providers(provider):
            settings = create_settings_with_llm_provider(provider)
            # Test with different providers
            pass
    """
    settings = MagicMock()
    settings.llm.provider = provider
    settings.llm.model = model
    settings.llm.providers = {
        provider: MagicMock(api_key="test-key", base_url=base_url),
    }
    return settings
