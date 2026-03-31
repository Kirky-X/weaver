# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Pipeline state type definitions."""

from __future__ import annotations

from typing import Any, TypedDict

from modules.ingestion.domain.models import ArticleRaw


class CredibilityInfo(TypedDict, total=False):
    """Credibility assessment result.

    Attributes:
        score: Final credibility score (0.0-1.0).
        source_credibility: Source authority score.
        content_check: LLM content analysis score.
        timeliness: Timeliness score.
        flags: List of credibility flags/issues.
    """

    score: float
    source_credibility: float
    content_check: float
    timeliness: float
    flags: list[str]


class PipelineState(TypedDict, total=False):
    """Typed dictionary representing the state flowing through the pipeline.

    Each pipeline node reads from and writes to this shared state.
    """

    # Input
    raw: ArticleRaw

    # Classifier
    is_news: bool
    terminal: bool  # If True, skip remaining nodes

    # Cleaner
    cleaned: dict[str, Any]  # {"title": str, "body": str, "publish_time": ...}
    tags: list[str]
    cleaner_entities: list[dict[str, Any]]  # Entities from cleaner prompt

    # Categorizer
    category: str
    language: str
    region: str

    # Vectorize
    vectors: dict[str, list[float]]  # {"content": [...], "title": [...]}

    # Merger
    is_merged: bool
    merged_into: str | None
    merged_source_ids: list[str]

    # Analyze
    summary_info: dict[str, Any]
    sentiment: dict[str, Any]
    score: float
    quality_score: float

    # Credibility (updated: removed cross_verification, verified_by_sources)
    credibility: CredibilityInfo

    # Entity extraction
    entities: list[dict[str, Any]]
    relations: list[dict[str, Any]]
    resolved_entities: list[dict[str, Any]]

    # Persist
    article_id: str
    task_id: str
    neo4j_ids: list[str]

    # Prompt version tracking
    prompt_versions: dict[str, str]

    # Degraded value tracking
    # Records fields that were set to fallback/default values due to LLM failures
    degraded_fields: list[str]  # Field names that used fallback values
    degradation_reasons: dict[str, str]  # Field name -> reason for degradation
