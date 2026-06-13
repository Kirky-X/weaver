# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for HybridSearchEngine - comprehensive coverage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.models.shared import ArticleSearchResultView
from modules.knowledge.search.engines.hybrid_search import (
    HybridSearchConfig,
    HybridSearchEngine,
    HybridSearchResult,
)


class TestHybridSearchEngineFuseResults:
    """Tests for _fuse_results method."""

    def test_fuse_basic(self):
        """Test basic result fusion with overlapping docs."""
        engine = HybridSearchEngine()

        vector_results = [("doc1", 0.9), ("doc2", 0.8)]
        bm25_results = [
            {"doc_id": "doc2", "score": 15.0, "title": "Doc 2", "content": "Content 2"},
            {"doc_id": "doc3", "score": 12.0, "title": "Doc 3", "content": "Content 3"},
        ]

        fused = engine._fuse_results(vector_results, bm25_results)

        assert len(fused) == 3  # 3 unique documents
        assert all("doc_id" in r for r in fused)
        assert all("rrf_score" in r for r in fused)

    def test_fuse_empty_both(self):
        """Test fusion with both lists empty."""
        engine = HybridSearchEngine()

        fused = engine._fuse_results([], [])

        assert fused == []

    def test_fuse_vector_only(self):
        """Test fusion with only vector results."""
        engine = HybridSearchEngine()

        vector_results = [("doc1", 0.9), ("doc2", 0.8)]
        fused = engine._fuse_results(vector_results, [])

        assert len(fused) == 2
        assert fused[0]["doc_id"] == "doc1"

    def test_fuse_bm25_only(self):
        """Test fusion with only BM25 results."""
        engine = HybridSearchEngine()

        bm25_results = [
            {"doc_id": "doc1", "score": 15.0, "title": "Doc 1", "content": "Content 1"},
        ]
        fused = engine._fuse_results([], bm25_results)

        assert len(fused) == 1
        assert fused[0]["doc_id"] == "doc1"

    def test_fuse_preserves_ranks(self):
        """Test that fusion preserves vector and BM25 ranks."""
        engine = HybridSearchEngine()

        vector_results = [("doc1", 0.9)]
        bm25_results = [
            {"doc_id": "doc1", "score": 15.0, "title": "Doc 1", "content": "Content 1"},
        ]

        fused = engine._fuse_results(vector_results, bm25_results)

        assert fused[0]["vector_rank"] == 1
        assert fused[0]["bm25_rank"] == 1

    def test_fuse_preserves_bm25_content(self):
        """Test that fusion preserves BM25 content info."""
        engine = HybridSearchEngine()

        bm25_results = [
            {"doc_id": "doc1", "score": 15.0, "title": "Title", "content": "Content"},
        ]
        fused = engine._fuse_results([], bm25_results)

        assert fused[0]["title"] == "Title"
        assert fused[0]["content"] == "Content"

    def test_fuse_custom_rrf_k(self):
        """Test fusion with custom RRF k parameter."""
        config = HybridSearchConfig(rrf_k=100)
        engine = HybridSearchEngine(config=config)

        vector_results = [("doc1", 0.9)]
        bm25_results = [
            {"doc_id": "doc1", "score": 15.0, "title": "Doc 1", "content": "C1"},
        ]

        fused = engine._fuse_results(vector_results, bm25_results)

        assert len(fused) == 1


class TestHybridSearchEngineRerankResults:
    """Tests for _rerank_results method."""

    def test_rerank_basic(self):
        """Test basic reranking."""
        mock_reranker = MagicMock()
        mock_reranker.rerank = MagicMock(
            return_value=[
                {"doc_id": "doc1", "rerank_score": 0.95, "content": "C1"},
                {"doc_id": "doc2", "rerank_score": 0.85, "content": "C2"},
            ]
        )

        engine = HybridSearchEngine(reranker=mock_reranker)

        results = [
            {"doc_id": "doc1", "content": "C1", "title": "T1"},
            {"doc_id": "doc2", "content": "C2", "title": "T2"},
        ]

        reranked = engine._rerank_results("test query", results)

        assert len(reranked) == 2
        mock_reranker.rerank.assert_called_once()

    def test_rerank_empty_results(self):
        """Test reranking with empty results."""
        mock_reranker = MagicMock()
        engine = HybridSearchEngine(reranker=mock_reranker)

        reranked = engine._rerank_results("test query", [])

        assert reranked == []
        mock_reranker.rerank.assert_not_called()

    def test_rerank_no_reranker(self):
        """Test reranking when no reranker available."""
        engine = HybridSearchEngine(reranker=None)

        results = [{"doc_id": "doc1", "content": "C1"}]
        reranked = engine._rerank_results("test query", results)

        assert reranked == results

    def test_rerank_adds_rerank_score(self):
        """Test that reranking adds rerank_score field."""
        mock_reranker = MagicMock()
        mock_reranker.rerank = MagicMock(
            return_value=[
                {"doc_id": "doc1", "rerank_score": 0.95, "content": "C1"},
            ]
        )

        engine = HybridSearchEngine(reranker=mock_reranker)

        results = [{"doc_id": "doc1", "content": "C1", "title": "T1"}]
        reranked = engine._rerank_results("test query", results)

        assert "rerank_score" in reranked[0]


class TestHybridSearchEngineApplyMMR:
    """Tests for _apply_mmr method."""

    def test_apply_mmr_basic(self):
        """Test basic MMR application."""
        mock_mmr = MagicMock()
        mock_mmr.rerank = MagicMock(
            return_value=[
                {"doc_id": "doc1", "mmr_score": 0.9, "content": "C1"},
                {"doc_id": "doc2", "mmr_score": 0.8, "content": "C2"},
            ]
        )

        engine = HybridSearchEngine(mmr_reranker=mock_mmr)

        results = [
            {"doc_id": "doc1", "content": "C1"},
            {"doc_id": "doc2", "content": "C2"},
        ]

        mmr_results = engine._apply_mmr(results)

        assert len(mmr_results) == 2
        mock_mmr.rerank.assert_called_once()

    def test_apply_mmr_empty_results(self):
        """Test MMR with empty results."""
        mock_mmr = MagicMock()
        engine = HybridSearchEngine(mmr_reranker=mock_mmr)

        mmr_results = engine._apply_mmr([])

        assert mmr_results == []
        mock_mmr.rerank.assert_not_called()

    def test_apply_mmr_no_reranker(self):
        """Test MMR when no MMR reranker available."""
        engine = HybridSearchEngine(mmr_reranker=None)

        results = [{"doc_id": "doc1", "content": "C1"}]
        mmr_results = engine._apply_mmr(results)

        assert mmr_results == results

    def test_apply_mmr_passes_text_key(self):
        """Test that MMR passes correct text_key parameter."""
        mock_mmr = MagicMock()
        mock_mmr.rerank = MagicMock(return_value=[])

        engine = HybridSearchEngine(mmr_reranker=mock_mmr)

        results = [{"doc_id": "doc1", "content": "C1"}]
        engine._apply_mmr(results)

        call_kwargs = mock_mmr.rerank.call_args
        assert call_kwargs[1]["text_key"] == "content"


class TestHybridSearchEngineApplyTemporalDecay:
    """Tests for _apply_temporal_decay method."""

    @pytest.mark.asyncio
    async def test_temporal_decay_with_publish_time(self):
        """Test temporal decay with publish_time field."""
        config = HybridSearchConfig(
            temporal_decay_enabled=True,
            temporal_decay_half_life_days=30.0,
        )
        engine = HybridSearchEngine(config=config)

        now = datetime.now(UTC)
        old_date = now - timedelta(days=60)

        results = [
            {
                "doc_id": "doc1",
                "rrf_score": 0.9,
                "publish_time": old_date,
            },
        ]

        with (
            patch(
                "modules.knowledge.search.temporal_decay.apply_temporal_decay",
                return_value=0.45,
            ),
            patch(
                "modules.knowledge.search.temporal_decay.calculate_age_in_days",
                return_value=60.0,
            ),
        ):
            decayed = await engine._apply_temporal_decay(results)

        assert decayed[0]["temporal_decay_multiplier"] is not None

    @pytest.mark.asyncio
    async def test_temporal_decay_with_rerank_score(self):
        """Test temporal decay uses rerank_score when available."""
        config = HybridSearchConfig(
            temporal_decay_enabled=True,
            temporal_decay_half_life_days=30.0,
        )
        engine = HybridSearchEngine(config=config)

        now = datetime.now(UTC)
        old_date = now - timedelta(days=30)

        results = [
            {
                "doc_id": "doc1",
                "rerank_score": 0.95,
                "publish_time": old_date,
            },
        ]

        with (
            patch(
                "modules.knowledge.search.temporal_decay.apply_temporal_decay",
                return_value=0.5,
            ),
            patch(
                "modules.knowledge.search.temporal_decay.calculate_age_in_days",
                return_value=30.0,
            ),
        ):
            decayed = await engine._apply_temporal_decay(results)

        # Should update rerank_score, not rrf_score
        assert decayed[0]["rerank_score"] == 0.5

    @pytest.mark.asyncio
    async def test_temporal_decay_fallback_to_created_at(self):
        """Test temporal decay falls back to created_at."""
        config = HybridSearchConfig(
            temporal_decay_enabled=True,
            temporal_decay_half_life_days=30.0,
        )
        engine = HybridSearchEngine(config=config)

        now = datetime.now(UTC)
        old_date = now - timedelta(days=15)

        results = [
            {
                "doc_id": "doc1",
                "rrf_score": 0.8,
                "created_at": old_date,
            },
        ]

        with (
            patch(
                "modules.knowledge.search.temporal_decay.apply_temporal_decay",
                return_value=0.7,
            ),
            patch(
                "modules.knowledge.search.temporal_decay.calculate_age_in_days",
                return_value=15.0,
            ),
        ):
            decayed = await engine._apply_temporal_decay(results)

        assert decayed[0]["rrf_score"] == 0.7

    @pytest.mark.asyncio
    async def test_temporal_decay_no_timestamp(self):
        """Test temporal decay with no timestamp."""
        config = HybridSearchConfig(
            temporal_decay_enabled=True,
            temporal_decay_half_life_days=30.0,
        )
        engine = HybridSearchEngine(config=config)

        results = [
            {
                "doc_id": "doc1",
                "rrf_score": 0.8,
            },
        ]

        with (
            patch(
                "modules.knowledge.search.temporal_decay.apply_temporal_decay",
                return_value=0.8,
            ),
            patch(
                "modules.knowledge.search.temporal_decay.calculate_age_in_days",
                return_value=0.0,
            ),
        ):
            decayed = await engine._apply_temporal_decay(results)

        assert decayed[0]["temporal_decay_multiplier"] is not None

    @pytest.mark.asyncio
    async def test_temporal_decay_resorts_results(self):
        """Test temporal decay re-sorts results by final score."""
        config = HybridSearchConfig(
            temporal_decay_enabled=True,
            temporal_decay_half_life_days=30.0,
        )
        engine = HybridSearchEngine(config=config)

        now = datetime.now(UTC)

        results = [
            {
                "doc_id": "doc1",
                "rrf_score": 0.9,
                "publish_time": now - timedelta(days=60),
            },
            {
                "doc_id": "doc2",
                "rrf_score": 0.5,
                "publish_time": now - timedelta(days=1),
            },
        ]

        with (
            patch(
                "modules.knowledge.search.temporal_decay.apply_temporal_decay",
                side_effect=[0.3, 0.48],
            ),
            patch(
                "modules.knowledge.search.temporal_decay.calculate_age_in_days",
                side_effect=[60.0, 1.0],
            ),
        ):
            decayed = await engine._apply_temporal_decay(results)

        # doc2 should now be first (0.48 > 0.3)
        assert decayed[0]["doc_id"] == "doc2"

    @pytest.mark.asyncio
    async def test_temporal_decay_zero_score(self):
        """Test temporal decay with zero original score."""
        config = HybridSearchConfig(
            temporal_decay_enabled=True,
            temporal_decay_half_life_days=30.0,
        )
        engine = HybridSearchEngine(config=config)

        results = [
            {
                "doc_id": "doc1",
                "rrf_score": 0.0,
            },
        ]

        with (
            patch(
                "modules.knowledge.search.temporal_decay.apply_temporal_decay",
                return_value=0.0,
            ),
            patch(
                "modules.knowledge.search.temporal_decay.calculate_age_in_days",
                return_value=10.0,
            ),
        ):
            decayed = await engine._apply_temporal_decay(results)

        # Multiplier should be 1.0 when original score is 0
        assert decayed[0]["temporal_decay_multiplier"] == 1.0


class TestHybridSearchEngineSearch:
    """Tests for search() method."""

    @pytest.mark.asyncio
    async def test_search_hybrid_disabled(self):
        """Test search with hybrid disabled falls back to vector."""
        mock_repo = MagicMock()
        mock_repo.find_similar = AsyncMock(
            return_value=[ArticleSearchResultView(article_id="doc1", similarity=0.9)]
        )

        config = HybridSearchConfig(hybrid_enabled=False)
        engine = HybridSearchEngine(vector_repo=mock_repo, config=config)

        results = await engine.search("test query", embedding=[0.1] * 768, limit=10)

        mock_repo.find_similar.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_hybrid_enabled(self):
        """Test search with hybrid enabled."""
        mock_repo = MagicMock()
        mock_repo.find_similar = AsyncMock(
            return_value=[ArticleSearchResultView(article_id="doc1", similarity=0.9)]
        )
        mock_bm25 = MagicMock()
        mock_bm25.retrieve = MagicMock(return_value=[])

        config = HybridSearchConfig(rerank_enabled=False, mmr_enabled=False)
        engine = HybridSearchEngine(
            vector_repo=mock_repo,
            bm25_retriever=mock_bm25,
            config=config,
        )

        results = await engine.search("test query", embedding=[0.1] * 768, limit=10)

        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_search_with_temporal_decay(self):
        """Test search with temporal decay enabled."""
        mock_repo = MagicMock()
        mock_repo.find_similar = AsyncMock(return_value=[])
        mock_bm25 = MagicMock()
        mock_bm25.retrieve = MagicMock(return_value=[])

        config = HybridSearchConfig(
            rerank_enabled=False,
            mmr_enabled=False,
            temporal_decay_enabled=True,
        )
        engine = HybridSearchEngine(
            vector_repo=mock_repo,
            bm25_retriever=mock_bm25,
            config=config,
        )

        results = await engine.search("test query", embedding=[0.1] * 768, limit=10)

        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_search_no_embedding(self):
        """Test search without embedding."""
        mock_repo = MagicMock()
        mock_bm25 = MagicMock()
        mock_bm25.retrieve = MagicMock(return_value=[])

        config = HybridSearchConfig(rerank_enabled=False, mmr_enabled=False)
        engine = HybridSearchEngine(
            vector_repo=mock_repo,
            bm25_retriever=mock_bm25,
            config=config,
        )

        results = await engine.search("test query", embedding=None, limit=10)

        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_search_respects_limit(self):
        """Test that search respects the limit parameter."""
        mock_repo = MagicMock()
        mock_repo.find_similar = AsyncMock(
            return_value=[{"id": f"doc{i}", "score": 0.9 - i * 0.1} for i in range(5)]
        )
        mock_bm25 = MagicMock()
        mock_bm25.retrieve = MagicMock(return_value=[])

        config = HybridSearchConfig(rerank_enabled=False, mmr_enabled=False)
        engine = HybridSearchEngine(
            vector_repo=mock_repo,
            bm25_retriever=mock_bm25,
            config=config,
        )

        results = await engine.search("test query", embedding=[0.1] * 768, limit=3)

        assert len(results) <= 3


class TestHybridSearchEngineVectorSearch:
    """Tests for _vector_search method."""

    @pytest.mark.asyncio
    async def test_vector_search_basic(self):
        """Test basic vector search."""
        mock_repo = MagicMock()
        mock_repo.find_similar = AsyncMock(
            return_value=[
                ArticleSearchResultView(article_id="doc1", similarity=0.9),
                ArticleSearchResultView(article_id="doc2", similarity=0.8),
            ]
        )

        engine = HybridSearchEngine(vector_repo=mock_repo)
        results = await engine._vector_search([0.1] * 768, limit=10)

        assert len(results) == 2
        assert results[0][0] == "doc1"
        assert results[0][1] == 0.9

    @pytest.mark.asyncio
    async def test_vector_search_no_repo(self):
        """Test vector search without repo returns empty."""
        engine = HybridSearchEngine(vector_repo=None)
        results = await engine._vector_search([0.1] * 768, limit=10)

        assert results == []

    @pytest.mark.asyncio
    async def test_vector_search_handles_error(self):
        """Test vector search handles errors gracefully."""
        mock_repo = MagicMock()
        mock_repo.find_similar = AsyncMock(side_effect=Exception("Search failed"))

        engine = HybridSearchEngine(vector_repo=mock_repo)
        results = await engine._vector_search([0.1] * 768, limit=10)

        assert results == []

    @pytest.mark.asyncio
    async def test_vector_search_doc_id_fallback(self):
        """Test vector search uses doc_id when id is missing."""
        mock_repo = MagicMock()
        mock_repo.find_similar = AsyncMock(
            return_value=[ArticleSearchResultView(article_id="doc1", similarity=0.9)]
        )

        engine = HybridSearchEngine(vector_repo=mock_repo)
        results = await engine._vector_search([0.1] * 768, limit=10)

        assert results[0][0] == "doc1"


class TestHybridSearchEngineBM25Search:
    """Tests for _bm25_search method."""

    @pytest.mark.asyncio
    async def test_bm25_search_basic(self):
        """Test basic BM25 search."""
        mock_bm25 = MagicMock()
        mock_result = MagicMock()
        mock_result.doc_id = "doc1"
        mock_result.score = 15.0
        mock_result.title = "Title"
        mock_result.content = "Content"
        mock_result.metadata = {}
        mock_bm25.retrieve = MagicMock(return_value=[mock_result])

        engine = HybridSearchEngine(bm25_retriever=mock_bm25)
        results = await engine._bm25_search("test query", limit=10)

        assert len(results) == 1
        assert results[0]["doc_id"] == "doc1"

    @pytest.mark.asyncio
    async def test_bm25_search_no_retriever(self):
        """Test BM25 search without retriever returns empty."""
        engine = HybridSearchEngine(bm25_retriever=None)
        results = await engine._bm25_search("test query", limit=10)

        assert results == []

    @pytest.mark.asyncio
    async def test_bm25_search_handles_error(self):
        """Test BM25 search handles errors gracefully."""
        mock_bm25 = MagicMock()
        mock_bm25.retrieve = MagicMock(side_effect=Exception("BM25 failed"))

        engine = HybridSearchEngine(bm25_retriever=mock_bm25)
        results = await engine._bm25_search("test query", limit=10)

        assert results == []


class TestHybridSearchEngineToHybridResults:
    """Tests for _to_hybrid_results method."""

    def test_to_hybrid_results_basic(self):
        """Test conversion to HybridSearchResult objects."""
        engine = HybridSearchEngine()

        results = [
            {
                "doc_id": "doc1",
                "rrf_score": 0.9,
                "title": "Title 1",
                "content": "Content 1",
                "vector_rank": 1,
                "bm25_rank": None,
            },
        ]

        hybrid_results = engine._to_hybrid_results(results)

        assert len(hybrid_results) == 1
        assert isinstance(hybrid_results[0], HybridSearchResult)
        assert hybrid_results[0].doc_id == "doc1"
        assert hybrid_results[0].score == 0.9

    def test_to_hybrid_results_prefers_rerank_score(self):
        """Test that rerank_score is preferred over rrf_score."""
        engine = HybridSearchEngine()

        results = [
            {
                "doc_id": "doc1",
                "rrf_score": 0.5,
                "rerank_score": 0.95,
                "title": "Title",
                "content": "Content",
            },
        ]

        hybrid_results = engine._to_hybrid_results(results)

        assert hybrid_results[0].score == 0.95

    def test_to_hybrid_results_empty(self):
        """Test conversion with empty results."""
        engine = HybridSearchEngine()

        hybrid_results = engine._to_hybrid_results([])

        assert hybrid_results == []


class TestHybridSearchEngineVectorOnlySearch:
    """Tests for _vector_only_search method."""

    @pytest.mark.asyncio
    async def test_vector_only_search(self):
        """Test vector-only fallback search."""
        mock_repo = MagicMock()
        mock_repo.find_similar = AsyncMock(
            return_value=[ArticleSearchResultView(article_id="doc1", similarity=0.9)]
        )

        engine = HybridSearchEngine(vector_repo=mock_repo)
        results = await engine._vector_only_search("test", [0.1] * 768, limit=10)

        assert len(results) == 1
        assert results[0].doc_id == "doc1"
        assert results[0].source == "vector"

    @pytest.mark.asyncio
    async def test_vector_only_no_embedding(self):
        """Test vector-only search without embedding."""
        engine = HybridSearchEngine(vector_repo=MagicMock())

        results = await engine._vector_only_search("test", None, limit=10)

        assert results == []

    @pytest.mark.asyncio
    async def test_vector_only_no_repo(self):
        """Test vector-only search without repo."""
        engine = HybridSearchEngine(vector_repo=None)

        results = await engine._vector_only_search("test", [0.1] * 768, limit=10)

        assert results == []


class TestHybridSearchConfigExtended:
    """Extended tests for HybridSearchConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = HybridSearchConfig()

        assert config.hybrid_enabled is True
        assert config.rerank_enabled is True
        assert config.rerank_model == "tiny"
        assert config.mmr_enabled is True
        assert config.mmr_lambda == 0.7
        assert config.vector_weight == 1.0
        assert config.bm25_weight == 1.0
        assert config.graph_weight == 1.0
        assert config.rrf_k == 60
        assert config.top_k == 10
        assert config.temporal_decay_enabled is False
        assert config.temporal_decay_half_life_days == 30.0

    def test_custom_config(self):
        """Test custom configuration values."""
        config = HybridSearchConfig(
            hybrid_enabled=False,
            rerank_enabled=False,
            mmr_enabled=True,
            temporal_decay_enabled=True,
            temporal_decay_half_life_days=60.0,
        )

        assert config.hybrid_enabled is False
        assert config.mmr_enabled is True
        assert config.temporal_decay_enabled is True
        assert config.temporal_decay_half_life_days == 60.0


class TestHybridSearchResultExtended:
    """Extended tests for HybridSearchResult."""

    def test_result_creation(self):
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

    def test_result_defaults(self):
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
        assert result.publish_time is None
        assert result.temporal_decay_multiplier is None
        assert result.metadata == {}


class TestHybridSearchEngineSetConfig:
    """Tests for set_config method."""

    def test_set_config(self):
        """Test updating configuration."""
        engine = HybridSearchEngine()

        new_config = HybridSearchConfig(hybrid_enabled=False, rerank_enabled=False)
        engine.set_config(new_config)

        assert engine._config.hybrid_enabled is False
        assert engine._config.rerank_enabled is False


class TestHybridSearchEngineStats:
    """Tests for get_stats method."""

    def test_get_stats_with_components(self):
        """Test getting engine statistics with all components."""
        mock_bm25 = MagicMock()
        mock_bm25.get_document_count = MagicMock(return_value=100)
        mock_reranker = MagicMock()
        mock_reranker.is_available = MagicMock(return_value=True)

        engine = HybridSearchEngine(
            bm25_retriever=mock_bm25,
            reranker=mock_reranker,
        )

        stats = engine.get_stats()

        assert stats["hybrid_enabled"] is True
        assert stats["rerank_enabled"] is True
        assert stats["bm25_available"] is True
        assert stats["bm25_doc_count"] == 100
        assert stats["reranker_available"] is True

    def test_get_stats_without_components(self):
        """Test getting engine statistics without components."""
        engine = HybridSearchEngine()

        stats = engine.get_stats()

        assert stats["bm25_available"] is False
        assert stats["bm25_doc_count"] == 0
        assert stats["reranker_available"] is False
