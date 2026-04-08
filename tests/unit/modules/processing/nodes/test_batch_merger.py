# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for processing BatchMergerNode and UnionFind."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.llm.output_validator import MergerOutput
from modules.ingestion.domain.models import ArticleRaw
from modules.processing.nodes.batch_merger import BatchMergerNode, UnionFind
from modules.processing.pipeline.state import PipelineState


class TestUnionFind:
    """Tests for Union-Find data structure."""

    def test_union_find_initialization(self):
        """Test UnionFind initializes with all elements as separate sets."""
        elements = ["a", "b", "c"]
        uf = UnionFind(elements)

        # Each element should be its own parent
        for elem in elements:
            assert uf.find(elem) == elem

    def test_find_with_path_compression(self):
        """Test find compresses path."""
        elements = ["a", "b", "c"]
        uf = UnionFind(elements)

        # Union a and b
        uf.union("a", "b")

        # Find should return root
        assert uf.find("a") == uf.find("b")
        assert uf.find("a") != uf.find("c")

    def test_union_same_element(self):
        """Test unioning same element is no-op."""
        elements = ["a", "b"]
        uf = UnionFind(elements)

        uf.union("a", "a")

        # Should still be separate
        assert uf.find("a") == "a"

    def test_union_different_elements(self):
        """Test unioning different elements merges sets."""
        elements = ["a", "b", "c"]
        uf = UnionFind(elements)

        uf.union("a", "b")

        assert uf.find("a") == uf.find("b")
        assert uf.find("a") != uf.find("c")

    def test_union_transitive(self):
        """Test union is transitive."""
        elements = ["a", "b", "c"]
        uf = UnionFind(elements)

        uf.union("a", "b")
        uf.union("b", "c")

        # All should now be in same set
        assert uf.find("a") == uf.find("b") == uf.find("c")

    def test_get_groups(self):
        """Test get_groups returns correct groups."""
        elements = ["a", "b", "c", "d"]
        uf = UnionFind(elements)

        uf.union("a", "b")
        uf.union("c", "d")

        groups = uf.get_groups()

        # Should have 2 groups
        assert len(groups) == 2

        # Each group should have correct members
        group_values = [set(v) for v in groups.values()]
        assert {"a", "b"} in group_values
        assert {"c", "d"} in group_values

    def test_get_groups_all_separate(self):
        """Test get_groups when no unions performed."""
        elements = ["a", "b", "c"]
        uf = UnionFind(elements)

        groups = uf.get_groups()

        # Each element is its own group
        assert len(groups) == 3
        for elem in elements:
            assert elem in groups[elem]

    def test_rank_based_union(self):
        """Test union uses rank for optimization."""
        # Create UnionFind with ranks
        uf = UnionFind(["a", "b", "c"])

        # Initially all ranks are 0
        assert uf._rank["a"] == 0

        # Union a and b
        uf.union("a", "b")

        # One should have rank 1
        root = uf.find("a")
        assert uf._rank[root] == 1

    def test_find_nonexistent(self):
        """Test find raises error for nonexistent element."""
        uf = UnionFind(["a", "b"])

        with pytest.raises(KeyError):
            uf.find("nonexistent")


class TestUnionFindEdgeCases:
    """Edge case tests for UnionFind."""

    def test_single_element(self):
        """Test with single element."""
        uf = UnionFind(["a"])

        assert uf.find("a") == "a"
        groups = uf.get_groups()
        assert len(groups) == 1
        assert groups["a"] == ["a"]

    def test_empty_set(self):
        """Test with empty set."""
        uf = UnionFind([])

        groups = uf.get_groups()
        assert len(groups) == 0

    def test_duplicate_union_calls(self):
        """Test multiple union calls between same elements."""
        uf = UnionFind(["a", "b", "c"])

        uf.union("a", "b")
        uf.union("a", "b")  # Duplicate
        uf.union("a", "b")  # Another duplicate

        # Should still be in same group
        assert uf.find("a") == uf.find("b")

    def test_large_set(self):
        """Test with larger set of elements."""
        elements = [f"elem_{i}" for i in range(100)]
        uf = UnionFind(elements)

        # Connect every other element
        for i in range(0, 99, 2):
            uf.union(elements[i], elements[i + 1])

        groups = uf.get_groups()

        # Should have 50 groups
        assert len(groups) == 50


class TestUnionFindAdd:
    """Tests for UnionFind add method."""

    def test_add_new_element(self):
        """Test adding new element dynamically."""
        uf = UnionFind(["a", "b"])
        uf.add("c")
        assert "c" in uf._parent
        assert uf._parent["c"] == "c"
        assert uf._rank["c"] == 0

    def test_add_existing_element_no_change(self):
        """Test adding existing element doesn't change state."""
        uf = UnionFind(["a", "b"])
        original_parent = uf._parent["a"]
        uf.add("a")
        assert uf._parent["a"] == original_parent

    def test_add_and_union(self):
        """Test adding element and then union."""
        uf = UnionFind(["a"])
        uf.add("b")
        uf.union("a", "b")
        assert uf.find("a") == uf.find("b")

    def test_add_multiple_elements(self):
        """Test adding multiple elements."""
        uf = UnionFind(["a"])
        for i in range(10):
            uf.add(f"new_{i}")
        assert len(uf._parent) == 11

    def test_add_after_get_groups(self):
        """Test adding element after get_groups."""
        uf = UnionFind(["a", "b"])
        uf.union("a", "b")
        groups1 = uf.get_groups()
        uf.add("c")
        groups2 = uf.get_groups()
        assert len(groups2) == 2


class TestBatchMergerNodeInit:
    """Tests for BatchMergerNode initialization."""

    @pytest.fixture
    def mock_llm(self):
        return AsyncMock()

    @pytest.fixture
    def mock_prompt_loader(self):
        loader = MagicMock()
        loader.get_version = MagicMock(return_value="1.0.0")
        return loader

    def test_init_basic(self, mock_llm, mock_prompt_loader):
        """Test basic initialization."""
        node = BatchMergerNode(mock_llm, mock_prompt_loader)

        assert node._llm == mock_llm
        assert node._prompt_loader == mock_prompt_loader
        assert node._vector_repo is None
        assert node._article_repo is None
        assert node._graph_writer is None

    def test_init_with_optional_deps(self, mock_llm, mock_prompt_loader):
        """Test initialization with optional dependencies."""
        mock_vector_repo = MagicMock()
        mock_article_repo = MagicMock()
        mock_graph_writer = MagicMock()

        node = BatchMergerNode(
            mock_llm,
            mock_prompt_loader,
            vector_repo=mock_vector_repo,
            article_repo=mock_article_repo,
            graph_writer=mock_graph_writer,
        )

        assert node._vector_repo == mock_vector_repo
        assert node._article_repo == mock_article_repo
        assert node._graph_writer == mock_graph_writer


class TestBatchMergerNodeExecuteBatch:
    """Tests for execute_batch method."""

    @pytest.fixture
    def mock_llm(self):
        return AsyncMock()

    @pytest.fixture
    def mock_prompt_loader(self):
        loader = MagicMock()
        loader.get_version = MagicMock(return_value="1.0.0")
        return loader

    @pytest.fixture
    def sample_states(self):
        """Create sample pipeline states."""
        states = []
        for i in range(3):
            raw = ArticleRaw(
                url=f"https://example.com/article-{i}",
                title=f"Article {i}",
                body=f"Body content {i}",
                source="test",
                source_host="example.com",
                publish_time=datetime.now(UTC),
            )
            state = PipelineState(raw=raw)
            state["cleaned"] = {"title": f"Article {i}", "body": f"Body content {i}"}
            state["vectors"] = {"content": [0.1] * 1024, "title": [0.2] * 1024}
            state["category"] = "科技"
            states.append(state)
        return states

    @pytest.mark.asyncio
    async def test_execute_batch_empty(self, mock_llm, mock_prompt_loader):
        """Test execute_batch with empty list."""
        node = BatchMergerNode(mock_llm, mock_prompt_loader)
        result = await node.execute_batch([])
        assert result == []

    @pytest.mark.asyncio
    async def test_execute_batch_all_terminal(self, mock_llm, mock_prompt_loader, sample_states):
        """Test execute_batch skips terminal states."""
        for state in sample_states:
            state["terminal"] = True

        node = BatchMergerNode(mock_llm, mock_prompt_loader)
        result = await node.execute_batch(sample_states)

        assert result == sample_states
        mock_llm.call_at.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_batch_no_similar_articles(self, mock_llm, mock_prompt_loader):
        """Test execute_batch with no similar articles."""
        # Create states with orthogonal vectors (dissimilar)
        states = []
        for i in range(3):
            raw = ArticleRaw(
                url=f"https://example.com/article-{i}",
                title=f"Article {i}",
                body=f"Body content {i}",
                source="test",
                source_host="example.com",
                publish_time=datetime.now(UTC),
            )
            state = PipelineState(raw=raw)
            state["cleaned"] = {"title": f"Article {i}", "body": f"Body content {i}"}
            # Use orthogonal vectors: each article has a unique basis vector
            vec = [0.0] * 1024
            vec[i * 100] = 1.0  # Unique dimension for each article
            state["vectors"] = {"content": vec, "title": vec}
            state["category"] = "科技"
            states.append(state)

        node = BatchMergerNode(mock_llm, mock_prompt_loader)
        result = await node.execute_batch(states)

        # Should return all states unchanged
        assert len(result) == 3
        # No merge should be called since all are dissimilar (orthogonal vectors)
        mock_llm.call_at.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_batch_with_similar_articles(self, mock_llm, mock_prompt_loader):
        """Test execute_batch with similar articles triggers merge."""
        # Create two very similar articles
        raw1 = ArticleRaw(
            url="https://example.com/article-1",
            title="AI Breakthrough",
            body="A major AI breakthrough was announced today.",
            source="test",
            source_host="example.com",
            publish_time=datetime.now(UTC),
        )
        state1 = PipelineState(raw=raw1)
        state1["cleaned"] = {
            "title": "AI Breakthrough",
            "body": "A major AI breakthrough was announced today.",
        }
        # Use identical vectors to simulate high similarity
        state1["vectors"] = {"content": [0.5] * 1024, "title": [0.5] * 1024}
        state1["category"] = "科技"

        raw2 = ArticleRaw(
            url="https://example.com/article-2",
            title="AI Major Discovery",
            body="Scientists announced a major AI discovery.",
            source="test",
            source_host="example.com",
            publish_time=datetime.now(UTC),
        )
        state2 = PipelineState(raw=raw2)
        state2["cleaned"] = {
            "title": "AI Major Discovery",
            "body": "Scientists announced a major AI discovery.",
        }
        # Use identical vectors to force similarity
        state2["vectors"] = {"content": [0.5] * 1024, "title": [0.5] * 1024}
        state2["category"] = "科技"

        mock_llm.call_at = AsyncMock(
            return_value=MergerOutput(merged_title="Merged Title", merged_body="Merged Body")
        )

        node = BatchMergerNode(mock_llm, mock_prompt_loader)
        result = await node.execute_batch([state1, state2])

        # Should trigger merge
        assert len(result) == 2
        # One should be marked as merged
        merged_count = sum(1 for s in result if s.get("is_merged"))
        assert merged_count == 1

    @pytest.mark.asyncio
    async def test_execute_batch_different_categories_not_merged(
        self, mock_llm, mock_prompt_loader
    ):
        """Test articles with different categories are not merged."""
        raw1 = ArticleRaw(
            url="https://example.com/article-1",
            title="Tech News",
            body="Tech content.",
            source="test",
            source_host="example.com",
            publish_time=datetime.now(UTC),
        )
        state1 = PipelineState(raw=raw1)
        state1["cleaned"] = {"title": "Tech News", "body": "Tech content."}
        state1["vectors"] = {"content": [0.5] * 1024, "title": [0.5] * 1024}
        state1["category"] = "科技"

        raw2 = ArticleRaw(
            url="https://example.com/article-2",
            title="Sports News",
            body="Sports content.",
            source="test",
            source_host="example.com",
            publish_time=datetime.now(UTC),
        )
        state2 = PipelineState(raw=raw2)
        state2["cleaned"] = {"title": "Sports News", "body": "Sports content."}
        state2["vectors"] = {"content": [0.5] * 1024, "title": [0.5] * 1024}
        state2["category"] = "体育"  # Different category

        node = BatchMergerNode(mock_llm, mock_prompt_loader)
        result = await node.execute_batch([state1, state2])

        # Should not merge due to different categories
        mock_llm.call_at.assert_not_called()


class TestBatchMergerNodePersistBatchSaga:
    """Tests for persist_batch_saga method."""

    @pytest.fixture
    def mock_llm(self):
        return AsyncMock()

    @pytest.fixture
    def mock_prompt_loader(self):
        loader = MagicMock()
        loader.get_version = MagicMock(return_value="1.0.0")
        return loader

    @pytest.fixture
    def sample_states(self):
        """Create sample pipeline states."""
        states = []
        for i in range(2):
            raw = ArticleRaw(
                url=f"https://example.com/article-{i}",
                title=f"Article {i}",
                body=f"Body content {i}",
                source="test",
                source_host="example.com",
                publish_time=datetime.now(UTC),
            )
            state = PipelineState(raw=raw)
            state["cleaned"] = {"title": f"Article {i}", "body": f"Body content {i}"}
            state["vectors"] = {"content": [0.1] * 1024, "title": [0.2] * 1024, "model_id": "test"}
            state["category"] = "科技"
            state["score"] = 0.8
            states.append(state)
        return states

    @pytest.mark.asyncio
    async def test_persist_batch_saga_no_repo(self, mock_llm, mock_prompt_loader):
        """Test persist_batch_saga raises error without article_repo on valid states."""
        states = []
        for i in range(2):
            raw = ArticleRaw(
                url=f"https://example.com/article-{i}",
                title=f"Article {i}",
                body=f"Body {i}",
                source="test",
                source_host="example.com",
            )
            state = PipelineState(raw=raw)
            state["cleaned"] = {"title": f"Article {i}", "body": f"Body {i}"}
            states.append(state)

        node = BatchMergerNode(mock_llm, mock_prompt_loader, article_repo=None)

        # Should raise AttributeError when trying to call get_existing_urls on None
        with pytest.raises(AttributeError):
            await node.persist_batch_saga(states)

    @pytest.mark.asyncio
    async def test_persist_batch_saga_empty_states(self, mock_llm, mock_prompt_loader):
        """Test persist_batch_saga with empty states."""
        node = BatchMergerNode(mock_llm, mock_prompt_loader)
        result = await node.persist_batch_saga([])

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_persist_batch_saga_all_terminal(self, mock_llm, mock_prompt_loader):
        """Test persist_batch_saga skips terminal states."""
        states = []
        for i in range(2):
            raw = ArticleRaw(
                url=f"https://example.com/article-{i}",
                title=f"Article {i}",
                body=f"Body {i}",
                source="test",
                source_host="example.com",
            )
            state = PipelineState(raw=raw)
            state["terminal"] = True
            states.append(state)

        mock_article_repo = MagicMock()
        mock_article_repo.get_existing_urls = AsyncMock(return_value=[])

        node = BatchMergerNode(mock_llm, mock_prompt_loader, article_repo=mock_article_repo)
        result = await node.persist_batch_saga(states)

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_persist_batch_saga_phase1_success(
        self, mock_llm, mock_prompt_loader, sample_states
    ):
        """Test persist_batch_saga Phase 1 (PostgreSQL) success."""
        import uuid

        mock_article_repo = MagicMock()
        mock_article_repo.get_existing_urls = AsyncMock(return_value=[])
        mock_article_repo.bulk_upsert = AsyncMock(
            return_value=[uuid.uuid4() for _ in sample_states]
        )
        mock_article_repo.update_persist_status = AsyncMock()

        node = BatchMergerNode(mock_llm, mock_prompt_loader, article_repo=mock_article_repo)
        result = await node.persist_batch_saga(sample_states)

        assert result["success"] is True
        assert len(result["pg_ids"]) == 2
        mock_article_repo.bulk_upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_persist_batch_saga_phase1_failure(
        self, mock_llm, mock_prompt_loader, sample_states
    ):
        """Test persist_batch_saga handles Phase 1 failure."""
        mock_article_repo = MagicMock()
        mock_article_repo.get_existing_urls = AsyncMock(return_value=[])
        mock_article_repo.bulk_upsert = AsyncMock(side_effect=Exception("PG connection failed"))

        node = BatchMergerNode(mock_llm, mock_prompt_loader, article_repo=mock_article_repo)
        result = await node.persist_batch_saga(sample_states)

        assert result["success"] is False
        assert "Phase 1" in result["error"]

    @pytest.mark.asyncio
    async def test_persist_batch_saga_skips_duplicates(
        self, mock_llm, mock_prompt_loader, sample_states
    ):
        """Test persist_batch_saga skips duplicate articles."""
        import uuid

        # Mark first URL as existing
        existing_urls = [sample_states[0]["raw"].url]

        mock_article_repo = MagicMock()
        mock_article_repo.get_existing_urls = AsyncMock(return_value=existing_urls)
        mock_article_repo.bulk_upsert = AsyncMock(return_value=[uuid.uuid4()])
        mock_article_repo.update_persist_status = AsyncMock()

        node = BatchMergerNode(mock_llm, mock_prompt_loader, article_repo=mock_article_repo)
        result = await node.persist_batch_saga(sample_states)

        # Should succeed - one duplicate skipped, one new article processed
        assert result["success"] is True
        # Only one new article should be persisted
        assert len(result["pg_ids"]) == 1


class TestBatchMergerNodeIntraBatchSimilarity:
    """Tests for _intra_batch_similarity method."""

    @pytest.fixture
    def mock_llm(self):
        return AsyncMock()

    @pytest.fixture
    def mock_prompt_loader(self):
        loader = MagicMock()
        loader.get_version = MagicMock(return_value="1.0.0")
        return loader

    @pytest.mark.asyncio
    async def test_intra_batch_similarity_groups_similar(self, mock_llm, mock_prompt_loader):
        """Test intra-batch similarity correctly groups similar articles."""
        import numpy as np

        # Create states with known similar vectors
        states = []
        base_vec = np.random.randn(1024).astype(np.float32)
        base_vec = base_vec / np.linalg.norm(base_vec)

        for i in range(3):
            raw = ArticleRaw(
                url=f"https://example.com/article-{i}",
                title=f"Article {i}",
                body=f"Body {i}",
                source="test",
                source_host="example.com",
                publish_time=datetime.now(UTC),
            )
            state = PipelineState(raw=raw)
            state["cleaned"] = {"title": f"Article {i}", "body": f"Body {i}"}
            # Add small noise to create similar but not identical vectors
            noise = np.random.randn(1024).astype(np.float32) * 0.01
            similar_vec = base_vec + noise
            similar_vec = similar_vec / np.linalg.norm(similar_vec)
            state["vectors"] = {"content": similar_vec.tolist(), "title": similar_vec.tolist()}
            state["category"] = "科技"
            states.append(state)

        node = BatchMergerNode(mock_llm, mock_prompt_loader)
        uf = UnionFind([s["raw"].url for s in states])

        vectors = [s["vectors"]["content"] for s in states]
        await node._intra_batch_similarity(states, vectors, uf)

        # All three should be grouped together due to high similarity
        groups = uf.get_groups()
        assert len(groups) == 1  # All in one group

    @pytest.mark.asyncio
    async def test_intra_batch_similarity_different_categories(self, mock_llm, mock_prompt_loader):
        """Test articles with different categories are not grouped."""
        import numpy as np

        # Create states with identical vectors but different categories
        base_vec = np.random.randn(1024).astype(np.float32)
        base_vec = base_vec / np.linalg.norm(base_vec)
        vec_list = base_vec.tolist()

        raw1 = ArticleRaw(
            url="https://example.com/article-1",
            title="Tech Article",
            body="Tech content",
            source="test",
            source_host="example.com",
            publish_time=datetime.now(UTC),
        )
        state1 = PipelineState(raw=raw1)
        state1["cleaned"] = {"title": "Tech Article", "body": "Tech content"}
        state1["vectors"] = {"content": vec_list, "title": vec_list}
        state1["category"] = "科技"

        raw2 = ArticleRaw(
            url="https://example.com/article-2",
            title="Sports Article",
            body="Sports content",
            source="test",
            source_host="example.com",
            publish_time=datetime.now(UTC),
        )
        state2 = PipelineState(raw=raw2)
        state2["cleaned"] = {"title": "Sports Article", "body": "Sports content"}
        state2["vectors"] = {"content": vec_list, "title": vec_list}
        state2["category"] = "体育"  # Different category

        states = [state1, state2]

        node = BatchMergerNode(mock_llm, mock_prompt_loader)
        uf = UnionFind([s["raw"].url for s in states])

        vectors = [s["vectors"]["content"] for s in states]
        await node._intra_batch_similarity(states, vectors, uf)

        # Should not be grouped due to different categories
        groups = uf.get_groups()
        assert len(groups) == 2  # Each in separate group


class TestBatchMergerConflictResolution:
    """Tests for conflict resolution during merge."""

    @pytest.fixture
    def mock_llm(self):
        return AsyncMock()

    @pytest.fixture
    def mock_prompt_loader(self):
        loader = MagicMock()
        loader.get_version = MagicMock(return_value="1.0.0")
        return loader

    @pytest.mark.asyncio
    async def test_merge_resolves_conflicting_titles(self, mock_llm, mock_prompt_loader):
        """Test that LLM merge resolves conflicting titles."""
        from datetime import timedelta

        now = datetime.now(UTC)

        # Create two articles with different titles
        raw1 = ArticleRaw(
            url="https://example.com/article-1",
            title="Breaking: Major AI Breakthrough",
            body="Content 1",
            source="source1",
            source_host="example.com",
            publish_time=now,
        )
        state1 = PipelineState(raw=raw1)
        state1["cleaned"] = {"title": "Breaking: Major AI Breakthrough", "body": "Content 1"}
        state1["vectors"] = {"content": [0.5] * 1024, "title": [0.5] * 1024}
        state1["category"] = "科技"

        raw2 = ArticleRaw(
            url="https://example.com/article-2",
            title="AI Discovery Announced",
            body="Content 2",
            source="source2",
            source_host="example.com",
            publish_time=now + timedelta(hours=1),  # Newer
        )
        state2 = PipelineState(raw=raw2)
        state2["cleaned"] = {"title": "AI Discovery Announced", "body": "Content 2"}
        state2["vectors"] = {"content": [0.5] * 1024, "title": [0.5] * 1024}
        state2["category"] = "科技"

        mock_llm.call_at = AsyncMock(
            return_value=MergerOutput(
                merged_title="Major AI Breakthrough Announced",
                merged_body="Merged content from multiple sources",
            )
        )

        node = BatchMergerNode(mock_llm, mock_prompt_loader)
        result = await node.execute_batch([state1, state2])

        # Should have called LLM merge
        mock_llm.call_at.assert_called_once()

        # Check merge result applied
        primary = next(s for s in result if not s.get("is_merged"))
        assert "merged_source_ids" in primary

    @pytest.mark.asyncio
    async def test_merge_selects_primary_by_publish_time(self, mock_llm, mock_prompt_loader):
        """Test that newer article is selected as primary during merge."""
        from datetime import timedelta

        now = datetime.now(UTC)

        # Older article
        raw1 = ArticleRaw(
            url="https://example.com/old",
            title="Old Article",
            body="Old content",
            source="source1",
            source_host="example.com",
            publish_time=now - timedelta(hours=2),
        )
        state1 = PipelineState(raw=raw1)
        state1["cleaned"] = {"title": "Old Article", "body": "Old content"}
        state1["vectors"] = {"content": [0.5] * 1024, "title": [0.5] * 1024}
        state1["category"] = "科技"

        # Newer article
        raw2 = ArticleRaw(
            url="https://example.com/new",
            title="New Article",
            body="New content",
            source="source2",
            source_host="example.com",
            publish_time=now,
        )
        state2 = PipelineState(raw=raw2)
        state2["cleaned"] = {"title": "New Article", "body": "New content"}
        state2["vectors"] = {"content": [0.5] * 1024, "title": [0.5] * 1024}
        state2["category"] = "科技"

        mock_llm.call_at = AsyncMock(
            return_value=MergerOutput(merged_title="Merged", merged_body="Merged body")
        )

        node = BatchMergerNode(mock_llm, mock_prompt_loader)
        result = await node.execute_batch([state1, state2])

        # Newer article should be primary
        primary = next(s for s in result if not s.get("is_merged"))
        assert primary["raw"].url == "https://example.com/new"

        # Older should be marked merged
        merged = next(s for s in result if s.get("is_merged"))
        assert merged["raw"].url == "https://example.com/old"

    @pytest.mark.asyncio
    async def test_merge_combines_different_sources(self, mock_llm, mock_prompt_loader):
        """Test that merge tracks all source URLs."""
        now = datetime.now(UTC)

        states = []
        for i in range(3):
            raw = ArticleRaw(
                url=f"https://example.com/article-{i}",
                title=f"Article {i}",
                body=f"Content {i}",
                source=f"source{i}",
                source_host="example.com",
                publish_time=now,
            )
            state = PipelineState(raw=raw)
            state["cleaned"] = {"title": f"Article {i}", "body": f"Content {i}"}
            state["vectors"] = {"content": [0.5] * 1024, "title": [0.5] * 1024}
            state["category"] = "科技"
            states.append(state)

        mock_llm.call_at = AsyncMock(
            return_value=MergerOutput(merged_title="Merged", merged_body="Merged")
        )

        node = BatchMergerNode(mock_llm, mock_prompt_loader)
        result = await node.execute_batch(states)

        primary = next(s for s in result if not s.get("is_merged"))
        # Should track all merged sources
        assert len(primary.get("merged_source_ids", [])) == 2


class TestBatchMergerPerformance:
    """Tests for batch merger performance scenarios."""

    @pytest.fixture
    def mock_llm(self):
        return AsyncMock()

    @pytest.fixture
    def mock_prompt_loader(self):
        loader = MagicMock()
        loader.get_version = MagicMock(return_value="1.0.0")
        return loader

    @pytest.mark.asyncio
    async def test_large_batch_processes_correctly(self, mock_llm, mock_prompt_loader):
        """Test that large batches are processed without error."""
        now = datetime.now(UTC)

        # Create 100 articles
        states = []
        for i in range(100):
            raw = ArticleRaw(
                url=f"https://example.com/article-{i}",
                title=f"Article {i}",
                body=f"Body content {i}" * 10,
                source="test",
                source_host="example.com",
                publish_time=now,
            )
            state = PipelineState(raw=raw)
            state["cleaned"] = {"title": f"Article {i}", "body": f"Body content {i}"}
            # Use orthogonal vectors to avoid merging
            vec = [0.0] * 1024
            vec[i % 1024] = 1.0
            state["vectors"] = {"content": vec, "title": vec}
            state["category"] = "科技"
            states.append(state)

        node = BatchMergerNode(mock_llm, mock_prompt_loader)
        result = await node.execute_batch(states)

        # All states should be returned
        assert len(result) == 100
        # No merges should occur with orthogonal vectors
        mock_llm.call_at.assert_not_called()

    @pytest.mark.asyncio
    async def test_batch_with_many_similar_groups(self, mock_llm, mock_prompt_loader):
        """Test batch with many similar article groups."""
        now = datetime.now(UTC)

        # Create 10 groups of 5 similar articles each
        states = []
        for group in range(10):
            # Create base vector for this group
            base_vec = [0.0] * 1024
            base_vec[group * 100] = 0.9

            for i in range(5):
                raw = ArticleRaw(
                    url=f"https://example.com/group-{group}-article-{i}",
                    title=f"Group {group} Article {i}",
                    body=f"Content for group {group}",
                    source="test",
                    source_host="example.com",
                    publish_time=now,
                )
                state = PipelineState(raw=raw)
                state["cleaned"] = {
                    "title": f"Group {group} Article {i}",
                    "body": f"Content for group {group}",
                }
                state["vectors"] = {"content": base_vec.copy(), "title": base_vec.copy()}
                state["category"] = "科技"
                states.append(state)

        mock_llm.call_at = AsyncMock(
            return_value=MergerOutput(merged_title="Merged", merged_body="Merged")
        )

        node = BatchMergerNode(mock_llm, mock_prompt_loader)
        result = await node.execute_batch(states)

        # Should have 10 merge calls (one per group)
        assert mock_llm.call_at.call_count == 10

        # 50 articles - 10 primaries = 40 merged
        merged_count = sum(1 for s in result if s.get("is_merged"))
        assert merged_count == 40

    @pytest.mark.asyncio
    async def test_batch_similarity_limit_respected(self, mock_llm, mock_prompt_loader):
        """Test that batch similarity limit is used correctly."""
        now = datetime.now(UTC)

        states = []
        for i in range(10):
            raw = ArticleRaw(
                url=f"https://example.com/article-{i}",
                title=f"Article {i}",
                body=f"Body {i}",
                source="test",
                source_host="example.com",
                publish_time=now,
            )
            state = PipelineState(raw=raw)
            state["cleaned"] = {"title": f"Article {i}", "body": f"Body {i}"}
            state["vectors"] = {"content": [0.5] * 1024, "title": [0.5] * 1024}
            state["category"] = "科技"
            states.append(state)

        # Mock vector repo with batch_find_similar
        mock_vector_repo = MagicMock()
        mock_vector_repo.batch_find_similar = AsyncMock(return_value={})
        mock_vector_repo.find_similar = AsyncMock(return_value=[])

        node = BatchMergerNode(mock_llm, mock_prompt_loader, vector_repo=mock_vector_repo)
        result = await node.execute_batch(states)

        # batch_find_similar should be called with limit
        if mock_vector_repo.batch_find_similar.called:
            call_kwargs = mock_vector_repo.batch_find_similar.call_args[1]
            assert call_kwargs.get("limit") == node.BATCH_SIMILARITY_LIMIT

    @pytest.mark.asyncio
    async def test_empty_batch_returns_immediately(self, mock_llm, mock_prompt_loader):
        """Test empty batch returns immediately."""
        node = BatchMergerNode(mock_llm, mock_prompt_loader)
        result = await node.execute_batch([])

        assert result == []
        mock_llm.call_at.assert_not_called()


class TestBatchMergerCrossQuery:
    """Tests for cross-query functionality."""

    @pytest.fixture
    def mock_llm(self):
        return AsyncMock()

    @pytest.fixture
    def mock_prompt_loader(self):
        loader = MagicMock()
        loader.get_version = MagicMock(return_value="1.0.0")
        return loader

    @pytest.mark.asyncio
    async def test_cross_query_finds_historical_similar(self, mock_llm, mock_prompt_loader):
        """Test cross-query finds similar historical articles."""
        now = datetime.now(UTC)

        raw = ArticleRaw(
            url="https://example.com/new-article",
            title="New Article",
            body="New content",
            source="test",
            source_host="example.com",
            publish_time=now,
        )
        state = PipelineState(raw=raw)
        state["cleaned"] = {"title": "New Article", "body": "New content"}
        state["vectors"] = {"content": [0.5] * 1024, "title": [0.5] * 1024}
        state["category"] = "科技"

        # Mock hit from historical articles
        mock_hit = MagicMock()
        mock_hit.article_id = "https://example.com/historical-article"
        mock_hit.similarity = 0.95
        mock_hit.category = "科技"

        mock_vector_repo = MagicMock()
        mock_vector_repo.find_similar = AsyncMock(return_value=[mock_hit])
        mock_vector_repo.batch_find_similar = AsyncMock(return_value={})

        node = BatchMergerNode(mock_llm, mock_prompt_loader, vector_repo=mock_vector_repo)
        result = await node.execute_batch([state])

        # Should have queried for similar
        mock_vector_repo.find_similar.assert_called()

    @pytest.mark.asyncio
    async def test_cross_query_handles_error_gracefully(self, mock_llm, mock_prompt_loader):
        """Test cross-query error doesn't crash the batch."""
        now = datetime.now(UTC)

        raw = ArticleRaw(
            url="https://example.com/article",
            title="Article",
            body="Content",
            source="test",
            source_host="example.com",
            publish_time=now,
        )
        state = PipelineState(raw=raw)
        state["cleaned"] = {"title": "Article", "body": "Content"}
        state["vectors"] = {"content": [0.5] * 1024, "title": [0.5] * 1024}
        state["category"] = "科技"

        mock_vector_repo = MagicMock()
        mock_vector_repo.find_similar = AsyncMock(side_effect=Exception("Query failed"))
        mock_vector_repo.batch_find_similar = AsyncMock(return_value={})

        node = BatchMergerNode(mock_llm, mock_prompt_loader, vector_repo=mock_vector_repo)

        # Should not raise
        result = await node.execute_batch([state])
        assert len(result) == 1


class TestBatchMergerSagaCompensation:
    """Tests for Saga pattern compensation scenarios."""

    @pytest.fixture
    def mock_llm(self):
        return AsyncMock()

    @pytest.fixture
    def mock_prompt_loader(self):
        loader = MagicMock()
        loader.get_version = MagicMock(return_value="1.0.0")
        return loader

    @pytest.mark.asyncio
    async def test_saga_compensation_on_neo4j_failure(self, mock_llm, mock_prompt_loader):
        """Test compensation is triggered when Neo4j write fails."""
        import uuid

        now = datetime.now(UTC)

        raw = ArticleRaw(
            url="https://example.com/article",
            title="Article",
            body="Content",
            source="test",
            source_host="example.com",
            publish_time=now,
        )
        state = PipelineState(raw=raw)
        state["cleaned"] = {"title": "Article", "body": "Content"}
        state["vectors"] = {"content": [0.1] * 1024, "title": [0.2] * 1024}
        state["category"] = "科技"

        article_id = uuid.uuid4()

        mock_article_repo = MagicMock()
        mock_article_repo.get_existing_urls = AsyncMock(return_value=[])
        mock_article_repo.bulk_upsert = AsyncMock(return_value=[article_id])
        mock_article_repo.update_persist_status = AsyncMock()
        mock_article_repo.delete = AsyncMock()

        mock_graph_writer = MagicMock()
        mock_graph_writer.write = AsyncMock(side_effect=Exception("Neo4j connection failed"))

        node = BatchMergerNode(
            mock_llm,
            mock_prompt_loader,
            article_repo=mock_article_repo,
            graph_writer=mock_graph_writer,
        )

        result = await node.persist_batch_saga([state])

        assert result["success"] is False
        assert result["compensation_executed"] is True
        mock_article_repo.delete.assert_called_once_with(article_id)

    @pytest.mark.asyncio
    async def test_saga_partial_neo4j_failure(self, mock_llm, mock_prompt_loader):
        """Test saga handles partial Neo4j failures."""
        import uuid

        now = datetime.now(UTC)

        states = []
        for i in range(3):
            raw = ArticleRaw(
                url=f"https://example.com/article-{i}",
                title=f"Article {i}",
                body=f"Content {i}",
                source="test",
                source_host="example.com",
                publish_time=now,
            )
            state = PipelineState(raw=raw)
            state["cleaned"] = {"title": f"Article {i}", "body": f"Content {i}"}
            state["vectors"] = {"content": [0.1] * 1024, "title": [0.2] * 1024}
            states.append(state)

        article_ids = [uuid.uuid4() for _ in range(3)]

        mock_article_repo = MagicMock()
        mock_article_repo.get_existing_urls = AsyncMock(return_value=[])
        mock_article_repo.bulk_upsert = AsyncMock(return_value=article_ids)
        mock_article_repo.update_persist_status = AsyncMock()
        mock_article_repo.delete = AsyncMock()

        # First succeeds, second fails, third succeeds
        mock_graph_writer = MagicMock()
        mock_graph_writer.write = AsyncMock(
            side_effect=[
                ["node1"],  # Success
                Exception("Failed"),  # Failure
                ["node3"],  # Success
            ]
        )

        node = BatchMergerNode(
            mock_llm,
            mock_prompt_loader,
            article_repo=mock_article_repo,
            graph_writer=mock_graph_writer,
        )

        result = await node.persist_batch_saga(states)

        # Should mark as failed due to partial failure
        assert result["success"] is False
        assert result["compensation_executed"] is True
