# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for processing EntityExtractorNode."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.llm.output_validator import EntityExtractorOutput
from core.llm.types import CallPoint
from modules.ingestion.domain.models import ArticleRaw
from modules.processing.nodes.entity_extractor import EntityExtractorNode
from modules.processing.pipeline.state import PipelineState


@pytest.fixture
def sample_raw():
    """Create sample raw article."""
    return ArticleRaw(
        url="https://example.com/tech-news",
        title="OpenAI and Microsoft Announce Partnership",
        body="OpenAI and Microsoft have announced a major partnership deal. "
        "The agreement involves GPT-4 integration into Azure services. "
        "CEO Satya Nadella expressed enthusiasm about the collaboration.",
        source="tech_news",
        publish_time=datetime.now(UTC),
        source_host="example.com",
    )


@pytest.fixture
def mock_llm():
    """Mock LLM client."""
    return AsyncMock()


@pytest.fixture
def mock_budget():
    """Mock token budget manager."""
    budget = MagicMock()
    budget.truncate = lambda text, call_point: text
    return budget


@pytest.fixture
def mock_prompt_loader():
    """Mock prompt loader."""
    loader = MagicMock()
    loader.get = MagicMock(return_value="Entity extractor prompt")
    loader.get_version = MagicMock(return_value="3.2.0")
    return loader


@pytest.fixture
def mock_spacy():
    """Mock spaCy extractor."""
    return MagicMock()


@pytest.fixture
def mock_vector_repo():
    """Mock vector repository."""
    return AsyncMock()


class TestEntityExtractorNodeBasic:
    """Basic functionality tests for EntityExtractorNode."""

    @pytest.mark.asyncio
    async def test_extract_entities_successful(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_spacy, mock_vector_repo, sample_raw
    ):
        """Test successful entity extraction with all phases."""
        # Mock spaCy extraction
        mock_entity = MagicMock()
        mock_entity.name = "OpenAI"
        mock_entity.type = "ORG"
        mock_entity.label = "ORG"
        mock_spacy.extract = MagicMock(return_value=[mock_entity])

        # Mock batch embedding
        mock_llm.embed = AsyncMock(return_value=[[0.1] * 1536])

        # Mock LLM call
        mock_llm.call_at = AsyncMock(
            return_value=EntityExtractorOutput(
                entities=[{"name": "OpenAI", "type": "ORG", "description": "AI company"}],
                relations=[],
            )
        )

        node = EntityExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            spacy=mock_spacy,
            vector_repo=mock_vector_repo,
        )
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        # Verify entities and relations are set
        assert "entities" in result
        assert "relations" in result
        assert len(result["entities"]) == 1
        assert result["entities"][0]["name"] == "OpenAI"

    @pytest.mark.asyncio
    async def test_extract_sets_prompt_version(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_spacy, sample_raw
    ):
        """Test that entity extractor records prompt version."""
        mock_spacy.extract = MagicMock(return_value=[])
        mock_llm.call_at = AsyncMock(return_value=EntityExtractorOutput(entities=[], relations=[]))

        node = EntityExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            spacy=mock_spacy,
        )
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        assert "prompt_versions" in result
        assert result["prompt_versions"]["entity_extractor"] == "3.2.0"

    @pytest.mark.asyncio
    async def test_extract_calls_llm_with_correct_params(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_spacy, sample_raw
    ):
        """Test that entity extractor calls LLM with correct parameters."""
        mock_entity = MagicMock()
        mock_entity.name = "Microsoft"
        mock_entity.type = "ORG"
        mock_entity.label = "ORG"
        mock_spacy.extract = MagicMock(return_value=[mock_entity])

        mock_llm.embed = AsyncMock(return_value=[[0.1] * 1536])
        mock_llm.call_at = AsyncMock(return_value=EntityExtractorOutput(entities=[], relations=[]))

        node = EntityExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            spacy=mock_spacy,
        )
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        await node.execute(state)

        # Verify LLM was called with correct CallPoint
        mock_llm.call_at.assert_called_once()
        call_args = mock_llm.call_at.call_args
        assert call_args[0][0] == CallPoint.ENTITY_EXTRACTOR

        # Verify input data
        input_data = call_args[0][1]
        assert "body" in input_data
        assert "spacy_entities" in input_data
        assert len(input_data["spacy_entities"]) == 1


class TestEntityExtractorNodeEdgeCases:
    """Edge case tests for EntityExtractorNode."""

    @pytest.mark.asyncio
    async def test_extract_skips_terminal_state(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_spacy, sample_raw
    ):
        """Test that entity extractor skips terminal articles."""
        node = EntityExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            spacy=mock_spacy,
        )
        state = PipelineState(raw=sample_raw)
        state["terminal"] = True
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        # Should return state unchanged
        assert "entities" not in result
        assert "relations" not in result
        mock_spacy.extract.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_skips_merged_articles(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_spacy, sample_raw
    ):
        """Test that entity extractor skips merged articles."""
        node = EntityExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            spacy=mock_spacy,
        )
        state = PipelineState(raw=sample_raw)
        state["is_merged"] = True
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        assert "entities" not in result
        mock_spacy.extract.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_with_no_spacy_entities(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_spacy, sample_raw
    ):
        """Test entity extraction with no spaCy entities found."""
        mock_spacy.extract = MagicMock(return_value=[])
        mock_llm.call_at = AsyncMock(
            return_value=EntityExtractorOutput(
                entities=[{"name": "Implicit Entity", "type": "MISC"}],
                relations=[],
            )
        )

        node = EntityExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            spacy=mock_spacy,
        )
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        # LLM should still be called
        assert len(result["entities"]) == 1
        # Batch embed should not be called with empty list
        mock_llm.embed.assert_not_called()


class TestEntityExtractorNodeErrorHandling:
    """Error handling tests for EntityExtractorNode."""

    @pytest.mark.asyncio
    async def test_extract_handles_spacy_error(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_spacy, sample_raw
    ):
        """Test that entity extractor handles spaCy errors gracefully."""
        mock_spacy.extract = MagicMock(side_effect=Exception("spaCy model not found"))
        mock_llm.call_at = AsyncMock(return_value=EntityExtractorOutput(entities=[], relations=[]))

        node = EntityExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            spacy=mock_spacy,
        )
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        # Should use empty list and continue
        assert result["entities"] == []
        assert result["relations"] == []

    @pytest.mark.asyncio
    async def test_extract_handles_llm_error(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_spacy, sample_raw
    ):
        """Test that entity extractor handles LLM errors gracefully."""
        mock_spacy.extract = MagicMock(return_value=[])
        mock_llm.call_at = AsyncMock(side_effect=Exception("LLM service unavailable"))

        node = EntityExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            spacy=mock_spacy,
        )
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        # Should use empty lists
        assert result["entities"] == []
        assert result["relations"] == []

    @pytest.mark.asyncio
    async def test_extract_handles_embedding_error(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_spacy, sample_raw
    ):
        """Test that entity extractor handles embedding errors."""
        mock_entity = MagicMock()
        mock_entity.name = "Test"
        mock_entity.type = "ORG"
        mock_entity.label = "ORG"
        mock_spacy.extract = MagicMock(return_value=[mock_entity])

        mock_llm.embed = AsyncMock(side_effect=Exception("Embedding failed"))
        mock_llm.call_at = AsyncMock(
            return_value=EntityExtractorOutput(
                entities=[{"name": "Test", "type": "ORG"}],
                relations=[],
            )
        )

        node = EntityExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            spacy=mock_spacy,
        )
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        # Should continue without embeddings
        assert len(result["entities"]) == 1
        assert "embedding" not in result["entities"][0]

    @pytest.mark.asyncio
    async def test_extract_handles_vector_repo_error(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_spacy, mock_vector_repo, sample_raw
    ):
        """Test that entity extractor handles vector repository errors."""
        mock_entity = MagicMock()
        mock_entity.name = "Test"
        mock_entity.type = "ORG"
        mock_entity.label = "ORG"
        mock_spacy.extract = MagicMock(return_value=[mock_entity])

        mock_llm.embed = AsyncMock(return_value=[[0.1] * 1536])
        mock_vector_repo.upsert_entity_vectors = AsyncMock(
            side_effect=Exception("Vector DB connection failed")
        )
        mock_llm.call_at = AsyncMock(
            return_value=EntityExtractorOutput(
                entities=[{"name": "Test", "type": "ORG"}],
                relations=[],
            )
        )

        node = EntityExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            spacy=mock_spacy,
            vector_repo=mock_vector_repo,
        )
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        # Should continue without vector storage
        assert len(result["entities"]) == 1


class TestEntityExtractorNodeIntegration:
    """Integration tests for EntityExtractorNode."""

    @pytest.mark.asyncio
    async def test_extract_with_embeddings_attached(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_spacy, sample_raw
    ):
        """Test that embeddings are attached to entities."""
        mock_entity = MagicMock()
        mock_entity.name = "OpenAI"
        mock_entity.type = "ORG"
        mock_entity.label = "ORG"
        mock_spacy.extract = MagicMock(return_value=[mock_entity])

        mock_llm.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
        mock_llm.call_at = AsyncMock(
            return_value=EntityExtractorOutput(
                entities=[{"name": "OpenAI", "type": "ORG", "description": "AI company"}],
                relations=[],
            )
        )

        node = EntityExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            spacy=mock_spacy,
        )
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        # Verify embedding is attached
        assert "embedding" in result["entities"][0]
        assert result["entities"][0]["embedding"] == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_extract_with_multiple_entities(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_spacy, sample_raw
    ):
        """Test extraction with multiple entities."""
        mock_entity1 = MagicMock()
        mock_entity1.name = "OpenAI"
        mock_entity1.type = "ORG"
        mock_entity1.label = "ORG"

        mock_entity2 = MagicMock()
        mock_entity2.name = "Microsoft"
        mock_entity2.type = "ORG"
        mock_entity2.label = "ORG"

        mock_spacy.extract = MagicMock(return_value=[mock_entity1, mock_entity2])

        mock_llm.embed = AsyncMock(return_value=[[0.1] * 1536, [0.2] * 1536])
        mock_llm.call_at = AsyncMock(
            return_value=EntityExtractorOutput(
                entities=[
                    {"name": "OpenAI", "type": "ORG"},
                    {"name": "Microsoft", "type": "ORG"},
                ],
                relations=[{"source": "OpenAI", "target": "Microsoft", "type": "partnership"}],
            )
        )

        node = EntityExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            spacy=mock_spacy,
        )
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        assert len(result["entities"]) == 2
        assert len(result["relations"]) == 1
        assert result["relations"][0]["source"] == "OpenAI"

    @pytest.mark.asyncio
    async def test_extract_runs_spacy_in_executor(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_spacy, sample_raw
    ):
        """Test that spaCy extraction runs in executor (non-blocking)."""
        mock_spacy.extract = MagicMock(return_value=[])
        mock_llm.call_at = AsyncMock(return_value=EntityExtractorOutput(entities=[], relations=[]))

        node = EntityExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            spacy=mock_spacy,
        )
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        await node.execute(state)

        # Verify spaCy.extract was called
        mock_spacy.extract.assert_called_once()
        # It should be called with body and language
        call_args = mock_spacy.extract.call_args
        assert call_args[0][0] == sample_raw.body


class TestEntityExtractorNodeWithRelationTypeNormalizer:
    """Tests for EntityExtractorNode with relation type normalizer."""

    @pytest.mark.asyncio
    async def test_with_relation_type_normalizer_success(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_spacy, sample_raw
    ):
        """Test entity extraction with relation type normalizer."""
        mock_spacy.extract = MagicMock(return_value=[])
        mock_llm.call_at = AsyncMock(return_value=EntityExtractorOutput(entities=[], relations=[]))

        # Mock relation type normalizer
        mock_normalizer = AsyncMock()
        mock_relation_type = MagicMock()
        mock_relation_type.name = "任职于"
        mock_relation_type.description = "某人在某组织担任职务"
        mock_normalizer.get_all_active = AsyncMock(return_value=[mock_relation_type])

        node = EntityExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            spacy=mock_spacy,
            relation_type_normalizer=mock_normalizer,
        )
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        # Verify normalizer was called
        mock_normalizer.get_all_active.assert_called_once()
        assert "entities" in result

    @pytest.mark.asyncio
    async def test_relation_type_normalizer_error_fallback(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_spacy, sample_raw
    ):
        """Test fallback when relation type normalizer fails."""
        mock_spacy.extract = MagicMock(return_value=[])
        mock_llm.call_at = AsyncMock(return_value=EntityExtractorOutput(entities=[], relations=[]))

        # Mock relation type normalizer that fails
        mock_normalizer = AsyncMock()
        mock_normalizer.get_all_active = AsyncMock(side_effect=Exception("DB error"))

        node = EntityExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            spacy=mock_spacy,
            relation_type_normalizer=mock_normalizer,
        )
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        # Should use default relation types
        assert "entities" in result


class TestEntityExtractorNodeArticleTaskId:
    """Tests for article_id and task_id propagation."""

    @pytest.mark.asyncio
    async def test_article_id_propagated_to_llm(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_spacy, sample_raw
    ):
        """Test that article_id is passed to LLM call."""
        mock_spacy.extract = MagicMock(return_value=[])
        mock_llm.call_at = AsyncMock(return_value=EntityExtractorOutput(entities=[], relations=[]))

        node = EntityExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            spacy=mock_spacy,
        )
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}
        state["article_id"] = "test-article-123"
        state["task_id"] = "test-task-456"

        await node.execute(state)

        call_args = mock_llm.call_at.call_args
        input_data = call_args[0][1]
        assert input_data["article_id"] == "test-article-123"
        assert input_data["task_id"] == "test-task-456"
