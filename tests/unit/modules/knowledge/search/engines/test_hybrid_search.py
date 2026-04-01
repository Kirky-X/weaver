# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for HybridSearchEngine (knowledge module)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.knowledge.search.engines.hybrid_search import (
    HybridSearchConfig,
    HybridSearchEngine,
    HybridSearchResult,
)


class TestHybridSearchConfig:
    """Tests for HybridSearchConfig."""

    def test_defaults(self) -> None:
        config = HybridSearchConfig()
        assert config.hybrid_enabled is True
        assert config.rerank_enabled is True
        assert config.mmr_enabled is False
        assert config.rrf_k == 60
        assert config.top_k == 10


class TestHybridSearchEngineInit:
    """Tests for initialization."""

    def test_default_init(self) -> None:
        engine = HybridSearchEngine()
        assert engine._vector_repo is None
        assert engine._bm25_retriever is None

    def test_with_components(self) -> None:
        mock_vector = MagicMock()
        mock_bm25 = MagicMock()
        mock_reranker = MagicMock()
        mock_mmr = MagicMock()

        engine = HybridSearchEngine(
            vector_repo=mock_vector,
            bm25_retriever=mock_bm25,
            reranker=mock_reranker,
            mmr_reranker=mock_mmr,
        )
        assert engine._vector_repo is mock_vector
        assert engine._bm25_retriever is mock_bm25


class TestHybridSearchEngineSearch:
    """Tests for search method."""

    @pytest.mark.asyncio
    async def test_hybrid_disabled_falls_back_to_vector(self) -> None:
        """Disabled hybrid uses vector-only search."""
        config = HybridSearchConfig(hybrid_enabled=False)
        mock_vector = AsyncMock()
        mock_vector.find_similar = AsyncMock(return_value=[{"id": "doc1", "score": 0.9}])

        engine = HybridSearchEngine(vector_repo=mock_vector, config=config)
        results = await engine.search("test", embedding=[0.1, 0.2])

        assert len(results) == 1
        assert isinstance(results[0], HybridSearchResult)

    @pytest.mark.asyncio
    async def test_hybrid_disabled_no_embedding(self) -> None:
        """No embedding with hybrid disabled returns empty."""
        config = HybridSearchConfig(hybrid_enabled=False)
        mock_vector = MagicMock()

        engine = HybridSearchEngine(vector_repo=mock_vector, config=config)
        results = await engine.search("test")
        assert results == []

    @pytest.mark.asyncio
    async def test_hybrid_enabled_parallel_retrieve(self) -> None:
        """Hybrid enabled performs parallel retrieval and fusion."""
        mock_vector = AsyncMock()
        mock_vector.find_similar = AsyncMock(
            return_value=[
                {"id": "d1", "score": 0.9},
                {"id": "d2", "score": 0.8},
            ]
        )
        mock_bm25 = MagicMock()
        mock_bm25.retrieve.return_value = [
            MagicMock(doc_id="d2", score=5.0),
            MagicMock(doc_id="d3", score=3.0),
        ]

        engine = HybridSearchEngine(
            vector_repo=mock_vector,
            bm25_retriever=mock_bm25,
            config=HybridSearchConfig(),
        )
        results = await engine.search("test", embedding=[0.1], limit=5)

        assert len(results) > 0
        assert all(isinstance(r, HybridSearchResult) for r in results)

    @pytest.mark.asyncio
    async def test_hybrid_with_reranker(self) -> None:
        """Reranker is applied when enabled."""
        mock_reranker = MagicMock()
        mock_reranker.rerank.return_value = [
            {"id": "d1", "doc_id": "d1", "rrf_score": 0.05, "rerank_score": 0.95},
        ]

        config = HybridSearchConfig(rerank_enabled=True)
        engine = HybridSearchEngine(reranker=mock_reranker, config=config)

        # Test _rerank_results directly
        results = [{"doc_id": "d1", "rrf_score": 0.05}]
        reranked = engine._rerank_results("test", results)
        assert len(reranked) == 1

    @pytest.mark.asyncio
    async def test_empty_results(self) -> None:
        """No sources returns empty results."""
        engine = HybridSearchEngine(config=HybridSearchConfig())
        results = await engine.search("test", embedding=None)
        assert results == []


class TestFuseResults:
    """Tests for _fuse_results."""

    def test_fuse_both_sources(self) -> None:
        engine = HybridSearchEngine()
        vector = [("d1", 0.9), ("d2", 0.8)]
        bm25 = [("d2", 5.0), ("d3", 3.0)]
        fused = engine._fuse_results(vector, bm25)
        assert len(fused) == 3
        assert all("doc_id" in r for r in fused)

    def test_fuse_vector_only(self) -> None:
        engine = HybridSearchEngine()
        vector = [("d1", 0.9)]
        fused = engine._fuse_results(vector, [])
        assert len(fused) == 1

    def test_fuse_empty(self) -> None:
        engine = HybridSearchEngine()
        fused = engine._fuse_results([], [])
        assert fused == []


class TestSetConfig:
    """Tests for set_config."""

    def test_update_config(self) -> None:
        engine = HybridSearchEngine()
        new_config = HybridSearchConfig(mmr_enabled=True)
        engine.set_config(new_config)
        assert engine._config.mmr_enabled is True


class TestGetStats:
    """Tests for get_stats."""

    def test_stats_no_components(self) -> None:
        engine = HybridSearchEngine()
        stats = engine.get_stats()
        assert stats["hybrid_enabled"] is True
        assert stats["bm25_available"] is False
        assert stats["bm25_doc_count"] == 0

    def test_stats_with_bm25(self) -> None:
        mock_bm25 = MagicMock()
        mock_bm25.get_document_count.return_value = 42
        engine = HybridSearchEngine(bm25_retriever=mock_bm25)
        stats = engine.get_stats()
        assert stats["bm25_available"] is True
        assert stats["bm25_doc_count"] == 42


class TestToHybridResults:
    """Tests for _to_hybrid_results."""

    def test_conversion(self) -> None:
        engine = HybridSearchEngine()
        internal = [{"doc_id": "d1", "rrf_score": 0.05, "title": "Test"}]
        results = engine._to_hybrid_results(internal)

        assert len(results) == 1
        assert results[0].doc_id == "d1"
        assert results[0].source == "hybrid"
