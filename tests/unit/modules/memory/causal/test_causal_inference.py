# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for CausalInferenceService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.memory.causal.causal_inference import (
    RELATION_CATEGORY_MAP,
    CausalInference,
    CausalInferenceService,
    InferenceConfig,
    RelationCategory,
)
from modules.memory.core.graph_types import CausalRelationType


class TestCausalInferenceMainFlow:
    """Tests for infer_and_create_causal_edges main flow."""

    @pytest.fixture
    def mock_pool(self):
        pool = MagicMock()
        pool.database_type = "ladybug"
        pool.execute_query = AsyncMock(return_value=[])
        return pool

    @pytest.fixture
    def mock_llm(self):
        return MagicMock()

    @pytest.fixture
    def mock_causal_repo(self):
        repo = MagicMock()
        repo.add_causal_edge = AsyncMock(return_value=True)
        return repo

    @pytest.mark.asyncio
    async def test_no_relations_returns_empty_stats(self, mock_pool, mock_llm, mock_causal_repo):
        service = CausalInferenceService(
            pool=mock_pool,
            llm_client=mock_llm,
            causal_repo=mock_causal_repo,
        )

        stats = await service.infer_and_create_causal_edges()

        assert stats["edges_created"] == 0
        assert stats["edges_filtered"] == 0
        assert stats["errors"] == 0
        assert stats["relations_analyzed"] == 0

    @pytest.mark.asyncio
    async def test_successful_edge_creation(self, mock_pool, mock_llm, mock_causal_repo):
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "source": "公司A",
                    "target": "公司B",
                    "relation_type": "INVESTS_IN",
                }
            ]
        )
        mock_llm.call_at = AsyncMock(
            return_value='[{"source": "公司A", "target": "公司B", "type": "CAUSES", "confidence": 0.8, "evidence": "投资导致控制"}]'
        )

        service = CausalInferenceService(
            pool=mock_pool,
            llm_client=mock_llm,
            causal_repo=mock_causal_repo,
        )
        service._get_or_create_event_node = AsyncMock(side_effect=["event-A", "event-B"])

        stats = await service.infer_and_create_causal_edges()

        assert stats["edges_created"] == 1
        assert stats["relations_analyzed"] == 1

    @pytest.mark.asyncio
    async def test_below_threshold_filtered(self, mock_pool, mock_llm, mock_causal_repo):
        config = InferenceConfig(confidence_threshold=0.7)
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {"source": "A", "target": "B", "relation_type": "INVESTS_IN"},
            ]
        )
        mock_llm.call_at = AsyncMock(
            return_value='[{"source": "A", "target": "B", "type": "CAUSES", "confidence": 0.3, "evidence": "low confidence"}]'
        )

        service = CausalInferenceService(
            pool=mock_pool,
            llm_client=mock_llm,
            causal_repo=mock_causal_repo,
            config=config,
        )
        service._get_or_create_event_node = AsyncMock(return_value="event-1")

        stats = await service.infer_and_create_causal_edges()

        assert stats["edges_filtered"] == 1
        assert stats["edges_created"] == 0

    @pytest.mark.asyncio
    async def test_event_node_creation_failure(self, mock_pool, mock_llm, mock_causal_repo):
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {"source": "A", "target": "B", "relation_type": "INVESTS_IN"},
            ]
        )
        mock_llm.call_at = AsyncMock(
            return_value='[{"source": "A", "target": "B", "type": "CAUSES", "confidence": 0.8, "evidence": "test"}]'
        )

        service = CausalInferenceService(
            pool=mock_pool,
            llm_client=mock_llm,
            causal_repo=mock_causal_repo,
        )
        service._get_or_create_event_node = AsyncMock(return_value=None)

        stats = await service.infer_and_create_causal_edges()

        assert stats["errors"] == 1

    @pytest.mark.asyncio
    async def test_causal_repo_add_failure(self, mock_pool, mock_llm, mock_causal_repo):
        mock_causal_repo.add_causal_edge = AsyncMock(return_value=False)
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {"source": "A", "target": "B", "relation_type": "INVESTS_IN"},
            ]
        )
        mock_llm.call_at = AsyncMock(
            return_value='[{"source": "A", "target": "B", "type": "CAUSES", "confidence": 0.8, "evidence": "test"}]'
        )

        service = CausalInferenceService(
            pool=mock_pool,
            llm_client=mock_llm,
            causal_repo=mock_causal_repo,
        )
        service._get_or_create_event_node = AsyncMock(side_effect=["event-A", "event-B"])

        stats = await service.infer_and_create_causal_edges()

        assert stats["errors"] == 1
        assert stats["edges_created"] == 0

    @pytest.mark.asyncio
    async def test_with_entity_filter(self, mock_pool, mock_llm, mock_causal_repo):
        service = CausalInferenceService(
            pool=mock_pool,
            llm_client=mock_llm,
            causal_repo=mock_causal_repo,
        )

        stats = await service.infer_and_create_causal_edges(
            entity_names=["公司A"],
            relation_types=["INVESTS_IN"],
        )

        mock_pool.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_multiple_inferences(self, mock_pool, mock_llm, mock_causal_repo):
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {"source": "A", "target": "B", "relation_type": "INVESTS_IN"},
                {"source": "C", "target": "D", "relation_type": "ACQUIRES"},
            ]
        )
        mock_llm.call_at = AsyncMock(
            return_value='[{"source": "A", "target": "B", "type": "CAUSES", "confidence": 0.8, "evidence": "e1"}, {"source": "C", "target": "D", "type": "ENABLES", "confidence": 0.7, "evidence": "e2"}]'
        )

        service = CausalInferenceService(
            pool=mock_pool,
            llm_client=mock_llm,
            causal_repo=mock_causal_repo,
        )
        service._get_or_create_event_node = AsyncMock(side_effect=["eA", "eB", "eC", "eD"])

        stats = await service.infer_and_create_causal_edges()

        assert stats["edges_created"] == 2
        assert stats["relations_analyzed"] == 2


class TestCausalInferenceBatchInfer:
    """Tests for _batch_infer_causality and _infer_batch."""

    @pytest.fixture
    def service(self):
        pool = MagicMock()
        pool.database_type = "ladybug"
        llm = MagicMock()
        repo = MagicMock()
        return CausalInferenceService(pool=pool, llm_client=llm, causal_repo=repo)

    @pytest.mark.asyncio
    async def test_batch_infer_empty(self, service):
        result = await service._batch_infer_causality([])
        assert result == []

    @pytest.mark.asyncio
    async def test_batch_infer_single_batch(self, service):
        service._llm.call_at = AsyncMock(
            return_value='[{"source": "A", "target": "B", "type": "CAUSES", "confidence": 0.8, "evidence": "test"}]'
        )

        relations = [{"source": "A", "target": "B", "relation_type": "INVESTS_IN"}]
        result = await service._batch_infer_causality(relations)

        assert len(result) == 1
        assert result[0].source_entity == "A"
        assert result[0].causal_type == CausalRelationType.CAUSES

    @pytest.mark.asyncio
    async def test_batch_infer_multiple_batches(self, service):
        config = InferenceConfig(batch_size=2)
        service._config = config
        service._llm.call_at = AsyncMock(
            return_value='[{"source": "A", "target": "B", "type": "CAUSES", "confidence": 0.8, "evidence": "e1"}]'
        )

        relations = [
            {"source": "A", "target": "B", "relation_type": "INVESTS_IN"},
            {"source": "C", "target": "D", "relation_type": "ACQUIRES"},
            {"source": "E", "target": "F", "relation_type": "合资"},
        ]
        result = await service._batch_infer_causality(relations)

        assert service._llm.call_at.call_count == 2

    @pytest.mark.asyncio
    async def test_infer_batch_invalid_json(self, service):
        service._llm.call_at = AsyncMock(return_value="not valid json")

        relations = [{"source": "A", "target": "B", "relation_type": "INVESTS_IN"}]
        result = await service._infer_batch(relations)

        assert result == []

    @pytest.mark.asyncio
    async def test_infer_batch_invalid_causal_type(self, service):
        service._llm.call_at = AsyncMock(
            return_value='[{"source": "A", "target": "B", "type": "INVALID", "confidence": 0.8, "evidence": "test"}]'
        )

        relations = [{"source": "A", "target": "B", "relation_type": "INVESTS_IN"}]
        result = await service._infer_batch(relations)

        assert result == []

    @pytest.mark.asyncio
    async def test_infer_batch_no_matching_relation(self, service):
        service._llm.call_at = AsyncMock(
            return_value='[{"source": "X", "target": "Y", "type": "CAUSES", "confidence": 0.8, "evidence": "test"}]'
        )

        relations = [{"source": "A", "target": "B", "relation_type": "INVESTS_IN"}]
        result = await service._infer_batch(relations)

        assert result == []

    @pytest.mark.asyncio
    async def test_infer_batch_llm_exception(self, service):
        service._llm.call_at = AsyncMock(side_effect=Exception("LLM down"))

        relations = [{"source": "A", "target": "B", "relation_type": "INVESTS_IN"}]
        result = await service._infer_batch(relations)

        assert result == []

    @pytest.mark.asyncio
    async def test_batch_infer_continues_on_error(self, service):
        config = InferenceConfig(batch_size=1)
        service._config = config
        call_count = 0

        async def mock_call_at(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("First batch fails")
            return '[{"source": "C", "target": "D", "type": "ENABLES", "confidence": 0.7, "evidence": "test"}]'

        service._llm.call_at = AsyncMock(side_effect=mock_call_at)

        relations = [
            {"source": "A", "target": "B", "relation_type": "INVESTS_IN"},
            {"source": "C", "target": "D", "relation_type": "ACQUIRES"},
        ]
        result = await service._batch_infer_causality(relations)

        assert len(result) == 1
        assert result[0].source_entity == "C"


class TestCausalInferenceGetEntityRelations:
    """Tests for _get_entity_relations."""

    @pytest.mark.asyncio
    async def test_ladybug_query(self):
        pool = MagicMock()
        pool.database_type = "ladybug"
        pool.execute_query = AsyncMock(
            return_value=[
                {"source": "A", "target": "B", "relation_type": "INVESTS_IN", "properties": {}}
            ]
        )

        service = CausalInferenceService(
            pool=pool,
            llm_client=MagicMock(),
            causal_repo=MagicMock(),
        )

        relations = await service._get_entity_relations(None, None)
        assert len(relations) == 1

    @pytest.mark.asyncio
    async def test_neo4j_query(self):
        pool = MagicMock()
        pool.database_type = "neo4j"
        pool.execute_query = AsyncMock(
            return_value=[
                {"source": "A", "target": "B", "relation_type": "INVESTS_IN", "description": "test"}
            ]
        )

        service = CausalInferenceService(
            pool=pool,
            llm_client=MagicMock(),
            causal_repo=MagicMock(),
        )

        relations = await service._get_entity_relations(None, None)
        assert len(relations) == 1

    @pytest.mark.asyncio
    async def test_query_exception(self):
        pool = MagicMock()
        pool.database_type = "ladybug"
        pool.execute_query = AsyncMock(side_effect=Exception("DB error"))

        service = CausalInferenceService(
            pool=pool,
            llm_client=MagicMock(),
            causal_repo=MagicMock(),
        )

        relations = await service._get_entity_relations(None, None)
        assert relations == []


class TestCausalInferenceEventNode:
    """Tests for _get_or_create_event_node."""

    @pytest.mark.asyncio
    async def test_existing_event_id(self):
        pool = MagicMock()
        pool.database_type = "ladybug"

        service = CausalInferenceService(
            pool=pool,
            llm_client=MagicMock(),
            causal_repo=MagicMock(),
        )

        result = await service._get_or_create_event_node(
            entity_name="A",
            existing_event_id="event-123",
        )

        assert result == "event-123"

    @pytest.mark.asyncio
    async def test_find_existing_event_node(self):
        pool = MagicMock()
        pool.database_type = "ladybug"
        pool.execute_query = AsyncMock(return_value=[{"event_id": "existing-event"}])

        service = CausalInferenceService(
            pool=pool,
            llm_client=MagicMock(),
            causal_repo=MagicMock(),
        )

        result = await service._get_or_create_event_node(entity_name="A")

        assert result == "existing-event"

    @pytest.mark.asyncio
    async def test_create_event_node(self):
        pool = MagicMock()
        pool.database_type = "ladybug"
        # First call: no existing event; second call: entity data; third call: create
        pool.execute_query = AsyncMock(
            side_effect=[
                [],  # No existing event
                [{"entity_id": "ent-1", "description": "test entity", "created_at": 1700000000}],
                [{"id": "ent-1"}],  # Create result
            ]
        )

        service = CausalInferenceService(
            pool=pool,
            llm_client=MagicMock(),
            causal_repo=MagicMock(),
        )

        result = await service._get_or_create_event_node(entity_name="A")

        assert result == "ent-1"

    @pytest.mark.asyncio
    async def test_event_node_creation_failure(self):
        pool = MagicMock()
        pool.database_type = "ladybug"
        pool.execute_query = AsyncMock(
            side_effect=[
                [],  # No existing event
                [],  # No entity data
            ]
        )

        service = CausalInferenceService(
            pool=pool,
            llm_client=MagicMock(),
            causal_repo=MagicMock(),
        )

        result = await service._get_or_create_event_node(entity_name="A")

        assert result is None

    @pytest.mark.asyncio
    async def test_query_exception_returns_none(self):
        pool = MagicMock()
        pool.database_type = "ladybug"
        pool.execute_query = AsyncMock(side_effect=Exception("DB error"))

        service = CausalInferenceService(
            pool=pool,
            llm_client=MagicMock(),
            causal_repo=MagicMock(),
        )

        result = await service._get_or_create_event_node(entity_name="A")

        assert result is None
