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


@dataclass
class TrendDetectionResult:
    """Result returned by TrendDetectionProtocol.detect_trends (R-trend-001).

    Used by:
        - TrendDetector.detect_trends (T015)
        - T016 trends API endpoint (serialized to APIResponse[dict])
        - T018 TrendAlertEvaluator (trend_spike / trend_drop trigger_type rules
          consume trend_score + direction per entity)

    Fields (spec R-trend-001 — 5 fields, exact order):
        window_days: Time window in days (7 or 30 per spec constraints).
            Echoed from detect_trends input for client transparency.
        entity_type: Optional entity_type filter applied to EventNode.name
            (R-trend-002: "按 entity_type 过滤"). None means no filter —
            aggregate trends across all entity types.
        trends: Per-entity trend entries. Each dict carries:
            - entity_name: canonical entity name from EventNode.name
            - trend_score: 0.6 * frequency_change + 0.4 * sentiment_change
              (R-trend-005); degenerates to frequency_change alone when
              sentiment_shifts has no data for the entity.
            - direction: 'up' (>0.2) / 'down' (<-0.2) / 'stable' (otherwise)
              per spec R-trend-005 thresholds.
            - frequency_change: (current_window_count - previous_window_count)
              / max(previous_window_count, 1) — in [-1.0, +inf).
            Empty list when status='insufficient_data'.
        list: Aggregated MENTIONS heat time-series data points (R-trend-002:
            "Entity MENTIONS 时序热度：按时间聚合 MENTIONS 关系计数").
            Each dict represents one day bucket with day/mentions/count
            fields. Empty list when no data. Field name ``list`` mirrors
            SentimentTrendResult.list convention (Rule 7 — exposed in
            docstring; shadows Python builtin only within attribute access).
        status: 'ok' when EventNode count ≥ 50 (R-trend-002);
            'insufficient_data' when < 50 (R-trend-003, includes count=0).
            The detector MUST NOT raise on insufficient data — it returns
            this status explicitly (Rule 12: fail loud, fail visible).

    No-data contract (R-trend-003):
        trends=[], list=[], status='insufficient_data'. The detector MUST
        return this shape (not None, not raise) when EventNode count < 50 —
        API endpoint relies on it to return HTTP 200 (R-trend-004: data
        insufficiency is not an error).
    """

    window_days: int = 7
    entity_type: str | None = None
    trends: list[dict[str, Any]] = field(default_factory=list)
    list: list[dict[str, Any]] = field(default_factory=list)
    status: str = "insufficient_data"


__all__ = ["SentimentTrendResult", "TrendDetectionResult"]
