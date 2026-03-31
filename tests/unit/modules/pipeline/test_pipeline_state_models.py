# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for ValidatedPipelineState model validation (task 3.3.5)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from core.constants import PipelineState, ProcessingStatus
from modules.collector.models import ArticleRaw
from modules.processing.pipeline.state_models import (
    CleanedData,
    CredibilityModel,
    EntityData,
    RelationData,
    ValidatedPipelineState,
    VectorData,
)


def _make_raw(url: str = "https://example.com/test") -> ArticleRaw:
    """Create a sample raw article."""
    return ArticleRaw(
        url=url,
        title="Test Article",
        body="Test body content about technology and artificial intelligence.",
        source="test",
        publish_time=datetime.now(UTC),
        source_host="example.com",
    )


class TestCleanedDataValidation:
    """Tests for CleanedData model validation."""

    def test_valid_cleaned_data(self):
        """Test that valid cleaned data passes validation."""
        data = CleanedData(title="Test Title", body="Test body content")
        assert data.title == "Test Title"
        assert data.body == "Test body content"

    def test_title_stripped(self):
        """Test that title whitespace is stripped."""
        data = CleanedData(title="  Test Title  ", body="Body")
        assert data.title == "Test Title"

    def test_body_stripped(self):
        """Test that body whitespace is stripped."""
        data = CleanedData(title="Title", body="  Body content  ")
        assert data.body == "Body content"

    def test_title_min_length_validation(self):
        """Test that empty title fails validation."""
        with pytest.raises(ValidationError):
            CleanedData(title="", body="Body")

    def test_title_max_length_validation(self):
        """Test that title over 500 chars fails validation."""
        with pytest.raises(ValidationError):
            CleanedData(title="x" * 501, body="Body")

    def test_body_min_length_validation(self):
        """Test that empty body fails validation."""
        with pytest.raises(ValidationError):
            CleanedData(title="Title", body="")


class TestCredibilityModelValidation:
    """Tests for CredibilityModel validation."""

    def test_valid_credibility(self):
        """Test that valid credibility data passes validation."""
        cred = CredibilityModel(
            score=0.85,
            source_credibility=0.9,
            content_check=0.8,
            timeliness=0.75,
            flags=["test_flag"],
        )
        assert cred.score == 0.85
        assert cred.flags == ["test_flag"]

    def test_score_range_validation(self):
        """Test that scores must be in 0-1 range."""
        with pytest.raises(ValidationError):
            CredibilityModel(score=1.5)

        with pytest.raises(ValidationError):
            CredibilityModel(score=-0.1)

    def test_default_values(self):
        """Test that default values are set correctly."""
        cred = CredibilityModel(score=0.5)
        assert cred.source_credibility == 0.5
        assert cred.content_check == 0.5
        assert cred.timeliness == 0.5
        assert cred.flags == []


class TestEntityDataValidation:
    """Tests for EntityData validation."""

    def test_valid_entity(self):
        """Test that valid entity data passes validation."""
        entity = EntityData(name="OpenAI", type="ORG", description="AI company")
        assert entity.name == "OpenAI"
        assert entity.type == "ORG"

    def test_name_length_validation(self):
        """Test entity name length limits."""
        with pytest.raises(ValidationError):
            EntityData(name="", type="ORG")  # Empty name

        with pytest.raises(ValidationError):
            EntityData(name="x" * 201, type="ORG")  # Over 200 chars


class TestVectorDataValidation:
    """Tests for VectorData validation."""

    def test_valid_vector_data(self):
        """Test that valid vector data passes validation."""
        vectors = VectorData(
            content=[0.1, 0.2, 0.3],
            title=[0.4, 0.5, 0.6],
            model_id="text-embedding-3-large",
        )
        assert vectors.content == [0.1, 0.2, 0.3]
        assert vectors.title == [0.4, 0.5, 0.6]

    def test_default_model_id(self):
        """Test default model_id is set."""
        vectors = VectorData()
        assert vectors.model_id == "text-embedding-3-large"

    def test_optional_vectors(self):
        """Test that vectors are optional."""
        vectors = VectorData()
        assert vectors.content is None
        assert vectors.title is None


class TestValidatedPipelineState:
    """Tests for ValidatedPipelineState model."""

    def test_create_with_raw(self):
        """Test creating state with raw article."""
        raw = _make_raw()
        state = ValidatedPipelineState(raw=raw)
        assert state.raw == raw
        assert state.is_news is True  # Default
        assert state.terminal is False  # Default

    def test_create_from_dict(self):
        """Test creating state from dictionary."""
        data = {
            "is_news": True,
            "category": "tech",
            "language": "zh",
            "score": 0.85,
        }
        state = ValidatedPipelineState.from_dict(data)
        assert state.is_news is True
        assert state.category == "tech"
        assert state.score == 0.85

    def test_to_dict(self):
        """Test converting state to dictionary."""
        raw = _make_raw()
        state = ValidatedPipelineState(
            raw=raw,
            is_news=True,
            category="tech",
            score=0.75,
        )
        data = state.to_dict()
        assert data["is_news"] is True
        assert data["category"] == "tech"
        assert data["score"] == 0.75

    def test_category_validation(self):
        """Test category normalization."""
        state = ValidatedPipelineState(category="  TECH  ")
        assert state.category == "tech"

    def test_empty_category_fallback(self):
        """Test empty category falls back to 'unknown'."""
        state = ValidatedPipelineState(category="")
        assert state.category == "unknown"

    def test_score_range_validation(self):
        """Test score must be in valid range."""
        # Valid scores
        state = ValidatedPipelineState(score=0.5)
        assert state.score == 0.5

        state = ValidatedPipelineState(score=0.0)
        assert state.score == 0.0

        state = ValidatedPipelineState(score=1.0)
        assert state.score == 1.0

        # Invalid scores should raise ValidationError
        with pytest.raises(ValidationError):
            ValidatedPipelineState(score=1.5)

        with pytest.raises(ValidationError):
            ValidatedPipelineState(score=-0.5)

    def test_cleaned_data_handling(self):
        """Test handling of cleaned data."""
        raw = _make_raw()
        state = ValidatedPipelineState(raw=raw)
        state.cleaned = CleanedData(title="Test", body="Body")

        assert state.get_cleaned_title() == "Test"
        assert state.get_cleaned_body() == "Body"

    def test_cleaned_dict_handling(self):
        """Test handling of cleaned data as dict."""
        raw = _make_raw()
        state = ValidatedPipelineState(raw=raw)
        state.cleaned = {"title": "Dict Title", "body": "Dict Body"}

        assert state.get_cleaned_title() == "Dict Title"
        assert state.get_cleaned_body() == "Dict Body"

    def test_vector_data_handling(self):
        """Test handling of vector data."""
        raw = _make_raw()
        state = ValidatedPipelineState(raw=raw)
        state.vectors = VectorData(content=[0.1, 0.2], title=[0.3, 0.4])

        assert state.get_content_vector() == [0.1, 0.2]
        assert state.get_title_vector() == [0.3, 0.4]

    def test_vector_dict_handling(self):
        """Test handling of vector data as dict."""
        raw = _make_raw()
        state = ValidatedPipelineState(raw=raw)
        state.vectors = {"content": [0.5, 0.6], "title": [0.7, 0.8]}

        assert state.get_content_vector() == [0.5, 0.6]
        assert state.get_title_vector() == [0.7, 0.8]

    def test_extra_fields_allowed(self):
        """Test that extra fields are allowed."""
        raw = _make_raw()
        state = ValidatedPipelineState(
            raw=raw,
            custom_field="custom_value",
        )
        assert state.custom_field == "custom_value"  # type: ignore[attr-defined]

    def test_terminal_state(self):
        """Test terminal state handling."""
        raw = _make_raw()
        state = ValidatedPipelineState(raw=raw, terminal=True)
        assert state.terminal is True

    def test_merged_state(self):
        """Test merged article state."""
        raw = _make_raw()
        state = ValidatedPipelineState(
            raw=raw,
            is_merged=True,
            merged_into="article-123",
            merged_source_ids=["source-1", "source-2"],
        )
        assert state.is_merged is True
        assert state.merged_into == "article-123"

    def test_persist_info(self):
        """Test persistence information."""
        raw = _make_raw()
        state = ValidatedPipelineState(
            raw=raw,
            article_id="article-456",
            task_id="task-789",
            neo4j_ids=["neo4j-1", "neo4j-2"],
        )
        assert state.article_id == "article-456"
        assert state.task_id == "task-789"


class TestPipelineStage:
    """Tests for PipelineState enum (formerly PipelineStage)."""

    def test_stage_values(self):
        """Test that all expected stages exist."""
        assert PipelineState.RAW == "raw"
        assert PipelineState.CLASSIFIED == "classified"
        assert PipelineState.CLEANED == "cleaned"
        assert PipelineState.VECTORIZED == "vectorized"
        assert PipelineState.ANALYZED == "analyzed"
        assert PipelineState.CREDIBILITY_SCORED == "credibility_scored"
        assert PipelineState.ENTITY_EXTRACTED == "entity_extracted"
        assert PipelineState.PERSISTED == "persisted"
        assert PipelineState.DONE == "done"
        assert PipelineState.FAILED == "failed"

    def test_stage_is_string(self):
        """Test that stages are strings."""
        assert isinstance(PipelineState.RAW, str)


class TestPersistStatus:
    """Tests for ProcessingStatus enum (formerly PersistStatus)."""

    def test_status_values(self):
        """Test that all expected statuses exist."""
        assert ProcessingStatus.PENDING == "pending"
        assert ProcessingStatus.PROCESSING == "processing"
        assert ProcessingStatus.COMPLETED == "completed"
        assert ProcessingStatus.FAILED == "failed"
        assert ProcessingStatus.RETRY == "retry"

    def test_status_is_string(self):
        """Test that statuses are strings."""
        assert isinstance(ProcessingStatus.COMPLETED, str)


class TestStateConversionRoundTrip:
    """Tests for converting between dict and ValidatedPipelineState."""

    def test_round_trip_conversion(self):
        """Test converting to dict and back preserves data."""
        raw = _make_raw()
        original = ValidatedPipelineState(
            raw=raw,
            is_news=True,
            category="tech",
            language="zh",
            score=0.85,
            quality_score=0.75,
        )

        data = original.to_dict()
        restored = ValidatedPipelineState.from_dict(data)

        assert restored.is_news == original.is_news
        assert restored.category == original.category
        assert restored.language == original.language
        assert restored.score == original.score
        assert restored.quality_score == original.quality_score

    def test_conversion_handles_nested_models(self):
        """Test conversion handles nested Pydantic models."""
        raw = _make_raw()
        original = ValidatedPipelineState(
            raw=raw,
            credibility=CredibilityModel(score=0.9, flags=["verified"]),
        )

        data = original.to_dict()
        restored = ValidatedPipelineState.from_dict(data)

        # Credibility should be preserved as dict in round-trip
        assert restored.credibility is not None


class TestIntegrationWithExistingCode:
    """Tests for compatibility with existing pipeline code."""

    def test_state_behaves_like_dict(self):
        """Test that state can be used in dict-like contexts."""
        raw = _make_raw()
        state = ValidatedPipelineState(raw=raw)

        # Can be converted to dict
        data = state.to_dict()
        assert isinstance(data, dict)

        # Dict can be accessed
        assert "is_news" in data
        assert data["is_news"] is True

    def test_state_field_assignment(self):
        """Test field assignment after creation."""
        raw = _make_raw()
        state = ValidatedPipelineState(raw=raw)

        state.is_news = False
        state.terminal = True
        state.category = "politics"

        assert state.is_news is False
        assert state.terminal is True
        assert state.category == "politics"
