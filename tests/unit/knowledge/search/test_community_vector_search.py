# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for community vector search integration in DeepGraphRAG.

Covers:
- Vector search returns relevant communities
- No results fallback to text search
- Community vector index priority over article vectors
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.models.shared import ArticleSearchResultView, CommunitySearchResultView
from modules.knowledge.search.engines.deep_graph_rag import (
    DeepGraphRAGConfig,
    DeepGraphRAGEngine,
)


def _make_engine(
    vector_repo: MagicMock | None = None,
    community_vector_repo: MagicMock | None = None,
    community_repo: MagicMock | None = None,
    graph_repo: MagicMock | None = None,
    llm_client: MagicMock | None = None,
) -> DeepGraphRAGEngine:
    """Create a test DeepGraphRAGEngine with mocks."""
    return DeepGraphRAGEngine(
        vector_repo=vector_repo or MagicMock(),
        graph_repo=graph_repo or MagicMock(),
        community_repo=community_repo or MagicMock(),
        llm_client=llm_client or MagicMock(),
        community_vector_repo=community_vector_repo,
        config=DeepGraphRAGConfig(),
    )


class TestCommunityVectorSearch:
    """Test community vector search integration."""

    @pytest.mark.asyncio
    async def test_vector_search_returns_communities(self):
        """Vector search should return relevant communities."""
        # Mock community vector repo
        community_vector_repo = AsyncMock()
        community_vector_repo.find_similar_communities.return_value = [
            CommunitySearchResultView(community_id="comm1", score=0.95, title="Community 1"),
            CommunitySearchResultView(community_id="comm2", score=0.85, title="Community 2"),
        ]

        # Mock LLM client for embedding
        llm_client = AsyncMock()
        llm_client.embed_default.return_value = [[0.1] * 1024]

        engine = _make_engine(
            community_vector_repo=community_vector_repo,
            llm_client=llm_client,
        )

        # Call _community_filter
        result = await engine._community_filter(query="test query", top_k=5)

        # Verify community vector repo was called
        community_vector_repo.find_similar_communities.assert_called_once()
        assert len(result) == 2
        assert result[0]["id"] == "comm1"
        assert result[0]["score"] == 0.95

    @pytest.mark.asyncio
    async def test_no_results_fallback_to_text_search(self):
        """When vector search returns empty, fallback to text search."""
        # Mock community vector repo with empty results
        community_vector_repo = AsyncMock()
        community_vector_repo.find_similar_communities.return_value = []

        # Mock vector repo with empty results
        vector_repo = AsyncMock()
        vector_repo.find_similar.return_value = []

        # Mock community repo for text fallback
        community_repo = AsyncMock()
        community_repo.search_by_text.return_value = [
            {"id": "comm1", "score": 0.5, "title": "Community 1"},
        ]

        # Mock LLM client for embedding
        llm_client = AsyncMock()
        llm_client.embed_default.return_value = [[0.1] * 1024]

        engine = _make_engine(
            vector_repo=vector_repo,
            community_vector_repo=community_vector_repo,
            community_repo=community_repo,
            llm_client=llm_client,
        )

        # Call _community_filter
        result = await engine._community_filter(query="test query", top_k=5)

        # Verify fallback to text search
        community_repo.search_by_text.assert_called_once_with("test query")
        assert len(result) == 1
        assert result[0]["id"] == "comm1"

    @pytest.mark.asyncio
    async def test_community_vector_priority_over_article_vectors(self):
        """Community vector index should be used when available."""
        # Mock community vector repo
        community_vector_repo = AsyncMock()
        community_vector_repo.find_similar_communities.return_value = [
            CommunitySearchResultView(community_id="comm1", score=0.95, title="Community 1"),
        ]

        # Mock article vector repo (should not be called)
        vector_repo = AsyncMock()
        vector_repo.find_similar.return_value = [
            ArticleSearchResultView(article_id="article1", similarity=0.8),
        ]

        # Mock LLM client for embedding
        llm_client = AsyncMock()
        llm_client.embed_default.return_value = [[0.1] * 1024]

        engine = _make_engine(
            vector_repo=vector_repo,
            community_vector_repo=community_vector_repo,
            llm_client=llm_client,
        )

        # Call _community_filter
        result = await engine._community_filter(query="test query", top_k=5)

        # Verify community vector repo was used, not article vector repo
        community_vector_repo.find_similar_communities.assert_called_once()
        vector_repo.find_similar.assert_not_called()
        assert len(result) == 1
        assert result[0]["id"] == "comm1"

    @pytest.mark.asyncio
    async def test_no_community_vector_repo_fallback(self):
        """When community_vector_repo is None, fallback to article vector repo."""
        # Mock article vector repo
        vector_repo = AsyncMock()
        vector_repo.find_similar.return_value = [
            ArticleSearchResultView(article_id="article1", similarity=0.8),
        ]

        # Mock LLM client for embedding
        llm_client = AsyncMock()
        llm_client.embed_default.return_value = [[0.1] * 1024]

        engine = _make_engine(
            vector_repo=vector_repo,
            community_vector_repo=None,  # No community vector repo
            llm_client=llm_client,
        )

        # Call _community_filter
        result = await engine._community_filter(query="test query", top_k=5)

        # Verify article vector repo was used
        vector_repo.find_similar.assert_called_once()
        assert len(result) == 1
        assert result[0]["id"] == "article1"

    @pytest.mark.asyncio
    async def test_embedding_failure_fallback(self):
        """When LLM embedding fails, use pre-computed embedding."""
        # Mock community vector repo
        community_vector_repo = AsyncMock()
        community_vector_repo.find_similar_communities.return_value = [
            CommunitySearchResultView(community_id="comm1", score=0.95, title="Community 1"),
        ]

        # Mock LLM client that fails
        llm_client = AsyncMock()
        llm_client.embed_default.side_effect = Exception("LLM unavailable")

        engine = _make_engine(
            community_vector_repo=community_vector_repo,
            llm_client=llm_client,
        )

        # Call _community_filter with pre-computed embedding
        pre_computed = [0.2] * 1024
        result = await engine._community_filter(
            query="test query",
            embedding=pre_computed,
            top_k=5,
        )

        # Verify community vector repo was called with pre-computed embedding
        community_vector_repo.find_similar_communities.assert_called_once()
        call_args = community_vector_repo.find_similar_communities.call_args
        assert call_args[0][0] == pre_computed  # First arg is embedding
        assert len(result) == 1
