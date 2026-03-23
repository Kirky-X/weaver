# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Structured output validation and Pydantic output models for LLM responses."""

from __future__ import annotations

import re
from typing import TypeVar

import json_repair
from pydantic import BaseModel, Field

T = TypeVar("T", bound=BaseModel)


class OutputParserException(Exception):
    """Raised when LLM output cannot be parsed into the expected model."""

    pass


def parse_llm_json(raw: str | list, model_cls: type[T]) -> T:
    """Parse raw LLM output into a Pydantic model.

    Uses json_repair to handle LLM JSON quirks:
    - Markdown code block wrappers (```json ... ```)
    - Trailing content after valid JSON
    - Trailing commas, missing commas
    - Single-quoted keys/values
    - Inline comments
    - Claude extended thinking format

    json_repair.loads returns a parsed object directly (no separate json.loads step).
    Pydantic model_validate is always the final validation layer.

    Args:
        raw: Raw string output from the LLM, or list of text blocks.
        model_cls: Target Pydantic model class.

    Returns:
        Validated Pydantic model instance.

    Raises:
        OutputParserException: If parsing or validation fails.
    """
    if isinstance(raw, list):
        raw = "".join(block.text if hasattr(block, "text") else str(block) for block in raw)

    # Strip Markdown code block wrappers
    clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    # Extract JSON object if there's trailing text (safety net; repair also handles this)
    json_match = re.search(r"\{[\s\S]*\}", clean)
    if json_match:
        clean = json_match.group(0)

    # json_repair.loads returns parsed object directly
    data = json_repair.loads(clean)
    # Handle completely invalid input (returns empty string)
    if data == "":
        raise OutputParserException(f"解析失败: 无法修复为有效 JSON\n原始内容: {raw[:200]}")
    # Handle plain numeric output (e.g., "0.85" → 0.85) for single-field
    # numeric models like QualityScorerOutput(score: float).
    if isinstance(data, (int, float)) and model_cls.__name__ == "QualityScorerOutput":
        return model_cls(score=float(data))
    try:
        return model_cls.model_validate(data)
    except Exception as e:  # Pydantic ValidationError
        raise OutputParserException(f"验证失败: {e!s}\n原始内容: {raw[:200]}")


# ── Output Models ────────────────────────────────────────────


class ClassifierOutput(BaseModel):
    """Output model for the classifier node."""

    is_news: bool
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
    sentiment: str = "neutral"
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
