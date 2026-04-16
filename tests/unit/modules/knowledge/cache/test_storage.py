# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for modules.knowledge.cache.storage module."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.protocols.knowledge_cache import KnowledgeCluster
from modules.knowledge.cache.storage import KnowledgeCache


class TestKnowledgeCacheInit:
    """Test KnowledgeCache initialization."""

    def test_init_with_defaults(self, tmp_path):
        """Test initialization with default parameters."""
        with patch("modules.knowledge.cache.storage.KnowledgeCache._create_table"):
            with patch("modules.knowledge.cache.storage.KnowledgeCache._load_from_parquet"):
                with patch("modules.knowledge.cache.storage.KnowledgeCache._start_sync_daemon"):
                    cache = KnowledgeCache(cache_path=str(tmp_path))

                    assert cache.cache_path == tmp_path.resolve()
                    assert cache._max_queries == 5

    def test_init_with_custom_params(self, tmp_path):
        """Test initialization with custom parameters."""
        mock_llm = MagicMock()

        with patch("modules.knowledge.cache.storage.KnowledgeCache._create_table"):
            with patch("modules.knowledge.cache.storage.KnowledgeCache._load_from_parquet"):
                with patch("modules.knowledge.cache.storage.KnowledgeCache._start_sync_daemon"):
                    cache = KnowledgeCache(
                        cache_path=str(tmp_path),
                        llm_client=mock_llm,
                        sync_interval=30,
                        sync_threshold=50,
                        max_queries=10,
                    )

                    assert cache._llm_client is mock_llm
                    assert cache._sync_threshold == 50
                    assert cache._max_queries == 10


class TestKnowledgeCacheGetStats:
    """Test get_stats method."""

    @pytest.fixture
    def cache(self, tmp_path):
        """Create KnowledgeCache with mock database."""
        with patch("modules.knowledge.cache.storage.KnowledgeCache._create_table"):
            with patch("modules.knowledge.cache.storage.KnowledgeCache._load_from_parquet"):
                with patch("modules.knowledge.cache.storage.KnowledgeCache._start_sync_daemon"):
                    with patch("modules.knowledge.cache.storage.KnowledgeCache._shutdown"):
                        cache = KnowledgeCache(cache_path=str(tmp_path))
                        return cache

    def test_get_stats_empty(self, cache):
        """Test get_stats with empty cache."""
        cache.db.execute = MagicMock(return_value=MagicMock())
        cache.db.execute.return_value.fetchone.return_value = [0, None, 0]

        stats = cache.get_stats()

        assert stats["count"] == 0
        assert stats["avg_hotness"] == 0.0
        assert stats["with_embedding"] == 0


class TestKnowledgeCacheGet:
    """Test get method."""

    @pytest.fixture
    def cache(self, tmp_path):
        """Create KnowledgeCache with mock database."""
        with patch("modules.knowledge.cache.storage.KnowledgeCache._create_table"):
            with patch("modules.knowledge.cache.storage.KnowledgeCache._load_from_parquet"):
                with patch("modules.knowledge.cache.storage.KnowledgeCache._start_sync_daemon"):
                    with patch("modules.knowledge.cache.storage.KnowledgeCache._shutdown"):
                        cache = KnowledgeCache(cache_path=str(tmp_path))
                        return cache

    @pytest.mark.asyncio
    async def test_get_found(self, cache):
        """Test get finds cluster."""
        cache.db.execute = MagicMock(return_value=MagicMock())
        cache.db.execute.return_value.fetchone.return_value = [
            "cluster1",
            "Test Cluster",
            "Description",
            "Content",
            None,  # embedding
            "",  # query
            0.5,  # hotness
            None,  # create_time
            None,  # last_modified
            0,  # version
        ]

        cluster = await cache.get("cluster1")

        assert cluster is not None
        assert cluster.id == "cluster1"
        assert cluster.name == "Test Cluster"

    @pytest.mark.asyncio
    async def test_get_not_found(self, cache):
        """Test get returns None when not found."""
        cache.db.execute = MagicMock(return_value=MagicMock())
        cache.db.execute.return_value.fetchone.return_value = None

        cluster = await cache.get("nonexistent")

        assert cluster is None


class TestKnowledgeCacheRemove:
    """Test remove method."""

    @pytest.fixture
    def cache(self, tmp_path):
        """Create KnowledgeCache with mock database."""
        with patch("modules.knowledge.cache.storage.KnowledgeCache._create_table"):
            with patch("modules.knowledge.cache.storage.KnowledgeCache._load_from_parquet"):
                with patch("modules.knowledge.cache.storage.KnowledgeCache._start_sync_daemon"):
                    with patch("modules.knowledge.cache.storage.KnowledgeCache._shutdown"):
                        cache = KnowledgeCache(cache_path=str(tmp_path))
                        return cache

    @pytest.mark.asyncio
    async def test_remove_found(self, cache):
        """Test remove removes cluster."""
        cache.db.execute = MagicMock(return_value=MagicMock())
        cache.db.execute.return_value.fetchone.return_value = [1]

        result = await cache.remove("cluster1")

        assert result is True

    @pytest.mark.asyncio
    async def test_remove_not_found(self, cache):
        """Test remove returns False when not found."""
        cache.db.execute = MagicMock(return_value=MagicMock())
        cache.db.execute.return_value.fetchone.return_value = [0]

        result = await cache.remove("nonexistent")

        assert result is False


class TestKnowledgeCacheCleanupStale:
    """Test cleanup_stale method."""

    @pytest.fixture
    def cache(self, tmp_path):
        """Create KnowledgeCache with mock database."""
        with patch("modules.knowledge.cache.storage.KnowledgeCache._create_table"):
            with patch("modules.knowledge.cache.storage.KnowledgeCache._load_from_parquet"):
                with patch("modules.knowledge.cache.storage.KnowledgeCache._start_sync_daemon"):
                    with patch("modules.knowledge.cache.storage.KnowledgeCache._shutdown"):
                        cache = KnowledgeCache(cache_path=str(tmp_path))
                        return cache

    @pytest.mark.asyncio
    async def test_cleanup_stale(self, cache):
        """Test cleanup_stale removes clusters below threshold."""
        cache.db.execute = MagicMock(return_value=MagicMock())
        cache.db.execute.return_value.fetchone.return_value = [5]

        removed = await cache.cleanup_stale(hotness_threshold=0.3)

        assert removed == 5


class TestKnowledgeCacheUpdateHotness:
    """Test update_hotness method."""

    @pytest.fixture
    def cache(self, tmp_path):
        """Create KnowledgeCache with mock database."""
        with patch("modules.knowledge.cache.storage.KnowledgeCache._create_table"):
            with patch("modules.knowledge.cache.storage.KnowledgeCache._load_from_parquet"):
                with patch("modules.knowledge.cache.storage.KnowledgeCache._start_sync_daemon"):
                    with patch("modules.knowledge.cache.storage.KnowledgeCache._shutdown"):
                        cache = KnowledgeCache(cache_path=str(tmp_path))
                        return cache

    @pytest.mark.asyncio
    async def test_update_hotness(self, cache):
        """Test update_hotness increments hotness."""
        cache.db.execute = MagicMock()

        await cache.update_hotness("cluster1", delta=0.1)

        assert cache.db.execute.called


class TestKnowledgeCacheAddQuery:
    """Test add_query method."""

    @pytest.fixture
    def cache(self, tmp_path):
        """Create KnowledgeCache with mock database."""
        with patch("modules.knowledge.cache.storage.KnowledgeCache._create_table"):
            with patch("modules.knowledge.cache.storage.KnowledgeCache._load_from_parquet"):
                with patch("modules.knowledge.cache.storage.KnowledgeCache._start_sync_daemon"):
                    with patch("modules.knowledge.cache.storage.KnowledgeCache._shutdown"):
                        cache = KnowledgeCache(cache_path=str(tmp_path))
                        return cache

    @pytest.mark.asyncio
    async def test_add_query(self, cache):
        """Test add_query adds query to history."""
        cache.db.execute = MagicMock(return_value=MagicMock())
        cache.db.execute.return_value.fetchone.return_value = ["query1\nquery2"]

        await cache.add_query("cluster1", "new_query")

        assert cache.db.execute.called


class TestKnowledgeCluster:
    """Test KnowledgeCluster model."""

    def test_create_cluster(self):
        """Test creating KnowledgeCluster."""
        cluster = KnowledgeCluster(
            id="cluster1",
            name="Test Cluster",
            description="A test cluster",
            content="Test content",
            query="test query",
        )

        assert cluster.id == "cluster1"
        assert cluster.name == "Test Cluster"
        assert cluster.hotness == 0.5  # default

    def test_cluster_with_embedding(self):
        """Test KnowledgeCluster with embedding."""
        embedding = [0.1] * 384
        cluster = KnowledgeCluster(
            id="cluster1",
            name="Test",
            description="",
            content="",
            embedding=embedding,
        )

        assert cluster.embedding == embedding

    def test_cluster_timestamps(self):
        """Test KnowledgeCluster timestamps."""
        now = datetime.now(UTC)
        cluster = KnowledgeCluster(
            id="cluster1",
            name="Test",
            description="",
            content="",
            create_time=now,
            last_modified=now,
        )

        assert cluster.create_time == now
        assert cluster.last_modified == now
