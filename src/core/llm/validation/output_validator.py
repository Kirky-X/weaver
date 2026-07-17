# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors

# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Structured output validation and Pydantic output models for LLM responses."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from core.constants import SentimentType

# ── Output Models ────────────────────────────────────────────


class ClassifierOutput(BaseModel):
    """Output model for the classifier node."""

    is_news: bool | None = None
    confidence: float = Field(ge=0, le=1)


class CleanerContent(BaseModel):
    """Content sub-model for cleaner output.

    title/body are `str | None` (not `str`) to align with cleaner prompt which
    explicitly tells the LLM to fill missing fields with null. Callers must
    apply `or ""` fallback when a non-None string is required (Bug-C HIGH-1).
    """

    title: str | None = None
    subtitle: str | None = None
    summary: str | None = None
    body: str | None = None


class CleanerEntity(BaseModel):
    """Entity sub-model for cleaner output."""

    name: str = ""
    type: str = ""
    description: str = ""


# Sub-field keys used to extract scalar values from dict-shaped LLM output.
_PUBLISH_TIME_SUB_KEYS: tuple[str, ...] = ("date", "time", "value", "text")
_AUTHOR_SUB_KEYS: tuple[str, ...] = ("name", "value", "text")
_CONTENT_SUB_KEYS: tuple[str, ...] = ("text", "value", "content")


def _coerce_str_field(val: Any, sub_keys: tuple[str, ...] = ()) -> str | None:
    """Coerce LLM output value to str | None, never stringifying dict/list.

    Prevents data corruption from str(dict)/str(list) producing Python repr
    strings (e.g., \"{'text': '...'}\") that silently pollute downstream fields
    (Bug-C HIGH-2 fix).

    - None/str → preserved as-is
    - bool → None (avoid \"True\"/\"False\" polluting str fields)
    - int/float → str(val)
    - dict → extract first non-None sub_key value (recursively); else None
    - list → first element that coerces to non-None; else None
    - other → None (don't str() unknown types)
    """
    if val is None or isinstance(val, str):
        return val
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, dict):
        for sk in sub_keys:
            if sk in val:
                coerced = _coerce_str_field(val[sk], sub_keys)
                if coerced is not None:
                    return coerced
        return None
    if isinstance(val, list):
        for item in val:
            coerced = _coerce_str_field(item, sub_keys)
            if coerced is not None:
                return coerced
        return None
    return None


class CleanerOutput(BaseModel):
    """Output model for the cleaner node.

    Implements: 容错解析 LLM 返回的不完整 JSON

    model_validator (Bug-C 修复) 处理 4 大类 LLM 输出异常:
    1. content 字段类型异常 → content=None 从顶层重建; content 非 dict 重置为空;
       content 子字段非 str|None 用 _coerce_str_field 安全转换 (不 str() dict/list)
    2. publish_time/author 非 str|None → 用 _coerce_str_field 安全转换
    3. tags 非 list → 置空; 过滤 None/dict/list/bool 项, 数值项转 str
    4. entities 非 list → 置空; 过滤畸形项 (需含 name 和 type)

    根因 (Bug-C HIGH-1): cleaner prompt 显式要求 LLM "缺失字段填 null", 但
    CleanerContent.title/body 原类型为 str (非 Optional), 导致 Pydantic 验证失败
    → provider_call_failed → cleaner 重试和降级 → 17 篇文章 pending.
    修复: title/body 改为 str | None = None 对齐 prompt 契约, 调用方用 `or ""` 兜底.

    数据腐败防护 (Bug-C HIGH-2): _coerce_str_field 永不 str(dict)/str(list),
    避免垃圾字符串 (如 \"{'text': '...'}\") 静默污染下游字段.
    """

    publish_time: str | None = None
    author: str | None = None
    content: CleanerContent = Field(default_factory=CleanerContent)
    tags: list[str] = Field(default_factory=list)
    entities: list[CleanerEntity] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _repair_llm_output(cls, data: Any) -> Any:
        """修复 LLM 返回的不完整/类型不匹配 JSON 结构.

        适配 cleaner prompt 与 Pydantic 模型之间的契约差异, 并防御 LLM 类型漂移.
        永不 str(dict)/str(list) — 使用 _coerce_str_field 安全转换.
        """
        if not isinstance(data, dict):
            return data

        # 修复 1: content 字段类型异常
        content_val = data.get("content")
        if content_val is None:
            # content=None → 从顶层 title/subtitle/summary/body 重建
            content: dict[str, Any] = {}
            for key in ("title", "subtitle", "summary", "body"):
                if key in data:
                    content[key] = data.pop(key)
            data["content"] = content
        elif isinstance(content_val, dict):
            # content 是 dict → 修复子字段类型 (str | None)
            # 永不 str(dict)/str(list); 用 _coerce_str_field 安全转换
            for key in ("title", "body", "subtitle", "summary"):
                val = content_val.get(key)
                if val is None or isinstance(val, str):
                    continue
                content_val[key] = _coerce_str_field(val, _CONTENT_SUB_KEYS)
        elif not isinstance(content_val, BaseModel):
            # content 是 str/list/int 等 → 重置为空 dict 让默认值生效
            data["content"] = {}
        # else: content 是 BaseModel 实例 (如 CleanerContent) → 不动, 让 Pydantic 直接验证

        # 修复 2: publish_time/author 非 str|None 类型
        # 永不 str(dict)/str(list); 用 _coerce_str_field 安全转换
        for key, sub_keys in (
            ("publish_time", _PUBLISH_TIME_SUB_KEYS),
            ("author", _AUTHOR_SUB_KEYS),
        ):
            val = data.get(key)
            if val is None or isinstance(val, str):
                continue
            data[key] = _coerce_str_field(val, sub_keys)

        # 修复 3: tags 非 list 类型 → 置空; 过滤 None/dict/list/bool 项, 数值项转 str
        raw_tags = data.get("tags")
        if not isinstance(raw_tags, list):
            data["tags"] = []
        else:
            cleaned_tags: list[str] = []
            for item in raw_tags:
                if isinstance(item, str):
                    cleaned_tags.append(item)
                elif isinstance(item, (int, float)) and not isinstance(item, bool):
                    cleaned_tags.append(str(item))
                # None/dict/list/bool/other → 过滤掉 (不 str() 容器类型)
            data["tags"] = cleaned_tags

        # 修复 4: entities 非 list 类型 → 置空; 过滤畸形项 (需含 name 和 type)
        raw_entities = data.get("entities")
        if not isinstance(raw_entities, list):
            data["entities"] = []
        else:
            valid_entities: list[Any] = []
            for item in raw_entities:
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


class NarrativeOutput(BaseModel):
    """Output model for the narrative synthesis node.

    Captures the four framing dimensions used to populate NarrativeNode:
    - source_bias: 媒体立场倾向（如 左倾/右倾/中立/官方/民营）
    - frame: 叙事框架（如 经济影响/技术突破/政策监管/社会影响）
    - tone: 文章语调（如 乐观/悲观/客观/批判/振奋）
    - emphasis: 报道侧重点（如 合作战略/市场竞争/风险警示/技术创新）

    Enum constraints on source_bias/tone align with the prompt contract
    (config/prompts/narrative_synthesis.toml) to prevent prompt injection
    from polluting the knowledge graph with arbitrary strings.
    """

    source_bias: Literal[
        "左倾",
        "右倾",
        "中立",
        "官方",
        "民营",
        "商业",
        "学术",
        "民间",
    ] = "中立"
    frame: str = Field(min_length=1, max_length=100)
    tone: Literal[
        "乐观",
        "悲观",
        "客观",
        "批判",
        "振奋",
        "焦虑",
        "冷静",
        "激昂",
        "嘲讽",
        "同情",
    ] = "客观"
    emphasis: str = Field(min_length=1, max_length=60)
