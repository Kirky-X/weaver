# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for KnowledgeCache."""

from __future__ import annotations

import pytest

from core.protocols.knowledge_cache import KnowledgeCluster


@pytest.fixture
def knowledge_cache():
    """Create a KnowledgeCache instance for testing."""
    from modules.knowledge.cache import KnowledgeCache

    cache = KnowledgeCache(
        cache_path="/tmp/test_knowledge_cache",
        embedding_service=None,  # Will test without embedding
        sync_interval=3600,  # Long interval for tests
    )
    yield cache
    # Cleanup
    cache.db.close()


@pytest.fixture
def sample_cluster():
    """Create a sample KnowledgeCluster for testing."""
    from datetime import datetime, timezone

    return KnowledgeCluster(
        id="test_cluster_001",
        name="Test Cluster",
        description="A test knowledge cluster",
        content="This is the content of the test cluster.",
        query="test query",
        hotness=0.5,
        create_time=datetime.now(timezone.utc),
    )


class TestKnowledgeCacheCRUD:
    """Tests for CRUD operations."""

    @pytest.mark.asyncio
    async def test_store_and_get_cluster(self, knowledge_cache, sample_cluster) -> None:
        """Test storing and retrieving a cluster."""
        # Store
        cluster_id = await knowledge_cache.store_cluster(sample_cluster)
        assert cluster_id == sample_cluster.id

        # Get
        retrieved = await knowledge_cache.get(cluster_id)
        assert retrieved is not None
        assert retrieved.id == sample_cluster.id
        assert retrieved.name == sample_cluster.name
        assert retrieved.content == sample_cluster.content

    @pytest.mark.asyncio
    async def test_get_nonexistent_cluster(self, knowledge_cache) -> None:
        """Test getting a cluster that doesn't exist."""
        result = await knowledge_cache.get("nonexistent_id")
        assert result is None

    @pytest.mark.asyncio
    async def test_remove_cluster(self, knowledge_cache, sample_cluster) -> None:
        """Test removing a cluster."""
        # Store first
        await knowledge_cache.store_cluster(sample_cluster)

        # Remove
        removed = await knowledge_cache.remove(sample_cluster.id)
        assert removed is True

        # Verify removed
        result = await knowledge_cache.get(sample_cluster.id)
        assert result is None

    @pytest.mark.asyncio
    async def test_remove_nonexistent_cluster(self, knowledge_cache) -> None:
        """Test removing a cluster that doesn't exist."""
        removed = await knowledge_cache.remove("nonexistent_id")
        assert removed is False

    @pytest.mark.asyncio
    async def test_update_cluster(self, knowledge_cache, sample_cluster) -> None:
        """Test updating an existing cluster."""
        # Store first
        await knowledge_cache.store_cluster(sample_cluster)

        # Update
        sample_cluster.name = "Updated Name"
        sample_cluster.content = "Updated content"
        await knowledge_cache.store_cluster(sample_cluster)

        # Verify update
        retrieved = await knowledge_cache.get(sample_cluster.id)
        assert retrieved is not None
        assert retrieved.name == "Updated Name"
        assert retrieved.content == "Updated content"
        assert retrieved.version == 1  # Version incremented


class TestKnowledgeCacheHotness:
    """Tests for hotness management."""

    @pytest.mark.asyncio
    async def test_update_hotness(self, knowledge_cache, sample_cluster) -> None:
        """Test updating cluster hotness."""
        await knowledge_cache.store_cluster(sample_cluster)
        initial_hotness = sample_cluster.hotness

        await knowledge_cache.update_hotness(sample_cluster.id, delta=0.2)

        retrieved = await knowledge_cache.get(sample_cluster.id)
        assert retrieved is not None
        # Use approximate comparison for float
        assert abs(retrieved.hotness - (initial_hotness + 0.2)) < 0.001

    @pytest.mark.asyncio
    async def test_hotness_cap_at_1(self, knowledge_cache, sample_cluster) -> None:
        """Test hotness is capped at 1.0."""
        sample_cluster.hotness = 0.95
        await knowledge_cache.store_cluster(sample_cluster)

        await knowledge_cache.update_hotness(sample_cluster.id, delta=0.2)

        retrieved = await knowledge_cache.get(sample_cluster.id)
        assert retrieved is not None
        assert retrieved.hotness == 1.0  # Capped at 1.0


class TestKnowledgeCacheCleanup:
    """Tests for cleanup operations."""

    @pytest.mark.asyncio
    async def test_cleanup_stale_clusters(self, knowledge_cache) -> None:
        """Test cleaning up stale clusters."""
        from datetime import datetime, timezone

        # Create clusters with different hotness
        hot_cluster = KnowledgeCluster(
            id="hot_cluster",
            name="Hot Cluster",
            description="High hotness",
            content="content",
            hotness=0.8,
            create_time=datetime.now(timezone.utc),
        )
        cold_cluster = KnowledgeCluster(
            id="cold_cluster",
            name="Cold Cluster",
            description="Low hotness",
            content="content",
            hotness=0.2,
            create_time=datetime.now(timezone.utc),
        )

        await knowledge_cache.store_cluster(hot_cluster)
        await knowledge_cache.store_cluster(cold_cluster)

        # Cleanup with threshold 0.3
        removed = await knowledge_cache.cleanup_stale(hotness_threshold=0.3)

        assert removed == 1  # One cluster removed (cold_cluster)

        # Verify hot cluster still exists
        hot_result = await knowledge_cache.get("hot_cluster")
        assert hot_result is not None

        # Verify cold cluster removed
        cold_result = await knowledge_cache.get("cold_cluster")
        assert cold_result is None


class TestKnowledgeCacheStats:
    """Tests for statistics."""

    @pytest.mark.asyncio
    async def test_get_stats_empty(self, knowledge_cache) -> None:
        """Test stats when cache is empty."""
        stats = knowledge_cache.get_stats()
        assert stats["count"] == 0
        assert stats["avg_hotness"] == 0.0

    @pytest.mark.asyncio
    async def test_get_stats_with_clusters(self, knowledge_cache, sample_cluster) -> None:
        """Test stats with clusters."""
        await knowledge_cache.store_cluster(sample_cluster)

        stats = knowledge_cache.get_stats()
        assert stats["count"] == 1
        assert stats["avg_hotness"] == sample_cluster.hotness


class TestKnowledgeCacheFindSimilar:
    """Tests for similarity search."""

    @pytest.mark.asyncio
    async def test_find_similar_without_embedding_service(self, knowledge_cache, sample_cluster) -> None:
        """Test find_similar_cluster returns None without embedding service."""
        await knowledge_cache.store_cluster(sample_cluster)

        # Without embedding service, should return None
        result = await knowledge_cache.find_similar_cluster("test query")
        assert result is None
