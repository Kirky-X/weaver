# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for DeepGraphRAGEngine — aligned with design spec."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.knowledge.search.engines.deep_graph_rag import (
    DeepGraphRAGConfig,
    DeepGraphRAGEngine,
    DeepGraphRAGResult,
)


class TestDeepGraphRAGConstructor:
    """Tests for constructor with full dependencies."""

    def test_constructor_accepts_all_dependencies(self):
        vector_repo = MagicMock()
        graph_repo = MagicMock()
        community_repo = MagicMock()
        llm_client = MagicMock()
        reranker = MagicMock()

        engine = DeepGraphRAGEngine(
            vector_repo=vector_repo,
            graph_repo=graph_repo,
            community_repo=community_repo,
            llm_client=llm_client,
            reranker=reranker,
        )

        assert engine._vector_repo is vector_repo
        assert engine._graph_repo is graph_repo
        assert engine._community_repo is community_repo
        assert engine._llm_client is llm_client
        assert engine._reranker is reranker

    def test_constructor_missing_graph_repo_raises(self):
        with pytest.raises(TypeError):
            DeepGraphRAGEngine(
                vector_repo=MagicMock(),
                community_repo=MagicMock(),
                llm_client=MagicMock(),
            )

    def test_constructor_missing_community_repo_raises(self):
        with pytest.raises(TypeError):
            DeepGraphRAGEngine(
                vector_repo=MagicMock(),
                graph_repo=MagicMock(),
                llm_client=MagicMock(),
            )

    def test_constructor_missing_llm_client_raises(self):
        with pytest.raises(TypeError):
            DeepGraphRAGEngine(
                vector_repo=MagicMock(),
                graph_repo=MagicMock(),
                community_repo=MagicMock(),
            )

    def test_constructor_reranker_is_optional(self):
        engine = DeepGraphRAGEngine(
            vector_repo=MagicMock(),
            graph_repo=MagicMock(),
            community_repo=MagicMock(),
            llm_client=MagicMock(),
        )
        assert engine._reranker is None


class TestStage1CommunityFilterWithLLMEmbed:
    """Tests for Stage 1: Community filter with LLM embedding."""

    @pytest.fixture
    def deps(self):
        vector_repo = MagicMock()
        vector_repo.find_similar = AsyncMock(
            return_value=[
                {"id": "comm_1", "score": 0.95, "name": "AI Research"},
            ]
        )
        graph_repo = MagicMock()
        community_repo = MagicMock()
        llm_client = MagicMock()
        llm_client.embed_default = AsyncMock(return_value=[[0.1] * 1024])
        return {
            "vector_repo": vector_repo,
            "graph_repo": graph_repo,
            "community_repo": community_repo,
            "llm_client": llm_client,
        }

    @pytest.mark.asyncio
    async def test_llm_embed_called_for_query(self, deps):
        """Stage 1 SHALL call llm_client.embed_default to get query embedding."""
        engine = DeepGraphRAGEngine(**deps)
        await engine._community_filter(query="test query")

        deps["llm_client"].embed_default.assert_called_once_with(["test query"])

    @pytest.mark.asyncio
    async def test_llm_embed_result_used_for_vector_search(self, deps):
        """Stage 1 SHALL use LLM embedding for vector search."""
        engine = DeepGraphRAGEngine(**deps)
        communities = await engine._community_filter(query="test query")

        deps["vector_repo"].find_similar.assert_called_once()
        call_args = deps["vector_repo"].find_similar.call_args
        assert call_args[0][0] == [0.1] * 1024  # LLM embedding used

    @pytest.mark.asyncio
    async def test_llm_embed_failure_falls_back_to_precomputed(self, deps):
        """When LLM embed fails, SHALL fall back to pre-computed embedding."""
        deps["llm_client"].embed_default = AsyncMock(side_effect=Exception("LLM error"))
        precomputed = [0.2] * 768

        engine = DeepGraphRAGEngine(**deps)
        communities = await engine._community_filter(query="test query", embedding=precomputed)

        deps["vector_repo"].find_similar.assert_called_once()
        call_args = deps["vector_repo"].find_similar.call_args
        assert call_args[0][0] == precomputed  # Fallback used

    @pytest.mark.asyncio
    async def test_llm_embed_failure_no_precomputed_returns_empty(self, deps):
        """When LLM embed fails and no precomputed, return empty."""
        deps["llm_client"].embed_default = AsyncMock(side_effect=Exception("LLM error"))

        engine = DeepGraphRAGEngine(**deps)
        communities = await engine._community_filter(query="test query")

        assert communities == []

    @pytest.mark.asyncio
    async def test_vector_search_empty_text_fallback(self, deps):
        """When vector search returns empty, text fallback on community title/summary."""
        deps["vector_repo"].find_similar = AsyncMock(return_value=[])
        deps["community_repo"].search_by_text = AsyncMock(
            return_value=[{"id": "comm_fb", "title": "AI", "score": 0.5}]
        )

        engine = DeepGraphRAGEngine(**deps)
        communities = await engine._community_filter(query="artificial intelligence")

        deps["community_repo"].search_by_text.assert_called_once()
        assert len(communities) == 1
        assert communities[0]["id"] == "comm_fb"


class TestStage2EntityRefineWithGraphRepo:
    """Tests for Stage 2: Entity refinement with graph database query."""

    @pytest.fixture
    def deps(self):
        vector_repo = MagicMock()
        graph_repo = MagicMock()
        community_repo = MagicMock()
        community_repo.get_community_entities = AsyncMock(
            return_value=[
                {"id": "e1", "canonical_name": "Entity1", "degree": 5, "type": "PERSON"},
                {"id": "e2", "canonical_name": "Entity2", "degree": 0, "type": "ORG"},
                {"id": "e3", "canonical_name": "Entity3", "degree": 3, "type": "GPE"},
            ]
        )
        llm_client = MagicMock()
        return {
            "vector_repo": vector_repo,
            "graph_repo": graph_repo,
            "community_repo": community_repo,
            "llm_client": llm_client,
        }

    @pytest.mark.asyncio
    async def test_entity_refine_queries_community_repo(self, deps):
        """Stage 2 SHALL query community_repo for entities."""
        engine = DeepGraphRAGEngine(**deps)
        communities = [{"id": "comm_1", "score": 0.9}]

        entities = await engine._entity_refine(communities)

        deps["community_repo"].get_community_entities.assert_called_once_with("comm_1")

    @pytest.mark.asyncio
    async def test_entity_refine_filters_by_degree(self, deps):
        """Stage 2 SHALL filter entities by degree >= min_degree."""
        engine = DeepGraphRAGEngine(**deps)
        communities = [{"id": "comm_1", "score": 0.9}]

        entities = await engine._entity_refine(communities)

        # e2 with degree=0 should be filtered
        assert all(e.get("degree", 0) >= 1 for e in entities)
        entity_names = [e["canonical_name"] for e in entities]
        assert "Entity2" not in entity_names

    @pytest.mark.asyncio
    async def test_entity_refine_multiple_communities(self, deps):
        """Stage 2 SHALL query entities for all communities."""
        deps["community_repo"].get_community_entities = AsyncMock(
            side_effect=[
                [{"id": "e1", "canonical_name": "A", "degree": 2}],
                [{"id": "e2", "canonical_name": "B", "degree": 3}],
            ]
        )
        engine = DeepGraphRAGEngine(**deps)
        communities = [{"id": "comm_1", "score": 0.9}, {"id": "comm_2", "score": 0.8}]

        entities = await engine._entity_refine(communities)

        assert deps["community_repo"].get_community_entities.call_count == 2
        assert len(entities) == 2

    @pytest.mark.asyncio
    async def test_entity_refine_community_repo_no_method(self):
        """When community_repo lacks get_community_entities, fall back to metadata."""
        community_repo = MagicMock(spec=[])  # No methods
        engine = DeepGraphRAGEngine(
            vector_repo=MagicMock(),
            graph_repo=MagicMock(),
            community_repo=community_repo,
            llm_client=MagicMock(),
        )
        communities = [
            {"id": "c1", "score": 0.9, "entities": [{"id": "e1", "degree": 2}]},
        ]

        entities = await engine._entity_refine(communities)

        assert len(entities) == 1
        assert entities[0]["id"] == "e1"


class TestStage3EntitySearchWithVectorRepo:
    """Tests for Stage 3: Entity search with vector similarity."""

    @pytest.fixture
    def deps(self):
        vector_repo = MagicMock()
        vector_repo.find_similar_entities = AsyncMock(
            return_value=[
                {"neo4j_id": "e1", "score": 0.92, "name": "Entity1"},
                {"neo4j_id": "e2", "score": 0.85, "name": "Entity2"},
            ]
        )
        graph_repo = MagicMock()
        community_repo = MagicMock()
        llm_client = MagicMock()
        return {
            "vector_repo": vector_repo,
            "graph_repo": graph_repo,
            "community_repo": community_repo,
            "llm_client": llm_client,
        }

    @pytest.mark.asyncio
    async def test_entity_search_uses_vector_repo(self, deps):
        """Stage 3 SHALL use vector_repo.find_similar_entities for similarity."""
        engine = DeepGraphRAGEngine(**deps)
        query_embedding = [0.1] * 768
        entities = [
            {"id": "e1", "canonical_name": "Entity1", "degree": 5, "embedding": [0.2] * 768},
        ]

        scored = await engine._entity_search(entities, query_embedding)

        deps["vector_repo"].find_similar_entities.assert_called()

    @pytest.mark.asyncio
    async def test_entity_search_fusion_scoring(self, deps):
        """Stage 3 SHALL compute fusion scores combining vector similarity."""
        engine = DeepGraphRAGEngine(**deps)
        query_embedding = [0.1] * 768
        entities = [
            {
                "id": "e1",
                "canonical_name": "Entity1",
                "degree": 5,
                "community_relevance": 0.8,
                "embedding": [0.2] * 768,
            },
        ]

        scored = await engine._entity_search(entities, query_embedding)

        # Should have fusion_score
        assert len(scored) > 0
        assert "fusion_score" in scored[0]

    @pytest.mark.asyncio
    async def test_entity_search_no_vector_repo_falls_back(self):
        """Without vector_repo, use in-memory fusion scoring."""
        engine = DeepGraphRAGEngine(
            vector_repo=None,
            graph_repo=MagicMock(),
            community_repo=MagicMock(),
            llm_client=MagicMock(),
        )
        entities = [
            {
                "id": "e1",
                "similarity": 0.9,
                "community_relevance": 0.8,
                "centrality": 0.7,
                "recency": 0.6,
            },
        ]

        scored = await engine._entity_search(entities, [0.1] * 768)

        expected = 0.4 * 0.9 + 0.3 * 0.8 + 0.2 * 0.7 + 0.1 * 0.6
        assert abs(scored[0]["fusion_score"] - expected) < 1e-6


class TestDeepGraphRAGConfig:
    """Tests for DeepGraphRAGConfig."""

    def test_default_config(self):
        config = DeepGraphRAGConfig()
        assert config.community_top_k == 5
        assert config.min_degree == 1
        assert config.sim_weight == 0.4
        assert config.community_weight == 0.3
        assert config.centrality_weight == 0.2
        assert config.recency_weight == 0.1
        assert config.max_depth == 3


class TestSearchEndToEnd:
    """End-to-end tests for the search pipeline."""

    @pytest.fixture
    def deps(self):
        vector_repo = MagicMock()
        vector_repo.find_similar = AsyncMock(
            return_value=[{"id": "comm_1", "score": 0.9, "name": "AI"}]
        )
        vector_repo.find_similar_entities = AsyncMock(
            return_value=[{"neo4j_id": "e1", "score": 0.88, "name": "GPT"}]
        )
        graph_repo = MagicMock()
        community_repo = MagicMock()
        community_repo.get_community_entities = AsyncMock(
            return_value=[
                {"id": "e1", "canonical_name": "GPT", "degree": 5, "type": "TECH"},
            ]
        )
        llm_client = MagicMock()
        llm_client.embed_default = AsyncMock(return_value=[[0.1] * 1024])
        return {
            "vector_repo": vector_repo,
            "graph_repo": graph_repo,
            "community_repo": community_repo,
            "llm_client": llm_client,
        }

    @pytest.mark.asyncio
    async def test_full_pipeline(self, deps):
        """Test full 3-stage pipeline."""
        engine = DeepGraphRAGEngine(**deps)
        result = await engine.search("artificial intelligence")

        assert isinstance(result, DeepGraphRAGResult)
        assert result.query == "artificial intelligence"
        assert result.communities_filtered > 0

    @pytest.mark.asyncio
    async def test_no_communities_returns_empty(self, deps):
        """Test pipeline returns empty when no communities found."""
        deps["vector_repo"].find_similar = AsyncMock(return_value=[])
        deps["community_repo"].search_by_text = AsyncMock(return_value=[])

        engine = DeepGraphRAGEngine(**deps)
        result = await engine.search("obscure query")

        assert result.entities == []
        assert result.communities_filtered == 0
