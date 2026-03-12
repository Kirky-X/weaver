"""Structured output validation and Pydantic output models for LLM responses."""

from __future__ import annotations

import json
from typing import TypeVar, Type

from pydantic import BaseModel, Field


T = TypeVar("T", bound=BaseModel)


class OutputParserException(Exception):
    """Raised when LLM output cannot be parsed into the expected model."""

    pass


def parse_llm_json(raw: str, model_cls: Type[T]) -> T:
    """Parse raw LLM output into a Pydantic model.

    Handles common LLM quirks:
    - Strips Markdown code block wrappers (```json ... ```)
    - Handles trailing content after valid JSON
    - Validates against the Pydantic model schema

    Args:
        raw: Raw string output from the LLM.
        model_cls: Target Pydantic model class.

    Returns:
        Validated Pydantic model instance.

    Raises:
        OutputParserException: If parsing or validation fails.
    """
    clean = (
        raw.strip()
        .removeprefix("```json")
        .removeprefix("```")
        .removesuffix("```")
        .strip()
    )

    # Try to find valid JSON within the output
    # Handle cases where model outputs extra text after JSON
    import re
    json_match = re.search(r'\{[\s\S]*\}', clean)
    if json_match:
        clean = json_match.group(0)

    try:
        data = json.loads(clean)
        return model_cls.model_validate(data)
    except Exception as exc:
        raise OutputParserException(
            f"解析失败: {exc}\n原始内容: {raw[:200]}"
        ) from exc


# ── Output Models ────────────────────────────────────────────


class ClassifierOutput(BaseModel):
    """Output model for the classifier node."""

    is_news: bool
    confidence: float = Field(ge=0, le=1)


class CleanerOutput(BaseModel):
    """Output model for the cleaner node."""

    title: str
    body: str


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
