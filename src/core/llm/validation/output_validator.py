# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Structured output validation and Pydantic output models for LLM responses."""

from __future__ import annotations

from pydantic import BaseModel, Field

from core.constants import SentimentType

# ── Output Models ────────────────────────────────────────────


class ClassifierOutput(BaseModel):
    """Output model for the classifier node."""

    is_news: bool | None = None
    confidence: float = Field(ge=0, le=1)


class CleanerContent(BaseModel):
    """Content sub-model for cleaner output."""

    title: str
    subtitle: str | None = None
    summary: str | None = None
    body: str


class CleanerEntity(BaseModel):
    """Entity sub-model for cleaner output."""

    name: str
    type: str
    description: str


class CleanerOutput(BaseModel):
    """Output model for the cleaner node."""

    publish_time: str | None = None
    author: str | None = None
    content: CleanerContent
    tags: list[str] = Field(default_factory=list)
    entities: list[CleanerEntity] = Field(default_factory=list)


class CategorizerOutput(BaseModel):
    """Output model for the categorizer node."""

    category: str
    language: str
    region: str


class AnalyzeOutput(BaseModel):
    """Output model for the analyze node (summary + score + sentiment)."""

    summary: str
    event_time: str | None = None
    subjects: list[str] = Field(default_factory=list)
    key_data: list[str] = Field(default_factory=list)
    impact: str = ""
    has_data: bool = False
    sentiment: str = SentimentType.NEUTRAL.value
    sentiment_score: float = Field(ge=-1, le=1, default=0.5)
    primary_emotion: str = "客观"
    emotion_targets: list[str] = Field(default_factory=list)
    score: float = Field(ge=0, le=1, default=0.5)


class CredibilityOutput(BaseModel):
    """Output model for the credibility checker node."""

    score: float = Field(ge=0, le=1)
    flags: list[str] = Field(default_factory=list)


class QualityScorerOutput(BaseModel):
    """Output model for the quality scorer node."""

    score: float = Field(ge=0, le=1, default=0.5)


class EntityExtractorOutput(BaseModel):
    """Output model for the entity extractor node."""

    entities: list[dict] = Field(default_factory=list)
    relations: list[dict] = Field(default_factory=list)


class EntityResolverOutput(BaseModel):
    """Output model for the entity resolver."""

    is_same: bool = False
    matched_id: str | None = None
    confidence: float = Field(ge=0, le=1, default=0.0)
    reason: str = ""


class MergerOutput(BaseModel):
    """Output model for the merger node."""

    merged_title: str
    merged_body: str
