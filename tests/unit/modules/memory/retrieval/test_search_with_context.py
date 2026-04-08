# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for MemoryIntegrationService search_with_context method."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.memory.integration.memory_service import (
    MemoryIntegrationService,
    MemoryServiceConfig,
)


class MockEmbeddingService:
    """Mock embedding service for tests."""

    async def embed(self, text: str) -> list[float]:
        return [0.0] * 384


class TestSearchWithContext:
    """Tests for search_with_context method."""

    @pytest.mark.asyncio
    async def test_search_with_context_raises_without_entity_repo(
        self,
        mock_neo4j_pool,
        mock_llm_client,
        mock_redis,
    ) -> None:
        """Test that search_with_context raises error without entity_repo."""
        # Create mock intent classifier
        mock_intent_classifier = MagicMock()
        mock_intent_classifier.classify = AsyncMock()
        mock_intent_classifier.classify.return_value = MagicMock(intent=MagicMock(value="open"))

        service = MemoryIntegrationService(
            graph_pool=mock_neo4j_pool,
            llm_client=mock_llm_client,
            cache=mock_redis,
            embedding_service=MockEmbeddingService(),
            intent_classifier=mock_intent_classifier,
            config=MemoryServiceConfig(),
            vector_repo=None,
            entity_repo=None,  # Not provided
        )

        # Should raise RuntimeError when calling search_with_context
        with pytest.raises(RuntimeError, match="entity_repo to be injected"):
            await service.search_with_context("test query")

    @pytest.mark.asyncio
    async def test_search_with_context_works_with_entity_repo(
        self,
        mock_neo4j_pool,
        mock_llm_client,
        mock_redis,
    ) -> None:
        """Test that search_with_context works when entity_repo is provided."""
        # Create mock intent classifier
        mock_intent_classifier = MagicMock()
        mock_intent_classifier.classify = AsyncMock()
        mock_intent_classifier.classify.return_value = MagicMock(intent=MagicMock(value="open"))

        # Create mock entity repo with required protocol methods
        mock_entity_repo = MagicMock()
        mock_entity_repo.get_entity_neighborhood = AsyncMock(return_value=None)
        mock_entity_repo.link_entities = AsyncMock(return_value=0)

        service = MemoryIntegrationService(
            graph_pool=mock_neo4j_pool,
            llm_client=mock_llm_client,
            cache=mock_redis,
            embedding_service=MockEmbeddingService(),
            intent_classifier=mock_intent_classifier,
            config=MemoryServiceConfig(),
            vector_repo=None,
            entity_repo=mock_entity_repo,
        )

        # Mock the response builder's build method
        service._response_builder.build = AsyncMock(
            return_value={
                "results": [{"id": "1", "content": "test", "score": 0.9}],
                "synthesis": None,
                "entities": [],
            }
        )

        # Should not raise
        result = await service.search_with_context("test query")
        assert "results" in result
