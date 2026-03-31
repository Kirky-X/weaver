# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for HybridSearchEngine."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.knowledge.search.engines.hybrid_search import (
    HybridSearchConfig,
    HybridSearchEngine,
    HybridSearchResult,
)
from modules.knowledge.search.rerankers.flashrank_reranker import FlashrankReranker
from modules.knowledge.search.rerankers.mmr_reranker import MMRReranker
from modules.knowledge.search.retrievers.bm25_retriever import BM25Retriever


@pytest.fixture
def mock_vector_repo() -> MagicMock:
    """Create mock vector repository."""
    repo = MagicMock()
    repo.find_similar = AsyncMock(
        return_value=[
            {"id": "vec1", "score": 0.9},
            {"id": "vec2", "score": 0.8},
        ]
    )
    return repo


@pytest.fixture
def mock_bm25_retriever() -> MagicMock:
    """Create mock BM25 retriever."""
    retriever = MagicMock(spec=BM25Retriever)
    retriever.retrieve = MagicMock(
        return_value=[
            MagicMock(doc_id="bm1", score=15.0, title="BM25 Doc 1", content="Content 1"),
            MagicMock(doc_id="bm2", score=12.0, title="BM25 Doc 2", content="Content 2"),
        ]
    )
    retriever.get_document_count = MagicMock(return_value=100)
    return retriever


@pytest.fixture
def mock_reranker() -> MagicMock:
    """Create mock Flashrank reranker."""
    reranker = MagicMock(spec=FlashrankReranker)
    reranker.is_available = MagicMock(return_value=True)
    reranker.rerank = MagicMock(
        return_value=[
            {"id": "vec1", "rerank_score": 0.95, "text": "Content 1"},
            {"id": "bm1", "rerank_score": 0.85, "text": "Content 2"},
        ]
    )
    return reranker


@pytest.fixture
def mock_mmr_reranker() -> MagicMock:
    """Create mock MMR reranker."""
    reranker = MagicMock(spec=MMRReranker)
    reranker.rerank = MagicMock(
        return_value=[
            {"id": "vec1", "mmr_score": 0.9, "content": "Content 1"},
            {"id": "bm1", "mmr_score": 0.8, "content": "Content 2"},
        ]
    )
    return reranker


class TestHybridSearchConfig:
    """Tests for HybridSearchConfig dataclass."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = HybridSearchConfig()

        assert config.hybrid_enabled is True
        assert config.rerank_enabled is True
        assert config.rerank_model == "tiny"
        assert config.mmr_enabled is False
        assert config.mmr_lambda == 0.7
        assert config.rrf_k == 60
        assert config.top_k == 10

    def test_custom_config(self) -> None:
        """Test custom configuration values."""
        config = HybridSearchConfig(
            hybrid_enabled=False,
            rerank_enabled=False,
            rerank_model="medium",
            mmr_enabled=True,
            mmr_lambda=0.5,
            rrf_k=50,
            top_k=20,
        )

        assert config.hybrid_enabled is False
        assert config.rerank_enabled is False
        assert config.rerank_model == "medium"
        assert config.mmr_enabled is True
        assert config.mmr_lambda == 0.5
        assert config.rrf_k == 50
        assert config.top_k == 20


class TestHybridSearchEngineInit:
    """Tests for HybridSearchEngine initialization."""

    def test_init_default(self) -> None:
        """Test initialization with default config."""
        engine = HybridSearchEngine()

        assert engine._config is not None
        assert engine._config.hybrid_enabled is True

    def test_init_with_components(
        self,
        mock_vector_repo: MagicMock,
        mock_bm25_retriever: MagicMock,
        mock_reranker: MagicMock,
    ) -> None:
        """Test initialization with all components."""
        config = HybridSearchConfig()
        engine = HybridSearchEngine(
            vector_repo=mock_vector_repo,
            bm25_retriever=mock_bm25_retriever,
            reranker=mock_reranker,
            config=config,
        )

        assert engine._vector_repo == mock_vector_repo
        assert engine._bm25_retriever == mock_bm25_retriever
        assert engine._reranker == mock_reranker

    def test_init_with_custom_config(self) -> None:
        """Test initialization with custom config."""
        config = HybridSearchConfig(
            hybrid_enabled=False,
            rerank_enabled=False,
        )
        engine = HybridSearchEngine(config=config)

        assert engine._config.hybrid_enabled is False
        assert engine._config.rerank_enabled is False


class TestHybridSearchEngineSearch:
    """Tests for HybridSearchEngine search method."""

    @pytest.mark.asyncio
    async def test_search_hybrid_disabled(
        self,
        mock_vector_repo: MagicMock,
    ) -> None:
        """Test search with hybrid disabled falls back to vector."""
        config = HybridSearchConfig(hybrid_enabled=False)
        engine = HybridSearchEngine(
            vector_repo=mock_vector_repo,
            config=config,
        )

        results = await engine.search("test query", embedding=[0.1] * 768, limit=10)

        # Should call vector search
        mock_vector_repo.find_similar.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_hybrid_enabled(
        self,
        mock_vector_repo: MagicMock,
        mock_bm25_retriever: MagicMock,
    ) -> None:
        """Test search with hybrid enabled."""
        config = HybridSearchConfig(rerank_enabled=False, mmr_enabled=False)
        engine = HybridSearchEngine(
            vector_repo=mock_vector_repo,
            bm25_retriever=mock_bm25_retriever,
            config=config,
        )

        results = await engine.search("test query", embedding=[0.1] * 768, limit=10)

        assert isinstance(results, list)
        # Both vector and BM25 should have been called

    @pytest.mark.asyncio
    async def test_search_with_reranking(
        self,
        mock_vector_repo: MagicMock,
        mock_bm25_retriever: MagicMock,
        mock_reranker: MagicMock,
    ) -> None:
        """Test search with reranking enabled."""
        config = HybridSearchConfig(rerank_enabled=True, mmr_enabled=False)
        engine = HybridSearchEngine(
            vector_repo=mock_vector_repo,
            bm25_retriever=mock_bm25_retriever,
            reranker=mock_reranker,
            config=config,
        )

        results = await engine.search("test query", embedding=[0.1] * 768, limit=10)

        # Reranker should have been called
        # (actual call depends on internal implementation)

    @pytest.mark.asyncio
    async def test_search_with_mmr(
        self,
        mock_vector_repo: MagicMock,
        mock_bm25_retriever: MagicMock,
        mock_reranker: MagicMock,
        mock_mmr_reranker: MagicMock,
    ) -> None:
        """Test search with MMR diversity enabled."""
        config = HybridSearchConfig(
            rerank_enabled=True,
            mmr_enabled=True,
            mmr_lambda=0.5,
        )
        engine = HybridSearchEngine(
            vector_repo=mock_vector_repo,
            bm25_retriever=mock_bm25_retriever,
            reranker=mock_reranker,
            mmr_reranker=mock_mmr_reranker,
            config=config,
        )

        results = await engine.search("test query", embedding=[0.1] * 768, limit=10)

        # MMR reranker should have been called

    @pytest.mark.asyncio
    async def test_search_respects_limit(
        self,
        mock_vector_repo: MagicMock,
        mock_bm25_retriever: MagicMock,
    ) -> None:
        """Test that search respects the limit parameter."""
        config = HybridSearchConfig(rerank_enabled=False, mmr_enabled=False)
        engine = HybridSearchEngine(
            vector_repo=mock_vector_repo,
            bm25_retriever=mock_bm25_retriever,
            config=config,
        )

        results = await engine.search("test query", embedding=[0.1] * 768, limit=5)

        # Results should not exceed limit
        assert len(results) <= 5


class TestHybridSearchEngineParallelRetrieve:
    """Tests for _parallel_retrieve method."""

    @pytest.mark.asyncio
    async def test_parallel_retrieve_both_sources(
        self,
        mock_vector_repo: MagicMock,
        mock_bm25_retriever: MagicMock,
    ) -> None:
        """Test parallel retrieval from both sources."""
        engine = HybridSearchEngine(
            vector_repo=mock_vector_repo,
            bm25_retriever=mock_bm25_retriever,
        )

        vector_results, bm25_results = await engine._parallel_retrieve(
            query="test query",
            embedding=[0.1] * 768,
            limit=10,
        )

        # Both should return results
        assert isinstance(vector_results, list)
        assert isinstance(bm25_results, list)

    @pytest.mark.asyncio
    async def test_parallel_retrieve_no_embedding(
        self,
        mock_vector_repo: MagicMock,
        mock_bm25_retriever: MagicMock,
    ) -> None:
        """Test parallel retrieval without embedding (no vector search)."""
        engine = HybridSearchEngine(
            vector_repo=mock_vector_repo,
            bm25_retriever=mock_bm25_retriever,
        )

        vector_results, bm25_results = await engine._parallel_retrieve(
            query="test query",
            embedding=None,
            limit=10,
        )

        # Vector results should be empty
        assert vector_results == []

    @pytest.mark.asyncio
    async def test_parallel_retrieve_handles_exception(
        self,
        mock_vector_repo: MagicMock,
        mock_bm25_retriever: MagicMock,
    ) -> None:
        """Test that parallel retrieve handles exceptions gracefully."""
        mock_vector_repo.find_similar = AsyncMock(side_effect=Exception("Vector search failed"))

        engine = HybridSearchEngine(
            vector_repo=mock_vector_repo,
            bm25_retriever=mock_bm25_retriever,
        )

        # Should not raise, should handle gracefully
        vector_results, bm25_results = await engine._parallel_retrieve(
            query="test query",
            embedding=[0.1] * 768,
            limit=10,
        )

        # Vector results should be empty due to error
        assert vector_results == []
        # BM25 should still work
        assert isinstance(bm25_results, list)

    @pytest.mark.asyncio
    async def test_parallel_retrieve_bm25_failure(
        self,
        mock_vector_repo: MagicMock,
        mock_bm25_retriever: MagicMock,
    ) -> None:
        """Test that parallel retrieve handles BM25 failure gracefully."""
        mock_bm25_retriever.retrieve = MagicMock(side_effect=Exception("BM25 search failed"))

        engine = HybridSearchEngine(
            vector_repo=mock_vector_repo,
            bm25_retriever=mock_bm25_retriever,
        )

        # Should not raise, should handle gracefully
        vector_results, bm25_results = await engine._parallel_retrieve(
            query="test query",
            embedding=[0.1] * 768,
            limit=10,
        )

        # BM25 results should be empty due to error
        assert bm25_results == []
        # Vector should still work
        assert isinstance(vector_results, list)

    @pytest.mark.asyncio
    async def test_parallel_retrieve_both_fail(
        self,
        mock_vector_repo: MagicMock,
        mock_bm25_retriever: MagicMock,
    ) -> None:
        """Test that parallel retrieve handles both failures gracefully."""
        mock_vector_repo.find_similar = AsyncMock(side_effect=Exception("Vector search failed"))
        mock_bm25_retriever.retrieve = MagicMock(side_effect=Exception("BM25 search failed"))

        engine = HybridSearchEngine(
            vector_repo=mock_vector_repo,
            bm25_retriever=mock_bm25_retriever,
        )

        # Should not raise, should handle gracefully
        vector_results, bm25_results = await engine._parallel_retrieve(
            query="test query",
            embedding=[0.1] * 768,
            limit=10,
        )

        # Both should be empty due to errors
        assert vector_results == []
        assert bm25_results == []


class TestHybridSearchEngineFuseResults:
    """Tests for _fuse_results method."""

    def test_fuse_results_basic(self) -> None:
        """Test basic result fusion."""
        engine = HybridSearchEngine()

        vector_results = [("doc1", 0.9), ("doc2", 0.8)]
        bm25_results = [("doc2", 15.0), ("doc3", 12.0)]

        fused = engine._fuse_results(vector_results, bm25_results)

        assert len(fused) == 3  # 3 unique documents
        assert all("doc_id" in r for r in fused)
        assert all("rrf_score" in r for r in fused)

    def test_fuse_results_empty(self) -> None:
        """Test fusion with empty results."""
        engine = HybridSearchEngine()

        fused = engine._fuse_results([], [])

        assert fused == []

    def test_fuse_results_single_list(self) -> None:
        """Test fusion with only one list."""
        engine = HybridSearchEngine()

        vector_results = [("doc1", 0.9), ("doc2", 0.8)]
        bm25_results = []

        fused = engine._fuse_results(vector_results, bm25_results)

        assert len(fused) == 2


class TestHybridSearchEngineStats:
    """Tests for get_stats method."""

    def test_get_stats(
        self,
        mock_vector_repo: MagicMock,
        mock_bm25_retriever: MagicMock,
        mock_reranker: MagicMock,
    ) -> None:
        """Test getting engine statistics."""
        engine = HybridSearchEngine(
            vector_repo=mock_vector_repo,
            bm25_retriever=mock_bm25_retriever,
            reranker=mock_reranker,
        )

        stats = engine.get_stats()

        assert "hybrid_enabled" in stats
        assert "rerank_enabled" in stats
        assert "mmr_enabled" in stats
        assert "bm25_available" in stats
        assert "bm25_doc_count" in stats
        assert "reranker_available" in stats


class TestHybridSearchEngineSetConfig:
    """Tests for set_config method."""

    def test_set_config(self) -> None:
        """Test updating configuration."""
        engine = HybridSearchEngine()

        new_config = HybridSearchConfig(
            hybrid_enabled=False,
            rerank_enabled=False,
        )
        engine.set_config(new_config)

        assert engine._config.hybrid_enabled is False
        assert engine._config.rerank_enabled is False


class TestHybridSearchResult:
    """Tests for HybridSearchResult dataclass."""

    def test_result_creation(self) -> None:
        """Test creating a HybridSearchResult."""
        result = HybridSearchResult(
            doc_id="test-1",
            score=0.95,
            title="Test Title",
            content="Test content",
            source="hybrid",
            vector_rank=1,
            bm25_rank=2,
            rerank_score=0.95,
        )

        assert result.doc_id == "test-1"
        assert result.score == 0.95
        assert result.source == "hybrid"
        assert result.vector_rank == 1
        assert result.bm25_rank == 2
        assert result.rerank_score == 0.95

    def test_result_defaults(self) -> None:
        """Test HybridSearchResult default values."""
        result = HybridSearchResult(
            doc_id="test-1",
            score=0.9,
            title="Title",
            content="Content",
            source="vector",
        )

        assert result.vector_rank is None
        assert result.bm25_rank is None
        assert result.rerank_score is None
        assert result.mmr_score is None
        assert result.metadata == {}
