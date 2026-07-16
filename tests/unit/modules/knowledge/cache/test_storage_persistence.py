# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for modules.knowledge.cache.storage persistence functionality."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _cleanup_duckdb_connections():
    """Ensure all DuckDB connections and KnowledgeCache instances are closed."""
    from modules.knowledge.cache.storage import KnowledgeCache

    # Track created caches and connections for cleanup
    _caches: list = []
    _connections: list = []
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

    # Cleanup any tracked connections
    for conn in _connections:
        try:
            conn.close()
        except Exception:
            pass
    _connections.clear()


class TestKnowledgeCachePersistence:
    """Test KnowledgeCache persistence operations."""

    def test_create_table_schema(self, tmp_path):
        """Test _create_table creates correct schema."""
        import duckdb

        with patch("modules.knowledge.cache.storage.KnowledgeCache._load_from_parquet"):
            with patch("modules.knowledge.cache.storage.KnowledgeCache._start_sync_daemon"):
                with patch("modules.knowledge.cache.storage.KnowledgeCache._shutdown"):
                    from modules.knowledge.cache.storage import KnowledgeCache

                    cache = KnowledgeCache(cache_path=str(tmp_path))

                    # Verify table exists
                    result = cache.db.execute(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'knowledge_clusters'"
                    ).fetchall()

                    column_names = [r[0] for r in result]
                    assert "id" in column_names
                    assert "name" in column_names
                    assert "embedding" in column_names
                    assert "hotness" in column_names

    def test_sync_to_parquet(self, tmp_path):
        """Test _sync_to_parquet creates parquet file."""
        with patch("modules.knowledge.cache.storage.KnowledgeCache._load_from_parquet"):
            with patch("modules.knowledge.cache.storage.KnowledgeCache._start_sync_daemon"):
                with patch("modules.knowledge.cache.storage.KnowledgeCache._shutdown"):
                    from modules.knowledge.cache.storage import KnowledgeCache

                    cache = KnowledgeCache(cache_path=str(tmp_path))

                    # Insert test data
                    cache.db.execute("""
                        INSERT INTO knowledge_clusters
                        (id, name, description, content, hotness, create_time, last_modified, version)
                        VALUES ('test1', 'Test', 'Desc', 'Content', 0.5, NULL, NULL, 0)
                    """)

                    # Sync to parquet
                    cache._sync_to_parquet()

                    # Verify file exists
                    parquet_path = Path(cache.parquet_file)
                    assert parquet_path.exists()

    def test_load_from_parquet(self, tmp_path):
        """Test _load_from_parquet loads existing data."""
        import duckdb

        # Create parquet file with test data
        parquet_file = tmp_path / "knowledge_clusters.parquet"
        db = duckdb.connect(":memory:")
        try:
            db.execute("""
                CREATE TABLE knowledge_clusters (
                    id VARCHAR, name VARCHAR, description VARCHAR, content VARCHAR,
                    embedding FLOAT[384], query VARCHAR, hotness FLOAT,
                    create_time TIMESTAMP, last_modified TIMESTAMP, version INTEGER
                )
            """)
            db.execute("""
                INSERT INTO knowledge_clusters
                (id, name, description, content, hotness, version)
                VALUES ('existing1', 'Existing Cluster', 'Desc', 'Content', 0.7, 1)
            """)
            db.execute(f"COPY knowledge_clusters TO '{parquet_file}' (FORMAT PARQUET)")
        finally:
            db.close()

        with patch("modules.knowledge.cache.storage.KnowledgeCache._start_sync_daemon"):
            with patch("modules.knowledge.cache.storage.KnowledgeCache._shutdown"):
                from modules.knowledge.cache.storage import KnowledgeCache

                cache = KnowledgeCache(cache_path=str(tmp_path))

                # Verify data was loaded
                result = cache.db.execute("SELECT id, name FROM knowledge_clusters").fetchall()

                assert len(result) == 1
                assert result[0][0] == "existing1"

    def test_dirty_count_tracking(self, tmp_path):
        """Test dirty count is tracked correctly."""
        with patch("modules.knowledge.cache.storage.KnowledgeCache._load_from_parquet"):
            with patch("modules.knowledge.cache.storage.KnowledgeCache._start_sync_daemon"):
                with patch("modules.knowledge.cache.storage.KnowledgeCache._shutdown"):
                    from modules.knowledge.cache.storage import KnowledgeCache

                    cache = KnowledgeCache(cache_path=str(tmp_path))

                    # Initial dirty count should be 0
                    assert cache._dirty_count == 0

                    # Mark dirty increments count
                    cache._mark_dirty()
                    assert cache._dirty_count == 1

                    cache._mark_dirty()
                    assert cache._dirty_count == 2

    def test_sync_threshold_triggers_immediate_sync(self, tmp_path):
        """Test sync threshold triggers immediate sync."""
        with patch("modules.knowledge.cache.storage.KnowledgeCache._load_from_parquet"):
            with patch("modules.knowledge.cache.storage.KnowledgeCache._start_sync_daemon"):
                with patch("modules.knowledge.cache.storage.KnowledgeCache._shutdown"):
                    from modules.knowledge.cache.storage import KnowledgeCache

                    cache = KnowledgeCache(
                        cache_path=str(tmp_path),
                        sync_threshold=2,
                    )

                    # Insert test data
                    cache.db.execute("""
                        INSERT INTO knowledge_clusters
                        (id, name, description, content, hotness, create_time, last_modified, version)
                        VALUES ('test1', 'Test', 'Desc', 'Content', 0.5, NULL, NULL, 0)
                    """)

                    # Mark dirty twice (reaches threshold)
                    cache._mark_dirty()
                    assert cache._dirty_count == 1

                    cache._mark_dirty()  # Should trigger sync
                    assert cache._dirty_count == 0  # Reset after sync


class TestKnowledgeCacheStats:
    """Test KnowledgeCache statistics."""

    def test_get_stats_with_data(self, tmp_path):
        """Test get_stats with data in cache."""
        with patch("modules.knowledge.cache.storage.KnowledgeCache._load_from_parquet"):
            with patch("modules.knowledge.cache.storage.KnowledgeCache._start_sync_daemon"):
                with patch("modules.knowledge.cache.storage.KnowledgeCache._shutdown"):
                    from modules.knowledge.cache.storage import KnowledgeCache

                    cache = KnowledgeCache(cache_path=str(tmp_path))

                    # Insert test data
                    cache.db.execute("""
                        INSERT INTO knowledge_clusters
                        (id, name, description, content, hotness, version)
                        VALUES
                            ('test1', 'Test1', 'Desc', 'Content', 0.8, 1),
                            ('test2', 'Test2', 'Desc', 'Content', 0.6, 1)
                    """)

                    stats = cache.get_stats()

                    assert stats["count"] == 2
                    assert 0.0 <= stats["avg_hotness"] <= 1.0

    def test_get_stats_empty_cache(self, tmp_path):
        """Test get_stats with empty cache."""
        with patch("modules.knowledge.cache.storage.KnowledgeCache._load_from_parquet"):
            with patch("modules.knowledge.cache.storage.KnowledgeCache._start_sync_daemon"):
                with patch("modules.knowledge.cache.storage.KnowledgeCache._shutdown"):
                    from modules.knowledge.cache.storage import KnowledgeCache

                    cache = KnowledgeCache(cache_path=str(tmp_path))

                    stats = cache.get_stats()

                    assert stats["count"] == 0
                    assert stats["avg_hotness"] == 0.0
                    assert stats["with_embedding"] == 0


class TestKnowledgeCacheSyncDaemon:
    """Test sync daemon functionality."""

    def test_shutdown_stops_daemon(self, tmp_path):
        """Test _shutdown stops the sync daemon."""
        with patch("modules.knowledge.cache.storage.KnowledgeCache._load_from_parquet"):
            with patch("modules.knowledge.cache.storage.KnowledgeCache._start_sync_daemon"):
                from modules.knowledge.cache.storage import KnowledgeCache

                cache = KnowledgeCache(cache_path=str(tmp_path))

                # Call shutdown
                cache._shutdown()

                # Stop event should be set
                assert cache._stop_event.is_set()

    def test_sync_thread_created(self, tmp_path):
        """Test sync thread is created."""
        with patch("modules.knowledge.cache.storage.KnowledgeCache._create_table"):
            with patch("modules.knowledge.cache.storage.KnowledgeCache._load_from_parquet"):
                from modules.knowledge.cache.storage import KnowledgeCache

                cache = KnowledgeCache(
                    cache_path=str(tmp_path),
                    sync_interval=60,
                )

                # Sync thread should exist
                assert hasattr(cache, "_sync_thread")
                assert cache._sync_thread.is_alive()

                # Cleanup
                cache._stop_event.set()


class TestKnowledgeCacheParquetFormat:
    """Test parquet file format compatibility."""

    def test_parquet_roundtrip(self, tmp_path):
        """Test data survives parquet roundtrip."""
        import duckdb

        with patch("modules.knowledge.cache.storage.KnowledgeCache._load_from_parquet"):
            with patch("modules.knowledge.cache.storage.KnowledgeCache._start_sync_daemon"):
                with patch("modules.knowledge.cache.storage.KnowledgeCache._shutdown"):
                    from modules.knowledge.cache.storage import KnowledgeCache

                    cache = KnowledgeCache(cache_path=str(tmp_path))

                    # Insert data with all fields
                    now = datetime.now(UTC)
                    cache.db.execute(
                        """
                        INSERT INTO knowledge_clusters
                        (id, name, description, content, hotness,
                         create_time, last_modified, version)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                        ["test1", "Test Cluster", "Description", "Content", 0.75, now, now, 2],
                    )

                    # Sync to parquet
                    cache._sync_to_parquet()

                    # Load into a new database
                    new_db = duckdb.connect(":memory:")
                    try:
                        parquet_path = cache.parquet_file
                        new_db.execute(
                            "CREATE TABLE test AS SELECT * FROM read_parquet(?)",
                            [parquet_path],
                        )

                        result = new_db.execute("SELECT * FROM test").fetchone()

                        assert result is not None
                        assert result[0] == "test1"
                        assert result[1] == "Test Cluster"
                        assert result[6] == 0.75  # hotness
                    finally:
                        new_db.close()
