# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Mapper for extracting ORM field dicts from PipelineState.

Extracted from ArticleRepo to reduce _upsert_single complexity
and keep ORM models anemic (per project convention).
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import Any

from core.change_detector import ChangeDetector
from core.db import EmotionType, PersistStatus
from core.types.pipeline_state import PipelineState
from core.url_utils import normalize_url


def _to_emotion(value: str | None) -> EmotionType | None:
    """Convert string emotion value to EmotionType enum for PostgreSQL ENUM column."""
    if not value:
        return None
    for member in EmotionType:
        if member.value == value or member.name.lower() == value.lower():
            return member
    return None


class ArticleStateMapper:
    """Maps PipelineState to ORM model field dictionaries.

    Extracted from ArticleRepo to reduce _upsert_single complexity
    and keep ORM models anemic (per project convention).
    """

    @staticmethod
    def to_core_values(state: PipelineState) -> dict[str, Any]:
        """Extract core field values from pipeline state.

        Computes normalized URL, title, body, and content hash from state
        and returns a dict suitable for ArticleCore insert/upsert.

        Args:
            state: Pipeline state containing article data.

        Returns:
            Dict suitable for ArticleCore insert/upsert.
        """
        raw = state["raw"]
        normalized_url = normalize_url(raw.url)
        title = state.get("cleaned", {}).get("title", getattr(raw, "title", ""))
        body = state.get("cleaned", {}).get("body", getattr(raw, "body", ""))
        content_hash = ChangeDetector.compute_hash({"title": title, "body": body})

        # REM-002: publish_time fallback chain — raw → cleaned (backfilled by cleaner)
        publish_time = getattr(raw, "publish_time", None)
        if publish_time is None:
            cleaned_pt = state.get("cleaned", {}).get("publish_time")
            if cleaned_pt:
                with contextlib.suppress(ValueError, TypeError):
                    if isinstance(cleaned_pt, datetime):
                        publish_time = cleaned_pt
                    else:
                        publish_time = datetime.fromisoformat(str(cleaned_pt))

        return {
            "source_url": normalized_url,
            "source_host": (
                getattr(raw, "source_host", None)
                or (raw.get("source_host") if isinstance(raw, dict) else None)
            ),
            "title": title,
            "category": state.get("category"),
            "language": state.get("language", "").strip()[:10] if state.get("language") else None,
            "region": state.get("region", "").strip()[:50] if state.get("region") else None,
            "score": state.get("score"),
            "sentiment_score": state.get("sentiment", {}).get("sentiment_score"),
            "credibility_score": state.get("credibility", {}).get("score"),
            "persist_status": PersistStatus.PG_DONE.value,
            "publish_time": publish_time,
            "content_hash": content_hash,
            "updated_at": datetime.now(UTC),
        }

    @staticmethod
    def to_analysis_values(state: PipelineState) -> dict[str, Any]:
        """Extract analysis field values from pipeline state.

        Returns analysis fields (without article_id) suitable for
        ArticleAnalysis insert/upsert. The caller is responsible for
        adding article_id.

        Args:
            state: Pipeline state containing analysis data.

        Returns:
            Dict of analysis field values (without article_id).
        """
        values: dict[str, Any] = {}
        if "is_news" in state:
            values["is_news"] = state["is_news"]
        if "summary_info" in state:
            si = state["summary_info"]
            values["subjects"] = si.get("subjects")
            values["key_data"] = si.get("key_data")
            values["impact"] = si.get("impact")
            values["has_data"] = si.get("has_data")
            if si.get("event_time"):
                with contextlib.suppress(ValueError, TypeError):
                    values["event_time"] = datetime.fromisoformat(si["event_time"])
            # Fallback: use publish_time when LLM didn't extract event_time
            if "event_time" not in values and state.get("cleaned", {}).get("publish_time"):
                pt = state["cleaned"]["publish_time"]
                try:
                    if isinstance(pt, datetime):
                        values["event_time"] = pt
                    else:
                        values["event_time"] = datetime.fromisoformat(str(pt))
                except (ValueError, TypeError):
                    pass
        if "sentiment" in state:
            sent = state["sentiment"]
            sentiment_value = sent.get("sentiment")
            values["sentiment"] = (
                sentiment_value.strip()[:10]
                if isinstance(sentiment_value, str)
                else sentiment_value
            )
            values["primary_emotion"] = _to_emotion(sent.get("primary_emotion"))
            values["emotion_targets"] = sent.get("emotion_targets")
        if "credibility" in state:
            cred = state["credibility"]
            values["source_credibility"] = cred.get("source_credibility")
            values["cross_verification"] = cred.get("cross_verification")
            values["content_check_score"] = cred.get("content_check")
            values["credibility_flags"] = cred.get("flags")
            values["verified_by_sources"] = cred.get("verified_by_sources", 0)
        if "quality_score" in state:
            values["quality_score"] = state["quality_score"]
        if "data_conflicts" in state:
            values["data_conflicts"] = state["data_conflicts"]
        if "prompt_versions" in state:
            values["prompt_versions"] = state["prompt_versions"]
        return values

    @staticmethod
    def to_body_values(state: PipelineState) -> dict[str, Any]:
        """Extract body field values from pipeline state.

        Returns body and summary fields (without article_id) suitable for
        ArticleBody insert/upsert. The caller is responsible for
        adding article_id.

        Args:
            state: Pipeline state containing article data.

        Returns:
            Dict with body and summary fields (without article_id).
        """
        raw = state["raw"]
        body = state.get("cleaned", {}).get("body", getattr(raw, "body", ""))
        return {
            "body": body,
            "summary": state.get("summary_info", {}).get("summary"),
        }
