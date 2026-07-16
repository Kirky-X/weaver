# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for SynapticIngestionService (Fast Path)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.memory.core.event_node import EventNode
from modules.memory.evolution.fast_path import SynapticIngestionService


class TestFastPathIngest:
    """Tests for SynapticIngestionService.ingest()."""

    @pytest.fixture
    def mock_temporal_repo(self):
        repo = MagicMock()
        repo.append_to_chain = AsyncMock(return_value=True)
        return repo

    @pytest.fixture
    def mock_vector_repo(self):
        repo = MagicMock()
        repo.upsert_event_embedding = AsyncMock(return_value=True)
        return repo

    @pytest.fixture
    def mock_entity_repo(self):
        repo = MagicMock()
        repo.link_entities = AsyncMock(return_value=2)
        return repo

    @pytest.fixture
    def mock_queue(self):
        queue = MagicMock()
        queue.enqueue = AsyncMock(return_value=True)
        return queue

    @pytest.fixture
    def pipeline_state(self):
        return {
            "article_id": "article-123",
            "cleaned": {
                "title": "Test Article",
                "content": "Test content for ingestion",
            },
            "vectors": {
                "content": [0.1] * 384,
            },
            "entities": [
                {"name": "EntityA", "type": "ORG"},
                {"name": "EntityB", "type": "PERSON"},
            ],
        }

    @pytest.mark.asyncio
    async def test_ingest_basic(
        self, mock_temporal_repo, mock_vector_repo, mock_entity_repo, mock_queue, pipeline_state
    ):
        service = SynapticIngestionService(
            temporal_repo=mock_temporal_repo,
            vector_repo=mock_vector_repo,
            entity_repo=mock_entity_repo,
            consolidation_queue=mock_queue,
        )

        result = await service.ingest(pipeline_state)

        assert result is not None
        assert isinstance(result, EventNode)
        assert result.id == "article-123"

    @pytest.mark.asyncio
    async def test_ingest_appends_to_temporal_chain(
        self, mock_temporal_repo, mock_vector_repo, mock_entity_repo, mock_queue, pipeline_state
    ):
        service = SynapticIngestionService(
            temporal_repo=mock_temporal_repo,
            vector_repo=mock_vector_repo,
            entity_repo=mock_entity_repo,
            consolidation_queue=mock_queue,
        )

        await service.ingest(pipeline_state)

        mock_temporal_repo.append_to_chain.assert_called_once()

    @pytest.mark.asyncio
    async def test_ingest_indexes_embedding(
        self, mock_temporal_repo, mock_vector_repo, mock_entity_repo, mock_queue, pipeline_state
    ):
        service = SynapticIngestionService(
            temporal_repo=mock_temporal_repo,
            vector_repo=mock_vector_repo,
            entity_repo=mock_entity_repo,
            consolidation_queue=mock_queue,
        )

        result = await service.ingest(pipeline_state)

        mock_vector_repo.upsert_event_embedding.assert_called_once()
        call_args = mock_vector_repo.upsert_event_embedding.call_args
        assert call_args[0][0] == result
        assert call_args[0][1] == "Qwen3-Embedding-0.6B"

    @pytest.mark.asyncio
    async def test_ingest_links_entities(
        self, mock_temporal_repo, mock_vector_repo, mock_entity_repo, mock_queue, pipeline_state
    ):
        service = SynapticIngestionService(
            temporal_repo=mock_temporal_repo,
            vector_repo=mock_vector_repo,
            entity_repo=mock_entity_repo,
            consolidation_queue=mock_queue,
        )

        result = await service.ingest(pipeline_state)

        mock_entity_repo.link_entities.assert_called_once()
        call_args = mock_entity_repo.link_entities.call_args
        assert call_args[0][0] == result
        assert call_args[0][1] == pipeline_state["entities"]

    @pytest.mark.asyncio
    async def test_ingest_triggers_slow_path(
        self, mock_temporal_repo, mock_vector_repo, mock_entity_repo, mock_queue, pipeline_state
    ):
        service = SynapticIngestionService(
            temporal_repo=mock_temporal_repo,
            vector_repo=mock_vector_repo,
            entity_repo=mock_entity_repo,
            consolidation_queue=mock_queue,
        )

        result = await service.ingest(pipeline_state)

        mock_queue.enqueue.assert_called_once_with(result.id)

    @pytest.mark.asyncio
    async def test_ingest_without_vector_repo(
        self, mock_temporal_repo, mock_entity_repo, mock_queue, pipeline_state
    ):
        service = SynapticIngestionService(
            temporal_repo=mock_temporal_repo,
            vector_repo=None,
            entity_repo=mock_entity_repo,
            consolidation_queue=mock_queue,
        )

        result = await service.ingest(pipeline_state)

        assert result is not None

    @pytest.mark.asyncio
    async def test_ingest_without_entity_repo(
        self, mock_temporal_repo, mock_vector_repo, mock_queue, pipeline_state
    ):
        service = SynapticIngestionService(
            temporal_repo=mock_temporal_repo,
            vector_repo=mock_vector_repo,
            entity_repo=None,
            consolidation_queue=mock_queue,
        )

        result = await service.ingest(pipeline_state)

        assert result is not None

    @pytest.mark.asyncio
    async def test_ingest_without_queue(
        self, mock_temporal_repo, mock_vector_repo, mock_entity_repo, pipeline_state
    ):
        service = SynapticIngestionService(
            temporal_repo=mock_temporal_repo,
            vector_repo=mock_vector_repo,
            entity_repo=mock_entity_repo,
            consolidation_queue=None,
        )

        result = await service.ingest(pipeline_state)

        assert result is not None

    @pytest.mark.asyncio
    async def test_ingest_without_embedding_skips_vector(
        self, mock_temporal_repo, mock_vector_repo, mock_entity_repo, mock_queue
    ):
        state = {
            "article_id": "no-embed",
            "cleaned": {"title": "Test", "content": "Content"},
        }

        service = SynapticIngestionService(
            temporal_repo=mock_temporal_repo,
            vector_repo=mock_vector_repo,
            entity_repo=mock_entity_repo,
            consolidation_queue=mock_queue,
        )

        result = await service.ingest(state)

        mock_vector_repo.upsert_event_embedding.assert_not_called()

    @pytest.mark.asyncio
    async def test_ingest_without_entities_skips_linking(
        self, mock_temporal_repo, mock_vector_repo, mock_entity_repo, mock_queue
    ):
        state = {
            "article_id": "no-entities",
            "cleaned": {"title": "Test", "content": "Content"},
            "vectors": {"content": [0.1] * 384},
        }

        service = SynapticIngestionService(
            temporal_repo=mock_temporal_repo,
            vector_repo=mock_vector_repo,
            entity_repo=mock_entity_repo,
            consolidation_queue=mock_queue,
        )

        result = await service.ingest(state)

        mock_entity_repo.link_entities.assert_not_called()

    @pytest.mark.asyncio
    async def test_ingest_temporal_chain_failure(
        self, mock_temporal_repo, mock_vector_repo, mock_entity_repo, mock_queue, pipeline_state
    ):
        mock_temporal_repo.append_to_chain = AsyncMock(side_effect=Exception("DB error"))

        service = SynapticIngestionService(
            temporal_repo=mock_temporal_repo,
            vector_repo=mock_vector_repo,
            entity_repo=mock_entity_repo,
            consolidation_queue=mock_queue,
        )

        result = await service.ingest(pipeline_state)

        assert result is None

    @pytest.mark.asyncio
    async def test_ingest_custom_embedding_model(
        self, mock_temporal_repo, mock_vector_repo, mock_entity_repo, mock_queue, pipeline_state
    ):
        service = SynapticIngestionService(
            temporal_repo=mock_temporal_repo,
            vector_repo=mock_vector_repo,
            entity_repo=mock_entity_repo,
            consolidation_queue=mock_queue,
            embedding_model="custom-model",
        )

        result = await service.ingest(pipeline_state)

        call_args = mock_vector_repo.upsert_event_embedding.call_args
        assert call_args[0][1] == "custom-model"

    @pytest.mark.asyncio
    async def test_ingest_empty_state(
        self, mock_temporal_repo, mock_vector_repo, mock_entity_repo, mock_queue
    ):
        service = SynapticIngestionService(
            temporal_repo=mock_temporal_repo,
            vector_repo=mock_vector_repo,
            entity_repo=mock_entity_repo,
            consolidation_queue=mock_queue,
        )

        result = await service.ingest({})

        assert result is not None
        assert result.id == ""

    @pytest.mark.asyncio
    async def test_ingest_entities_empty_list_skips_linking(
        self, mock_temporal_repo, mock_vector_repo, mock_entity_repo, mock_queue
    ):
        state = {
            "article_id": "empty-entities",
            "cleaned": {"title": "Test", "content": "Content"},
            "entities": [],
        }

        service = SynapticIngestionService(
            temporal_repo=mock_temporal_repo,
            vector_repo=mock_vector_repo,
            entity_repo=mock_entity_repo,
            consolidation_queue=mock_queue,
        )

        await service.ingest(state)

        mock_entity_repo.link_entities.assert_not_called()
