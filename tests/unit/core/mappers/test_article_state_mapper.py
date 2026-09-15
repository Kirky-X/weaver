# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for ArticleStateMapper."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from core.db import EmotionType, PersistStatus
from core.mappers.article_state_mapper import ArticleStateMapper, _to_emotion
from core.types.pipeline_state import PipelineState


def _make_raw(**overrides) -> MagicMock:
    """Build a mock RawArticle with sensible defaults."""
    raw = MagicMock()
    raw.url = overrides.get("url", "https://example.com/article/1")
    raw.title = overrides.get("title", "Test Title")
    raw.body = overrides.get("body", "Test body content")
    raw.source_host = overrides.get("source_host", "example.com")
    raw.publish_time = overrides.get("publish_time")
    return raw


def _make_state(**overrides) -> PipelineState:
    """Build a minimal PipelineState."""
    raw = overrides.pop("raw", None) or _make_raw()
    state: PipelineState = {"raw": raw}  # type: ignore[typeddict-item]
    state.update(overrides)
    return state


# ── _to_emotion ───────────────────────────────────────────────────


class TestToEmotion:
    """Tests for the _to_emotion helper."""

    def test_none_returns_none(self):
        assert _to_emotion(None) is None

    def test_empty_string_returns_none(self):
        assert _to_emotion("") is None

    def test_matching_value_returns_enum(self):
        result = _to_emotion("乐观")
        assert result == EmotionType.OPTIMISTIC

    def test_matching_name_case_insensitive(self):
        result = _to_emotion("optimistic")
        assert result == EmotionType.OPTIMISTIC

    def test_unknown_returns_none(self):
        assert _to_emotion("nonexistent_emotion") is None


# ── to_core_values ────────────────────────────────────────────────


class TestToCoreValues:
    """Tests for ArticleStateMapper.to_core_values()."""

    def test_basic_state_extracts_fields(self):
        """Basic state extracts url, title, body, and content hash."""
        raw = _make_raw(url="https://example.com/test", title="Raw Title", body="Raw Body")
        state = _make_state(
            raw=raw,
            cleaned={"title": "Cleaned Title", "body": "Cleaned Body"},
            category="tech",
            language="en",
            region="US",
            score=0.85,
            sentiment={"sentiment_score": 0.5},
            credibility={"score": 0.9},
        )

        result = ArticleStateMapper.to_core_values(state)

        assert result["source_url"] == "example.com/test" or "example.com" in result["source_url"]
        assert result["title"] == "Cleaned Title"
        assert result["category"] == "tech"
        assert result["language"] == "en"
        assert result["region"] == "US"
        assert result["score"] == 0.85
        assert result["sentiment_score"] == 0.5
        assert result["credibility_score"] == 0.9
        assert result["persist_status"] == PersistStatus.PG_DONE.value
        assert result["content_hash"] is not None
        assert result["updated_at"] is not None

    def test_fallback_to_raw_title(self):
        """Falls back to raw title when cleaned section is missing."""
        raw = _make_raw(title="Raw Title", body="Raw Body")
        state = _make_state(raw=raw)

        result = ArticleStateMapper.to_core_values(state)

        assert result["title"] == "Raw Title"

    def test_publish_time_from_raw(self):
        """publish_time is extracted from raw article."""
        dt = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
        raw = _make_raw(publish_time=dt)
        state = _make_state(raw=raw)

        result = ArticleStateMapper.to_core_values(state)

        assert result["publish_time"] == dt

    def test_publish_time_fallback_to_cleaned(self):
        """publish_time falls back to cleaned.publish_time when raw is None."""
        raw = _make_raw(publish_time=None)
        cleaned_dt = datetime(2026, 3, 20, 8, 0, 0, tzinfo=UTC)
        state = _make_state(
            raw=raw,
            cleaned={"title": "T", "body": "B", "publish_time": cleaned_dt},
        )

        result = ArticleStateMapper.to_core_values(state)

        assert result["publish_time"] == cleaned_dt

    def test_publish_time_from_iso_string(self):
        """publish_time parsed from ISO string in cleaned."""
        raw = _make_raw(publish_time=None)
        state = _make_state(
            raw=raw,
            cleaned={"title": "T", "body": "B", "publish_time": "2026-06-01T10:30:00+00:00"},
        )

        result = ArticleStateMapper.to_core_values(state)

        assert result["publish_time"] is not None
        assert isinstance(result["publish_time"], datetime)

    def test_publish_time_invalid_iso_suppressed(self):
        """Invalid ISO string in cleaned results in None publish_time."""
        raw = _make_raw(publish_time=None)
        state = _make_state(
            raw=raw,
            cleaned={"title": "T", "body": "B", "publish_time": "not-a-date"},
        )

        result = ArticleStateMapper.to_core_values(state)

        assert result["publish_time"] is None

    def test_language_truncated(self):
        """Language is truncated to 10 chars."""
        state = _make_state(language="en-US-very-long-locale-string")

        result = ArticleStateMapper.to_core_values(state)

        assert len(result["language"]) <= 10

    def test_region_truncated(self):
        """Region is truncated to 50 chars."""
        state = _make_state(region="A" * 100)

        result = ArticleStateMapper.to_core_values(state)

        assert len(result["region"]) <= 50

    def test_none_language_and_region(self):
        """None language/region produce None values."""
        state = _make_state()
        # No language or region set

        result = ArticleStateMapper.to_core_values(state)

        assert result["language"] is None
        assert result["region"] is None

    def test_source_host_from_raw(self):
        """source_host extracted from raw article."""
        raw = _make_raw(source_host="news.example.com")
        state = _make_state(raw=raw)

        result = ArticleStateMapper.to_core_values(state)

        assert result["source_host"] == "news.example.com"


# ── to_analysis_values ────────────────────────────────────────────


class TestToAnalysisValues:
    """Tests for ArticleStateMapper.to_analysis_values()."""

    def test_empty_state_returns_empty_dict(self):
        """Minimal state returns empty analysis dict."""
        state = _make_state()

        result = ArticleStateMapper.to_analysis_values(state)

        assert isinstance(result, dict)
        # No analysis keys present
        assert "is_news" not in result

    def test_is_news_extracted(self):
        """is_news flag is extracted."""
        state = _make_state(is_news=True)

        result = ArticleStateMapper.to_analysis_values(state)

        assert result["is_news"] is True

    def test_summary_info_fields(self):
        """summary_info fields are extracted correctly."""
        state = _make_state(
            summary_info={
                "subjects": ["AI", "Tech"],
                "key_data": "Important data",
                "impact": "High",
                "has_data": True,
                "event_time": "2026-05-01T00:00:00+00:00",
                "summary": "A brief summary",
            }
        )

        result = ArticleStateMapper.to_analysis_values(state)

        assert result["subjects"] == ["AI", "Tech"]
        assert result["key_data"] == "Important data"
        assert result["impact"] == "High"
        assert result["has_data"] is True
        assert isinstance(result["event_time"], datetime)

    def test_event_time_fallback_to_publish_time(self):
        """event_time falls back to cleaned.publish_time when not in summary."""
        dt = datetime(2026, 7, 4, 12, 0, 0, tzinfo=UTC)
        state = _make_state(
            cleaned={"title": "T", "body": "B", "publish_time": dt},
            summary_info={"subjects": ["test"]},
        )

        result = ArticleStateMapper.to_analysis_values(state)

        assert result["event_time"] == dt

    def test_event_time_invalid_iso_fallback(self):
        """Invalid event_time ISO falls back to publish_time."""
        dt = datetime(2026, 8, 1, tzinfo=UTC)
        state = _make_state(
            cleaned={"title": "T", "body": "B", "publish_time": dt},
            summary_info={"event_time": "invalid-date"},
        )

        result = ArticleStateMapper.to_analysis_values(state)

        # Invalid event_time is suppressed; fallback to publish_time
        assert result.get("event_time") == dt

    def test_sentiment_fields(self):
        """Sentiment fields are extracted correctly."""
        state = _make_state(
            sentiment={
                "sentiment": "positive",
                "primary_emotion": "乐观",
                "emotion_targets": ["entity1"],
                "sentiment_score": 0.8,
            }
        )

        result = ArticleStateMapper.to_analysis_values(state)

        assert result["sentiment"] == "positive"
        assert result["primary_emotion"] == EmotionType.OPTIMISTIC
        assert result["emotion_targets"] == ["entity1"]

    def test_sentiment_truncated(self):
        """Sentiment string is truncated to 10 chars."""
        state = _make_state(sentiment={"sentiment": "very_long_sentiment_value"})

        result = ArticleStateMapper.to_analysis_values(state)

        assert len(result["sentiment"]) <= 10

    def test_credibility_fields(self):
        """Credibility fields are extracted correctly."""
        state = _make_state(
            credibility={
                "source_credibility": 0.9,
                "cross_verification": 0.8,
                "content_check": 0.7,
                "flags": ["unverified_source"],
                "verified_by_sources": 2,
            }
        )

        result = ArticleStateMapper.to_analysis_values(state)

        assert result["source_credibility"] == 0.9
        assert result["cross_verification"] == 0.8
        assert result["content_check_score"] == 0.7
        assert result["credibility_flags"] == ["unverified_source"]
        assert result["verified_by_sources"] == 2

    def test_quality_score_extracted(self):
        """quality_score is extracted."""
        state = _make_state(quality_score=0.85)

        result = ArticleStateMapper.to_analysis_values(state)

        assert result["quality_score"] == 0.85

    def test_data_conflicts_extracted(self):
        """data_conflicts are extracted."""
        conflicts = [{"field": "title", "reason": "mismatch"}]
        state = _make_state(data_conflicts=conflicts)

        result = ArticleStateMapper.to_analysis_values(state)

        assert result["data_conflicts"] == conflicts

    def test_prompt_versions_extracted(self):
        """prompt_versions are extracted."""
        versions = {"classifier": "v2", "cleaner": "v1"}
        state = _make_state(prompt_versions=versions)

        result = ArticleStateMapper.to_analysis_values(state)

        assert result["prompt_versions"] == versions


# ── to_body_values ────────────────────────────────────────────────


class TestToBodyValues:
    """Tests for ArticleStateMapper.to_body_values()."""

    def test_extracts_body_and_summary(self):
        """Body and summary are extracted from state."""
        raw = _make_raw(body="Raw body")
        state = _make_state(
            raw=raw,
            cleaned={"body": "Cleaned body"},
            summary_info={"summary": "A summary"},
        )

        result = ArticleStateMapper.to_body_values(state)

        assert result["body"] == "Cleaned body"
        assert result["summary"] == "A summary"

    def test_fallback_to_raw_body(self):
        """Falls back to raw body when cleaned is missing."""
        raw = _make_raw(body="Raw body")
        state = _make_state(raw=raw)

        result = ArticleStateMapper.to_body_values(state)

        assert result["body"] == "Raw body"

    def test_summary_none_when_missing(self):
        """Summary is None when summary_info is absent."""
        state = _make_state()

        result = ArticleStateMapper.to_body_values(state)

        assert result["summary"] is None
