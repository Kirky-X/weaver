# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Pydantic models for pipeline state validation.

This module provides Pydantic models for type-safe pipeline state handling.
These models can be used for validation while maintaining compatibility
with the existing TypedDict-based PipelineState.

Example:
    from modules.pipeline.state_models import ValidatedPipelineState

    state = ValidatedPipelineState(raw=article_raw)
    state.cleaned = {"title": "...", "body": "..."}
"""

from __future__ import annotations

import warnings
from datetime import datetime
from typing import Any, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from core.constants import PipelineState, ProcessingStatus
from modules.collector.models import ArticleRaw

# ── Deprecated Aliases (for backward compatibility) ─────────────────────────
# These will be removed in a future version. Use core.constants instead.


def __getattr__(name: str) -> Any:
    """Provide deprecated aliases for backward compatibility."""
    if name == "PipelineStage":
        warnings.warn(
            "PipelineStage in state_models is deprecated. "
            "Use PipelineState from core.constants instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return PipelineState
    if name == "PersistStatus":
        warnings.warn(
            "PersistStatus in state_models is deprecated. "
            "Use ProcessingStatus from core.constants instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return ProcessingStatus
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class CredibilityModel(BaseModel):
    """Credibility assessment result with validation."""

    score: float = Field(ge=0.0, le=1.0, description="Final credibility score")
    source_credibility: float = Field(ge=0.0, le=1.0, default=0.5)
    content_check: float = Field(ge=0.0, le=1.0, default=0.5)
    timeliness: float = Field(ge=0.0, le=1.0, default=0.5)
    flags: list[str] = Field(default_factory=list)


class CleanedData(BaseModel):
    """Cleaned article data with validation."""

    title: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1)
    publish_time: datetime | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        """Strip whitespace from title."""
        return v.strip()

    @field_validator("body")
    @classmethod
    def validate_body(cls, v: str) -> str:
        """Strip whitespace from body."""
        return v.strip()


class VectorData(BaseModel):
    """Vector embedding data."""

    content: list[float] | None = None
    title: list[float] | None = None
    model_id: str = "text-embedding-3-large"


class EntityData(BaseModel):
    """Extracted entity data."""

    name: str = Field(min_length=1, max_length=200)
    type: str = Field(min_length=1, max_length=50)
    role: str | None = None
    description: str | None = None


class RelationData(BaseModel):
    """Entity relation data."""

    source: str
    target: str
    relation_type: str
    description: str | None = None


class ValidatedPipelineState(BaseModel):
    """Pydantic model for validated pipeline state.

    Provides type safety and validation for pipeline state data.
    Can be converted to/from dict for compatibility with existing code.
    """

    model_config = {"extra": "allow", "populate_by_name": True}

    # Input (required)
    raw: ArticleRaw | None = None

    # Classifier
    is_news: bool = True
    terminal: bool = False

    # Cleaner
    cleaned: CleanedData | dict[str, Any] | None = None
    tags: list[str] = Field(default_factory=list)
    cleaner_entities: list[dict[str, Any]] = Field(default_factory=list)

    # Categorizer
    category: str = "unknown"
    language: str = "zh"
    region: str = "unknown"

    # Vectorize
    vectors: VectorData | dict[str, Any] | None = None

    # Merger
    is_merged: bool = False
    merged_into: str | None = None
    merged_source_ids: list[str] = Field(default_factory=list)

    # Analyze
    summary_info: dict[str, Any] | None = None
    sentiment: dict[str, Any] | None = None
    score: float = Field(ge=0.0, le=1.0, default=0.5)
    quality_score: float = Field(ge=0.0, le=1.0, default=0.5)

    # Credibility
    credibility: CredibilityModel | dict[str, Any] | None = None

    # Entity extraction
    entities: list[EntityData | dict[str, Any]] = Field(default_factory=list)
    relations: list[RelationData | dict[str, Any]] = Field(default_factory=list)
    resolved_entities: list[dict[str, Any]] = Field(default_factory=list)

    # Persist
    article_id: str | None = None
    task_id: str | None = None
    neo4j_ids: list[str] = Field(default_factory=list)

    # Prompt version tracking
    prompt_versions: dict[str, str] = Field(default_factory=dict)

    # Internal tracking
    _current_stage: PipelineState = PipelineState.RAW

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        """Validate category is not empty."""
        if not v or not v.strip():
            return "unknown"
        return v.strip().lower()

    @field_validator("score", "quality_score")
    @classmethod
    def validate_scores(cls, v: float) -> float:
        """Ensure scores are in valid range."""
        return max(0.0, min(1.0, v))

    @model_validator(mode="after")
    def validate_consistency(self) -> Self:
        """Validate state consistency."""
        # Note: terminal news articles are valid (e.g., duplicates marked for skip)
        # Note: merged_into may be set later by merger node
        return self

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for compatibility with existing code."""
        return self.model_dump(exclude_none=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create from dictionary.

        Args:
            data: Dictionary containing pipeline state data.

        Returns:
            ValidatedPipelineState instance.
        """
        return cls.model_validate(data)

    def get_cleaned_title(self) -> str | None:
        """Get cleaned title safely."""
        if isinstance(self.cleaned, CleanedData):
            return self.cleaned.title
        if isinstance(self.cleaned, dict):
            return self.cleaned.get("title")
        return None

    def get_cleaned_body(self) -> str | None:
        """Get cleaned body safely."""
        if isinstance(self.cleaned, CleanedData):
            return self.cleaned.body
        if isinstance(self.cleaned, dict):
            return self.cleaned.get("body")
        return None

    def get_content_vector(self) -> list[float] | None:
        """Get content embedding vector safely."""
        if isinstance(self.vectors, VectorData):
            return self.vectors.content
        if isinstance(self.vectors, dict):
            return self.vectors.get("content")
        return None

    def get_title_vector(self) -> list[float] | None:
        """Get title embedding vector safely."""
        if isinstance(self.vectors, VectorData):
            return self.vectors.title
        if isinstance(self.vectors, dict):
            return self.vectors.get("title")
        return None
