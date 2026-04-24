# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for CausalInferenceService."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.memory.causal import (
    CausalInference,
    CausalInferenceService,
    InferenceConfig,
    RelationCategory,
)
from modules.memory.core.graph_types import CausalRelationType


class TestCausalInferenceDataclass:
    """Tests for CausalInference dataclass."""

    def test_causal_inference_creation(self):
        """Test basic CausalInference creation."""
        inference = CausalInference(
            source_entity="本田",
            target_entity="广汽集团",
            original_relation="合资",
            causal_type=CausalRelationType.ENABLES,
            confidence=0.75,
            evidence="合资促成合作",
        )
        assert inference.source_entity == "本田"
        assert inference.target_entity == "广汽集团"
        assert inference.original_relation == "合资"
        assert inference.causal_type == CausalRelationType.ENABLES
        assert inference.confidence == 0.75
        assert inference.evidence == "合资促成合作"

    def test_causal_inference_optional_event_ids(self):
        """Test CausalInference with optional event IDs."""
        inference = CausalInference(
            source_entity="EntityA",
            target_entity="EntityB",
            original_relation="INVESTS_IN",
            causal_type=CausalRelationType.CAUSES,
            confidence=0.8,
            evidence="投资导致控制",
            source_event_id="event-001",
            target_event_id="event-002",
        )
        assert inference.source_event_id == "event-001"
        assert inference.target_event_id == "event-002"


class TestInferenceConfig:
    """Tests for InferenceConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = InferenceConfig()
        assert config.batch_size == 20
        assert config.confidence_threshold == 0.6
        assert config.max_relations_per_entity == 50
        assert config.llm_timeout_seconds == 30
        assert config.enable_parallel_inference is True

    def test_custom_config(self):
        """Test custom configuration values."""
        config = InferenceConfig(
            batch_size=10,
            confidence_threshold=0.7,
            max_relations_per_entity=100,
        )
        assert config.batch_size == 10
        assert config.confidence_threshold == 0.7
        assert config.max_relations_per_entity == 100


class TestRelationCategory:
    """Tests for RelationCategory enum."""

    def test_relation_categories(self):
        """Test all relation categories exist."""
        assert RelationCategory.INVESTMENT.value == "investment"
        assert RelationCategory.PARTNERSHIP.value == "partnership"
        assert RelationCategory.ACQUISITION.value == "acquisition"
        assert RelationCategory.CONTROL.value == "control"
        assert RelationCategory.INFLUENCE.value == "influence"
        assert RelationCategory.REGULATION.value == "regulation"
        assert RelationCategory.SUPPLY.value == "supply"
        assert RelationCategory.COMPETITION.value == "competition"
        assert RelationCategory.OTHER.value == "other"

    def test_relation_category_map(self):
        """Test RELATION_CATEGORY_MAP mappings."""
        from modules.memory.causal.causal_inference import RELATION_CATEGORY_MAP

        assert RELATION_CATEGORY_MAP["INVESTS_IN"] == RelationCategory.INVESTMENT
        assert RELATION_CATEGORY_MAP["投资"] == RelationCategory.INVESTMENT
        assert RELATION_CATEGORY_MAP["合资"] == RelationCategory.PARTNERSHIP
        assert RELATION_CATEGORY_MAP["ACQUIRES"] == RelationCategory.ACQUISITION


class TestCausalInferenceServiceInit:
    """Tests for CausalInferenceService initialization."""

    def test_init_with_defaults(self):
        """Test service initialization with default config."""
        mock_pool = MagicMock()
        mock_llm = MagicMock()
        mock_repo = MagicMock()

        service = CausalInferenceService(
            pool=mock_pool,
            llm_client=mock_llm,
            causal_repo=mock_repo,
        )
        assert service._pool == mock_pool
        assert service._llm == mock_llm
        assert service._causal_repo == mock_repo
        assert service._config.batch_size == 20  # default

    def test_init_with_custom_config(self):
        """Test service initialization with custom config."""
        mock_pool = MagicMock()
        mock_llm = MagicMock()
        mock_repo = MagicMock()
        config = InferenceConfig(batch_size=5, confidence_threshold=0.8)

        service = CausalInferenceService(
            pool=mock_pool,
            llm_client=mock_llm,
            causal_repo=mock_repo,
            config=config,
        )
        assert service._config.batch_size == 5
        assert service._config.confidence_threshold == 0.8

    def test_ladybug_detection(self):
        """Test LadybugDB pool detection."""
        mock_pool = MagicMock()
        mock_pool.database_type = "ladybug"
        mock_llm = MagicMock()
        mock_repo = MagicMock()

        service = CausalInferenceService(
            pool=mock_pool,
            llm_client=mock_llm,
            causal_repo=mock_repo,
        )
        assert service._is_ladybug is True


class TestCausalInferenceServiceGetRelations:
    """Tests for _get_entity_relations method."""

    @pytest.mark.asyncio
    async def test_get_relations_ladybug(self):
        """Test getting relations from LadybugDB."""
        mock_pool = MagicMock()
        mock_pool.database_type = "ladybug"
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "source": "本田",
                    "target": "广汽集团",
                    "relation_type": "合资",
                    "properties": {},
                }
            ]
        )
        mock_llm = MagicMock()
        mock_repo = MagicMock()

        service = CausalInferenceService(
            pool=mock_pool,
            llm_client=mock_llm,
            causal_repo=mock_repo,
        )

        relations = await service._get_entity_relations(None, None)
        assert len(relations) == 1
        assert relations[0]["source"] == "本田"
        assert relations[0]["relation_type"] == "合资"

    @pytest.mark.asyncio
    async def test_get_relations_with_filter(self):
        """Test getting relations with entity filter."""
        mock_pool = MagicMock()
        mock_pool.database_type = "ladybug"
        mock_pool.execute_query = AsyncMock(return_value=[])
        mock_llm = MagicMock()
        mock_repo = MagicMock()

        service = CausalInferenceService(
            pool=mock_pool,
            llm_client=mock_llm,
            causal_repo=mock_repo,
        )

        relations = await service._get_entity_relations(
            entity_names=["本田"],
            relation_types=["合资"],
        )
        # Query was executed (empty result due to mock)
        assert mock_pool.execute_query.called


class TestCausalInferenceServiceInferBatch:
    """Tests for _infer_batch method."""

    @pytest.mark.asyncio
    async def test_infer_batch_empty_relations(self):
        """Test batch inference with empty relations."""
        mock_pool = MagicMock()
        mock_llm = MagicMock()
        mock_repo = MagicMock()

        service = CausalInferenceService(
            pool=mock_pool,
            llm_client=mock_llm,
            causal_repo=mock_repo,
        )

        result = await service._infer_batch([])
        assert result == []

    @pytest.mark.asyncio
    async def test_infer_batch_with_mock_llm(self):
        """Test batch inference with mocked LLM response."""
        mock_pool = MagicMock()
        mock_llm = MagicMock()
        mock_llm.call_at = AsyncMock(
            return_value='[{"source": "本田", "target": "广汽集团", "type": "ENABLES", "confidence": 0.75, "evidence": "合资促成合作"}]'
        )
        mock_repo = MagicMock()

        service = CausalInferenceService(
            pool=mock_pool,
            llm_client=mock_llm,
            causal_repo=mock_repo,
        )

        relations = [
            {
                "source": "本田",
                "target": "广汽集团",
                "relation_type": "合资",
            }
        ]

        result = await service._infer_batch(relations)
        assert len(result) == 1
        assert result[0].source_entity == "本田"
        assert result[0].causal_type == CausalRelationType.ENABLES
        assert result[0].confidence == 0.75


class TestCausalInferenceServiceMainFlow:
    """Tests for main infer_and_create_causal_edges flow."""

    @pytest.mark.asyncio
    async def test_infer_empty_relations(self):
        """Test inference when no relations are found."""
        mock_pool = MagicMock()
        mock_pool.database_type = "ladybug"
        mock_pool.execute_query = AsyncMock(return_value=[])
        mock_llm = MagicMock()
        mock_repo = MagicMock()

        service = CausalInferenceService(
            pool=mock_pool,
            llm_client=mock_llm,
            causal_repo=mock_repo,
        )

        stats = await service.infer_and_create_causal_edges()
        assert stats["relations_analyzed"] == 0
        assert stats["edges_created"] == 0

    @pytest.mark.asyncio
    async def test_infer_below_threshold(self):
        """Test inference filtering below confidence threshold."""
        mock_pool = MagicMock()
        mock_pool.database_type = "ladybug"
        mock_pool.execute_query = AsyncMock(
            return_value=[{"source": "A", "target": "B", "relation_type": "INVESTS_IN"}]
        )
        mock_llm = MagicMock()
        mock_llm.call_at = AsyncMock(
            return_value='[{"source": "A", "target": "B", "type": "CAUSES", "confidence": 0.3, "evidence": "test"}]'
        )
        mock_repo = MagicMock()

        config = InferenceConfig(confidence_threshold=0.6)
        service = CausalInferenceService(
            pool=mock_pool,
            llm_client=mock_llm,
            causal_repo=mock_repo,
            config=config,
        )

        # Mock event node creation
        service._get_or_create_event_node = AsyncMock(return_value="event-1")

        stats = await service.infer_and_create_causal_edges()
        assert stats["edges_filtered"] == 1  # Below threshold
        assert stats["edges_created"] == 0
