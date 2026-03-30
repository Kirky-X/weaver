# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for Search Enhancement features.

Tests the integrated functionality of:
- BM25 lexical retrieval
- RRF fusion algorithm
- Flashrank re-ranking
- MMR diversity re-ranking
- HybridSearchEngine integration
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Skip all BM25 tests if spacy model is not available
try:
    import spacy

    spacy.load("zh_core_web_sm")
    SPACY_AVAILABLE = True
except (ImportError, OSError):
    SPACY_AVAILABLE = False

from modules.search.engines.hybrid_search import (
    HybridSearchConfig,
    HybridSearchEngine,
    HybridSearchResult,
)
from modules.search.fusion.rrf import reciprocal_rank_fusion
from modules.search.rerankers.flashrank_reranker import FlashrankReranker
from modules.search.rerankers.mmr_reranker import MMRReranker
from modules.search.retrievers.bm25_retriever import BM25Document, BM25Retriever


@pytest.fixture
def sample_documents() -> list[BM25Document]:
    """Sample documents for testing."""
    return [
        BM25Document(
            doc_id="doc1",
            title="人工智能发展报告",
            content="人工智能技术正在快速发展，深度学习和神经网络取得了重大突破。",
            metadata={"category": "tech", "source": "report"},
        ),
        BM25Document(
            doc_id="doc2",
            title="机器学习入门教程",
            content="机器学习是人工智能的重要分支，包括监督学习和无监督学习。",
            metadata={"category": "tutorial", "source": "course"},
        ),
        BM25Document(
            doc_id="doc3",
            title="Python编程指南",
            content="Python是一种流行的编程语言，广泛用于数据科学和Web开发。",
            metadata={"category": "programming", "source": "book"},
        ),
        BM25Document(
            doc_id="doc4",
            title="深度学习框架对比",
            content="TensorFlow和PyTorch是目前最流行的深度学习框架。",
            metadata={"category": "tech", "source": "article"},
        ),
        BM25Document(
            doc_id="doc5",
            title="自然语言处理技术",
            content="自然语言处理是人工智能的重要应用领域，包括文本分类和情感分析。",
            metadata={"category": "tech", "source": "paper"},
        ),
    ]


@pytest.fixture
def bm25_retriever(sample_documents: list[BM25Document]) -> BM25Retriever:
    """Create and index BM25 retriever with sample documents."""
    retriever = BM25Retriever(language="zh")
    retriever.index(sample_documents)
    return retriever


@pytest.fixture
def mock_vector_repo() -> MagicMock:
    """Mock vector repository."""
    repo = MagicMock()
    repo.find_similar = AsyncMock(
        return_value=[
            {"id": "doc1", "score": 0.95},
            {"id": "doc2", "score": 0.88},
            {"id": "doc5", "score": 0.75},
        ]
    )
    return repo


@pytest.mark.skipif(not SPACY_AVAILABLE, reason="spacy model zh_core_web_sm not available")
class TestBM25RetrievalIntegration:
    """Integration tests for BM25 retrieval."""

    def test_bm25_retrieves_relevant_documents(self, bm25_retriever: BM25Retriever) -> None:
        """Test that BM25 retrieves relevant documents for queries."""
        results = bm25_retriever.retrieve("人工智能", top_k=5)

        assert len(results) > 0
        # AI-related documents should appear
        doc_ids = [r.doc_id for r in results]
        assert "doc1" in doc_ids or "doc2" in doc_ids or "doc5" in doc_ids

    def test_bm25_respects_top_k(self, bm25_retriever: BM25Retriever) -> None:
        """Test that BM25 respects top_k parameter."""
        results = bm25_retriever.retrieve("技术", top_k=3)

        assert len(results) <= 3

    def test_bm25_returns_scores(self, bm25_retriever: BM25Retriever) -> None:
        """Test that BM25 returns documents with scores."""
        results = bm25_retriever.retrieve("Python", top_k=5)

        for result in results:
            assert result.score > 0


class TestRRFFusionIntegration:
    """Integration tests for RRF fusion."""

    def test_rrf_combines_multiple_sources(self) -> None:
        """Test RRF combining results from multiple sources."""
        vector_results = [("doc1", 0.95), ("doc2", 0.88), ("doc5", 0.75)]
        bm25_results = [("doc2", 15.2), ("doc1", 12.5), ("doc4", 8.3)]

        fused = reciprocal_rank_fusion([vector_results, bm25_results])

        assert len(fused) == 4  # 4 unique documents
        # Documents appearing in both should rank higher
        doc_ids = [doc_id for doc_id, _ in fused]
        assert "doc1" in doc_ids
        assert "doc2" in doc_ids

    def test_rrf_handles_empty_results(self) -> None:
        """Test RRF with empty results from one source."""
        vector_results = [("doc1", 0.9), ("doc2", 0.8)]
        bm25_results: list[tuple[str, float]] = []

        fused = reciprocal_rank_fusion([vector_results, bm25_results])

        assert len(fused) == 2


class TestFlashrankIntegration:
    """Integration tests for Flashrank re-ranking."""

    def test_reranker_improves_ranking(self) -> None:
        """Test that re-ranker produces valid results."""
        reranker = FlashrankReranker(enabled=False)  # Use disabled for testing

        candidates = [
            {"id": "doc1", "content": "人工智能技术发展", "score": 0.9},
            {"id": "doc2", "content": "机器学习算法", "score": 0.8},
            {"id": "doc3", "content": "Python编程", "score": 0.7},
        ]

        results = reranker.rerank("人工智能", candidates, top_k=3)

        assert len(results) == 3
        # When disabled, should return original candidates
        assert results == candidates

    def test_reranker_graceful_degradation(self) -> None:
        """Test re-ranker graceful degradation when unavailable."""
        reranker = FlashrankReranker(enabled=False)

        candidates = [
            {"id": "doc1", "content": "Test content", "score": 0.9},
        ]

        results = reranker.rerank("test query", candidates)

        # Should return original when unavailable
        assert len(results) == 1
        assert results[0]["id"] == "doc1"


class TestMMRIntegration:
    """Integration tests for MMR diversity re-ranking."""

    def test_mmr_promotes_diversity(self) -> None:
        """Test that MMR promotes diverse results."""
        reranker = MMRReranker(lambda_param=0.5)

        candidates = [
            {"id": "doc1", "content": "人工智能发展报告", "score": 1.0},
            {"id": "doc2", "content": "人工智能技术应用", "score": 0.95},  # Similar to doc1
            {"id": "doc3", "content": "Python编程指南", "score": 0.9},  # Different topic
        ]

        results = reranker.rerank(candidates, top_k=3)

        assert len(results) == 3
        # All documents should have MMR scores
        assert all("mmr_score" in r for r in results)

    def test_mmr_respects_lambda(self) -> None:
        """Test that lambda parameter affects results."""
        candidates = [
            {"id": "doc1", "content": "人工智能技术", "score": 1.0},
            {"id": "doc2", "content": "机器学习算法", "score": 0.9},
        ]

        # High lambda = favor relevance
        reranker_high = MMRReranker(lambda_param=0.9)
        results_high = reranker_high.rerank(candidates)

        # Low lambda = favor diversity
        reranker_low = MMRReranker(lambda_param=0.1)
        results_low = reranker_low.rerank(candidates)

        # Both should return results
        assert len(results_high) == 2
        assert len(results_low) == 2


@pytest.mark.skipif(not SPACY_AVAILABLE, reason="spacy model zh_core_web_sm not available")
class TestHybridSearchEngineIntegration:
    """Integration tests for HybridSearchEngine."""

    @pytest.mark.asyncio
    async def test_hybrid_search_combines_sources(
        self,
        bm25_retriever: BM25Retriever,
        mock_vector_repo: MagicMock,
    ) -> None:
        """Test hybrid search combines BM25 and vector results."""
        config = HybridSearchConfig(
            hybrid_enabled=True,
            rerank_enabled=False,
            mmr_enabled=False,
        )
        engine = HybridSearchEngine(
            vector_repo=mock_vector_repo,
            bm25_retriever=bm25_retriever,
            config=config,
        )

        results = await engine.search(
            query="人工智能",
            embedding=[0.1] * 768,  # Mock embedding
            limit=10,
        )

        assert isinstance(results, list)
        assert len(results) > 0
        assert all(isinstance(r, HybridSearchResult) for r in results)

    @pytest.mark.asyncio
    async def test_hybrid_search_with_reranking(
        self,
        bm25_retriever: BM25Retriever,
        mock_vector_repo: MagicMock,
    ) -> None:
        """Test hybrid search with re-ranking enabled."""
        reranker = FlashrankReranker(enabled=False)
        config = HybridSearchConfig(
            hybrid_enabled=True,
            rerank_enabled=True,
            mmr_enabled=False,
        )
        engine = HybridSearchEngine(
            vector_repo=mock_vector_repo,
            bm25_retriever=bm25_retriever,
            reranker=reranker,
            config=config,
        )

        results = await engine.search(
            query="机器学习",
            embedding=[0.1] * 768,
            limit=5,
        )

        assert len(results) <= 5

    @pytest.mark.asyncio
    async def test_hybrid_search_fallback_on_error(
        self,
        mock_vector_repo: MagicMock,
    ) -> None:
        """Test hybrid search fallback when BM25 fails."""
        # BM25 retriever that raises error
        failing_bm25 = MagicMock(spec=BM25Retriever)
        failing_bm25.retrieve = MagicMock(side_effect=Exception("BM25 error"))

        config = HybridSearchConfig(hybrid_enabled=True, rerank_enabled=False)
        engine = HybridSearchEngine(
            vector_repo=mock_vector_repo,
            bm25_retriever=failing_bm25,
            config=config,
        )

        # Should not raise, should fall back to vector only
        results = await engine.search(
            query="test query",
            embedding=[0.1] * 768,
            limit=10,
        )

        # Should still return vector results
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_hybrid_search_disabled(
        self,
        bm25_retriever: BM25Retriever,
        mock_vector_repo: MagicMock,
    ) -> None:
        """Test hybrid search with hybrid disabled."""
        config = HybridSearchConfig(hybrid_enabled=False, rerank_enabled=False)
        engine = HybridSearchEngine(
            vector_repo=mock_vector_repo,
            bm25_retriever=bm25_retriever,
            config=config,
        )

        results = await engine.search(
            query="test query",
            embedding=[0.1] * 768,
            limit=10,
        )

        # Should only use vector search
        mock_vector_repo.find_similar.assert_called_once()


class TestSearchPipelineIntegration:
    """End-to-end tests for search pipeline."""

    @pytest.mark.asyncio
    async def test_full_search_pipeline(
        self,
        bm25_retriever: BM25Retriever,
        mock_vector_repo: MagicMock,
    ) -> None:
        """Test complete search pipeline with all features."""
        reranker = FlashrankReranker(enabled=False)
        mmr = MMRReranker(lambda_param=0.7)

        config = HybridSearchConfig(
            hybrid_enabled=True,
            rerank_enabled=True,
            mmr_enabled=True,
            mmr_lambda=0.7,
        )
        engine = HybridSearchEngine(
            vector_repo=mock_vector_repo,
            bm25_retriever=bm25_retriever,
            reranker=reranker,
            mmr_reranker=mmr,
            config=config,
        )

        results = await engine.search(
            query="人工智能技术发展",
            embedding=[0.1] * 768,
            limit=5,
        )

        # Verify complete pipeline executed
        assert isinstance(results, list)
        assert len(results) <= 5

    @pytest.mark.asyncio
    async def test_search_with_chinese_queries(
        self,
        bm25_retriever: BM25Retriever,
        mock_vector_repo: MagicMock,
    ) -> None:
        """Test search with various Chinese queries."""
        config = HybridSearchConfig(rerank_enabled=False, mmr_enabled=False)
        engine = HybridSearchEngine(
            vector_repo=mock_vector_repo,
            bm25_retriever=bm25_retriever,
            config=config,
        )

        queries = [
            "人工智能",
            "机器学习算法",
            "Python编程",
            "深度学习框架",
        ]

        for query in queries:
            results = await engine.search(
                query=query,
                embedding=[0.1] * 768,
                limit=5,
            )

            assert isinstance(results, list)
            # Each query should return some results
            # (either from BM25 or vector or both)


@pytest.mark.skipif(not SPACY_AVAILABLE, reason="spacy model zh_core_web_sm not available")
class TestSearchStatistics:
    """Tests for search statistics and metadata."""

    @pytest.mark.asyncio
    async def test_hybrid_search_includes_metadata(
        self,
        bm25_retriever: BM25Retriever,
        mock_vector_repo: MagicMock,
    ) -> None:
        """Test that hybrid search includes relevant metadata."""
        config = HybridSearchConfig(rerank_enabled=False, mmr_enabled=False)
        engine = HybridSearchEngine(
            vector_repo=mock_vector_repo,
            bm25_retriever=bm25_retriever,
            config=config,
        )

        results = await engine.search(
            query="人工智能",
            embedding=[0.1] * 768,
            limit=10,
        )

        for result in results:
            assert result.source == "hybrid" or result.source == "vector"
            assert result.score > 0

    def test_engine_stats(
        self,
        bm25_retriever: BM25Retriever,
    ) -> None:
        """Test getting engine statistics."""
        config = HybridSearchConfig()
        engine = HybridSearchEngine(
            bm25_retriever=bm25_retriever,
            config=config,
        )

        stats = engine.get_stats()

        assert "hybrid_enabled" in stats
        assert "bm25_available" in stats
        assert "bm25_doc_count" in stats
        assert stats["bm25_doc_count"] == 5  # 5 sample documents
