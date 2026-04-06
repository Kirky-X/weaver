# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for environment validator module."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from core.constants import Defaults, LLMProvider
from core.health.env_validator import (
    Colors,
    EnvironmentValidator,
    ValidationCache,
    ValidationResult,
    validate_environment,
)

# ────────────────────────────────────────────────────────────
# Tests for Colors
# ────────────────────────────────────────────────────────────


class TestColors:
    """Tests for Colors ANSI codes."""

    def test_color_constants_exist(self):
        """Test all color constants are defined."""
        assert Colors.GREEN == "\033[92m"
        assert Colors.RED == "\033[91m"
        assert Colors.YELLOW == "\033[93m"
        assert Colors.BLUE == "\033[94m"
        assert Colors.CYAN == "\033[96m"
        assert Colors.RESET == "\033[0m"
        assert Colors.BOLD == "\033[1m"

    def test_reset_code(self):
        """Test reset code clears formatting."""
        assert Colors.RESET == "\033[0m"


# ────────────────────────────────────────────────────────────
# Tests for ValidationResult
# ────────────────────────────────────────────────────────────


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_default_values(self):
        """Test ValidationResult with default values."""
        result = ValidationResult(service="TestService", healthy=True)

        assert result.service == "TestService"
        assert result.healthy is True
        assert result.details == []
        assert result.suggestions == []
        assert result.latency_ms is None

    def test_with_details(self):
        """Test ValidationResult with details."""
        result = ValidationResult(
            service="PostgreSQL",
            healthy=True,
            details=["✓ Connection successful", "✓ Database: weaver"],
        )

        assert len(result.details) == 2
        assert "Connection successful" in result.details[0]

    def test_with_suggestions(self):
        """Test ValidationResult with suggestions."""
        result = ValidationResult(
            service="Redis",
            healthy=False,
            suggestions=["Check if Redis is running", "Verify credentials"],
        )

        assert len(result.suggestions) == 2

    def test_with_latency(self):
        """Test ValidationResult with latency measurement."""
        result = ValidationResult(service="Neo4j", healthy=True, latency_ms=42.5)

        assert result.latency_ms == 42.5
        assert isinstance(result.latency_ms, float)

    def test_unhealthy_with_failed_details(self):
        """Test unhealthy result with failure details."""
        result = ValidationResult(
            service="PostgreSQL",
            healthy=False,
            details=["✗ Connection failed: Connection refused"],
            suggestions=["Check if PostgreSQL is running"],
        )

        assert result.healthy is False
        assert any("failed" in d for d in result.details)


# ────────────────────────────────────────────────────────────
# Tests for ValidationCache
# ────────────────────────────────────────────────────────────


class TestValidationCache:
    """Tests for ValidationCache."""

    @pytest.fixture
    def cache(self):
        """Create a validation cache instance."""
        return ValidationCache(ttl_minutes=5)

    @pytest.fixture
    def sample_result(self):
        """Create a sample validation result."""
        return ValidationResult(service="Test", healthy=True, details=["✓ OK"])

    def test_cache_initialization(self):
        """Test cache initializes with default TTL."""
        cache = ValidationCache()
        assert cache._ttl == timedelta(minutes=5)

    def test_cache_initialization_custom_ttl(self):
        """Test cache initializes with custom TTL."""
        cache = ValidationCache(ttl_minutes=10)
        assert cache._ttl == timedelta(minutes=10)

    def test_get_returns_none_for_missing_key(self, cache):
        """Test get returns None for non-existent key."""
        result = cache.get("nonexistent")
        assert result is None

    def test_set_and_get(self, cache, sample_result):
        """Test set and get operations."""
        cache.set("test_key", sample_result)

        result = cache.get("test_key")
        assert result is sample_result
        assert result.service == "Test"
        assert result.healthy is True

    def test_cache_returns_same_instance(self, cache, sample_result):
        """Test cache returns the exact same result instance."""
        cache.set("key", sample_result)
        retrieved = cache.get("key")
        assert retrieved is sample_result

    def test_cache_expiry(self, sample_result):
        """Test cache entry expires after TTL."""
        cache = ValidationCache(ttl_minutes=1)

        # Manually set an expired entry
        expired_time = datetime.now() - timedelta(minutes=2)
        cache._cache["expired_key"] = (sample_result, expired_time)

        result = cache.get("expired_key")
        assert result is None
        assert "expired_key" not in cache._cache

    def test_cache_does_not_expire_before_ttl(self, sample_result):
        """Test cache entry does not expire before TTL."""
        cache = ValidationCache(ttl_minutes=5)

        # Set a recent entry
        recent_time = datetime.now() - timedelta(minutes=2)
        cache._cache["recent_key"] = (sample_result, recent_time)

        result = cache.get("recent_key")
        assert result is sample_result

    def test_clear_removes_all_entries(self, cache, sample_result):
        """Test clear removes all cached entries."""
        cache.set("key1", sample_result)
        cache.set("key2", sample_result)
        cache.set("key3", sample_result)

        assert len(cache._cache) == 3

        cache.clear()

        assert len(cache._cache) == 0
        assert cache.get("key1") is None
        assert cache.get("key2") is None

    def test_multiple_keys_stored_separately(self, cache):
        """Test multiple keys are stored separately."""
        result1 = ValidationResult(service="Service1", healthy=True)
        result2 = ValidationResult(service="Service2", healthy=False)

        cache.set("key1", result1)
        cache.set("key2", result2)

        assert cache.get("key1").service == "Service1"
        assert cache.get("key2").service == "Service2"

    def test_overwrite_existing_key(self, cache):
        """Test overwriting existing cache key."""
        result1 = ValidationResult(service="Original", healthy=True)
        result2 = ValidationResult(service="Updated", healthy=False)

        cache.set("key", result1)
        cache.set("key", result2)

        result = cache.get("key")
        assert result.service == "Updated"
        assert result.healthy is False


# ────────────────────────────────────────────────────────────
# Tests for EnvironmentValidator
# ────────────────────────────────────────────────────────────


class TestEnvironmentValidatorInit:
    """Tests for EnvironmentValidator initialization."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings."""
        settings = MagicMock()
        settings.postgres = MagicMock()
        settings.postgres.dsn = "postgresql+asyncpg://user:pass@localhost:5432/weaver"
        settings.neo4j = MagicMock()
        settings.neo4j.uri = "bolt://localhost:7687"
        settings.neo4j.user = "neo4j"
        settings.neo4j.password = "password"
        settings.redis = MagicMock()
        settings.redis.url = "redis://localhost:6379/0"
        settings.llm = MagicMock()
        settings.llm.providers = {}
        settings.llm.embedding_provider = "openai"
        settings.llm.embedding_model = "text-embedding-3-small"
        return settings

    def test_initialization(self, mock_settings):
        """Test validator initializes correctly."""
        validator = EnvironmentValidator(mock_settings)

        assert validator._settings is mock_settings
        assert validator._cache._ttl == timedelta(minutes=5)

    def test_initialization_custom_ttl(self, mock_settings):
        """Test validator with custom cache TTL."""
        validator = EnvironmentValidator(mock_settings, cache_ttl_minutes=10)

        assert validator._cache._ttl == timedelta(minutes=10)


def _create_mock_settings():
    """Create a standard mock settings object."""
    settings = MagicMock()
    settings.postgres = MagicMock()
    settings.postgres.dsn = "postgresql+asyncpg://user:pass@localhost:5432/weaver"
    settings.neo4j = MagicMock()
    settings.neo4j.uri = "bolt://localhost:7687"
    settings.neo4j.user = "neo4j"
    settings.neo4j.password = "password"
    settings.redis = MagicMock()
    settings.redis.url = "redis://localhost:6379/0"
    settings.llm = MagicMock()
    settings.llm.providers = {}
    settings.llm.embedding_provider = "openai"
    settings.llm.embedding_model = "text-embedding-3-small"
    return settings


class TestValidatePostgres:
    """Tests for PostgreSQL validation."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings."""
        return _create_mock_settings()

    @pytest.fixture
    def validator(self, mock_settings):
        """Create validator instance."""
        return EnvironmentValidator(mock_settings)

    @pytest.mark.asyncio
    async def test_postgres_connection_success_with_pgvector(self, validator):
        """Test successful PostgreSQL connection with pgvector."""
        mock_engine = MagicMock()
        mock_conn = AsyncMock()

        # Mock execute responses
        select_result = MagicMock()
        select_result.fetchone = MagicMock(return_value=True)

        ext_result = MagicMock()
        ext_result.fetchone = MagicMock(return_value=("vector",))

        mock_conn.execute = AsyncMock(side_effect=[select_result, ext_result])

        # Create async context manager for connection
        async_conn_cm = AsyncMock()
        async_conn_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        async_conn_cm.__aexit__ = AsyncMock(return_value=None)
        mock_engine.connect = MagicMock(return_value=async_conn_cm)

        mock_engine.dispose = AsyncMock()

        with patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_engine):
            result = await validator.validate_postgres()

        assert result.healthy is True
        assert result.service == "PostgreSQL"
        assert any("Connection successful" in d for d in result.details)
        assert any("pgvector extension available" in d for d in result.details)
        assert result.latency_ms is not None

    @pytest.mark.asyncio
    async def test_postgres_connection_success_without_pgvector(self, validator):
        """Test PostgreSQL connection without pgvector extension."""
        mock_engine = MagicMock()
        mock_conn = AsyncMock()

        select_result = MagicMock()
        select_result.fetchone = MagicMock(return_value=True)

        ext_result = MagicMock()
        ext_result.fetchone = MagicMock(return_value=None)

        mock_conn.execute = AsyncMock(side_effect=[select_result, ext_result])

        async_conn_cm = AsyncMock()
        async_conn_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        async_conn_cm.__aexit__ = AsyncMock(return_value=None)
        mock_engine.connect = MagicMock(return_value=async_conn_cm)

        mock_engine.dispose = AsyncMock()

        with patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_engine):
            result = await validator.validate_postgres()

        assert result.healthy is False
        assert any("pgvector extension not installed" in d for d in result.details)
        assert any("CREATE EXTENSION" in s for s in result.suggestions)

    @pytest.mark.asyncio
    async def test_postgres_connection_refused(self, validator):
        """Test PostgreSQL connection refused error."""
        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(side_effect=Exception("Connection refused: localhost:5432"))

        async_conn_cm = AsyncMock()
        async_conn_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        async_conn_cm.__aexit__ = AsyncMock(return_value=None)
        mock_engine.connect = MagicMock(return_value=async_conn_cm)

        mock_engine.dispose = AsyncMock()

        with patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_engine):
            with patch("asyncio.sleep", AsyncMock()):
                result = await validator.validate_postgres()

        assert result.healthy is False
        assert any("Connection failed" in d for d in result.details)
        assert any("Check if PostgreSQL is running" in s for s in result.suggestions)

    @pytest.mark.asyncio
    async def test_postgres_authentication_failed(self, validator):
        """Test PostgreSQL authentication failure."""
        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(side_effect=Exception("authentication failed for user"))

        async_conn_cm = AsyncMock()
        async_conn_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        async_conn_cm.__aexit__ = AsyncMock(return_value=None)
        mock_engine.connect = MagicMock(return_value=async_conn_cm)

        mock_engine.dispose = AsyncMock()

        with patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_engine):
            with patch("asyncio.sleep", AsyncMock()):
                result = await validator.validate_postgres()

        assert result.healthy is False
        assert any("Check PostgreSQL credentials" in s for s in result.suggestions)

    @pytest.mark.asyncio
    async def test_postgres_general_error(self, validator):
        """Test PostgreSQL general error."""
        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(side_effect=Exception("Unknown error"))

        async_conn_cm = AsyncMock()
        async_conn_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        async_conn_cm.__aexit__ = AsyncMock(return_value=None)
        mock_engine.connect = MagicMock(return_value=async_conn_cm)

        mock_engine.dispose = AsyncMock()

        with patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_engine):
            with patch("asyncio.sleep", AsyncMock()):
                result = await validator.validate_postgres()

        assert result.healthy is False
        assert any("Check PostgreSQL service status" in s for s in result.suggestions)

    @pytest.mark.asyncio
    async def test_postgres_latency_measured(self, validator):
        """Test PostgreSQL latency is measured."""
        mock_engine = MagicMock()
        mock_conn = AsyncMock()

        select_result = MagicMock()
        select_result.fetchone = MagicMock(return_value=True)

        ext_result = MagicMock()
        ext_result.fetchone = MagicMock(return_value=("vector",))

        mock_conn.execute = AsyncMock(side_effect=[select_result, ext_result])

        async_conn_cm = AsyncMock()
        async_conn_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        async_conn_cm.__aexit__ = AsyncMock(return_value=None)
        mock_engine.connect = MagicMock(return_value=async_conn_cm)

        mock_engine.dispose = AsyncMock()

        with patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_engine):
            result = await validator.validate_postgres()

        assert result.latency_ms is not None
        assert isinstance(result.latency_ms, float)
        assert result.latency_ms >= 0


class TestValidateNeo4j:
    """Tests for Neo4j validation."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings."""
        return _create_mock_settings()

    @pytest.fixture
    def validator(self, mock_settings):
        """Create validator instance."""
        return EnvironmentValidator(mock_settings)

    @pytest.mark.asyncio
    async def test_neo4j_connection_success(self, validator):
        """Test successful Neo4j connection."""
        mock_driver = MagicMock()
        mock_driver.verify_connectivity = AsyncMock()
        mock_driver.close = AsyncMock()

        with patch("neo4j.AsyncGraphDatabase.driver", return_value=mock_driver):
            result = await validator.validate_neo4j()

        assert result.healthy is True
        assert result.service == "Neo4j"
        assert any("Connection successful" in d for d in result.details)
        assert any("bolt://localhost:7687" in d for d in result.details)
        assert result.latency_ms is not None

    @pytest.mark.asyncio
    async def test_neo4j_connection_refused(self, validator):
        """Test Neo4j connection refused error."""
        mock_driver = MagicMock()
        mock_driver.verify_connectivity = AsyncMock(side_effect=Exception("Connection refused"))
        mock_driver.close = AsyncMock()

        with patch("neo4j.AsyncGraphDatabase.driver", return_value=mock_driver):
            with patch("asyncio.sleep", AsyncMock()):
                result = await validator.validate_neo4j()

        assert result.healthy is False
        assert any("Check if Neo4j is running" in s for s in result.suggestions)

    @pytest.mark.asyncio
    async def test_neo4j_authentication_error(self, validator):
        """Test Neo4j authentication failure."""
        mock_driver = MagicMock()
        mock_driver.verify_connectivity = AsyncMock(side_effect=Exception("authentication failed"))
        mock_driver.close = AsyncMock()

        with patch("neo4j.AsyncGraphDatabase.driver", return_value=mock_driver):
            with patch("asyncio.sleep", AsyncMock()):
                result = await validator.validate_neo4j()

        assert result.healthy is False
        assert any("Check Neo4j credentials" in s for s in result.suggestions)

    @pytest.mark.asyncio
    async def test_neo4j_general_error(self, validator):
        """Test Neo4j general error."""
        mock_driver = MagicMock()
        mock_driver.verify_connectivity = AsyncMock(side_effect=Exception("Unknown error"))
        mock_driver.close = AsyncMock()

        with patch("neo4j.AsyncGraphDatabase.driver", return_value=mock_driver):
            with patch("asyncio.sleep", AsyncMock()):
                result = await validator.validate_neo4j()

        assert result.healthy is False
        assert any("Check Neo4j service status" in s for s in result.suggestions)


class TestValidateRedis:
    """Tests for Redis validation."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings."""
        return _create_mock_settings()

    @pytest.fixture
    def validator(self, mock_settings):
        """Create validator instance."""
        return EnvironmentValidator(mock_settings)

    @pytest.mark.asyncio
    async def test_redis_connection_success(self, validator):
        """Test successful Redis connection."""
        mock_pool = MagicMock()
        mock_pool.disconnect = AsyncMock()

        mock_redis = MagicMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.aclose = AsyncMock()

        with (
            patch("redis.asyncio.ConnectionPool.from_url", return_value=mock_pool),
            patch("redis.asyncio.Redis", return_value=mock_redis),
        ):
            result = await validator.validate_redis()

        assert result.healthy is True
        assert result.service == "Redis"
        assert any("Connection successful" in d for d in result.details)
        assert result.latency_ms is not None

    @pytest.mark.asyncio
    async def test_redis_connection_refused(self, validator):
        """Test Redis connection refused error."""
        mock_pool = MagicMock()
        mock_pool.disconnect = AsyncMock()

        mock_redis = MagicMock()
        mock_redis.ping = AsyncMock(side_effect=Exception("Connection refused"))
        mock_redis.aclose = AsyncMock()

        with (
            patch("redis.asyncio.ConnectionPool.from_url", return_value=mock_pool),
            patch("redis.asyncio.Redis", return_value=mock_redis),
            patch("asyncio.sleep", AsyncMock()),
        ):
            result = await validator.validate_redis()

        assert result.healthy is False
        assert any("Check if Redis is running" in s for s in result.suggestions)

    @pytest.mark.asyncio
    async def test_redis_general_error(self, validator):
        """Test Redis general error."""
        mock_pool = MagicMock()
        mock_pool.disconnect = AsyncMock()

        mock_redis = MagicMock()
        mock_redis.ping = AsyncMock(side_effect=Exception("Unknown error"))
        mock_redis.aclose = AsyncMock()

        with (
            patch("redis.asyncio.ConnectionPool.from_url", return_value=mock_pool),
            patch("redis.asyncio.Redis", return_value=mock_redis),
            patch("asyncio.sleep", AsyncMock()),
        ):
            result = await validator.validate_redis()

        assert result.healthy is False
        assert any("Check Redis service status" in s for s in result.suggestions)

    @pytest.mark.asyncio
    async def test_redis_database_number_extracted(self, validator):
        """Test Redis database number is extracted from URL."""
        mock_pool = MagicMock()
        mock_pool.disconnect = AsyncMock()

        mock_redis = MagicMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.aclose = AsyncMock()

        with (
            patch("redis.asyncio.ConnectionPool.from_url", return_value=mock_pool),
            patch("redis.asyncio.Redis", return_value=mock_redis),
        ):
            result = await validator.validate_redis()

        assert any("Database: 0" in d for d in result.details)


class TestValidateLLM:
    """Tests for LLM validation."""

    @pytest.fixture
    def mock_settings_openai(self):
        """Create mock settings with OpenAI provider."""
        settings = _create_mock_settings()
        settings.llm.providers = {
            "openai_primary": {
                "provider": LLMProvider.OPENAI.value,
                "model": "gpt-4",
                "base_url": "https://api.openai.com/v1",
                "api_key": "test-api-key",
            }
        }
        return settings

    @pytest.fixture
    def mock_settings_ollama(self):
        """Create mock settings with Ollama provider."""
        settings = _create_mock_settings()
        settings.llm.providers = {
            "ollama_local": {
                "provider": LLMProvider.OLLAMA.value,
                "model": "llama2",
                "base_url": "http://localhost:11434",
            }
        }
        return settings

    @pytest.fixture
    def mock_settings_anthropic(self):
        """Create mock settings with Anthropic provider."""
        settings = _create_mock_settings()
        settings.llm.providers = {
            "anthropic_primary": {
                "provider": LLMProvider.ANTHROPIC.value,
                "model": "claude-3-sonnet",
                "base_url": "https://api.anthropic.com",
            }
        }
        return settings

    @pytest.fixture
    def mock_settings_no_providers(self):
        """Create mock settings without providers."""
        settings = _create_mock_settings()
        settings.llm.providers = {}
        return settings

    @pytest.mark.asyncio
    async def test_llm_no_providers_configured(self, mock_settings_no_providers):
        """Test LLM validation when no providers configured."""
        validator = EnvironmentValidator(mock_settings_no_providers)
        result = await validator.validate_llm()

        assert result.healthy is False
        assert any("No LLM providers configured" in d for d in result.details)
        assert any("Configure at least one LLM provider" in s for s in result.suggestions)

    @pytest.mark.asyncio
    async def test_llm_openai_success(self, mock_settings_openai):
        """Test successful OpenAI validation."""
        validator = EnvironmentValidator(mock_settings_openai)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(
            return_value={"data": [{"id": "gpt-4"}, {"id": "gpt-3.5-turbo"}]}
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await validator.validate_llm()

        assert result.healthy is True
        assert any("API key valid" in d for d in result.details)
        assert any("Model gpt-4 available" in d for d in result.details)

    @pytest.mark.asyncio
    async def test_llm_openai_model_not_found(self, mock_settings_openai):
        """Test OpenAI validation when model not found."""
        validator = EnvironmentValidator(mock_settings_openai)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"data": [{"id": "gpt-3.5-turbo"}]})

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await validator.validate_llm()

        assert result.healthy is True
        assert any("Model gpt-4 not found" in d for d in result.details)

    @pytest.mark.asyncio
    async def test_llm_openai_no_api_key(self, mock_settings_openai):
        """Test OpenAI validation without API key."""
        mock_settings_openai.llm.providers["openai_primary"]["api_key"] = ""
        validator = EnvironmentValidator(mock_settings_openai)

        result = await validator.validate_llm()

        assert result.healthy is False
        assert any("API key not configured" in d for d in result.details)
        assert any("Set OpenAI API key" in s for s in result.suggestions)

    @pytest.mark.asyncio
    async def test_llm_openai_api_error(self, mock_settings_openai):
        """Test OpenAI validation when API returns error."""
        validator = EnvironmentValidator(mock_settings_openai)

        mock_response = MagicMock()
        mock_response.status_code = 401

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await validator.validate_llm()

        assert result.healthy is False
        assert any("API returned status 401" in d for d in result.details)
        assert any("Check API key and base URL" in s for s in result.suggestions)

    @pytest.mark.asyncio
    async def test_llm_ollama_success(self, mock_settings_ollama):
        """Test successful Ollama validation."""
        validator = EnvironmentValidator(mock_settings_ollama)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"models": [{"name": "llama2:latest"}]})

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await validator.validate_llm()

        assert result.healthy is True
        assert any("Model llama2 available" in d for d in result.details)

    @pytest.mark.asyncio
    async def test_llm_ollama_model_not_found(self, mock_settings_ollama):
        """Test Ollama validation when model not pulled."""
        validator = EnvironmentValidator(mock_settings_ollama)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"models": [{"name": "other-model"}]})

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await validator.validate_llm()

        assert result.healthy is True
        assert any("Model llama2 not found" in d for d in result.details)
        assert any("ollama pull llama2" in s for s in result.suggestions)

    @pytest.mark.asyncio
    async def test_llm_ollama_server_error(self, mock_settings_ollama):
        """Test Ollama validation when server returns error."""
        validator = EnvironmentValidator(mock_settings_ollama)

        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with patch("asyncio.sleep", AsyncMock()):
                result = await validator.validate_llm()

        assert result.healthy is False

    @pytest.mark.asyncio
    async def test_llm_anthropic_success(self, mock_settings_anthropic):
        """Test successful Anthropic validation."""
        validator = EnvironmentValidator(mock_settings_anthropic)

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await validator.validate_llm()

        assert result.healthy is True
        assert any("Provider accessible" in d for d in result.details)

    @pytest.mark.asyncio
    async def test_llm_unknown_provider(self):
        """Test validation with unknown provider type."""
        settings = _create_mock_settings()
        settings.llm.providers = {
            "unknown": {
                "provider": "unknown_provider",
                "model": "unknown-model",
                "base_url": "http://unknown",
            }
        }

        validator = EnvironmentValidator(settings)
        result = await validator.validate_llm()

        assert result.healthy is False
        assert any("Unknown provider type" in d for d in result.details)
        assert any("Configure a supported provider" in s for s in result.suggestions)

    @pytest.mark.asyncio
    async def test_llm_connection_error(self, mock_settings_openai):
        """Test LLM validation with connection error."""
        validator = EnvironmentValidator(mock_settings_openai)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection failed"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with patch("asyncio.sleep", AsyncMock()):
                result = await validator.validate_llm()

        assert result.healthy is False
        assert any("Connection failed" in d for d in result.details)
        assert any("server is running" in s for s in result.suggestions)

    @pytest.mark.asyncio
    async def test_llm_general_exception(self, mock_settings_openai):
        """Test LLM validation with general exception."""
        validator = EnvironmentValidator(mock_settings_openai)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("Unexpected error"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with patch("asyncio.sleep", AsyncMock()):
                result = await validator.validate_llm()

        assert result.healthy is False
        assert any("Validation failed" in d for d in result.details)

    @pytest.mark.asyncio
    async def test_llm_cache_returns_cached_result(self, mock_settings_openai):
        """Test LLM validation returns cached result."""
        validator = EnvironmentValidator(mock_settings_openai)

        cached_result = ValidationResult(
            service="LLM",
            healthy=True,
            details=["Cached result"],
        )

        # Set cache manually
        cache_key = "llm:openai:gpt-4:https://api.openai.com/v1"
        validator._cache.set(cache_key, cached_result)

        result = await validator.validate_llm()

        # Should return cached result without making HTTP calls
        assert "Cached result" in result.details


class TestValidateEmbedding:
    """Tests for embedding validation."""

    @pytest.fixture
    def mock_settings_openai(self):
        """Create mock settings with OpenAI embedding provider."""
        settings = _create_mock_settings()
        settings.llm.providers = {
            "openai": {
                "provider": LLMProvider.OPENAI.value,
                "base_url": "https://api.openai.com/v1",
                "api_key": "test-api-key",
            }
        }
        settings.llm.embedding_provider = "openai"
        settings.llm.embedding_model = "text-embedding-3-small"
        return settings

    @pytest.fixture
    def mock_settings_ollama(self):
        """Create mock settings with Ollama embedding provider."""
        settings = _create_mock_settings()
        settings.llm.providers = {
            "ollama": {
                "provider": LLMProvider.OLLAMA.value,
                "base_url": "http://localhost:11434",
            }
        }
        settings.llm.embedding_provider = "ollama"
        settings.llm.embedding_model = "nomic-embed-text"
        return settings

    @pytest.fixture
    def mock_settings_provider_not_configured(self):
        """Create mock settings where embedding provider not in providers dict."""
        settings = _create_mock_settings()
        settings.llm.providers = {}
        settings.llm.embedding_provider = "missing_provider"
        settings.llm.embedding_model = "some-model"
        return settings

    @pytest.mark.asyncio
    async def test_embedding_provider_not_configured(self, mock_settings_provider_not_configured):
        """Test embedding validation when provider not configured."""
        validator = EnvironmentValidator(mock_settings_provider_not_configured)
        result = await validator.validate_embedding()

        assert result.healthy is False
        assert any("Provider 'missing_provider' not configured" in d for d in result.details)
        assert any("Configure 'missing_provider' provider" in s for s in result.suggestions)

    @pytest.mark.asyncio
    async def test_embedding_openai_success(self, mock_settings_openai):
        """Test successful OpenAI embedding validation."""
        validator = EnvironmentValidator(mock_settings_openai)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"data": [{"embedding": [0.1, 0.2, 0.3]}]})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await validator.validate_embedding()

        assert result.healthy is True
        assert any("API key valid" in d for d in result.details)
        assert any("text-embedding-3-small available" in d for d in result.details)

    @pytest.mark.asyncio
    async def test_embedding_openai_no_api_key(self, mock_settings_openai):
        """Test OpenAI embedding validation without API key."""
        mock_settings_openai.llm.providers["openai"]["api_key"] = ""
        validator = EnvironmentValidator(mock_settings_openai)

        result = await validator.validate_embedding()

        assert result.healthy is False
        assert any("API key not configured" in d for d in result.details)
        assert any("Set API key for embedding provider" in s for s in result.suggestions)

    @pytest.mark.asyncio
    async def test_embedding_openai_api_error(self, mock_settings_openai):
        """Test OpenAI embedding validation when API returns error."""
        validator = EnvironmentValidator(mock_settings_openai)

        mock_response = MagicMock()
        mock_response.status_code = 400

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with patch("asyncio.sleep", AsyncMock()):
                result = await validator.validate_embedding()

        assert result.healthy is False
        assert any("API returned status 400" in d for d in result.details)
        assert any("Check embedding model name" in s for s in result.suggestions)

    @pytest.mark.asyncio
    async def test_embedding_ollama_success(self, mock_settings_ollama):
        """Test successful Ollama embedding validation."""
        validator = EnvironmentValidator(mock_settings_ollama)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"embedding": [0.1, 0.2, 0.3]})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await validator.validate_embedding()

        assert result.healthy is True
        assert any("nomic-embed-text available" in d for d in result.details)

    @pytest.mark.asyncio
    async def test_embedding_ollama_server_error(self, mock_settings_ollama):
        """Test Ollama embedding validation when server returns error."""
        validator = EnvironmentValidator(mock_settings_ollama)

        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with patch("asyncio.sleep", AsyncMock()):
                result = await validator.validate_embedding()

        assert result.healthy is False
        assert any("Check if model" in s for s in result.suggestions)

    @pytest.mark.asyncio
    async def test_embedding_connection_error(self, mock_settings_openai):
        """Test embedding validation with connection error."""
        validator = EnvironmentValidator(mock_settings_openai)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection failed"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with patch("asyncio.sleep", AsyncMock()):
                result = await validator.validate_embedding()

        assert result.healthy is False
        assert any("Connection failed" in d for d in result.details)

    @pytest.mark.asyncio
    async def test_embedding_general_exception(self, mock_settings_openai):
        """Test embedding validation with general exception."""
        validator = EnvironmentValidator(mock_settings_openai)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("Unexpected error"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with patch("asyncio.sleep", AsyncMock()):
                result = await validator.validate_embedding()

        assert result.healthy is False
        assert any("Validation failed" in d for d in result.details)

    @pytest.mark.asyncio
    async def test_embedding_latency_measured(self, mock_settings_openai):
        """Test embedding latency is measured."""
        validator = EnvironmentValidator(mock_settings_openai)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"data": [{"embedding": []}]})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await validator.validate_embedding()

        assert result.latency_ms is not None
        assert isinstance(result.latency_ms, float)


class TestValidateAll:
    """Tests for validate_all method."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings."""
        settings = _create_mock_settings()
        settings.llm.providers = {
            "openai": {
                "provider": LLMProvider.OPENAI.value,
                "model": "gpt-4",
                "base_url": "https://api.openai.com/v1",
                "api_key": "test-key",
            }
        }
        return settings

    @pytest.fixture
    def validator(self, mock_settings):
        """Create validator instance."""
        return EnvironmentValidator(mock_settings)

    @pytest.mark.asyncio
    async def test_validate_all_runs_all_validators(self, validator):
        """Test validate_all runs all validators."""
        # Mock all validator methods to return quickly
        validator.validate_postgres = AsyncMock(
            return_value=ValidationResult(service="PostgreSQL", healthy=True)
        )
        validator.validate_neo4j = AsyncMock(
            return_value=ValidationResult(service="Neo4j", healthy=True)
        )
        validator.validate_redis = AsyncMock(
            return_value=ValidationResult(service="Redis", healthy=True)
        )
        validator.validate_llm = AsyncMock(
            return_value=ValidationResult(service="LLM", healthy=True)
        )
        validator.validate_embedding = AsyncMock(
            return_value=ValidationResult(service="Embedding", healthy=True)
        )

        results = await validator.validate_all()

        assert len(results) == 5
        assert "postgres" in results
        assert "neo4j" in results
        assert "redis" in results
        assert "llm" in results
        assert "embedding" in results

    @pytest.mark.asyncio
    async def test_validate_all_specific_services(self, validator):
        """Test validate_all with specific services."""
        validator.validate_postgres = AsyncMock(
            return_value=ValidationResult(service="PostgreSQL", healthy=True)
        )
        validator.validate_redis = AsyncMock(
            return_value=ValidationResult(service="Redis", healthy=True)
        )

        results = await validator.validate_all(services=["postgres", "redis"])

        assert len(results) == 2
        assert "postgres" in results
        assert "redis" in results
        assert "neo4j" not in results

    @pytest.mark.asyncio
    async def test_validate_all_handles_validator_exception(self, validator):
        """Test validate_all handles exceptions in validators."""
        validator.validate_postgres = AsyncMock(side_effect=Exception("Validator crashed"))
        validator.validate_neo4j = AsyncMock(
            return_value=ValidationResult(service="Neo4j", healthy=True)
        )

        results = await validator.validate_all()

        assert "postgres" in results
        assert results["postgres"].healthy is False
        assert any("Validation raised exception" in d for d in results["postgres"].details)

    @pytest.mark.asyncio
    async def test_validate_all_empty_services_list(self, validator):
        """Test validate_all with empty services list runs all validators."""
        # Empty list is falsy, so it runs all validators (same as None)
        validator.validate_postgres = AsyncMock(
            return_value=ValidationResult(service="PostgreSQL", healthy=True)
        )
        validator.validate_neo4j = AsyncMock(
            return_value=ValidationResult(service="Neo4j", healthy=True)
        )
        validator.validate_redis = AsyncMock(
            return_value=ValidationResult(service="Redis", healthy=True)
        )
        validator.validate_llm = AsyncMock(
            return_value=ValidationResult(service="LLM", healthy=True)
        )
        validator.validate_embedding = AsyncMock(
            return_value=ValidationResult(service="Embedding", healthy=True)
        )

        results = await validator.validate_all(services=[])

        assert len(results) == 5

    @pytest.mark.asyncio
    async def test_validate_all_unknown_service(self, validator):
        """Test validate_all with unknown service name."""
        validator.validate_postgres = AsyncMock(
            return_value=ValidationResult(service="PostgreSQL", healthy=True)
        )

        results = await validator.validate_all(services=["postgres", "unknown"])

        assert len(results) == 1
        assert "postgres" in results
        assert "unknown" not in results


class TestPrintReport:
    """Tests for print_report method."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings."""
        return _create_mock_settings()

    @pytest.fixture
    def validator(self, mock_settings):
        """Create validator instance."""
        return EnvironmentValidator(mock_settings)

    def test_print_report_healthy_services(self, validator, capsys):
        """Test print_report with healthy services."""
        results = {
            "postgres": ValidationResult(
                service="PostgreSQL",
                healthy=True,
                details=["✓ Connection successful"],
                latency_ms=10.5,
            ),
            "redis": ValidationResult(
                service="Redis",
                healthy=True,
                details=["✓ Connection successful"],
                latency_ms=5.2,
            ),
        }

        validator.print_report(results)

        captured = capsys.readouterr()
        assert "Environment Validation Report" in captured.out
        assert "All 2 services healthy" in captured.out

    def test_print_report_unhealthy_services(self, validator, capsys):
        """Test print_report with unhealthy services."""
        results = {
            "postgres": ValidationResult(
                service="PostgreSQL",
                healthy=False,
                details=["✗ Connection failed"],
                suggestions=["Check PostgreSQL service"],
            ),
            "redis": ValidationResult(
                service="Redis",
                healthy=True,
                details=["✓ Connection successful"],
            ),
        }

        validator.print_report(results)

        captured = capsys.readouterr()
        assert "1/2 services healthy" in captured.out
        assert "Suggestion" in captured.out

    def test_print_report_all_unhealthy(self, validator, capsys):
        """Test print_report when all services unhealthy."""
        results = {
            "postgres": ValidationResult(
                service="PostgreSQL",
                healthy=False,
                details=["✗ Connection failed"],
                suggestions=["Check PostgreSQL"],
            ),
        }

        validator.print_report(results)

        captured = capsys.readouterr()
        assert "0/1 services healthy" in captured.out

    def test_print_report_with_latency(self, validator, capsys):
        """Test print_report includes latency."""
        results = {
            "postgres": ValidationResult(
                service="PostgreSQL",
                healthy=True,
                details=["✓ OK"],
                latency_ms=42.5,
            ),
        }

        validator.print_report(results)

        captured = capsys.readouterr()
        assert "Latency" in captured.out
        assert "42.50ms" in captured.out

    def test_print_report_empty_results(self, validator, capsys):
        """Test print_report with empty results."""
        results = {}

        validator.print_report(results)

        captured = capsys.readouterr()
        assert "Environment Validation Report" in captured.out
        assert "All 0 services healthy" in captured.out


class TestGetExitCode:
    """Tests for get_exit_code method."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings."""
        return _create_mock_settings()

    @pytest.fixture
    def validator(self, mock_settings):
        """Create validator instance."""
        return EnvironmentValidator(mock_settings)

    def test_exit_code_all_healthy(self, validator):
        """Test exit code when all services healthy."""
        results = {
            "postgres": ValidationResult(service="PostgreSQL", healthy=True),
            "redis": ValidationResult(service="Redis", healthy=True),
        }

        exit_code = validator.get_exit_code(results)
        assert exit_code == 0

    def test_exit_code_some_unhealthy(self, validator):
        """Test exit code when some services unhealthy."""
        results = {
            "postgres": ValidationResult(service="PostgreSQL", healthy=True),
            "redis": ValidationResult(service="Redis", healthy=False),
        }

        exit_code = validator.get_exit_code(results)
        assert exit_code == 1

    def test_exit_code_all_unhealthy(self, validator):
        """Test exit code when all services unhealthy."""
        results = {
            "postgres": ValidationResult(service="PostgreSQL", healthy=False),
            "redis": ValidationResult(service="Redis", healthy=False),
        }

        exit_code = validator.get_exit_code(results)
        assert exit_code == 1

    def test_exit_code_empty_results(self, validator):
        """Test exit code with empty results."""
        results = {}

        exit_code = validator.get_exit_code(results)
        assert exit_code == 0  # No failures = success


# ────────────────────────────────────────────────────────────
# Tests for validate_environment convenience function
# ────────────────────────────────────────────────────────────


class TestValidateEnvironmentFunction:
    """Tests for validate_environment convenience function."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings."""
        return _create_mock_settings()

    @pytest.mark.asyncio
    async def test_validate_environment_with_settings(self, mock_settings):
        """Test validate_environment with provided settings."""
        with patch.object(
            EnvironmentValidator,
            "validate_all",
            return_value={
                "postgres": ValidationResult(service="PostgreSQL", healthy=True),
            },
        ):
            all_healthy, results = await validate_environment(
                settings=mock_settings,
                print_report=False,
            )

        assert all_healthy is True
        assert "postgres" in results

    @pytest.mark.asyncio
    async def test_validate_environment_without_settings(self):
        """Test validate_environment loads settings when not provided."""
        mock_settings = _create_mock_settings()

        with (
            patch("config.settings.Settings", return_value=mock_settings),
            patch.object(
                EnvironmentValidator,
                "validate_all",
                return_value={
                    "postgres": ValidationResult(service="PostgreSQL", healthy=True),
                },
            ),
        ):
            all_healthy, results = await validate_environment(print_report=False)

        assert all_healthy is True

    @pytest.mark.asyncio
    async def test_validate_environment_with_specific_services(self, mock_settings):
        """Test validate_environment with specific services."""
        with patch.object(
            EnvironmentValidator,
            "validate_all",
            return_value={
                "postgres": ValidationResult(service="PostgreSQL", healthy=True),
            },
        ):
            all_healthy, results = await validate_environment(
                settings=mock_settings,
                services=["postgres"],
                print_report=False,
            )

        assert "postgres" in results

    @pytest.mark.asyncio
    async def test_validate_environment_prints_report(self, mock_settings, capsys):
        """Test validate_environment prints report when requested."""
        with patch.object(
            EnvironmentValidator,
            "validate_all",
            return_value={
                "postgres": ValidationResult(service="PostgreSQL", healthy=True),
            },
        ):
            await validate_environment(settings=mock_settings, print_report=True)

        captured = capsys.readouterr()
        assert "Environment Validation Report" in captured.out

    @pytest.mark.asyncio
    async def test_validate_environment_returns_unhealthy(self, mock_settings):
        """Test validate_environment returns correct unhealthy status."""
        with patch.object(
            EnvironmentValidator,
            "validate_all",
            return_value={
                "postgres": ValidationResult(service="PostgreSQL", healthy=False),
            },
        ):
            all_healthy, results = await validate_environment(
                settings=mock_settings,
                print_report=False,
            )

        assert all_healthy is False


# ────────────────────────────────────────────────────────────
# Tests for Retry Logic
# ────────────────────────────────────────────────────────────


class TestRetryLogic:
    """Tests for retry logic in validation methods."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings."""
        settings = _create_mock_settings()
        settings.llm.providers = {
            "openai": {
                "provider": LLMProvider.OPENAI.value,
                "model": "gpt-4",
                "base_url": "https://api.openai.com/v1",
                "api_key": "test-key",
            }
        }
        return settings

    @pytest.fixture
    def validator(self, mock_settings):
        """Create validator instance."""
        return EnvironmentValidator(mock_settings)

    @pytest.mark.asyncio
    async def test_postgres_retries_on_transient_error(self, validator):
        """Test PostgreSQL retries on transient errors."""
        # Track connection attempts (each attempt creates a new connection)
        connection_attempts = 0

        def create_mock_engine(*args, **kwargs):
            nonlocal connection_attempts
            connection_attempts += 1

            mock_engine = MagicMock()
            mock_conn = AsyncMock()

            # First two connection attempts fail, third succeeds
            if connection_attempts < 3:
                mock_conn.execute = AsyncMock(side_effect=Exception("Connection refused"))
            else:
                # Third attempt succeeds with both queries
                select_result = MagicMock()
                select_result.fetchone = MagicMock(return_value=True)

                ext_result = MagicMock()
                ext_result.fetchone = MagicMock(return_value=("vector",))

                mock_conn.execute = AsyncMock(side_effect=[select_result, ext_result])

            async_conn_cm = AsyncMock()
            async_conn_cm.__aenter__ = AsyncMock(return_value=mock_conn)
            async_conn_cm.__aexit__ = AsyncMock(return_value=None)
            mock_engine.connect = MagicMock(return_value=async_conn_cm)
            mock_engine.dispose = AsyncMock()

            return mock_engine

        with patch("sqlalchemy.ext.asyncio.create_async_engine", side_effect=create_mock_engine):
            with patch("asyncio.sleep", AsyncMock()):
                result = await validator.validate_postgres()

        # Should succeed after 3 connection attempts
        assert connection_attempts == 3
        assert result.healthy is True

    @pytest.mark.asyncio
    async def test_postgres_fails_after_max_retries(self, validator):
        """Test PostgreSQL fails after max retries."""
        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(side_effect=Exception("Connection refused"))

        async_conn_cm = AsyncMock()
        async_conn_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        async_conn_cm.__aexit__ = AsyncMock(return_value=None)
        mock_engine.connect = MagicMock(return_value=async_conn_cm)
        mock_engine.dispose = AsyncMock()

        with patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_engine):
            with patch("asyncio.sleep", AsyncMock()):
                result = await validator.validate_postgres()

        assert result.healthy is False
