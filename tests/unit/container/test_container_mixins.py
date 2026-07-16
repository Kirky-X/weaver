# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for container mixin modules.

Covers:
- ContainerPoolsMixin (pools.py): database strategy, pool access, cache init
- ContainerServicesMixin (services.py): lazy service initialization
- ContainerSearchMixin (search.py): search engine creation
- ContainerLifecycleMixin (lifecycle.py): startup/shutdown, event handlers
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.constants import DatabaseType

# ── Helpers ─────────────────────────────────────────────────────────────


def _make_container():
    """Create a Container instance with all private attrs set to None/False."""
    from src.container import Container

    c = Container()
    c._shutdown = False
    return c


def _make_settings(**overrides):
    """Create a mock Settings with sensible defaults."""
    settings = MagicMock()

    # LLM
    settings.llm = MagicMock()
    settings.llm.model = "gpt-4"
    settings.llm.provider = "openai"
    settings.llm.providers = {"openai": MagicMock(api_key="test-key", base_url=None)}
    settings.llm.eval_config = MagicMock(enabled=False)

    # Redis
    settings.redis = MagicMock()
    settings.redis.url = "redis://localhost:6379"

    # Postgres
    settings.postgres = MagicMock()
    settings.postgres.dsn = "postgresql+asyncpg://user:pass@localhost:5432/weaver"

    # Neo4j
    settings.neo4j = MagicMock()
    settings.neo4j.enabled = False

    # DuckDB
    settings.duckdb = MagicMock()
    settings.duckdb.enabled = True

    # Ladybug
    settings.ladybug = MagicMock()
    settings.ladybug.enabled = False

    # Fetcher
    settings.fetcher = MagicMock()
    settings.fetcher.rate_limit_enabled = False
    settings.fetcher.httpx_timeout = 30
    settings.fetcher.user_agent = "test"
    settings.fetcher.crawl4ai_headless = True
    settings.fetcher.crawl4ai_stealth_enabled = False
    settings.fetcher.crawl4ai_user_agent = "test"
    settings.fetcher.crawl4ai_timeout = 60
    settings.fetcher.circuit_breaker_enabled = False
    settings.fetcher.circuit_breaker_threshold = 5
    settings.fetcher.circuit_breaker_timeout = 60
    settings.fetcher.default_per_host_concurrency = 2

    # Prompt
    settings.prompt = MagicMock()
    settings.prompt.dir = "/tmp/prompts"

    # Scheduler
    settings.scheduler = MagicMock()
    settings.scheduler.enabled = False

    # Pipeline
    settings.pipeline = MagicMock()
    settings.pipeline.monte_carlo = MagicMock(enabled=False)

    # Search
    settings.search = MagicMock()
    settings.search.rerank_enabled = False
    settings.search.mmr_enabled = False
    settings.search.mmr_lambda = 0.5

    # Knowledge cache
    settings.knowledge_cache = MagicMock()
    settings.knowledge_cache.path = "/tmp/kcache"
    settings.knowledge_cache.sync_interval = 60
    settings.knowledge_cache.sync_threshold = 10
    settings.knowledge_cache.max_queries = 1000

    # Memory
    settings.memory = MagicMock()
    settings.memory.fast_path_enabled = True
    settings.memory.slow_path_enabled = True
    settings.memory.causal_confidence_threshold = 0.7
    settings.memory.consolidation_batch_size = 10
    settings.memory.max_traversal_depth = 3
    settings.memory.beam_width = 4
    settings.memory.token_budget = 4000
    settings.memory.max_relations_per_entity = 20
    settings.memory.consolidation_interval_minutes = 30

    # Temporal memory
    settings.temporal_memory = MagicMock()
    settings.temporal_memory.why_anchor_limit = 5
    settings.temporal_memory.when_anchor_limit = 5
    settings.temporal_memory.default_anchor_limit = 5
    settings.temporal_memory.event_lookup_limit = 20

    # Entity
    settings.entity = MagicMock()
    settings.entity.disable_data_metrics_nodes = False

    # Pipeline process
    settings.pipeline_process = MagicMock()
    settings.pipeline_process.worker_batch_size = 10
    settings.pipeline_process.drain_timeout = 120

    # spaCy
    settings.spacy = MagicMock()
    settings.spacy.zh_model_path = "zh_core_web_lg"
    settings.spacy.en_model_path = "en_core_web_lg"

    for k, v in overrides.items():
        setattr(settings, k, v)

    return settings


def _make_strategy(
    relational_type=DatabaseType.POSTGRES,
    graph_type="neo4j",
    has_graph=True,
):
    """Create a mock DatabaseStrategy."""
    strategy = MagicMock()
    strategy.relational_type = relational_type
    strategy.graph_type = graph_type

    mock_rel_pool = MagicMock()
    mock_rel_pool.shutdown = AsyncMock()
    strategy.relational_pool = mock_rel_pool

    if has_graph:
        mock_graph_pool = MagicMock()
        mock_graph_pool.shutdown = AsyncMock()
        strategy.graph_pool = mock_graph_pool
    else:
        strategy.graph_pool = None

    return strategy


# ══════════════════════════════════════════════════════════════════════
# ContainerPoolsMixin Tests
# ══════════════════════════════════════════════════════════════════════


class TestContainerPoolsInitStrategy:
    """Tests for ContainerPoolsMixin.init_strategy."""

    @pytest.mark.asyncio
    async def test_init_strategy_creates_strategy(self) -> None:
        """init_strategy should create and store a DatabaseStrategy."""
        c = _make_container()
        c._settings = _make_settings()

        mock_strategy = _make_strategy()
        with patch("core.db.create_strategy", AsyncMock(return_value=mock_strategy)):
            result = await c.init_strategy()

        assert result is mock_strategy
        assert c._strategy is mock_strategy

    @pytest.mark.asyncio
    async def test_init_strategy_idempotent(self) -> None:
        """init_strategy should return existing strategy if already initialized."""
        c = _make_container()
        existing = _make_strategy()
        c._strategy = existing

        result = await c.init_strategy()
        assert result is existing


class TestContainerPoolsRelationalPool:
    """Tests for ContainerPoolsMixin.relational_pool."""

    def test_relational_pool_returns_pool(self) -> None:
        """relational_pool should return the strategy's relational pool."""
        c = _make_container()
        strategy = _make_strategy()
        c._strategy = strategy

        pool = c.relational_pool()
        assert pool is strategy.relational_pool

    def test_relational_pool_raises_without_strategy(self) -> None:
        """relational_pool should raise RuntimeError if strategy not initialized."""
        c = _make_container()
        c._strategy = None

        with pytest.raises(RuntimeError, match="init_strategy"):
            c.relational_pool()


class TestContainerPoolsGraphPool:
    """Tests for ContainerPoolsMixin.graph_pool."""

    def test_graph_pool_returns_pool(self) -> None:
        """graph_pool should return the strategy's graph pool."""
        c = _make_container()
        strategy = _make_strategy(has_graph=True)
        c._strategy = strategy

        pool = c.graph_pool()
        assert pool is strategy.graph_pool

    def test_graph_pool_returns_none_without_strategy(self) -> None:
        """graph_pool should return None if strategy not initialized."""
        c = _make_container()
        c._strategy = None
        assert c.graph_pool() is None

    def test_graph_pool_returns_none_without_graph(self) -> None:
        """graph_pool should return None if strategy has no graph pool."""
        c = _make_container()
        strategy = _make_strategy(has_graph=False)
        c._strategy = strategy
        assert c.graph_pool() is None


class TestContainerPoolsPoolTypes:
    """Tests for relational_pool_type and graph_pool_type properties."""

    def test_relational_pool_type_postgres(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy(relational_type=DatabaseType.POSTGRES)
        assert c.relational_pool_type == "postgres"

    def test_relational_pool_type_duckdb(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy(relational_type=DatabaseType.DUCKDB)
        assert c.relational_pool_type == "duckdb"

    def test_relational_pool_type_raises_without_strategy(self) -> None:
        c = _make_container()
        c._strategy = None
        with pytest.raises(RuntimeError, match="init_strategy"):
            _ = c.relational_pool_type

    def test_graph_pool_type_neo4j(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy(graph_type="neo4j")
        assert c.graph_pool_type == "neo4j"

    def test_graph_pool_type_ladybug(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy(graph_type="ladybug")
        assert c.graph_pool_type == "ladybug"

    def test_graph_pool_type_none_without_strategy(self) -> None:
        c = _make_container()
        c._strategy = None
        assert c.graph_pool_type is None


class TestContainerPoolsInitCacheClient:
    """Tests for ContainerPoolsMixin.init_cache_client."""

    @pytest.mark.asyncio
    async def test_init_cache_client_redis_success(self) -> None:
        """init_cache_client should create FallbackCachePool with Redis primary."""
        from core.cache import FallbackCachePool

        c = _make_container()
        c._settings = _make_settings()

        mock_redis = MagicMock()
        mock_redis.startup = AsyncMock()

        mock_cashews = MagicMock()
        mock_cashews.startup = AsyncMock()

        with patch("core.cache.RedisClient", return_value=mock_redis):
            with patch("core.cache.CashewsClient", return_value=mock_cashews):
                result = await c.init_cache_client()

        assert isinstance(result, FallbackCachePool)
        assert result.primary_healthy is True
        mock_redis.startup.assert_called_once()
        mock_cashews.startup.assert_called_once()

    @pytest.mark.asyncio
    async def test_init_cache_client_fallback_to_cashews(self) -> None:
        """init_cache_client should mark FallbackCachePool as degraded when Redis fails."""
        from core.cache import FallbackCachePool

        c = _make_container()
        c._settings = _make_settings()

        def redis_fail(*args, **kwargs):
            client = MagicMock()
            client.startup = AsyncMock(side_effect=ConnectionError("Redis unavailable"))
            return client

        mock_cashews = MagicMock()
        mock_cashews.startup = AsyncMock()

        with patch("core.cache.RedisClient", redis_fail):
            with patch("core.cache.CashewsClient", return_value=mock_cashews):
                result = await c.init_cache_client()

        assert isinstance(result, FallbackCachePool)
        assert result.primary_healthy is False
        mock_cashews.startup.assert_called_once()

    @pytest.mark.asyncio
    async def test_init_cache_client_idempotent(self) -> None:
        c = _make_container()
        existing = MagicMock()
        c._cache_client = existing

        result = await c.init_cache_client()
        assert result is existing


class TestContainerPoolsCacheClient:
    """Tests for ContainerPoolsMixin.cache_client."""

    def test_cache_client_returns_client(self) -> None:
        c = _make_container()
        mock_cache = MagicMock()
        c._cache_client = mock_cache
        assert c.cache_client() is mock_cache

    def test_cache_client_raises_without_init(self) -> None:
        c = _make_container()
        c._cache_client = None
        with pytest.raises(RuntimeError, match="init_cache_client"):
            c.cache_client()


# ══════════════════════════════════════════════════════════════════════
# ContainerServicesMixin Tests
# ══════════════════════════════════════════════════════════════════════


class TestContainerServicesPromptLoader:
    """Tests for ContainerServicesMixin.prompt_loader."""

    def test_prompt_loader_creates_instance(self) -> None:
        c = _make_container()
        c._settings = _make_settings()
        c._prompt_loader = None

        mock_loader = MagicMock()
        with patch("core.prompt.PromptLoader", return_value=mock_loader):
            result = c.prompt_loader()

        assert result is mock_loader
        assert c._prompt_loader is mock_loader

    def test_prompt_loader_returns_cached(self) -> None:
        c = _make_container()
        existing = MagicMock()
        c._prompt_loader = existing
        assert c.prompt_loader() is existing


class TestContainerServicesSourceRegistry:
    """Tests for ContainerServicesMixin.source_registry."""

    def test_source_registry_raises_without_smart_fetcher(self) -> None:
        c = _make_container()
        c._smart_fetcher = None
        c._source_registry = None

        with pytest.raises(RuntimeError, match="Smart fetcher"):
            c.source_registry()

    def test_source_registry_creates_instance(self) -> None:
        c = _make_container()
        c._smart_fetcher = MagicMock()
        c._source_registry = None

        mock_registry = MagicMock()
        with patch("modules.ingestion.SourceRegistry", return_value=mock_registry):
            result = c.source_registry()

        assert result is mock_registry
        assert c._source_registry is mock_registry


class TestContainerServicesSourceConfigRepo:
    """Tests for ContainerServicesMixin.source_config_repo."""

    def test_source_config_repo_raises_without_strategy(self) -> None:
        c = _make_container()
        c._strategy = None
        c._source_config_repo = None
        with pytest.raises(RuntimeError, match="init_strategy"):
            c.source_config_repo()

    def test_source_config_repo_creates_instance(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy()
        c._source_config_repo = None

        mock_repo = MagicMock()
        with patch("modules.ingestion.SourceConfigRepo", return_value=mock_repo):
            result = c.source_config_repo()

        assert result is mock_repo

    def test_source_config_repo_returns_cached(self) -> None:
        c = _make_container()
        existing = MagicMock()
        c._source_config_repo = existing
        assert c.source_config_repo() is existing


class TestContainerServicesArticleRepo:
    """Tests for ContainerServicesMixin.article_repo."""

    def test_article_repo_raises_without_strategy(self) -> None:
        c = _make_container()
        c._strategy = None
        c._article_repo = None
        with pytest.raises(RuntimeError, match="init_strategy"):
            c.article_repo()

    def test_article_repo_postgres(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy(relational_type=DatabaseType.POSTGRES)
        c._article_repo = None

        mock_repo = MagicMock()
        with patch("modules.storage.postgres.ArticleRepo", return_value=mock_repo):
            result = c.article_repo()
        assert result is mock_repo

    def test_article_repo_duckdb(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy(relational_type=DatabaseType.DUCKDB)
        c._article_repo = None

        mock_repo = MagicMock()
        with patch("modules.storage.duckdb.DuckDBArticleRepo", return_value=mock_repo):
            result = c.article_repo()
        assert result is mock_repo


class TestContainerServicesSourceAuthorityRepo:
    """Tests for ContainerServicesMixin.source_authority_repo."""

    def test_source_authority_repo_raises_without_strategy(self) -> None:
        c = _make_container()
        c._strategy = None
        c._source_authority_repo = None
        with pytest.raises(RuntimeError, match="init_strategy"):
            c.source_authority_repo()

    def test_source_authority_repo_postgres(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy(relational_type=DatabaseType.POSTGRES)
        c._source_authority_repo = None

        mock_repo = MagicMock()
        with patch("modules.storage.postgres.SourceAuthorityRepo", return_value=mock_repo):
            result = c.source_authority_repo()
        assert result is mock_repo

    def test_source_authority_repo_duckdb(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy(relational_type=DatabaseType.DUCKDB)
        c._source_authority_repo = None

        mock_repo = MagicMock()
        with patch("modules.storage.duckdb.DuckDBSourceAuthorityRepo", return_value=mock_repo):
            result = c.source_authority_repo()
        assert result is mock_repo


class TestContainerServicesPendingSyncRepo:
    """Tests for ContainerServicesMixin.pending_sync_repo."""

    def test_pending_sync_repo_raises_without_strategy(self) -> None:
        c = _make_container()
        c._strategy = None
        c._pending_sync_repo = None
        with pytest.raises(RuntimeError, match="init_strategy"):
            c.pending_sync_repo()

    def test_pending_sync_repo_postgres(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy(relational_type=DatabaseType.POSTGRES)
        c._pending_sync_repo = None

        mock_repo = MagicMock()
        with patch("modules.storage.postgres.PendingSyncRepo", return_value=mock_repo):
            result = c.pending_sync_repo()
        assert result is mock_repo


class TestContainerServicesLLMFailureRepo:
    """Tests for ContainerServicesMixin.llm_failure_repo."""

    def test_llm_failure_repo_creates_instance(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy()
        c._llm_failure_repo = None

        mock_repo = MagicMock()
        with patch("modules.analytics.llm_failure.repo.LLMFailureRepo", return_value=mock_repo):
            result = c.llm_failure_repo()
        assert result is mock_repo

    def test_llm_failure_repo_returns_cached(self) -> None:
        c = _make_container()
        existing = MagicMock()
        c._llm_failure_repo = existing
        assert c.llm_failure_repo() is existing


class TestContainerServicesLLMUsageBuffer:
    """Tests for ContainerServicesMixin.llm_usage_buffer."""

    def test_llm_usage_buffer_returns_none_when_not_initialized(self) -> None:
        c = _make_container()
        c._llm_usage_buffer = None
        assert c.llm_usage_buffer() is None

    def test_llm_usage_buffer_returns_instance(self) -> None:
        c = _make_container()
        mock_buffer = MagicMock()
        c._llm_usage_buffer = mock_buffer
        assert c.llm_usage_buffer() is mock_buffer


class TestContainerServicesLLMUsageRepo:
    """Tests for ContainerServicesMixin.llm_usage_repo."""

    def test_llm_usage_repo_creates_instance(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy()
        c._llm_usage_repo = None

        mock_repo = MagicMock()
        with patch("modules.analytics.LLMUsageRepo", return_value=mock_repo):
            result = c.llm_usage_repo()
        assert result is mock_repo

    def test_llm_usage_repo_returns_cached(self) -> None:
        c = _make_container()
        existing = MagicMock()
        c._llm_usage_repo = existing
        assert c.llm_usage_repo() is existing


class TestContainerServicesGraphEntityRepo:
    """Tests for ContainerServicesMixin.graph_entity_repo."""

    def test_graph_entity_repo_returns_none_without_graph_pool(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy(has_graph=False)
        c._graph_entity_repo = None
        assert c.graph_entity_repo() is None

    def test_graph_entity_repo_returns_none_without_strategy(self) -> None:
        c = _make_container()
        c._strategy = None
        c._graph_entity_repo = None
        assert c.graph_entity_repo() is None

    def test_graph_entity_repo_neo4j(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy(graph_type="neo4j")
        c._graph_entity_repo = None

        mock_repo = MagicMock()
        with patch("modules.storage.neo4j.Neo4jEntityRepo", return_value=mock_repo):
            result = c.graph_entity_repo()
        assert result is mock_repo

    def test_graph_entity_repo_ladybug(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy(graph_type="ladybug")
        c._graph_entity_repo = None

        mock_repo = MagicMock()
        with patch("modules.storage.ladybug.LadybugEntityRepo", return_value=mock_repo):
            result = c.graph_entity_repo()
        assert result is mock_repo


class TestContainerServicesGraphArticleRepo:
    """Tests for ContainerServicesMixin.graph_article_repo."""

    def test_graph_article_repo_returns_none_without_graph_pool(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy(has_graph=False)
        c._graph_article_repo = None
        assert c.graph_article_repo() is None

    def test_graph_article_repo_neo4j(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy(graph_type="neo4j")
        c._graph_article_repo = None

        mock_repo = MagicMock()
        with patch("modules.storage.neo4j.Neo4jArticleRepo", return_value=mock_repo):
            result = c.graph_article_repo()
        assert result is mock_repo

    def test_graph_article_repo_ladybug(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy(graph_type="ladybug")
        c._graph_article_repo = None

        mock_repo = MagicMock()
        with patch("modules.storage.ladybug.LadybugArticleRepo", return_value=mock_repo):
            result = c.graph_article_repo()
        assert result is mock_repo


class TestContainerServicesCausalRepo:
    """Tests for ContainerServicesMixin.causal_repo."""

    def test_causal_repo_returns_none_without_graph_pool(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy(has_graph=False)
        c._causal_repo = None
        assert c.causal_repo() is None

    def test_causal_repo_creates_instance(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy(has_graph=True)
        c._causal_repo = None

        mock_repo = MagicMock()
        with patch("modules.memory.graphs.causal.CausalGraphRepo", return_value=mock_repo):
            result = c.causal_repo()
        assert result is mock_repo


class TestContainerServicesGraphWriter:
    """Tests for ContainerServicesMixin.graph_writer."""

    def test_graph_writer_returns_none_without_graph_pool(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy(has_graph=False)
        c._graph_writer = None
        assert c.graph_writer() is None

    def test_graph_writer_returns_none_without_strategy(self) -> None:
        c = _make_container()
        c._strategy = None
        c._graph_writer = None
        assert c.graph_writer() is None

    def test_graph_writer_neo4j(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy(graph_type="neo4j")
        c._graph_writer = None

        mock_normalizer = MagicMock()
        mock_writer = MagicMock()
        with (
            patch.object(c, "relation_normalizer", return_value=mock_normalizer),
            patch("modules.knowledge.graph.Neo4jWriter", return_value=mock_writer),
        ):
            result = c.graph_writer()
        assert result is mock_writer

    def test_graph_writer_ladybug(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy(graph_type="ladybug")
        c._graph_writer = None

        mock_normalizer = MagicMock()
        mock_writer = MagicMock()
        with (
            patch.object(c, "relation_normalizer", return_value=mock_normalizer),
            patch("modules.storage.ladybug.LadybugWriter", return_value=mock_writer),
        ):
            result = c.graph_writer()
        assert result is mock_writer


class TestContainerServicesGraphRepo:
    """Tests for ContainerServicesMixin.graph_repo."""

    def test_graph_repo_raises_without_graph(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy(has_graph=False)
        c._graph_repo = None

        with pytest.raises(RuntimeError, match="Graph database not available"):
            c.graph_repo()

    def test_graph_repo_raises_without_strategy(self) -> None:
        c = _make_container()
        c._strategy = None
        c._graph_repo = None

        with pytest.raises(RuntimeError, match="Graph database not available"):
            c.graph_repo()

    def test_graph_repo_creates_instance(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy(has_graph=True)
        c._graph_repo = None

        mock_qb = MagicMock()
        mock_gr = MagicMock()
        with (
            patch("core.db.graph_query_builders.create_graph_query_builder", return_value=mock_qb),
            patch("modules.storage.graph_repo.GraphRepository", return_value=mock_gr),
        ):
            result = c.graph_repo()
        assert result is mock_gr

    def test_graph_repo_neo4j_adds_ladybug_fallback(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy(graph_type="neo4j", has_graph=True)
        c._graph_repo = None
        c._settings = _make_settings()

        mock_qb = MagicMock()
        mock_gr = MagicMock()
        with (
            patch("core.db.graph_query_builders.create_graph_query_builder", return_value=mock_qb),
            patch("modules.storage.graph_repo.GraphRepository", return_value=mock_gr),
        ):
            result = c.graph_repo()
        assert result is mock_gr


class TestContainerServicesRelationNormalizer:
    """Tests for ContainerServicesMixin.relation_normalizer."""

    def test_relation_normalizer_returns_none_without_strategy(self) -> None:
        c = _make_container()
        c._strategy = None
        c._relation_type_normalizer = None
        assert c.relation_normalizer() is None

    def test_relation_normalizer_creates_instance(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy()
        c._relation_type_normalizer = None

        mock_norm = MagicMock()
        with patch(
            "modules.knowledge.graph.relation_type_normalizer.RelationTypeNormalizer",
            return_value=mock_norm,
        ):
            result = c.relation_normalizer()
        assert result is mock_norm


class TestContainerServicesVectorRepo:
    """Tests for ContainerServicesMixin.vector_repo."""

    def test_vector_repo_raises_without_strategy(self) -> None:
        c = _make_container()
        c._strategy = None
        c._vector_repo = None
        with pytest.raises(RuntimeError, match="init_strategy"):
            c.vector_repo()

    def test_vector_repo_creates_with_query_builder(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy()
        c._vector_repo = None

        mock_qb = MagicMock()
        mock_vr = MagicMock()
        with (
            patch("core.db.query_builders.create_vector_query_builder", return_value=mock_qb),
            patch("modules.storage.postgres.VectorRepo", return_value=mock_vr),
        ):
            result = c.vector_repo()
        assert result is mock_vr
        assert c._vector_repo is mock_vr


class TestContainerServicesSmartFetcher:
    """Tests for ContainerServicesMixin smart fetcher methods."""

    @pytest.mark.asyncio
    async def test_init_smart_fetcher_creates_instance(self) -> None:
        c = _make_container()
        c._settings = _make_settings()
        c._smart_fetcher = None

        mock_sf = MagicMock()
        with (
            patch("modules.ingestion.fetching.HttpxFetcher", return_value=MagicMock()),
            patch(
                "modules.ingestion.fetching.crawl4ai_fetcher.Crawl4AIFetcher",
                return_value=MagicMock(),
            ),
            patch("modules.ingestion.SmartFetcher", return_value=mock_sf),
        ):
            result = await c.init_smart_fetcher()
        assert result is mock_sf
        assert c._smart_fetcher is mock_sf

    @pytest.mark.asyncio
    async def test_init_smart_fetcher_idempotent(self) -> None:
        c = _make_container()
        existing = MagicMock()
        c._smart_fetcher = existing
        result = await c.init_smart_fetcher()
        assert result is existing


class TestContainerServicesCrawler:
    """Tests for ContainerServicesMixin.crawler."""

    def test_crawler_creates_instance(self) -> None:
        c = _make_container()
        c._settings = _make_settings()
        c._smart_fetcher = MagicMock()
        c._crawler = None

        mock_crawler = MagicMock()
        with patch("modules.ingestion.Crawler", return_value=mock_crawler):
            result = c.crawler()
        assert result is mock_crawler


class TestContainerServicesDeduplicator:
    """Tests for ContainerServicesMixin.deduplicator."""

    def test_deduplicator_creates_instance(self) -> None:
        c = _make_container()
        c._cache_client = MagicMock()
        c._article_repo = MagicMock()
        c._deduplicator = None

        mock_dedup = MagicMock()
        with patch("modules.ingestion.Deduplicator", return_value=mock_dedup):
            result = c.deduplicator()
        assert result is mock_dedup


class TestContainerServicesPipeline:
    """Tests for ContainerServicesMixin pipeline methods."""

    def test_pipeline_raises_without_init(self) -> None:
        c = _make_container()
        c._pipeline = None
        with pytest.raises(RuntimeError, match="Pipeline"):
            c.pipeline()

    def test_pipeline_returns_instance(self) -> None:
        c = _make_container()
        mock_pipeline = MagicMock()
        c._pipeline = mock_pipeline
        assert c.pipeline() is mock_pipeline

    @pytest.mark.asyncio
    async def test_init_pipeline_creates_instance(self) -> None:
        c = _make_container()
        c._settings = _make_settings()
        c._llm_client = MagicMock()
        c._prompt_loader = MagicMock()
        c._cache_client = MagicMock()
        c._event_bus = MagicMock()
        c._pipeline = None
        c._debug_mode = False
        c._strategy = _make_strategy(has_graph=True)
        c._vector_repo = MagicMock()
        c._article_repo = MagicMock()
        c._graph_writer = MagicMock()
        c._source_authority_repo = MagicMock()
        c._entity_resolver = MagicMock()
        c._community_updater = MagicMock()
        c._relation_type_normalizer = MagicMock()

        mock_pipeline = MagicMock()
        with (
            patch("core.llm.config.token_budget.TokenBudgetManager", return_value=MagicMock()),
            patch(
                "modules.processing.nlp.spacy_extractor.SpacyExtractor", return_value=MagicMock()
            ),
            patch("modules.processing.pipeline.graph.Pipeline", return_value=mock_pipeline),
            patch.object(c, "_get_embedding_model_id", return_value="text-embedding-3-small"),
        ):
            result = await c.init_pipeline()
        assert result is mock_pipeline
        assert c._pipeline is mock_pipeline

    @pytest.mark.asyncio
    async def test_init_pipeline_creates_event_bus_if_none(self) -> None:
        c = _make_container()
        c._settings = _make_settings()
        c._llm_client = MagicMock()
        c._prompt_loader = MagicMock()
        c._cache_client = MagicMock()
        c._event_bus = None
        c._pipeline = None
        c._debug_mode = False
        c._strategy = _make_strategy(has_graph=True)
        c._vector_repo = MagicMock()
        c._article_repo = MagicMock()
        c._graph_writer = MagicMock()
        c._source_authority_repo = MagicMock()
        c._entity_resolver = MagicMock()
        c._community_updater = MagicMock()
        c._relation_type_normalizer = MagicMock()

        mock_event_bus = MagicMock()
        mock_pipeline = MagicMock()
        with (
            patch("core.event.EventBus", return_value=mock_event_bus),
            patch("core.llm.config.token_budget.TokenBudgetManager", return_value=MagicMock()),
            patch(
                "modules.processing.nlp.spacy_extractor.SpacyExtractor", return_value=MagicMock()
            ),
            patch("modules.processing.pipeline.graph.Pipeline", return_value=mock_pipeline),
            patch.object(c, "_get_embedding_model_id", return_value="text-embedding-3-small"),
        ):
            await c.init_pipeline()
        assert c._event_bus is mock_event_bus


class TestContainerServicesProcessingQueue:
    """Tests for ContainerServicesMixin.processing_queue."""

    def test_processing_queue_creates_instance(self) -> None:
        c = _make_container()
        c._cache_client = MagicMock()
        c._processing_queue = None

        mock_queue = MagicMock()
        with patch("modules.processing.queue.ProcessingQueue", return_value=mock_queue):
            result = c.processing_queue()
        assert result is mock_queue


class TestContainerServicesPipelineWorker:
    """Tests for ContainerServicesMixin.pipeline_worker."""

    def test_pipeline_worker_returns_none_without_pipeline(self) -> None:
        c = _make_container()
        c._pipeline = None
        c._pipeline_worker = None
        assert c.pipeline_worker() is None

    def test_pipeline_worker_creates_instance(self) -> None:
        c = _make_container()
        c._pipeline = MagicMock()
        c._cache_client = MagicMock()
        c._article_repo = MagicMock()
        c._processing_queue = MagicMock()
        c._pipeline_worker = None
        c._settings = _make_settings()

        mock_worker = MagicMock()
        with patch("modules.processing.worker.PipelineWorker", return_value=mock_worker):
            result = c.pipeline_worker()
        assert result is mock_worker


class TestContainerServicesPipelineService:
    """Tests for ContainerServicesMixin.pipeline_service."""

    def test_pipeline_service_raises_without_pipeline(self) -> None:
        c = _make_container()
        c._pipeline = None
        c._pipeline_service = None
        with pytest.raises(RuntimeError, match="Pipeline"):
            c.pipeline_service()

    def test_pipeline_service_creates_instance(self) -> None:
        c = _make_container()
        c._pipeline = MagicMock()
        c._pipeline_service = None

        mock_svc = MagicMock()
        with patch("core.services.pipeline_service.PipelineServiceImpl", return_value=mock_svc):
            result = c.pipeline_service()
        assert result is mock_svc


class TestContainerServicesTaskRegistry:
    """Tests for ContainerServicesMixin.task_registry."""

    def test_task_registry_creates_instance(self) -> None:
        c = _make_container()
        c._task_registry = None

        mock_reg = MagicMock()
        with patch("core.services.task_registry.InMemoryTaskRegistry", return_value=mock_reg):
            result = c.task_registry()
        assert result is mock_reg

    def test_task_registry_returns_cached(self) -> None:
        c = _make_container()
        existing = MagicMock()
        c._task_registry = existing
        assert c.task_registry() is existing


class TestContainerServicesCommunityUpdater:
    """Tests for ContainerServicesMixin.community_updater."""

    def test_community_updater_returns_none_without_strategy(self) -> None:
        c = _make_container()
        c._strategy = None
        c._community_updater = None
        assert c.community_updater() is None

    def test_community_updater_creates_instance(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy(has_graph=True)
        c._community_updater = None
        c._llm_client = MagicMock()

        mock_updater = MagicMock()
        with (
            patch.object(c, "graph_pool", return_value=MagicMock()),
            patch.object(c, "llm_client", return_value=MagicMock()),
            patch(
                "modules.knowledge.graph.community.updater.IncrementalCommunityUpdater",
                return_value=mock_updater,
            ),
        ):
            result = c.community_updater()
        assert result is mock_updater


class TestContainerServicesSchedulerJobRunner:
    """Tests for ContainerServicesMixin.scheduler_job_runner."""

    def test_scheduler_job_runner_creates_instance(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy()
        c._settings = _make_settings()
        c._scheduler_jobs_service = None

        mock_jobs = MagicMock()
        with (
            patch.object(c, "relational_pool", return_value=MagicMock()),
            patch.object(c, "cache_client", return_value=MagicMock()),
            patch.object(c, "graph_writer", return_value=None),
            patch.object(c, "vector_repo", return_value=MagicMock()),
            patch.object(c, "article_repo", return_value=MagicMock()),
            patch.object(c, "source_authority_repo", return_value=MagicMock()),
            patch.object(c, "pending_sync_repo", return_value=MagicMock()),
            patch.object(c, "pipeline", return_value=MagicMock()),
            patch.object(c, "llm_failure_repo", return_value=MagicMock()),
            patch("modules.scheduler.jobs.SchedulerJobs", return_value=mock_jobs),
        ):
            result = c.scheduler_job_runner()
        assert result is mock_jobs


# ══════════════════════════════════════════════════════════════════════
# ContainerSearchMixin Tests
# ══════════════════════════════════════════════════════════════════════


class TestContainerSearchInitSearchEngines:
    """Tests for ContainerSearchMixin.init_search_engines."""

    def test_init_search_returns_none_without_graph_pool(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy(has_graph=False)
        c._llm_client = MagicMock()

        with patch.object(c, "graph_pool", return_value=None):
            result = c.init_search_engines()
        assert result is None

    def test_init_search_returns_none_without_llm(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy(has_graph=True)
        c._llm_client = None
        assert c.init_search_engines() is None

    def test_init_search_returns_none_without_strategy(self) -> None:
        c = _make_container()
        c._strategy = None
        c._llm_client = MagicMock()
        assert c.init_search_engines() is None

    def test_init_search_creates_neo4j_engines(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy(graph_type="neo4j", has_graph=True)
        c._llm_client = MagicMock()
        c._local_search_engine = None
        c._global_search_engine = None
        c._settings = _make_settings()

        mock_local = MagicMock()
        mock_global = MagicMock()
        with (
            patch.object(c, "graph_pool", return_value=MagicMock()),
            patch.object(c, "article_repo", return_value=MagicMock()),
            patch(
                "modules.knowledge.search.context.local_context.LocalContextBuilder",
                return_value=MagicMock(),
            ),
            patch(
                "modules.knowledge.search.context.global_context.GlobalContextBuilder",
                return_value=MagicMock(),
            ),
            patch("container.search.LocalSearchEngine", return_value=mock_local),
            patch("container.search.GlobalSearchEngine", return_value=mock_global),
        ):
            result = c.init_search_engines()
        assert result == (mock_local, mock_global)

    def test_init_search_creates_ladybug_engines(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy(graph_type="ladybug", has_graph=True)
        c._llm_client = MagicMock()
        c._local_search_engine = None
        c._global_search_engine = None
        c._settings = _make_settings()

        mock_local = MagicMock()
        mock_global = MagicMock()
        with (
            patch.object(c, "graph_pool", return_value=MagicMock()),
            patch.object(c, "article_repo", return_value=MagicMock()),
            patch(
                "modules.knowledge.search.context.ladybug_local_context.LadybugLocalContextBuilder",
                return_value=MagicMock(),
            ),
            patch(
                "modules.knowledge.search.context.ladybug_global_context.LadybugGlobalContextBuilder",
                return_value=MagicMock(),
            ),
            patch("container.search.LocalSearchEngine", return_value=mock_local),
            patch("container.search.GlobalSearchEngine", return_value=mock_global),
        ):
            result = c.init_search_engines()
        assert result == (mock_local, mock_global)

    def test_init_search_does_not_recreate_existing_engines(self) -> None:
        c = _make_container()
        c._strategy = _make_strategy(graph_type="neo4j", has_graph=True)
        c._llm_client = MagicMock()
        existing_local = MagicMock()
        existing_global = MagicMock()
        c._local_search_engine = existing_local
        c._global_search_engine = existing_global
        c._settings = _make_settings()

        with (
            patch.object(c, "graph_pool", return_value=MagicMock()),
            patch.object(c, "article_repo", return_value=MagicMock()),
            patch(
                "modules.knowledge.search.context.local_context.LocalContextBuilder",
                return_value=MagicMock(),
            ),
            patch(
                "modules.knowledge.search.context.global_context.GlobalContextBuilder",
                return_value=MagicMock(),
            ),
        ):
            result = c.init_search_engines()
        assert result[0] is existing_local
        assert result[1] is existing_global


class TestContainerSearchLocalSearchEngine:
    """Tests for ContainerSearchMixin.local_search_engine."""

    def test_local_search_engine_lazy_init(self) -> None:
        c = _make_container()
        c._local_search_engine = None
        c._strategy = _make_strategy(has_graph=True)
        c._llm_client = MagicMock()
        c._settings = _make_settings()

        mock_engine = MagicMock()

        def mock_init():
            c._local_search_engine = mock_engine
            return (mock_engine, MagicMock())

        with (
            patch.object(c, "graph_pool", return_value=MagicMock()),
            patch.object(c, "init_search_engines", side_effect=mock_init),
        ):
            result = c.local_search_engine()
        assert result is mock_engine

    def test_local_search_engine_returns_none_without_graph(self) -> None:
        c = _make_container()
        c._local_search_engine = None
        with patch.object(c, "graph_pool", return_value=None):
            result = c.local_search_engine()
        assert result is None


class TestContainerSearchGlobalSearchEngine:
    """Tests for ContainerSearchMixin.global_search_engine."""

    def test_global_search_engine_lazy_init(self) -> None:
        c = _make_container()
        c._global_search_engine = None
        c._strategy = _make_strategy(has_graph=True)
        c._llm_client = MagicMock()
        c._settings = _make_settings()

        mock_engine = MagicMock()

        def mock_init():
            c._global_search_engine = mock_engine
            return (MagicMock(), mock_engine)

        with (
            patch.object(c, "graph_pool", return_value=MagicMock()),
            patch.object(c, "init_search_engines", side_effect=mock_init),
        ):
            result = c.global_search_engine()
        assert result is mock_engine

    def test_global_search_engine_returns_none_without_graph(self) -> None:
        c = _make_container()
        c._global_search_engine = None
        with patch.object(c, "graph_pool", return_value=None):
            result = c.global_search_engine()
        assert result is None


class TestContainerSearchHybridSearchEngine:
    """Tests for ContainerSearchMixin.hybrid_search_engine."""

    def test_hybrid_engine_returns_none_without_vector_repo(self) -> None:
        c = _make_container()
        c._hybrid_engine = None
        c._vector_repo = None
        c._settings = _make_settings()

        with patch.object(c, "vector_repo", return_value=None):
            result = c.hybrid_search_engine()
        assert result is None

    def test_hybrid_engine_creates_instance(self) -> None:
        c = _make_container()
        c._hybrid_engine = None
        c._vector_repo = MagicMock()
        c._settings = _make_settings()
        c._strategy = _make_strategy()

        mock_hybrid = MagicMock()
        with (
            patch.object(c, "vector_repo", return_value=MagicMock()),
            patch.object(c, "relational_pool", return_value=MagicMock()),
            patch(
                "modules.knowledge.search.retrievers.bm25_retriever.BM25Retriever",
                return_value=MagicMock(),
            ),
            patch("modules.knowledge.search.HybridSearchConfig", return_value=MagicMock()),
            patch("container.search.HybridSearchEngine", return_value=mock_hybrid),
        ):
            result = c.hybrid_search_engine()
        assert result is mock_hybrid
        assert c._hybrid_engine is mock_hybrid

    def test_hybrid_engine_returns_cached(self) -> None:
        c = _make_container()
        existing = MagicMock()
        c._hybrid_engine = existing
        assert c.hybrid_search_engine() is existing

    def test_hybrid_engine_with_reranker_enabled(self) -> None:
        c = _make_container()
        c._hybrid_engine = None
        c._vector_repo = MagicMock()
        c._strategy = _make_strategy()
        settings = _make_settings()
        settings.search.rerank_enabled = True
        settings.search.rerank_model = "test-model"
        c._settings = settings

        mock_hybrid = MagicMock()
        with (
            patch.object(c, "vector_repo", return_value=MagicMock()),
            patch.object(c, "relational_pool", return_value=MagicMock()),
            patch(
                "modules.knowledge.search.retrievers.bm25_retriever.BM25Retriever",
                return_value=MagicMock(),
            ),
            patch("modules.knowledge.search.HybridSearchConfig", return_value=MagicMock()),
            patch("container.search.HybridSearchEngine", return_value=mock_hybrid),
            patch(
                "modules.knowledge.search.rerankers.flashrank_reranker.FlashrankReranker",
                return_value=MagicMock(),
            ),
        ):
            result = c.hybrid_search_engine()
        assert result is mock_hybrid

    def test_hybrid_engine_with_mmr_enabled(self) -> None:
        c = _make_container()
        c._hybrid_engine = None
        c._vector_repo = MagicMock()
        c._strategy = _make_strategy()
        settings = _make_settings()
        settings.search.mmr_enabled = True
        settings.search.mmr_lambda = 0.7
        c._settings = settings

        mock_hybrid = MagicMock()
        with (
            patch.object(c, "vector_repo", return_value=MagicMock()),
            patch.object(c, "relational_pool", return_value=MagicMock()),
            patch(
                "modules.knowledge.search.retrievers.bm25_retriever.BM25Retriever",
                return_value=MagicMock(),
            ),
            patch("modules.knowledge.search.HybridSearchConfig", return_value=MagicMock()),
            patch("container.search.HybridSearchEngine", return_value=mock_hybrid),
            patch(
                "modules.knowledge.search.rerankers.mmr_reranker.MMRReranker",
                return_value=MagicMock(),
            ),
        ):
            result = c.hybrid_search_engine()
        assert result is mock_hybrid


class TestContainerSearchBM25Index:
    """Tests for ContainerSearchMixin._init_bm25_index."""

    @pytest.mark.asyncio
    async def test_init_bm25_skips_if_already_initialized(self) -> None:
        c = _make_container()
        c._bm25_index_service = MagicMock()
        await c._init_bm25_index()

    @pytest.mark.asyncio
    async def test_init_bm25_handles_hybrid_engine_none(self) -> None:
        c = _make_container()
        c._bm25_index_service = None
        c._strategy = _make_strategy()
        c._settings = _make_settings()

        with (
            patch.object(c, "hybrid_search_engine", return_value=None),
            patch.object(c, "relational_pool", return_value=MagicMock()),
        ):
            await c._init_bm25_index()
        assert c._bm25_index_service is None

    @pytest.mark.asyncio
    async def test_init_bm25_creates_service(self) -> None:
        c = _make_container()
        c._bm25_index_service = None
        c._strategy = _make_strategy()
        c._settings = _make_settings()

        mock_hybrid = MagicMock()
        mock_bm25_retriever = MagicMock()
        mock_bm25_retriever.is_initialized = True
        mock_hybrid._bm25_retriever = mock_bm25_retriever

        mock_index_svc = MagicMock()
        mock_index_svc.build_full_index = AsyncMock(return_value=5)

        with (
            patch.object(c, "hybrid_search_engine", return_value=mock_hybrid),
            patch.object(c, "relational_pool", return_value=MagicMock()),
            patch(
                "modules.knowledge.search.retrievers.bm25_index_service.BM25IndexService",
                return_value=mock_index_svc,
            ),
        ):
            await c._init_bm25_index()
        assert c._bm25_index_service is mock_index_svc

    @pytest.mark.asyncio
    async def test_init_bm25_handles_exception(self) -> None:
        c = _make_container()
        c._bm25_index_service = None
        c._strategy = _make_strategy()
        c._settings = _make_settings()

        with patch.object(c, "hybrid_search_engine", side_effect=Exception("test error")):
            await c._init_bm25_index()
        assert c._bm25_index_service is None


# ══════════════════════════════════════════════════════════════════════
# ContainerLifecycleMixin Tests
# ══════════════════════════════════════════════════════════════════════


class TestContainerLifecycleLLMClient:
    """Tests for ContainerLifecycleMixin LLM client methods."""

    def test_llm_client_raises_without_init(self) -> None:
        c = _make_container()
        c._llm_client = None
        with pytest.raises(RuntimeError, match="LLM client not initialized"):
            c.llm_client()

    def test_llm_client_returns_instance(self) -> None:
        c = _make_container()
        mock_llm = MagicMock()
        c._llm_client = mock_llm
        assert c.llm_client() is mock_llm

    @pytest.mark.asyncio
    async def test_init_llm_creates_client(self) -> None:
        c = _make_container()
        c._settings = _make_settings()
        c._llm_client = None
        c._event_bus = None
        c._cache_client = MagicMock()
        c._prompt_loader = MagicMock()
        c._eval_runner = None

        mock_llm = MagicMock()
        with (
            patch("core.event.EventBus", return_value=MagicMock()),
            patch("core.llm.evaluation.experience.ExperienceStore", return_value=MagicMock()),
            patch("core.llm.routing.smart_router.SmartRouter", return_value=MagicMock()),
            patch("core.llm.config.live_config.LiveConfig", return_value=MagicMock()),
            patch("core.llm.LLMClient.create_from_settings", AsyncMock(return_value=mock_llm)),
            patch.object(c, "prompt_loader", return_value=MagicMock()),
        ):
            result = await c.init_llm()
        assert result is mock_llm
        assert c._llm_client is mock_llm

    @pytest.mark.asyncio
    async def test_init_llm_idempotent(self) -> None:
        c = _make_container()
        existing = MagicMock()
        c._llm_client = existing
        result = await c.init_llm()
        assert result is existing

    @pytest.mark.asyncio
    async def test_init_llm_creates_event_bus_if_none(self) -> None:
        c = _make_container()
        c._settings = _make_settings()
        c._llm_client = None
        c._event_bus = None
        c._cache_client = MagicMock()
        c._eval_runner = None

        mock_event_bus = MagicMock()
        with (
            patch("core.event.EventBus", return_value=mock_event_bus),
            patch("core.llm.evaluation.experience.ExperienceStore", return_value=MagicMock()),
            patch("core.llm.routing.smart_router.SmartRouter", return_value=MagicMock()),
            patch("core.llm.config.live_config.LiveConfig", return_value=MagicMock()),
            patch("core.llm.LLMClient.create_from_settings", AsyncMock(return_value=MagicMock())),
            patch.object(c, "prompt_loader", return_value=MagicMock()),
        ):
            await c.init_llm()
        assert c._event_bus is mock_event_bus

    @pytest.mark.asyncio
    async def test_init_llm_reuses_event_bus(self) -> None:
        c = _make_container()
        c._settings = _make_settings()
        c._llm_client = None
        existing_bus = MagicMock()
        c._event_bus = existing_bus
        c._cache_client = MagicMock()
        c._eval_runner = None

        with (
            patch("core.llm.evaluation.experience.ExperienceStore", return_value=MagicMock()),
            patch("core.llm.routing.smart_router.SmartRouter", return_value=MagicMock()),
            patch("core.llm.config.live_config.LiveConfig", return_value=MagicMock()),
            patch("core.llm.LLMClient.create_from_settings", AsyncMock(return_value=MagicMock())),
            patch.object(c, "prompt_loader", return_value=MagicMock()),
        ):
            await c.init_llm()
        assert c._event_bus is existing_bus

    @pytest.mark.asyncio
    async def test_init_llm_with_eval_enabled(self) -> None:
        c = _make_container()
        settings = _make_settings()
        settings.llm.eval_config.enabled = True
        c._settings = settings
        c._llm_client = None
        c._event_bus = MagicMock()
        c._cache_client = MagicMock()
        c._eval_runner = None

        mock_eval = MagicMock()
        with (
            patch("core.llm.evaluation.experience.ExperienceStore", return_value=MagicMock()),
            patch("core.llm.routing.smart_router.SmartRouter", return_value=MagicMock()),
            patch("core.llm.config.live_config.LiveConfig", return_value=MagicMock()),
            patch(
                "core.llm.evaluation.eval_runner.EvalRunner.from_eval_config",
                return_value=mock_eval,
            ),
            patch("core.llm.LLMClient.create_from_settings", AsyncMock(return_value=MagicMock())),
            patch.object(c, "prompt_loader", return_value=MagicMock()),
        ):
            await c.init_llm()
        assert c._eval_runner is mock_eval


class TestContainerLifecycleKnowledgeCache:
    """Tests for ContainerLifecycleMixin knowledge cache methods."""

    def test_knowledge_cache_raises_without_init(self) -> None:
        c = _make_container()
        c._knowledge_cache = None
        with pytest.raises(RuntimeError, match="Knowledge cache not initialized"):
            c.knowledge_cache()

    def test_knowledge_cache_returns_instance(self) -> None:
        c = _make_container()
        mock_cache = MagicMock()
        c._knowledge_cache = mock_cache
        assert c.knowledge_cache() is mock_cache

    @pytest.mark.asyncio
    async def test_init_knowledge_cache_creates_instance(self) -> None:
        c = _make_container()
        c._settings = _make_settings()
        c._knowledge_cache = None
        c._llm_client = MagicMock()

        mock_kc = MagicMock()
        with patch("modules.knowledge.cache.KnowledgeCache", return_value=mock_kc):
            result = await c.init_knowledge_cache()
        assert result is mock_kc
        assert c._knowledge_cache is mock_kc

    @pytest.mark.asyncio
    async def test_init_knowledge_cache_inits_llm_first(self) -> None:
        c = _make_container()
        c._settings = _make_settings()
        c._knowledge_cache = None
        c._llm_client = None

        mock_llm = MagicMock()
        mock_kc = MagicMock()
        with (
            patch.object(c, "init_llm", AsyncMock(return_value=mock_llm)),
            patch("modules.knowledge.cache.KnowledgeCache", return_value=mock_kc),
        ):
            result = await c.init_knowledge_cache()
        assert result is mock_kc

    @pytest.mark.asyncio
    async def test_init_knowledge_cache_idempotent(self) -> None:
        c = _make_container()
        existing = MagicMock()
        c._knowledge_cache = existing
        result = await c.init_knowledge_cache()
        assert result is existing


class TestContainerLifecycleMCSampler:
    """Tests for ContainerLifecycleMixin MC sampler methods."""

    def test_mc_sampler_returns_none_when_disabled(self) -> None:
        c = _make_container()
        c._settings = _make_settings()
        c._mc_sampler = None
        assert c.mc_sampler() is None

    def test_mc_sampler_raises_when_enabled_but_not_initialized(self) -> None:
        c = _make_container()
        settings = _make_settings()
        settings.pipeline.monte_carlo.enabled = True
        c._settings = settings
        c._mc_sampler = None
        with pytest.raises(RuntimeError, match="MC sampler not initialized"):
            c.mc_sampler()

    @pytest.mark.asyncio
    async def test_init_mc_sampler_skips_when_disabled(self) -> None:
        c = _make_container()
        c._settings = _make_settings()
        c._mc_sampler = None
        c._llm_client = MagicMock()
        result = await c.init_mc_sampler()
        assert result is None

    @pytest.mark.asyncio
    async def test_init_mc_sampler_creates_instance(self) -> None:
        c = _make_container()
        settings = _make_settings()
        settings.pipeline.monte_carlo.enabled = True
        settings.pipeline.monte_carlo.threshold = 0.5
        settings.pipeline.monte_carlo.sample_size = 3
        settings.pipeline.monte_carlo.region_size = 500
        settings.pipeline.monte_carlo.confidence_threshold = 0.7
        c._settings = settings
        c._mc_sampler = None
        c._llm_client = MagicMock()

        mock_sampler = MagicMock()
        with patch("core.evidence.MCSampler", return_value=mock_sampler):
            result = await c.init_mc_sampler()
        assert result is mock_sampler
        assert c._mc_sampler is mock_sampler

    @pytest.mark.asyncio
    async def test_init_mc_sampler_inits_llm_first(self) -> None:
        c = _make_container()
        settings = _make_settings()
        settings.pipeline.monte_carlo.enabled = True
        settings.pipeline.monte_carlo.threshold = 0.5
        settings.pipeline.monte_carlo.sample_size = 3
        settings.pipeline.monte_carlo.region_size = 500
        settings.pipeline.monte_carlo.confidence_threshold = 0.7
        c._settings = settings
        c._mc_sampler = None
        c._llm_client = None

        mock_llm = MagicMock()
        mock_sampler = MagicMock()
        with (
            patch.object(c, "init_llm", AsyncMock(return_value=mock_llm)),
            patch("core.evidence.MCSampler", return_value=mock_sampler),
        ):
            result = await c.init_mc_sampler()
        assert result is mock_sampler


class TestContainerLifecycleMemoryService:
    """Tests for ContainerLifecycleMixin memory service methods."""

    def test_memory_service_property(self) -> None:
        c = _make_container()
        c._memory_service = None
        assert c.memory_service is None

        mock_ms = MagicMock()
        c._memory_service = mock_ms
        assert c.memory_service is mock_ms

    @pytest.mark.asyncio
    async def test_init_memory_service_skips_without_deps(self) -> None:
        c = _make_container()
        c._memory_service = None
        c._llm_client = None
        c._cache_client = None

        with patch.object(c, "graph_pool", return_value=None):
            result = await c.init_memory_service()
        assert result is None

    @pytest.mark.asyncio
    async def test_init_memory_service_returns_existing(self) -> None:
        c = _make_container()
        existing = MagicMock()
        c._memory_service = existing
        result = await c.init_memory_service()
        assert result is existing

    @pytest.mark.asyncio
    async def test_init_memory_service_handles_exception(self) -> None:
        c = _make_container()
        c._memory_service = None
        c._llm_client = MagicMock()
        c._cache_client = MagicMock()
        c._settings = _make_settings()

        with (
            patch.object(c, "graph_pool", return_value=MagicMock()),
            patch.object(c, "vector_repo", return_value=MagicMock()),
            patch.object(c, "graph_entity_repo", return_value=MagicMock()),
            patch.object(c, "_get_embedding_model_id", return_value="text-embedding-3-small"),
            patch(
                "modules.memory.integration.memory_service.MemoryIntegrationService",
                side_effect=Exception("init failed"),
            ),
        ):
            result = await c.init_memory_service()
        assert result is None


class TestContainerLifecycleCausalInferenceService:
    """Tests for ContainerLifecycleMixin causal inference service."""

    @pytest.mark.asyncio
    async def test_init_causal_returns_existing(self) -> None:
        c = _make_container()
        existing = MagicMock()
        c._causal_inference_service = existing
        result = await c.init_causal_inference_service()
        assert result is existing

    @pytest.mark.asyncio
    async def test_init_causal_skips_without_graph_pool(self) -> None:
        c = _make_container()
        c._causal_inference_service = None
        c._llm_client = MagicMock()
        with patch.object(c, "graph_pool", return_value=None):
            result = await c.init_causal_inference_service()
        assert result is None

    @pytest.mark.asyncio
    async def test_init_causal_skips_without_llm(self) -> None:
        c = _make_container()
        c._causal_inference_service = None
        c._llm_client = None
        with patch.object(c, "graph_pool", return_value=MagicMock()):
            result = await c.init_causal_inference_service()
        assert result is None

    @pytest.mark.asyncio
    async def test_init_causal_skips_without_causal_repo(self) -> None:
        c = _make_container()
        c._causal_inference_service = None
        c._llm_client = MagicMock()
        c._settings = _make_settings()
        with (
            patch.object(c, "graph_pool", return_value=MagicMock()),
            patch.object(c, "causal_repo", return_value=None),
        ):
            result = await c.init_causal_inference_service()
        assert result is None

    @pytest.mark.asyncio
    async def test_init_causal_creates_instance(self) -> None:
        c = _make_container()
        c._causal_inference_service = None
        c._llm_client = MagicMock()
        c._settings = _make_settings()

        mock_svc = MagicMock()
        with (
            patch.object(c, "graph_pool", return_value=MagicMock()),
            patch.object(c, "causal_repo", return_value=MagicMock()),
            patch("modules.memory.causal.CausalInferenceService", return_value=mock_svc),
            patch("modules.memory.causal.InferenceConfig", return_value=MagicMock()),
        ):
            result = await c.init_causal_inference_service()
        assert result is mock_svc

    @pytest.mark.asyncio
    async def test_init_causal_handles_exception(self) -> None:
        c = _make_container()
        c._causal_inference_service = None
        c._llm_client = MagicMock()
        c._settings = _make_settings()

        with (
            patch.object(c, "graph_pool", return_value=MagicMock()),
            patch.object(c, "causal_repo", return_value=MagicMock()),
            patch(
                "modules.memory.causal.CausalInferenceService", side_effect=Exception("init failed")
            ),
            patch("modules.memory.causal.InferenceConfig", return_value=MagicMock()),
        ):
            result = await c.init_causal_inference_service()
        assert result is None


class TestContainerLifecycleShutdown:
    """Tests for ContainerLifecycleMixin.shutdown."""

    @pytest.mark.asyncio
    async def test_shutdown_sets_flag(self) -> None:
        c = _make_container()
        c._strategy = None
        c._cache_client = None
        c._scheduler = None
        c._source_scheduler = None
        c._pipeline = None
        c._llm_client = None
        c._live_config = None
        c._smart_fetcher = None
        await c.shutdown()
        assert c._shutdown is True

    @pytest.mark.asyncio
    async def test_shutdown_idempotent(self) -> None:
        c = _make_container()
        c._shutdown = True
        c._strategy = None
        c._cache_client = None
        await c.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_stops_scheduler(self) -> None:
        c = _make_container()
        mock_scheduler = MagicMock()
        c._scheduler = mock_scheduler
        c._source_scheduler = None
        c._pipeline = None
        c._llm_client = None
        c._live_config = None
        c._smart_fetcher = None
        c._cache_client = None
        c._strategy = None
        await c.shutdown()
        mock_scheduler.shutdown.assert_called_once_with(wait=False)

    @pytest.mark.asyncio
    async def test_shutdown_stops_source_scheduler(self) -> None:
        c = _make_container()
        mock_ss = MagicMock()
        c._source_scheduler = mock_ss
        c._scheduler = None
        c._pipeline = None
        c._llm_client = None
        c._live_config = None
        c._smart_fetcher = None
        c._cache_client = None
        c._strategy = None
        await c.shutdown()
        mock_ss.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_stops_pipeline_worker(self) -> None:
        c = _make_container()
        mock_worker = MagicMock()
        mock_worker.stop = AsyncMock()
        c._pipeline = MagicMock()
        c._pipeline_worker = mock_worker
        c._scheduler = None
        c._source_scheduler = None
        c._llm_client = None
        c._live_config = None
        c._smart_fetcher = None
        c._cache_client = None
        c._strategy = None
        with patch.object(c, "pipeline_worker", return_value=mock_worker):
            await c.shutdown()
        mock_worker.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_stops_llm_queue_manager(self) -> None:
        c = _make_container()
        mock_queue_mgr = MagicMock()
        mock_queue_mgr.shutdown = AsyncMock()
        mock_llm = MagicMock()
        mock_llm._queue_manager = mock_queue_mgr
        c._llm_client = mock_llm
        c._scheduler = None
        c._source_scheduler = None
        c._pipeline = None
        c._live_config = None
        c._smart_fetcher = None
        c._cache_client = None
        c._strategy = None
        await c.shutdown()
        mock_queue_mgr.shutdown.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_stops_live_config(self) -> None:
        c = _make_container()
        mock_live_config = MagicMock()
        mock_live_config.stop = AsyncMock()
        c._live_config = mock_live_config
        c._scheduler = None
        c._source_scheduler = None
        c._pipeline = None
        c._llm_client = None
        c._smart_fetcher = None
        c._cache_client = None
        c._strategy = None
        await c.shutdown()
        mock_live_config.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_closes_smart_fetcher(self) -> None:
        c = _make_container()
        mock_sf = MagicMock()
        mock_sf.close = AsyncMock()
        c._smart_fetcher = mock_sf
        c._scheduler = None
        c._source_scheduler = None
        c._pipeline = None
        c._llm_client = None
        c._live_config = None
        c._cache_client = None
        c._strategy = None
        await c.shutdown()
        mock_sf.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_shuts_down_cache(self) -> None:
        c = _make_container()
        mock_cache = MagicMock()
        mock_cache.shutdown = AsyncMock()
        c._cache_client = mock_cache
        c._scheduler = None
        c._source_scheduler = None
        c._pipeline = None
        c._llm_client = None
        c._live_config = None
        c._smart_fetcher = None
        c._strategy = None
        await c.shutdown()
        mock_cache.shutdown.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_shuts_down_pools(self) -> None:
        c = _make_container()
        strategy = _make_strategy(has_graph=True)
        c._strategy = strategy
        c._scheduler = None
        c._source_scheduler = None
        c._pipeline = None
        c._llm_client = None
        c._live_config = None
        c._smart_fetcher = None
        c._cache_client = None
        await c.shutdown()
        strategy.relational_pool.shutdown.assert_called_once()
        strategy.graph_pool.shutdown.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_skips_graph_pool_if_none(self) -> None:
        c = _make_container()
        strategy = _make_strategy(has_graph=False)
        c._strategy = strategy
        c._scheduler = None
        c._source_scheduler = None
        c._pipeline = None
        c._llm_client = None
        c._live_config = None
        c._smart_fetcher = None
        c._cache_client = None
        await c.shutdown()
        strategy.relational_pool.shutdown.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_handles_llm_queue_error(self) -> None:
        c = _make_container()
        mock_queue_mgr = MagicMock()
        mock_queue_mgr.shutdown = AsyncMock(side_effect=Exception("queue error"))
        mock_llm = MagicMock()
        mock_llm._queue_manager = mock_queue_mgr
        c._llm_client = mock_llm
        c._scheduler = None
        c._source_scheduler = None
        c._pipeline = None
        c._live_config = None
        c._smart_fetcher = None
        c._cache_client = None
        c._strategy = None
        await c.shutdown()  # Should not raise

    @pytest.mark.asyncio
    async def test_shutdown_handles_live_config_error(self) -> None:
        c = _make_container()
        mock_live_config = MagicMock()
        mock_live_config.stop = AsyncMock(side_effect=Exception("config error"))
        c._live_config = mock_live_config
        c._scheduler = None
        c._source_scheduler = None
        c._pipeline = None
        c._llm_client = None
        c._smart_fetcher = None
        c._cache_client = None
        c._strategy = None
        await c.shutdown()  # Should not raise


class TestContainerLifecycleLLMConfigReload:
    """Tests for ContainerLifecycleMixin._on_llm_config_reload."""

    @pytest.mark.asyncio
    async def test_config_reload_updates_settings(self) -> None:
        c = _make_container()
        c._settings = _make_settings()
        c._smart_router = None
        c._llm_experience = None
        new_config = MagicMock()
        await c._on_llm_config_reload(new_config)
        assert c._settings.llm is new_config

    @pytest.mark.asyncio
    async def test_config_reload_recreates_smart_router(self) -> None:
        c = _make_container()
        c._settings = _make_settings()
        c._smart_router = MagicMock()
        c._smart_router._circuit_breakers = {}
        c._llm_experience = MagicMock()
        c._llm_client = MagicMock()

        new_config = MagicMock()
        with patch("core.llm.routing.smart_router.SmartRouter", return_value=MagicMock()):
            await c._on_llm_config_reload(new_config)
        assert c._smart_router is not None

    @pytest.mark.asyncio
    async def test_config_reload_handles_exception(self) -> None:
        c = _make_container()
        c._settings = MagicMock()
        type(c._settings).llm = property(lambda self: 1 / 0)
        c._smart_router = MagicMock()
        c._llm_experience = MagicMock()
        await c._on_llm_config_reload(MagicMock())


class TestContainerLifecycleCommunityHealthCheck:
    """Tests for ContainerLifecycleMixin._community_health_check."""

    @pytest.mark.asyncio
    async def test_community_health_check_skips_without_graph_pool(self) -> None:
        c = _make_container()
        with patch.object(c, "graph_pool", return_value=None):
            result = await c._community_health_check()
        assert result["status"] == "skipped"
        assert result["reason"] == "no_graph_pool"

    @pytest.mark.asyncio
    async def test_community_health_check_handles_exception(self) -> None:
        c = _make_container()
        with (
            patch.object(c, "graph_pool", return_value=MagicMock()),
            patch(
                "modules.knowledge.graph.community.health.checker.CommunityHealthChecker",
                side_effect=Exception("check failed"),
            ),
        ):
            result = await c._community_health_check()
        assert result["status"] == "error"


class TestContainerLifecycleSetupScheduler:
    """Tests for ContainerLifecycleMixin._setup_scheduler."""

    def test_setup_scheduler_disabled(self) -> None:
        c = _make_container()
        c._settings = _make_settings()
        c._settings.scheduler.enabled = False
        c._setup_scheduler()
        assert c._scheduler is None

    def test_setup_scheduler_creates_and_starts(self) -> None:
        c = _make_container()
        settings = _make_settings()
        settings.scheduler.enabled = True
        c._settings = settings
        c._strategy = _make_strategy(has_graph=True)
        c._graph_writer = MagicMock()
        c._memory_service = None
        c._scheduler = None

        mock_jobs = MagicMock()
        mock_scheduler = MagicMock()
        mock_scheduler.get_jobs.return_value = []
        mock_scheduler.start = MagicMock()

        with (
            patch.object(c, "scheduler_job_runner", return_value=mock_jobs),
            patch.object(c, "graph_pool", return_value=MagicMock()),
            patch.object(c, "llm_client", return_value=MagicMock()),
            patch.object(c, "community_updater", return_value=MagicMock()),
            patch("apscheduler.schedulers.asyncio.AsyncIOScheduler", return_value=mock_scheduler),
            patch("apscheduler.triggers.interval.IntervalTrigger"),
            patch("apscheduler.triggers.cron.CronTrigger"),
            patch("apscheduler.triggers.date.DateTrigger"),
        ):
            c._setup_scheduler()
        assert c._scheduler is mock_scheduler
        mock_scheduler.start.assert_called_once()

    def test_setup_scheduler_adds_archive_jobs_with_graph_writer(self) -> None:
        c = _make_container()
        settings = _make_settings()
        settings.scheduler.enabled = True
        c._settings = settings
        c._strategy = _make_strategy(has_graph=True)
        c._graph_writer = MagicMock()
        c._memory_service = None
        c._scheduler = None

        mock_jobs = MagicMock()
        mock_scheduler = MagicMock()
        mock_scheduler.get_jobs.return_value = []
        mock_scheduler.start = MagicMock()

        with (
            patch.object(c, "scheduler_job_runner", return_value=mock_jobs),
            patch.object(c, "graph_pool", return_value=MagicMock()),
            patch.object(c, "llm_client", return_value=MagicMock()),
            patch.object(c, "community_updater", return_value=MagicMock()),
            patch("apscheduler.schedulers.asyncio.AsyncIOScheduler", return_value=mock_scheduler),
            patch("apscheduler.triggers.interval.IntervalTrigger"),
            patch("apscheduler.triggers.cron.CronTrigger"),
            patch("apscheduler.triggers.date.DateTrigger"),
        ):
            c._setup_scheduler()

        job_ids = [call.kwargs.get("id", "") for call in mock_scheduler.add_job.call_args_list]
        assert "archive_old_neo4j_nodes" in job_ids
        assert "cleanup_orphan_entity_vectors" in job_ids

    def test_setup_scheduler_adds_memory_consolidation(self) -> None:
        c = _make_container()
        settings = _make_settings()
        settings.scheduler.enabled = True
        c._settings = settings
        c._strategy = _make_strategy(has_graph=True)
        c._graph_writer = MagicMock()
        c._memory_service = MagicMock()
        c._scheduler = None

        mock_jobs = MagicMock()
        mock_scheduler = MagicMock()
        mock_scheduler.get_jobs.return_value = []
        mock_scheduler.start = MagicMock()

        with (
            patch.object(c, "scheduler_job_runner", return_value=mock_jobs),
            patch.object(c, "graph_pool", return_value=MagicMock()),
            patch.object(c, "llm_client", return_value=MagicMock()),
            patch.object(c, "community_updater", return_value=MagicMock()),
            patch("apscheduler.schedulers.asyncio.AsyncIOScheduler", return_value=mock_scheduler),
            patch("apscheduler.triggers.interval.IntervalTrigger"),
            patch("apscheduler.triggers.cron.CronTrigger"),
            patch("apscheduler.triggers.date.DateTrigger"),
        ):
            c._setup_scheduler()

        job_ids = [call.kwargs.get("id", "") for call in mock_scheduler.add_job.call_args_list]
        assert "memory_consolidation" in job_ids


# ══════════════════════════════════════════════════════════════════════
# Module-level Event Handler Tests
# ══════════════════════════════════════════════════════════════════════


class TestHandleLLMFailureAsync:
    """Tests for _handle_llm_failure_async module-level handler."""

    @pytest.mark.asyncio
    async def test_handler_records_event(self) -> None:
        from src.container.lifecycle import _handle_llm_failure_async

        mock_repo = MagicMock()
        mock_repo.record = AsyncMock()
        mock_event = MagicMock()
        mock_event.call_point = "test"
        mock_event.provider = "openai"
        await _handle_llm_failure_async(mock_event, mock_repo)
        mock_repo.record.assert_called_once_with(mock_event)

    @pytest.mark.asyncio
    async def test_handler_handles_repo_error(self) -> None:
        from src.container.lifecycle import _handle_llm_failure_async

        mock_repo = MagicMock()
        mock_repo.record = AsyncMock(side_effect=Exception("db error"))
        mock_event = MagicMock()
        mock_event.call_point = "test"
        mock_event.provider = "openai"
        await _handle_llm_failure_async(mock_event, mock_repo)  # Should not raise


class TestHandleLLMUsageMetrics:
    """Tests for _handle_llm_usage_metrics module-level handler."""

    @pytest.mark.asyncio
    async def test_handler_updates_metrics(self) -> None:
        from src.container.lifecycle import _handle_llm_usage_metrics

        mock_event = MagicMock()
        mock_event.provider = "openai"
        mock_event.model = "gpt-4"
        mock_event.call_point = "test"
        mock_event.label = "test-label"
        mock_event.tokens = MagicMock(input_tokens=100, output_tokens=50, total_tokens=150)

        mock_metrics = MagicMock()
        mock_metrics.llm_token_input_total.labels.return_value.inc = MagicMock()
        mock_metrics.llm_token_output_total.labels.return_value.inc = MagicMock()
        mock_metrics.llm_token_total.labels.return_value.inc = MagicMock()

        with patch("core.observability.metrics.metrics", mock_metrics):
            await _handle_llm_usage_metrics(mock_event)

        mock_metrics.llm_token_input_total.labels.assert_called_once()
        mock_metrics.llm_token_output_total.labels.assert_called_once()
        mock_metrics.llm_token_total.labels.assert_called_once()

    @pytest.mark.asyncio
    async def test_handler_handles_metrics_error(self) -> None:
        from src.container.lifecycle import _handle_llm_usage_metrics

        mock_event = MagicMock()
        mock_event.provider = "openai"
        mock_event.model = "gpt-4"
        mock_event.call_point = "test"
        mock_event.label = "test-label"
        mock_event.tokens = MagicMock(input_tokens=100, output_tokens=50, total_tokens=150)

        with patch("core.observability.metrics.metrics", side_effect=Exception("metrics error")):
            await _handle_llm_usage_metrics(mock_event)  # Should not raise


# ══════════════════════════════════════════════════════════════════════
# Container Integration Tests (facade)
# ══════════════════════════════════════════════════════════════════════


class TestContainerConfigure:
    """Tests for Container.configure and settings property."""

    def test_configure_sets_settings(self) -> None:
        c = _make_container()
        settings = _make_settings()
        result = c.configure(settings)
        assert result is c
        assert c._settings is settings

    def test_configure_with_debug(self) -> None:
        c = _make_container()
        settings = _make_settings()
        c.configure(settings, debug=True)
        assert c._debug_mode is True

    def test_settings_property_raises_without_configure(self) -> None:
        c = _make_container()
        c._settings = None
        with pytest.raises(RuntimeError, match="Container not configured"):
            _ = c.settings

    def test_settings_property_returns_settings(self) -> None:
        c = _make_container()
        settings = _make_settings()
        c.configure(settings)
        assert c.settings is settings


class TestContainerIsJobRegistered:
    """Tests for Container.is_job_registered."""

    def test_is_job_registered_returns_false_without_scheduler(self) -> None:
        c = _make_container()
        c._scheduler = None
        assert c.is_job_registered("test_job") is False

    def test_is_job_registered_returns_true_for_existing_job(self) -> None:
        c = _make_container()
        mock_scheduler = MagicMock()
        mock_job = MagicMock()
        mock_job.id = "test_job"
        mock_scheduler.get_jobs.return_value = [mock_job]
        c._scheduler = mock_scheduler
        assert c.is_job_registered("test_job") is True

    def test_is_job_registered_returns_false_for_missing_job(self) -> None:
        c = _make_container()
        mock_scheduler = MagicMock()
        mock_job = MagicMock()
        mock_job.id = "other_job"
        mock_scheduler.get_jobs.return_value = [mock_job]
        c._scheduler = mock_scheduler
        assert c.is_job_registered("test_job") is False

    def test_is_job_registered_handles_exception(self) -> None:
        c = _make_container()
        mock_scheduler = MagicMock()
        mock_scheduler.get_jobs.side_effect = Exception("scheduler error")
        c._scheduler = mock_scheduler
        assert c.is_job_registered("test_job") is False


class TestContainerMemoryDiagnostics:
    """Tests for Container.memory_diagnostics."""

    @pytest.mark.asyncio
    async def test_memory_diagnostics_without_service(self) -> None:
        c = _make_container()
        c._memory_service = None
        result = await c.memory_diagnostics()
        assert result["service_initialized"] is False
        assert result["temporal_event_count"] == 0
        assert result["causal_link_count"] == 0

    @pytest.mark.asyncio
    async def test_memory_diagnostics_with_service(self) -> None:
        c = _make_container()
        mock_ms = MagicMock()
        mock_ms._temporal_repo.count_events = AsyncMock(return_value=10)
        mock_ms._causal_repo.count_causal_links = AsyncMock(return_value=5)
        mock_ms._consolidation_queue.length = AsyncMock(return_value=2)
        mock_ms._config.slow_path_enabled = True
        c._memory_service = mock_ms

        result = await c.memory_diagnostics()
        assert result["service_initialized"] is True
        assert result["temporal_event_count"] == 10
        assert result["causal_link_count"] == 5
        assert result["pending_consolidation"] == 2
        assert result["slow_path_enabled"] is True

    @pytest.mark.asyncio
    async def test_memory_diagnostics_handles_query_error(self) -> None:
        c = _make_container()
        mock_ms = MagicMock()
        mock_ms._temporal_repo.count_events = AsyncMock(side_effect=Exception("query error"))
        c._memory_service = mock_ms
        result = await c.memory_diagnostics()
        assert result["service_initialized"] is True


class TestContainerGlobalAccess:
    """Tests for get_container, set_container, get_settings, set_settings."""

    def test_set_and_get_container(self) -> None:
        from src.container import get_container, set_container

        c = _make_container()
        set_container(c)
        assert get_container() is c

    def test_get_container_raises_without_init(self) -> None:
        from src.container import get_container, reset_container, set_container

        try:
            original = get_container()
        except RuntimeError:
            original = None
        reset_container()
        try:
            with pytest.raises(RuntimeError, match="Container not initialized"):
                get_container()
        finally:
            if original is not None:
                set_container(original)

    def test_set_and_get_settings(self) -> None:
        from src.container import get_settings, set_settings

        settings = _make_settings()
        set_settings(settings)
        assert get_settings() is settings
