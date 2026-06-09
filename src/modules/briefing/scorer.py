# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Briefing scorer — 5-dimension weighted scoring for article selection."""

from __future__ import annotations

from typing import Any

from core.observability.logging import get_logger

log = get_logger(__name__)

BRIEFING_WEIGHTS = {
    "credibility": 0.30,
    "timeliness": 0.25,
    "quality": 0.20,
    "impact": 0.15,
    "novelty": 0.10,
}


class BriefingScorer:
    """Score articles for briefing selection."""

    @staticmethod
    def score(article: dict[str, Any]) -> float:
        """Compute composite score for an article.

        Args:
            article: Article dict with score fields.

        Returns:
            Composite score (0.0-1.0).
        """
        credibility = article.get("credibility_score") or 0.5
        timeliness = BriefingScorer._score_timeliness(article)
        quality = article.get("quality_score") or 0.5
        impact = article.get("score") or 0.5
        novelty = 0.5

        return (
            credibility * BRIEFING_WEIGHTS["credibility"]
            + timeliness * BRIEFING_WEIGHTS["timeliness"]
            + quality * BRIEFING_WEIGHTS["quality"]
            + impact * BRIEFING_WEIGHTS["impact"]
            + novelty * BRIEFING_WEIGHTS["novelty"]
        )

    @staticmethod
    def _score_timeliness(article: dict[str, Any]) -> float:
        """Score how timely an article is."""
        from datetime import UTC, datetime

        publish_time = article.get("publish_time") or article.get("created_at")
        if not publish_time:
            return 0.5
        if isinstance(publish_time, str):
            try:
                publish_time = datetime.fromisoformat(publish_time)
            except ValueError:
                return 0.5
        now = datetime.now(UTC)
        if publish_time.tzinfo is None:
            publish_time = publish_time.replace(tzinfo=UTC)
        hours_ago = (now - publish_time).total_seconds() / 3600
        if hours_ago <= 6:
            return 1.0
        if hours_ago <= 24:
            return 0.8
        if hours_ago <= 72:
            return 0.5
        return 0.2
