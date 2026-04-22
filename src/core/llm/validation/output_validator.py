# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Structured output validation and Pydantic output models for LLM responses."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from core.constants import SentimentType

# ── Output Models ────────────────────────────────────────────


class ClassifierOutput(BaseModel):
    """Output model for the classifier node."""

    is_news: bool | None = None
    confidence: float = Field(ge=0, le=1)


class CleanerContent(BaseModel):
    """Content sub-model for cleaner output."""

    title: str = ""
    subtitle: str | None = None
    summary: str | None = None
    body: str = ""


class CleanerEntity(BaseModel):
    """Entity sub-model for cleaner output."""

    name: str = ""
    type: str = ""
    description: str = ""


class CleanerOutput(BaseModel):
    """Output model for the cleaner node.

    Implements: 容错解析 LLM 返回的不完整 JSON

    model_validator 处理两种常见 LLM 输出异常:
    1. content 嵌套对象缺失 → 从顶层 title/body 字段重建
    2. entities 列表中的畸形项 → 过滤掉无效条目
    """

    publish_time: str | None = None
    author: str | None = None
    content: CleanerContent = Field(default_factory=CleanerContent)
    tags: list[str] = Field(default_factory=list)
    entities: list[CleanerEntity] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _repair_llm_output(cls, data: Any) -> Any:
        """修复 LLM 返回的不完整 JSON 结构."""
        if not isinstance(data, dict):
            return data

        # 修复: content 嵌套对象缺失时, 从顶层字段提取
        # 注意: 当 content 已经是 CleanerContent 实例时, 不需要修复
        content_val = data.get("content")
        if content_val is None or (isinstance(content_val, dict) and not content_val):
            content: dict[str, Any] = {}
            for key in ("title", "subtitle", "summary", "body"):
                if key in data:
                    content[key] = data.pop(key)
            data["content"] = content

        # 修复: entities 列表中的畸形项 (非 dict/非 BaseModel 且缺少必需字段)
        raw_entities = data.get("entities")
        if isinstance(raw_entities, list):
            valid_entities: list[Any] = []
            for item in raw_entities:
                # 已经是 BaseModel 实例的, 直接保留
                if isinstance(item, BaseModel) or (
                    isinstance(item, dict) and item.get("name") and item.get("type")
                ):
                    valid_entities.append(item)
            data["entities"] = valid_entities

        return data


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
