# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Mapper for extracting ORM field dicts from PipelineState.

Extracted from ArticleRepo to reduce _upsert_single complexity
and keep ORM models anemic (per project convention).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from core.change_detector import ChangeDetector
from core.db import EmotionType, PersistStatus
from core.observability import get_logger
from core.types.pipeline_state import PipelineState
from core.url_utils import normalize_url

log = get_logger(__name__)


def _to_emotion(value: str | None) -> EmotionType | None:
    """Convert string emotion value to EmotionType enum for PostgreSQL ENUM column."""
    if not value:
        return None
    for member in EmotionType:
        if member.value == value or member.name.lower() == value.lower():
            return member
    # Unrecognized LLM output must stay diagnosable — a silent None makes
    # primary_emotion gaps in the database impossible to explain.
    log.warning("unknown_emotion_value", value=value)
    return None


def _to_utc(value: datetime) -> datetime:
    """Ensure a datetime is timezone-aware (naive values are treated as UTC)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


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

        # publish_time fallback chain — raw → cleaned (backfilled by cleaner)
        publish_time = getattr(raw, "publish_time", None)
        if isinstance(publish_time, datetime):
            publish_time = _to_utc(publish_time)
        if publish_time is None:
            cleaned_pt = state.get("cleaned", {}).get("publish_time")
            if cleaned_pt:
                try:
                    if isinstance(cleaned_pt, datetime):
                        publish_time = _to_utc(cleaned_pt)
                    else:
                        publish_time = _to_utc(datetime.fromisoformat(str(cleaned_pt)))
                except (ValueError, TypeError) as exc:
                    log.warning(
                        "publish_time_parse_failed",
                        value=str(cleaned_pt),
                        error=str(exc),
                    )

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
                try:
                    if isinstance(si["event_time"], datetime):
                        values["event_time"] = _to_utc(si["event_time"])
                    else:
                        values["event_time"] = _to_utc(
                            datetime.fromisoformat(str(si["event_time"]))
                        )
                except (ValueError, TypeError) as exc:
                    log.warning(
                        "event_time_parse_failed",
                        value=str(si["event_time"]),
                        error=str(exc),
                    )
            # Fallback: use publish_time when LLM didn't extract event_time
            if "event_time" not in values and state.get("cleaned", {}).get("publish_time"):
                pt = state["cleaned"]["publish_time"]
                try:
                    if isinstance(pt, datetime):
                        values["event_time"] = _to_utc(pt)
                    else:
                        values["event_time"] = _to_utc(datetime.fromisoformat(str(pt)))
                except (ValueError, TypeError) as exc:
                    log.warning("event_time_fallback_parse_failed", value=str(pt), error=str(exc))
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
