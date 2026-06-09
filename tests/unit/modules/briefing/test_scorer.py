# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for BriefingScorer."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from modules.briefing.scorer import BRIEFING_WEIGHTS, BriefingScorer

CRED = BRIEFING_WEIGHTS["credibility"]
TIME = BRIEFING_WEIGHTS["timeliness"]
QUAL = BRIEFING_WEIGHTS["quality"]
IMPA = BRIEFING_WEIGHTS["impact"]
NOVE = BRIEFING_WEIGHTS["novelty"]

WEIGHT_SUM = CRED + TIME + QUAL + IMPA + NOVE


class TestBriefingWeights:
    """Tests for BRIEFING_WEIGHTS."""

    def test_weights_sum_to_one(self):
        """Test that weights sum to approximately 1.0."""
        assert abs(WEIGHT_SUM - 1.0) < 0.001

    def test_credibility_weight(self):
        """Test credibility weight is 0.30."""
        assert CRED == 0.30

    def test_timeliness_weight(self):
        """Test timeliness weight is 0.25."""
        assert TIME == 0.25

    def test_quality_weight(self):
        """Test quality weight is 0.20."""
        assert QUAL == 0.20

    def test_impact_weight(self):
        """Test impact weight is 0.15."""
        assert IMPA == 0.15

    def test_novelty_weight(self):
        """Test novelty weight is 0.10."""
        assert NOVE == 0.10


class TestBriefingScorer:
    """Tests for BriefingScorer.score."""

    def test_score_returns_float(self):
        """Test score returns a float."""
        article = {}
        score = BriefingScorer.score(article)
        assert isinstance(score, float)

    def test_score_default_values(self):
        """Test score with default values."""
        article = {}
        expected = 0.5 * CRED + 0.5 * TIME + 0.5 * QUAL + 0.5 * IMPA + 0.5 * NOVE
        score = BriefingScorer.score(article)
        assert abs(score - expected) < 0.001

    def test_score_high_values(self):
        """Test score with high values."""
        now = datetime.now(UTC)
        article = {
            "credibility_score": 0.9,
            "publish_time": now.isoformat(),
            "quality_score": 0.9,
            "score": 0.9,
        }
        score = BriefingScorer.score(article)
        expected = 0.9 * CRED + 1.0 * TIME + 0.9 * QUAL + 0.9 * IMPA + 0.5 * NOVE
        assert abs(score - expected) < 0.001

    def test_score_low_values(self):
        """Test score with low values."""
        past = datetime.now(UTC) - timedelta(days=7)
        article = {
            "credibility_score": 0.1,
            "publish_time": past.isoformat(),
            "quality_score": 0.1,
            "score": 0.1,
        }
        score = BriefingScorer.score(article)
        expected = 0.1 * CRED + 0.2 * TIME + 0.1 * QUAL + 0.1 * IMPA + 0.5 * NOVE
        assert abs(score - expected) < 0.001

    def test_score_missing_fields_default_to_mid(self):
        """Test missing fields default to 0.5."""
        article = {"publish_time": datetime.now(UTC).isoformat()}
        score = BriefingScorer.score(article)
        expected = 0.5 * CRED + 1.0 * TIME + 0.5 * QUAL + 0.5 * IMPA + 0.5 * NOVE
        assert abs(score - expected) < 0.001

    def test_score_with_zero_values(self):
        """Test score with zero values."""
        now = datetime.now(UTC)
        article = {
            "credibility_score": 0.0,
            "publish_time": now.isoformat(),
            "quality_score": 0.0,
            "score": 0.0,
        }
        score = BriefingScorer.score(article)
        assert score >= 0.0
        assert score <= 1.0

    def test_score_between_zero_and_one(self):
        """Test score is always between 0 and 1."""
        article = {
            "credibility_score": 1.0,
            "publish_time": datetime.now(UTC).isoformat(),
            "quality_score": 1.0,
            "score": 1.0,
        }
        score = BriefingScorer.score(article)
        assert 0.0 <= score <= 1.0

    def test_score_novelty_is_always_half(self):
        """Test that novelty component is always 0.5."""
        article = {}
        score = BriefingScorer.score(article)
        expected_novelty_contribution = 0.5 * NOVE
        full_default = 0.5 * CRED + 0.5 * TIME + 0.5 * QUAL + 0.5 * IMPA + 0.5 * NOVE
        assert abs(score - full_default) < 0.001


class TestScoreTimeliness:
    """Tests for _score_timeliness static method."""

    def test_within_6_hours(self):
        """Test timeliness within 6 hours returns 1.0."""
        now = datetime.now(UTC)
        article = {"publish_time": now.isoformat()}
        score = BriefingScorer._score_timeliness(article)
        assert score == 1.0

    def test_within_24_hours(self):
        """Test timeliness within 24 hours returns 0.8."""
        past = datetime.now(UTC) - timedelta(hours=12)
        article = {"publish_time": past.isoformat()}
        score = BriefingScorer._score_timeliness(article)
        assert score == 0.8

    def test_within_72_hours(self):
        """Test timeliness within 72 hours returns 0.5."""
        past = datetime.now(UTC) - timedelta(hours=48)
        article = {"publish_time": past.isoformat()}
        score = BriefingScorer._score_timeliness(article)
        assert score == 0.5

    def test_older_than_72_hours(self):
        """Test timeliness older than 72 hours returns 0.2."""
        past = datetime.now(UTC) - timedelta(hours=96)
        article = {"publish_time": past.isoformat()}
        score = BriefingScorer._score_timeliness(article)
        assert score == 0.2

    def test_no_publish_time(self):
        """Test no publish_time returns 0.5."""
        article = {}
        score = BriefingScorer._score_timeliness(article)
        assert score == 0.5

    def test_invalid_date_string(self):
        """Test invalid date string returns 0.5."""
        article = {"publish_time": "not-a-date"}
        score = BriefingScorer._score_timeliness(article)
        assert score == 0.5

    def test_created_at_as_fallback(self):
        """Test created_at is used when publish_time is missing."""
        now = datetime.now(UTC)
        article = {"created_at": now.isoformat()}
        score = BriefingScorer._score_timeliness(article)
        assert score == 1.0

    def test_naive_datetime_converted_to_utc(self):
        """Test naive datetime is treated as UTC."""
        past = datetime.now() - timedelta(hours=6)
        article = {"publish_time": past.isoformat()}
        score = BriefingScorer._score_timeliness(article)
        assert score == 1.0 or score == 0.8
