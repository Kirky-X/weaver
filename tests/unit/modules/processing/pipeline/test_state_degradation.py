# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for PipelineState degradation helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from modules.ingestion.domain.models import ArticleRaw
from modules.processing.pipeline.state import (
    PipelineState,
    get_degradation_summary,
    has_degraded_data,
)


def _make_state(**kwargs) -> PipelineState:
    """Create a sample PipelineState for testing."""
    raw = ArticleRaw(
        url="https://example.com/test",
        title="Test Article",
        body="Test body content.",
        source="test",
        publish_time=datetime.now(UTC),
        source_host="example.com",
    )
    return PipelineState(raw=raw, **kwargs)


class TestHasDegradedData:
    """Tests for has_degraded_data helper."""

    def test_returns_false_for_empty_state(self):
        """Test that state without degraded fields returns False."""
        state = _make_state()
        assert has_degraded_data(state) is False

    def test_returns_false_for_empty_degraded_fields_list(self):
        """Test that empty degraded_fields list returns False."""
        state = _make_state(degraded_fields=[])
        assert has_degraded_data(state) is False

    def test_returns_true_for_degraded_fields(self):
        """Test that state with degraded fields returns True."""
        state = _make_state(degraded_fields=["cleaned.title", "tags"])
        assert has_degraded_data(state) is True

    def test_returns_true_for_single_degraded_field(self):
        """Test that single degraded field returns True."""
        state = _make_state(degraded_fields=["category"])
        assert has_degraded_data(state) is True


class TestGetDegradationSummary:
    """Tests for get_degradation_summary helper."""

    def test_returns_empty_dict_for_no_degraded_fields(self):
        """Test that state without degraded fields returns empty dict."""
        state = _make_state()
        assert get_degradation_summary(state) == {}

    def test_returns_empty_dict_for_empty_degraded_fields_list(self):
        """Test that empty degraded_fields list returns empty dict."""
        state = _make_state(degraded_fields=[])
        assert get_degradation_summary(state) == {}

    def test_returns_summary_for_degraded_fields(self):
        """Test that degraded fields with reasons are returned."""
        state = _make_state(
            degraded_fields=["cleaned.title", "tags"],
            degradation_reasons={
                "cleaned.title": "LLM cleaner failed: timeout",
                "tags": "LLM cleaner failed: timeout",
            },
        )
        summary = get_degradation_summary(state)

        assert len(summary) == 2
        assert summary["cleaned.title"] == "LLM cleaner failed: timeout"
        assert summary["tags"] == "LLM cleaner failed: timeout"

    def test_handles_missing_reason(self):
        """Test that missing reason returns 'Unknown reason'."""
        state = _make_state(
            degraded_fields=["category"],
            degradation_reasons={},
        )
        summary = get_degradation_summary(state)

        assert summary["category"] == "Unknown reason"

    def test_handles_partial_reasons(self):
        """Test that some fields may have reasons while others don't."""
        state = _make_state(
            degraded_fields=["cleaned.title", "category"],
            degradation_reasons={
                "cleaned.title": "LLM cleaner failed",
            },
        )
        summary = get_degradation_summary(state)

        assert summary["cleaned.title"] == "LLM cleaner failed"
        assert summary["category"] == "Unknown reason"

    def test_ignores_extra_reasons_not_in_degraded_fields(self):
        """Test that reasons for non-degraded fields are not included."""
        state = _make_state(
            degraded_fields=["cleaned.title"],
            degradation_reasons={
                "cleaned.title": "LLM failed",
                "some_other_field": "Should not appear",
            },
        )
        summary = get_degradation_summary(state)

        assert len(summary) == 1
        assert "cleaned.title" in summary
        assert "some_other_field" not in summary
