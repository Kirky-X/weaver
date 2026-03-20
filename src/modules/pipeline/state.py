# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Pipeline state type definitions."""

from __future__ import annotations

from typing import Any, TypedDict

from modules.collector.models import ArticleRaw


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

    # Credibility
    credibility: dict[str, Any]

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
