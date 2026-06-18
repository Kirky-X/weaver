# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for modules.knowledge.cache.storage module."""

import contextlib
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


class TestKnowledgeCacheFindSimilarCluster:
    """Test find_similar_cluster method (Task 6: threshold 0.85→0.75 + confidence)."""

    @contextlib.contextmanager
    def _make_cache_with_result(self, tmp_path, similarity: float | None):
        """Create KnowledgeCache with mocked db returning given similarity.

        Args:
            similarity: Similarity value at index 10, or None for no result.
        """
        if similarity is None:
            fetchone_result = None
        else:
            fetchone_result = [
                "cluster1",
                "Test Cluster",
                "Description",
                "Content",
                [0.1] * 384,  # embedding
                "query",
                0.5,  # hotness
                None,  # create_time
                None,  # last_modified
                0,  # version
                similarity,  # index 10
            ]

        mock_result = MagicMock()
        mock_result.fetchone.return_value = fetchone_result
        mock_db = MagicMock()
        mock_db.execute.return_value = mock_result

        mock_llm = MagicMock()
        mock_llm.embed_default = AsyncMock(return_value=[[0.1] * 384])

        with patch("modules.knowledge.cache.storage.duckdb.connect", return_value=mock_db):
            with patch("modules.knowledge.cache.storage.KnowledgeCache._start_sync_daemon"):
                with patch("modules.knowledge.cache.storage.KnowledgeCache._shutdown"):
                    cache = KnowledgeCache(cache_path=str(tmp_path), llm_client=mock_llm)
                    yield cache

    @pytest.mark.asyncio
    async def test_default_threshold_hit_medium_confidence(self, tmp_path):
        """相似度 0.78 在新默认阈值 0.75 下命中，confidence=medium."""
        with patch("modules.knowledge.cache.storage.log") as mock_log:
            with self._make_cache_with_result(tmp_path, 0.78) as cache:
                cluster = await cache.find_similar_cluster("test query")

        assert cluster is not None
        assert cluster.id == "cluster1"
        # 验证 cache_hit 日志包含 confidence=medium
        cache_hit_calls = [c for c in mock_log.info.call_args_list if c.args[0] == "cache_hit"]
        assert len(cache_hit_calls) == 1
        assert cache_hit_calls[0].kwargs.get("confidence") == "medium"

    @pytest.mark.asyncio
    async def test_default_threshold_miss_below_075(self, tmp_path):
        """相似度 0.72 低于新默认阈值 0.75，不命中."""
        with patch("modules.knowledge.cache.storage.log") as mock_log:
            with self._make_cache_with_result(tmp_path, 0.72) as cache:
                cluster = await cache.find_similar_cluster("test query")

        assert cluster is None
        # cache_hit 不应被调用
        cache_hit_calls = [c for c in mock_log.info.call_args_list if c.args[0] == "cache_hit"]
        assert len(cache_hit_calls) == 0
        # cache_miss 应被调用
        cache_miss_calls = [c for c in mock_log.debug.call_args_list if c.args[0] == "cache_miss"]
        assert len(cache_miss_calls) == 1

    @pytest.mark.asyncio
    async def test_explicit_threshold_not_affected(self, tmp_path):
        """显式传入 threshold=0.9 时，相似度 0.78 不命中."""
        with self._make_cache_with_result(tmp_path, 0.78) as cache:
            cluster = await cache.find_similar_cluster("test query", threshold=0.9)

        assert cluster is None

    @pytest.mark.asyncio
    async def test_high_confidence_hit(self, tmp_path):
        """相似度 0.90 命中，confidence=high."""
        with patch("modules.knowledge.cache.storage.log") as mock_log:
            with self._make_cache_with_result(tmp_path, 0.90) as cache:
                cluster = await cache.find_similar_cluster("test query")

        assert cluster is not None
        cache_hit_calls = [c for c in mock_log.info.call_args_list if c.args[0] == "cache_hit"]
        assert len(cache_hit_calls) == 1
        assert cache_hit_calls[0].kwargs.get("confidence") == "high"

    @pytest.mark.asyncio
    async def test_medium_confidence_boundary_080(self, tmp_path):
        """相似度 0.80 命中，confidence=medium."""
        with patch("modules.knowledge.cache.storage.log") as mock_log:
            with self._make_cache_with_result(tmp_path, 0.80) as cache:
                cluster = await cache.find_similar_cluster("test query")

        assert cluster is not None
        cache_hit_calls = [c for c in mock_log.info.call_args_list if c.args[0] == "cache_hit"]
        assert len(cache_hit_calls) == 1
        assert cache_hit_calls[0].kwargs.get("confidence") == "medium"

    @pytest.mark.asyncio
    async def test_high_confidence_boundary_085(self, tmp_path):
        """相似度 0.85 命中，confidence=high（边界值）."""
        with patch("modules.knowledge.cache.storage.log") as mock_log:
            with self._make_cache_with_result(tmp_path, 0.85) as cache:
                cluster = await cache.find_similar_cluster("test query")

        assert cluster is not None
        cache_hit_calls = [c for c in mock_log.info.call_args_list if c.args[0] == "cache_hit"]
        assert len(cache_hit_calls) == 1
        assert cache_hit_calls[0].kwargs.get("confidence") == "high"


class TestKnowledgeCacheDecayHotness:
    """Test decay_hotness method (Task 7: hotness decay)."""

    @contextlib.contextmanager
    def _make_cache(self, tmp_path, count_result: int, execute_raises: bool = False):
        """Create KnowledgeCache with mocked db.

        Args:
            count_result: Value returned by COUNT(*) query.
            execute_raises: If True, db.execute raises an exception.
        """
        mock_db = MagicMock()
        if execute_raises:
            mock_db.execute.side_effect = Exception("db error")
        else:
            # COUNT(*) returns [count]; UPDATE returns a mock result
            count_mock = MagicMock()
            count_mock.fetchone.return_value = [count_result]
            update_mock = MagicMock()
            mock_db.execute.side_effect = [count_mock, update_mock]

        with patch("modules.knowledge.cache.storage.duckdb.connect", return_value=mock_db):
            with patch("modules.knowledge.cache.storage.KnowledgeCache._create_table"):
                with patch("modules.knowledge.cache.storage.KnowledgeCache._load_from_parquet"):
                    with patch("modules.knowledge.cache.storage.KnowledgeCache._start_sync_daemon"):
                        with patch("modules.knowledge.cache.storage.KnowledgeCache._shutdown"):
                            cache = KnowledgeCache(cache_path=str(tmp_path))
                            yield cache

    @pytest.mark.asyncio
    async def test_decay_returns_affected_count(self, tmp_path):
        """衰减 3 条 hotness>0 的记录，返回 3."""
        with self._make_cache(tmp_path, count_result=3) as cache:
            with patch.object(cache, "_mark_dirty") as mock_mark_dirty:
                result = await cache.decay_hotness(decay_factor=0.95)

            assert result == 3
            mock_mark_dirty.assert_called_once()

    @pytest.mark.asyncio
    async def test_decay_no_records_returns_zero(self, tmp_path):
        """无 hotness>0 的记录时返回 0，不调用 _mark_dirty."""
        with self._make_cache(tmp_path, count_result=0) as cache:
            with patch.object(cache, "_mark_dirty") as mock_mark_dirty:
                result = await cache.decay_hotness(decay_factor=0.95)

            assert result == 0
            mock_mark_dirty.assert_not_called()

    @pytest.mark.asyncio
    async def test_decay_exception_returns_zero_and_logs(self, tmp_path):
        """异常时返回 0 并记录 decay_hotness_failed 日志."""
        with self._make_cache(tmp_path, count_result=3, execute_raises=True) as cache:
            with patch("modules.knowledge.cache.storage.log") as mock_log:
                with patch.object(cache, "_mark_dirty") as mock_mark_dirty:
                    result = await cache.decay_hotness(decay_factor=0.95)

            assert result == 0
            mock_mark_dirty.assert_not_called()
            # 验证 decay_hotness_failed 错误日志被记录
            error_calls = [
                c for c in mock_log.error.call_args_list if c.args[0] == "decay_hotness_failed"
            ]
            assert len(error_calls) == 1

    @pytest.mark.asyncio
    async def test_decay_default_factor(self, tmp_path):
        """默认 decay_factor=0.95."""
        with self._make_cache(tmp_path, count_result=2) as cache:
            result = await cache.decay_hotness()

        assert result == 2
