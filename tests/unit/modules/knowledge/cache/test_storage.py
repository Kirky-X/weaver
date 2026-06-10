# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for modules.knowledge.cache.storage module."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.protocols.knowledge_cache import KnowledgeCluster
from modules.knowledge.cache.storage import KnowledgeCache


@pytest.fixture(autouse=True)
def _cleanup_knowledge_caches():
    """Ensure KnowledgeCache resources are released after each test."""
    # Track created caches for cleanup
    _caches: list[KnowledgeCache] = []
    original_init = KnowledgeCache.__init__

    def tracking_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        _caches.append(self)

    KnowledgeCache.__init__ = tracking_init
    yield
    KnowledgeCache.__init__ = original_init

    # Cleanup tracked instances
    for cache in _caches:
        if hasattr(cache, "db") and cache.db is not None:
            try:
                cache.db.close()
            except Exception:
                pass
            cache.db = None
        if hasattr(cache, "_stop_event"):
            cache._stop_event.set()
    _caches.clear()


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
        """Create KnowledgeCache with mock db connection."""
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchone.return_value = [0, None, 0]

        with patch("modules.knowledge.cache.storage.duckdb.connect", return_value=mock_db):
            with patch("modules.knowledge.cache.storage.KnowledgeCache._start_sync_daemon"):
                with patch("modules.knowledge.cache.storage.KnowledgeCache._shutdown"):
                    cache = KnowledgeCache(cache_path=str(tmp_path))
                    yield cache

    def test_get_stats_empty(self, cache):
        """Test get_stats with empty cache."""
        stats = cache.get_stats()
        assert stats["count"] == 0
        assert stats["avg_hotness"] == 0.0
        assert stats["with_embedding"] == 0


class TestKnowledgeCacheGet:
    """Test get method."""

    @pytest.fixture
    def cache_with_cluster(self, tmp_path):
        """Create KnowledgeCache with mock db and one cluster."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = [
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
        mock_db = MagicMock()
        mock_db.execute.return_value = mock_result

        with patch("modules.knowledge.cache.storage.duckdb.connect", return_value=mock_db):
            with patch("modules.knowledge.cache.storage.KnowledgeCache._start_sync_daemon"):
                with patch("modules.knowledge.cache.storage.KnowledgeCache._shutdown"):
                    cache = KnowledgeCache(cache_path=str(tmp_path))
                    yield cache

    @pytest.fixture
    def cache_empty(self, tmp_path):
        """Create KnowledgeCache with mock db returning None."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_db.execute.return_value = mock_result

        with patch("modules.knowledge.cache.storage.duckdb.connect", return_value=mock_db):
            with patch("modules.knowledge.cache.storage.KnowledgeCache._start_sync_daemon"):
                with patch("modules.knowledge.cache.storage.KnowledgeCache._shutdown"):
                    cache = KnowledgeCache(cache_path=str(tmp_path))
                    yield cache

    @pytest.mark.asyncio
    async def test_get_found(self, cache_with_cluster):
        """Test get finds cluster."""
        cluster = await cache_with_cluster.get("cluster1")
        assert cluster is not None
        assert cluster.id == "cluster1"
        assert cluster.name == "Test Cluster"

    @pytest.mark.asyncio
    async def test_get_not_found(self, cache_empty):
        """Test get returns None when not found."""
        cluster = await cache_empty.get("nonexistent")
        assert cluster is None


class TestKnowledgeCacheRemove:
    """Test remove method."""

    @pytest.fixture
    def cache_remove_found(self, tmp_path):
        """Create KnowledgeCache where remove will find cluster."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = [1]
        mock_db = MagicMock()
        mock_db.execute.return_value = mock_result

        with patch("modules.knowledge.cache.storage.duckdb.connect", return_value=mock_db):
            with patch("modules.knowledge.cache.storage.KnowledgeCache._start_sync_daemon"):
                with patch("modules.knowledge.cache.storage.KnowledgeCache._shutdown"):
                    cache = KnowledgeCache(cache_path=str(tmp_path))
                    yield cache

    @pytest.fixture
    def cache_remove_not_found(self, tmp_path):
        """Create KnowledgeCache where remove will not find cluster."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = [0]
        mock_db = MagicMock()
        mock_db.execute.return_value = mock_result

        with patch("modules.knowledge.cache.storage.duckdb.connect", return_value=mock_db):
            with patch("modules.knowledge.cache.storage.KnowledgeCache._start_sync_daemon"):
                with patch("modules.knowledge.cache.storage.KnowledgeCache._shutdown"):
                    cache = KnowledgeCache(cache_path=str(tmp_path))
                    yield cache

    @pytest.mark.asyncio
    async def test_remove_found(self, cache_remove_found):
        """Test remove removes cluster."""
        result = await cache_remove_found.remove("cluster1")
        assert result is True

    @pytest.mark.asyncio
    async def test_remove_not_found(self, cache_remove_not_found):
        """Test remove returns False when not found."""
        result = await cache_remove_not_found.remove("nonexistent")
        assert result is False


class TestKnowledgeCacheCleanupStale:
    """Test cleanup_stale method."""

    @pytest.fixture
    def cache_cleanup(self, tmp_path):
        """Create KnowledgeCache for cleanup test."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = [5]
        mock_db = MagicMock()
        mock_db.execute.return_value = mock_result

        with patch("modules.knowledge.cache.storage.duckdb.connect", return_value=mock_db):
            with patch("modules.knowledge.cache.storage.KnowledgeCache._start_sync_daemon"):
                with patch("modules.knowledge.cache.storage.KnowledgeCache._shutdown"):
                    cache = KnowledgeCache(cache_path=str(tmp_path))
                    yield cache

    @pytest.mark.asyncio
    async def test_cleanup_stale(self, cache_cleanup):
        """Test cleanup_stale removes clusters below threshold."""
        removed = await cache_cleanup.cleanup_stale(hotness_threshold=0.3)
        assert removed == 5


class TestKnowledgeCacheUpdateHotness:
    """Test update_hotness method."""

    @pytest.fixture
    def cache_update(self, tmp_path):
        """Create KnowledgeCache for update test."""
        mock_db = MagicMock()

        with patch("modules.knowledge.cache.storage.duckdb.connect", return_value=mock_db):
            with patch("modules.knowledge.cache.storage.KnowledgeCache._start_sync_daemon"):
                with patch("modules.knowledge.cache.storage.KnowledgeCache._shutdown"):
                    cache = KnowledgeCache(cache_path=str(tmp_path))
                    yield cache

    @pytest.mark.asyncio
    async def test_update_hotness(self, cache_update):
        """Test update_hotness increments hotness."""
        await cache_update.update_hotness("cluster1", delta=0.1)
        assert cache_update.db.execute.called


class TestKnowledgeCacheAddQuery:
    """Test add_query method."""

    @pytest.fixture
    def cache_add_query(self, tmp_path):
        """Create KnowledgeCache for add_query test."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = ["query1\nquery2"]
        mock_db = MagicMock()
        mock_db.execute.return_value = mock_result

        with patch("modules.knowledge.cache.storage.duckdb.connect", return_value=mock_db):
            with patch("modules.knowledge.cache.storage.KnowledgeCache._start_sync_daemon"):
                with patch("modules.knowledge.cache.storage.KnowledgeCache._shutdown"):
                    cache = KnowledgeCache(cache_path=str(tmp_path))
                    yield cache

    @pytest.mark.asyncio
    async def test_add_query(self, cache_add_query):
        """Test add_query adds query to history."""
        await cache_add_query.add_query("cluster1", "new_query")
        assert cache_add_query.db.execute.called


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
