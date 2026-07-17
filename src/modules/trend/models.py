# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Trend analysis data models.

Defines DTOs returned by trend-analysis services:
- SentimentTrendResult (T011 / R-sentiment-001): returned by
  SentimentTrendProtocol.analyze_trend.
- TrendDetectionResult (T014 / R-trend-001, future): returned by
  TrendDetectionProtocol.detect_trends.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SentimentTrendResult:
    """Result returned by SentimentTrendProtocol.analyze_trend (R-sentiment-001).

    Used by:
        - SentimentTrendAnalyzer.analyze_trend (T012)
        - T013 trends API endpoint (serialized to APIResponse[dict])
        - T018 TrendAlertEvaluator (sentiment_shift trigger_type)

    Fields (spec R-sentiment-001 — 6 fields, exact order):
        entity_name: The entity name filter used in the query. None when
            the query was by community_id only.
        window_days: Time window in days (7 or 30 per spec constraints).
            Echoed from analyze_trend input for client transparency.
        shifts: Raw shift records from sentiment_shifts table. Each
            dict carries article-level shift metadata
            (article_id/entity_name/shift_value/before_avg/after_avg/
            detected_at). Empty list when no shifts in the window.
        list: Aggregated trend data points. Each dict represents one
            bucket (e.g. daily) with avg_shift for that bucket — suitable
            for charting / time-series visualization. Empty list when no
            data. Field name ``list`` is mandated by spec R-sentiment-001
            — it shadows Python builtin within instance attribute access
            only (``result.list``); not a code smell given spec compliance
            (Rule 11 — convention over novelty; Rule 7 — exposed).
        avg_shift: Mean of shift_value across all shifts in the window.
            0.0 when no data (R-sentiment-002).
        trend_direction: Aggregated direction:
            - 'up' when avg_shift > 0.1
            - 'down' when avg_shift < -0.1
            - 'stable' otherwise (including no-data case)
            Threshold 0.1 per spec R-sentiment-002.

    No-data contract (R-sentiment-002):
        shifts=[], list=[], avg_shift=0.0, trend_direction='stable'.
        The analyzer MUST return this shape (not None) when no shifts
        are found in the window — API endpoint relies on it to return
        HTTP 200 with stable trend (R-sentiment-003).
    """

    entity_name: str | None = None
    window_days: int = 7
    shifts: list[dict[str, Any]] = field(default_factory=list)
    list: list[dict[str, Any]] = field(default_factory=list)
    avg_shift: float = 0.0
    trend_direction: str = "stable"


__all__ = ["SentimentTrendResult"]
