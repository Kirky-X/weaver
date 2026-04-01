# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for EntityResolver."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestEntityResolverInit:
    """Tests for EntityResolver initialization."""

    def test_init_with_required_params(self):
        """Test EntityResolver initializes with required params."""
        from modules.graph_store.entity_resolver import EntityResolver

        mock_vector_repo = MagicMock()
        mock_entity_repo = MagicMock()

        resolver = EntityResolver(
            entity_repo=mock_entity_repo,
            vector_repo=mock_vector_repo,
        )

        assert resolver._entity_repo is mock_entity_repo
        assert resolver._vector_repo is mock_vector_repo
        assert resolver._llm is None

    def test_init_with_optional_params(self):
        """Test EntityResolver initializes with optional params."""
        from modules.graph_store.entity_resolver import EntityResolver
        from modules.graph_store.name_normalizer import NameNormalizer
        from modules.graph_store.resolution_rules import EntityResolutionRules

        mock_vector_repo = MagicMock()
        mock_entity_repo = MagicMock()
        mock_llm = MagicMock()
        mock_rules = MagicMock(spec=EntityResolutionRules)
        mock_normalizer = MagicMock(spec=NameNormalizer)

        resolver = EntityResolver(
            entity_repo=mock_entity_repo,
            vector_repo=mock_vector_repo,
            llm=mock_llm,
            resolution_rules=mock_rules,
            name_normalizer=mock_normalizer,
        )

        assert resolver._llm is mock_llm
        assert resolver._rules is mock_rules
        assert resolver._normalizer is mock_normalizer


class TestEntityResolverResolveEntity:
    """Tests for EntityResolver.resolve_entity()."""

    @pytest.fixture
    def mock_entity_repo(self):
        repo = MagicMock()
        repo.find_entity = AsyncMock(return_value=None)
        repo.merge_entity = AsyncMock(return_value="neo4j-id-123")
        repo.add_alias = AsyncMock()
        repo.find_entities_by_ids = AsyncMock(return_value=[])
        return repo

    @pytest.fixture
    def mock_vector_repo(self):
        repo = MagicMock()
        repo.find_similar_entities = AsyncMock(return_value=[])
        repo.upsert_entity_vector = AsyncMock()
        return repo

    @pytest.fixture
    def resolver(self, mock_entity_repo, mock_vector_repo):
        from modules.graph_store.entity_resolver import EntityResolver

        return EntityResolver(
            entity_repo=mock_entity_repo,
            vector_repo=mock_vector_repo,
        )

    @pytest.mark.asyncio
    async def test_resolve_entity_filters_metric_string(self, resolver):
        """Test resolve_entity filters out metric strings."""
        result = await resolver.resolve_entity(
            name="12.73%",
            entity_type="数据指标",
            embedding=[0.1] * 1536,
        )

        assert result["match_type"] == "filtered_metric"
        assert result["is_new"] is False

    @pytest.mark.asyncio
    async def test_resolve_entity_filters_monetary_value(self, resolver):
        """Test resolve_entity filters out monetary values."""
        result = await resolver.resolve_entity(
            name="97.65亿元",
            entity_type="数据指标",
            embedding=[0.1] * 1536,
        )

        assert result["match_type"] == "filtered_metric"

    @pytest.mark.asyncio
    async def test_resolve_entity_returns_exact_match(self, resolver, mock_entity_repo):
        """Test resolve_entity returns exact match."""
        mock_entity_repo.find_entity.return_value = {
            "neo4j_id": "existing-id",
            "canonical_name": "Test Entity",
        }

        result = await resolver.resolve_entity(
            name="Test Entity",
            entity_type="PERSON",
            embedding=[0.1] * 1536,
        )

        assert result["match_type"] == "exact"
        assert result["is_new"] is False
        assert result["neo4j_id"] == "existing-id"

    @pytest.mark.asyncio
    async def test_resolve_entity_creates_new_without_embedding(self, resolver, mock_entity_repo):
        """Test resolve_entity creates new entity without embedding."""
        result = await resolver.resolve_entity(
            name="New Entity",
            entity_type="ORG",
            embedding=[],
        )

        assert result["is_new"] is True
        assert result["match_type"] == "new"
        mock_entity_repo.merge_entity.assert_called_once()

    @pytest.mark.asyncio
    async def test_resolve_entity_finds_similar(self, resolver, mock_entity_repo, mock_vector_repo):
        """Test resolve_entity finds similar entities."""
        mock_similar = MagicMock()
        mock_similar.neo4j_id = "similar-id"
        mock_similar.similarity = 0.9

        mock_vector_repo.find_similar_entities.return_value = [mock_similar]

        mock_entity_repo.find_entities_by_ids.return_value = [
            {"neo4j_id": "similar-id", "canonical_name": "Similar Entity", "type": "PERSON"}
        ]

        # Need to mock find_entity to return None initially
        mock_entity_repo.find_entity.return_value = None

        result = await resolver.resolve_entity(
            name="New Entity",
            entity_type="PERSON",
            embedding=[0.1] * 1536,
        )

        # Should call find_similar_entities
        mock_vector_repo.find_similar_entities.assert_called_once()


class TestEntityResolverLooksLikeMetricString:
    """Tests for _looks_like_metric_string()."""

    @pytest.fixture
    def resolver(self):
        from modules.graph_store.entity_resolver import EntityResolver

        return EntityResolver(
            entity_repo=MagicMock(),
            vector_repo=MagicMock(),
        )

    def test_percentage_detected(self, resolver):
        """Test percentage strings are detected."""
        assert resolver._looks_like_metric_string("12.73%") is True
        assert resolver._looks_like_metric_string("9.90%") is True

    def test_monetary_values_detected(self, resolver):
        """Test monetary values are detected."""
        assert resolver._looks_like_metric_string("97.65亿元") is True
        assert resolver._looks_like_metric_string("6亿元") is True

    def test_share_counts_detected(self, resolver):
        """Test share counts are detected."""
        assert resolver._looks_like_metric_string("2.42亿股") is True

    def test_composite_metrics_detected(self, resolver):
        """Test composite metrics are detected."""
        assert resolver._looks_like_metric_string("本土市场游戏收入1642亿元") is True

    def test_normal_names_not_detected(self, resolver):
        """Test normal entity names are not filtered."""
        assert resolver._looks_like_metric_string("腾讯控股") is False
        assert resolver._looks_like_metric_string("阿里巴巴集团") is False


class TestEntityResolverBatch:
    """Tests for resolve_entities_batch()."""

    @pytest.fixture
    def resolver(self):
        from modules.graph_store.entity_resolver import EntityResolver

        resolver = EntityResolver(
            entity_repo=MagicMock(),
            vector_repo=MagicMock(),
        )
        resolver.resolve_entity = AsyncMock(
            return_value={"neo4j_id": "id", "canonical_name": "name", "is_new": True}
        )
        return resolver

    @pytest.mark.asyncio
    async def test_resolve_entities_batch_processes_all(self, resolver):
        """Test resolve_entities_batch processes all entities."""
        entities = [
            {"name": "Entity 1", "type": "PERSON", "embedding": []},
            {"name": "Entity 2", "type": "ORG", "embedding": []},
        ]

        results = await resolver.resolve_entities_batch(entities)

        assert len(results) == 2
        assert resolver.resolve_entity.call_count == 2


class TestEntityResolverPreResolveCheck:
    """Tests for pre_resolve_check()."""

    @pytest.fixture
    def mock_entity_repo(self):
        repo = MagicMock()
        repo.find_entity = AsyncMock(return_value=None)
        return repo

    @pytest.fixture
    def resolver(self, mock_entity_repo):
        from modules.graph_store.entity_resolver import EntityResolver

        return EntityResolver(
            entity_repo=mock_entity_repo,
            vector_repo=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_pre_resolve_check_returns_none_when_not_found(self, resolver):
        """Test pre_resolve_check returns None when entity not found."""
        result = await resolver.pre_resolve_check("New Entity", "PERSON")

        assert result is None

    @pytest.mark.asyncio
    async def test_pre_resolve_check_returns_existing(self, resolver, mock_entity_repo):
        """Test pre_resolve_check returns existing entity."""
        mock_entity_repo.find_entity.return_value = {
            "neo4j_id": "existing-id",
            "canonical_name": "Existing Entity",
        }

        result = await resolver.pre_resolve_check("Existing Entity", "PERSON")

        assert result is not None
        assert result["exists"] is True
        assert result["neo4j_id"] == "existing-id"


class TestEntityResolverGetResolutionStats:
    """Tests for get_resolution_stats()."""

    @pytest.fixture
    def resolver(self):
        from modules.graph_store.entity_resolver import EntityResolver

        return EntityResolver(
            entity_repo=MagicMock(),
            vector_repo=MagicMock(),
        )

    def test_get_resolution_stats_returns_dict(self, resolver):
        """Test get_resolution_stats returns stats dict."""
        stats = resolver.get_resolution_stats()

        assert isinstance(stats, dict)
        assert "known_aliases" in stats
        assert "abbreviations" in stats
        assert "translations" in stats
        assert "rules_count" in stats
