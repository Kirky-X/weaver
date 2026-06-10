# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for DeepGraphRAGEngine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.knowledge.search.engines.deep_graph_rag import (
    DeepGraphRAGConfig,
    DeepGraphRAGEngine,
    DeepGraphRAGResult,
)


class TestDeepGraphRAGConfig:
    """Tests for DeepGraphRAGConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = DeepGraphRAGConfig()
        assert config.community_top_k == 5
        assert config.min_degree == 1
        assert config.sim_weight == 0.4
        assert config.community_weight == 0.3
        assert config.centrality_weight == 0.2
        assert config.recency_weight == 0.1
        assert config.max_depth == 3

    def test_custom_config(self):
        """Test custom configuration values."""
        config = DeepGraphRAGConfig(
            community_top_k=10,
            min_degree=2,
            sim_weight=0.5,
            community_weight=0.2,
            centrality_weight=0.2,
            recency_weight=0.1,
        )
        assert config.community_top_k == 10
        assert config.min_degree == 2


class TestStage1CommunityFiltering:
    """Tests for Stage 1: Community filtering."""

    @pytest.fixture
    def mock_vector_repo(self):
        """Create a mock vector repository."""
        repo = MagicMock()
        repo.find_similar = AsyncMock(
            return_value=[
                {"id": "comm_1", "score": 0.95, "name": "AI Research"},
                {"id": "comm_2", "score": 0.88, "name": "NLP"},
                {"id": "comm_3", "score": 0.82, "name": "Computer Vision"},
                {"id": "comm_4", "score": 0.75, "name": "Robotics"},
                {"id": "comm_5", "score": 0.70, "name": "Data Science"},
            ]
        )
        return repo

    @pytest.fixture
    def engine(self, mock_vector_repo):
        """Create a DeepGraphRAGEngine with mock dependencies."""
        return DeepGraphRAGEngine(vector_repo=mock_vector_repo)

    @pytest.mark.asyncio
    async def test_community_filtering_top_k(self, engine, mock_vector_repo):
        """Test community vector search returns top_k=5 communities."""
        embedding = [0.1] * 768
        communities = await engine._community_filter(embedding, top_k=5)

        mock_vector_repo.find_similar.assert_called_once()
        assert len(communities) <= 5

    @pytest.mark.asyncio
    async def test_community_filtering_preserves_scores(self, engine, mock_vector_repo):
        """Test community filtering preserves similarity scores."""
        embedding = [0.1] * 768
        communities = await engine._community_filter(embedding, top_k=5)

        for c in communities:
            assert "id" in c
            assert "score" in c

    @pytest.mark.asyncio
    async def test_community_filtering_no_repo(self):
        """Test community filtering with no vector repo returns empty."""
        engine = DeepGraphRAGEngine(vector_repo=None)
        communities = await engine._community_filter([0.1] * 768, top_k=5)
        assert communities == []

    @pytest.mark.asyncio
    async def test_community_filtering_handles_error(self):
        """Test community filtering handles repo errors gracefully."""
        mock_repo = MagicMock()
        mock_repo.find_similar = AsyncMock(side_effect=Exception("DB error"))
        engine = DeepGraphRAGEngine(vector_repo=mock_repo)
        communities = await engine._community_filter([0.1] * 768, top_k=5)
        assert communities == []


class TestStage2EntityRefinement:
    """Tests for Stage 2: Entity refinement."""

    @pytest.fixture
    def engine(self):
        """Create a DeepGraphRAGEngine with mock dependencies."""
        return DeepGraphRAGEngine(vector_repo=MagicMock())

    def test_entity_refinement_filters_isolated(self, engine):
        """Test filter isolated entities by degree."""
        entities = [
            {"id": "e1", "name": "Entity1", "degree": 5},
            {"id": "e2", "name": "Entity2", "degree": 0},
            {"id": "e3", "name": "Entity3", "degree": 3},
            {"id": "e4", "name": "Entity4", "degree": 1},
        ]
        config = DeepGraphRAGConfig(min_degree=1)
        engine._config = config

        refined = engine._entity_refine(entities)

        # e2 with degree=0 should be filtered
        assert all(e["degree"] >= 1 for e in refined)
        assert len(refined) == 3

    def test_entity_refinement_keeps_all_connected(self, engine):
        """Test entity refinement keeps all entities above min_degree."""
        entities = [
            {"id": "e1", "name": "Entity1", "degree": 5},
            {"id": "e2", "name": "Entity2", "degree": 3},
        ]
        config = DeepGraphRAGConfig(min_degree=1)
        engine._config = config

        refined = engine._entity_refine(entities)
        assert len(refined) == 2

    def test_entity_refinement_all_isolated(self, engine):
        """Test entity refinement with all isolated entities."""
        entities = [
            {"id": "e1", "name": "Entity1", "degree": 0},
            {"id": "e2", "name": "Entity2", "degree": 0},
        ]
        config = DeepGraphRAGConfig(min_degree=1)
        engine._config = config

        refined = engine._entity_refine(entities)
        assert refined == []

    def test_entity_refinement_empty_input(self, engine):
        """Test entity refinement with empty input."""
        refined = engine._entity_refine([])
        assert refined == []


class TestStage3EntityLevelSearch:
    """Tests for Stage 3: Entity-level search with fusion scoring."""

    @pytest.fixture
    def engine(self):
        """Create a DeepGraphRAGEngine with mock dependencies."""
        return DeepGraphRAGEngine(vector_repo=MagicMock())

    def test_entity_level_search_fusion_score(self, engine):
        """Test vector similarity × centrality × community relevance scoring."""
        entities = [
            {
                "id": "e1",
                "name": "Entity1",
                "similarity": 0.9,
                "community_relevance": 0.8,
                "centrality": 0.7,
                "recency": 0.6,
            },
        ]

        scored = engine._entity_search(entities)

        # Fusion score = 0.4*sim + 0.3*community + 0.2*centrality + 0.1*recency
        expected = 0.4 * 0.9 + 0.3 * 0.8 + 0.2 * 0.7 + 0.1 * 0.6
        assert abs(scored[0]["fusion_score"] - expected) < 1e-6

    def test_entity_level_search_sorted_by_fusion(self, engine):
        """Test entity-level search sorts by fusion score descending."""
        entities = [
            {
                "id": "e1",
                "similarity": 0.5,
                "community_relevance": 0.5,
                "centrality": 0.5,
                "recency": 0.5,
            },
            {
                "id": "e2",
                "similarity": 0.9,
                "community_relevance": 0.9,
                "centrality": 0.9,
                "recency": 0.9,
            },
        ]

        scored = engine._entity_search(entities)

        assert scored[0]["id"] == "e2"
        assert scored[0]["fusion_score"] > scored[1]["fusion_score"]

    def test_entity_level_search_empty(self, engine):
        """Test entity-level search with empty input."""
        scored = engine._entity_search([])
        assert scored == []


class TestFusionScoreFormula:
    """Tests for the fusion score formula."""

    @pytest.fixture
    def engine(self):
        """Create a DeepGraphRAGEngine with default config."""
        return DeepGraphRAGEngine(vector_repo=MagicMock())

    def test_fusion_score_formula(self, engine):
        """Test fusion score: 0.4*sim + 0.3*community + 0.2*centrality + 0.1*recency."""
        entity = {
            "id": "e1",
            "similarity": 1.0,
            "community_relevance": 1.0,
            "centrality": 1.0,
            "recency": 1.0,
        }

        scored = engine._entity_search([entity])
        # All weights sum to 1.0, all scores are 1.0
        assert abs(scored[0]["fusion_score"] - 1.0) < 1e-6

    def test_fusion_score_zero_inputs(self, engine):
        """Test fusion score with all zero inputs."""
        entity = {
            "id": "e1",
            "similarity": 0.0,
            "community_relevance": 0.0,
            "centrality": 0.0,
            "recency": 0.0,
        }

        scored = engine._entity_search([entity])
        assert scored[0]["fusion_score"] == 0.0

    def test_fusion_score_partial_inputs(self, engine):
        """Test fusion score with partial inputs."""
        entity = {
            "id": "e1",
            "similarity": 0.5,
            "community_relevance": 0.0,
            "centrality": 0.0,
            "recency": 0.0,
        }

        scored = engine._entity_search([entity])
        expected = 0.4 * 0.5
        assert abs(scored[0]["fusion_score"] - expected) < 1e-6

    def test_fusion_score_custom_weights(self):
        """Test fusion score with custom weights."""
        config = DeepGraphRAGConfig(
            sim_weight=0.5,
            community_weight=0.2,
            centrality_weight=0.2,
            recency_weight=0.1,
        )
        engine = DeepGraphRAGEngine(vector_repo=MagicMock(), config=config)

        entity = {
            "id": "e1",
            "similarity": 0.8,
            "community_relevance": 0.6,
            "centrality": 0.4,
            "recency": 0.2,
        }

        scored = engine._entity_search([entity])
        expected = 0.5 * 0.8 + 0.2 * 0.6 + 0.2 * 0.4 + 0.1 * 0.2
        assert abs(scored[0]["fusion_score"] - expected) < 1e-6


class TestBeamRerankIntegration:
    """Tests for BeamSearchReranker integration with DeepGraphRAGEngine."""

    @pytest.fixture
    def mock_reranker(self):
        """Create a mock BeamSearchReranker."""
        reranker = MagicMock()
        reranker.rerank = MagicMock(
            return_value=[
                {"id": "e1", "fusion_score": 0.95, "content": "Entity 1"},
                {"id": "e2", "fusion_score": 0.85, "content": "Entity 2"},
            ]
        )
        return reranker

    @pytest.fixture
    def engine(self, mock_reranker):
        """Create a DeepGraphRAGEngine with mock reranker."""
        return DeepGraphRAGEngine(
            vector_repo=MagicMock(),
            reranker=mock_reranker,
        )

    @pytest.mark.asyncio
    async def test_beam_rerank_called(self, engine, mock_reranker):
        """Test that beam reranker is called during search."""
        mock_repo = MagicMock()
        mock_repo.find_similar = AsyncMock(return_value=[{"id": "comm_1", "score": 0.9}])
        engine._vector_repo = mock_repo

        # Mock internal methods to isolate reranker test
        with (
            patch.object(engine, "_community_filter", return_value=[{"id": "c1", "score": 0.9}]),
            patch.object(engine, "_entity_refine", return_value=[{"id": "e1", "degree": 3}]),
            patch.object(
                engine,
                "_entity_search",
                return_value=[{"id": "e1", "fusion_score": 0.8}],
            ),
        ):
            result = await engine.search("test query", embedding=[0.1] * 768)

        mock_reranker.rerank.assert_called_once()

    @pytest.mark.asyncio
    async def test_beam_rerank_not_called_without_reranker(self):
        """Test that beam reranker is not called when not provided."""
        engine = DeepGraphRAGEngine(vector_repo=MagicMock(), reranker=None)

        with (
            patch.object(engine, "_community_filter", return_value=[{"id": "c1", "score": 0.9}]),
            patch.object(engine, "_entity_refine", return_value=[{"id": "e1", "degree": 3}]),
            patch.object(
                engine,
                "_entity_search",
                return_value=[{"id": "e1", "fusion_score": 0.8}],
            ),
        ):
            result = await engine.search("test query", embedding=[0.1] * 768)

        # Should work fine without reranker


class TestSearchReturnsStatistics:
    """Tests for search returning statistics."""

    @pytest.fixture
    def engine(self):
        """Create a DeepGraphRAGEngine with mock dependencies."""
        return DeepGraphRAGEngine(vector_repo=MagicMock())

    @pytest.mark.asyncio
    async def test_search_returns_statistics(self, engine):
        """Test search returns communities_filtered/entities_candidates/depth_reached."""
        with (
            patch.object(engine, "_community_filter", return_value=[{"id": "c1", "score": 0.9}]),
            patch.object(engine, "_entity_refine", return_value=[{"id": "e1", "degree": 3}]),
            patch.object(
                engine,
                "_entity_search",
                return_value=[{"id": "e1", "fusion_score": 0.8}],
            ),
        ):
            result = await engine.search("test query", embedding=[0.1] * 768)

        assert isinstance(result, DeepGraphRAGResult)
        assert hasattr(result, "communities_filtered")
        assert hasattr(result, "entities_candidates")
        assert hasattr(result, "depth_reached")

    @pytest.mark.asyncio
    async def test_search_statistics_values(self, engine):
        """Test search statistics reflect actual pipeline execution."""
        communities = [{"id": f"c{i}", "score": 0.9} for i in range(3)]
        entities = [{"id": f"e{i}", "degree": 2} for i in range(5)]

        with (
            patch.object(engine, "_community_filter", return_value=communities),
            patch.object(engine, "_entity_refine", return_value=entities),
            patch.object(
                engine,
                "_entity_search",
                return_value=[{"id": "e1", "fusion_score": 0.8}],
            ),
        ):
            result = await engine.search("test query", embedding=[0.1] * 768)

        assert result.communities_filtered == 3
        assert result.entities_candidates == 5

    @pytest.mark.asyncio
    async def test_search_empty_result(self, engine):
        """Test search with no communities found."""
        with patch.object(engine, "_community_filter", return_value=[]):
            result = await engine.search("test query", embedding=[0.1] * 768)

        assert result.communities_filtered == 0
        assert result.entities_candidates == 0
        assert result.entities == []


# Import patch for mocking
from unittest.mock import patch
