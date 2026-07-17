# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for TrendDetector (T015 / R-trend-002,003,005).

Verifies:
- Protocol compliance (isinstance(TrendDetectionProtocol))
- Scenario 1: sufficient data (>=50 EventNode) + sentiment available
    trend_score = 0.6 * freq_change + 0.4 * sentiment_change
- Scenario 2: sufficient data + sentiment unavailable (analyzer=None)
    trend_score degenerates to freq_change alone (R-trend-005)
- Scenario 3: insufficient data (<50 EventNode) → status='insufficient_data'
    trends=[], list=[] (does NOT raise — R-trend-003)
- Scenario 4: empty data (0 EventNode) → status='insufficient_data'
- window_days validation (only 7/30 supported)
- entity_type filter (EventNode.name filter, Rule 7 — exposed naming)
- DB errors propagate (Rule 12: fail loud)
- Cross-database compatibility: LadybugDB uses INT64 epoch created_at,
    Neo4j uses datetime created_at (temporal.py pattern)
- direction thresholds: >0.2 'up', <-0.2 'down', else 'stable'
- list field: aggregated MENTIONS heat time-series (day/mentions/count)

Patch surface: ``graph_pool.execute_query`` returns mock EventNode rows
as list[dict] with ``name`` + ``created_at`` fields. Neo4j rows use
datetime created_at; LadybugDB rows use INT64 epoch seconds.

Spec conflict (Rule 7 — exposed):
    spec/tasks say "按 entity_type 过滤", but EventNode schema field is
    ``name`` (not ``event_type``). Implementation uses ``e.name`` for the
    filter — the ``entity_type`` parameter name is kept for API/spec
    compatibility (R-trend-002), internally mapped to EventNode.name.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.protocols.services import TrendDetectionProtocol
from modules.trend.models import SentimentTrendResult, TrendDetectionResult

# ────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────


def _make_event_row(
    *,
    name: str = "OpenAI",
    days_ago: float = 1.0,
    database_type: str = "neo4j",
) -> dict:
    """Build a mock EventNode row as returned by graph_pool.execute_query.

    Args:
        name: EventNode.name value (used for entity_type filter).
        days_ago: Age of the event in days (0 = now).
        database_type: "neo4j" (datetime created_at) or "ladybug" (INT64 epoch).

    Returns:
        Dict with ``name`` + ``created_at`` fields matching the Cypher
        RETURN clause shape.
    """
    created_at_dt = datetime.now(UTC) - timedelta(days=days_ago)
    if database_type == "ladybug":
        return {"name": name, "created_at": int(created_at_dt.timestamp())}
    return {"name": name, "created_at": created_at_dt}


def _make_graph_pool_with_rows(
    rows: list[dict],
    *,
    database_type: str = "neo4j",
) -> MagicMock:
    """Build a mock GraphPool that yields the given rows on execute_query.

    Sets ``database_type`` attribute so TrendDetector can branch on
    Neo4j vs LadybugDB query syntax (temporal.py pattern).
    """
    pool = MagicMock()
    pool.execute_query = AsyncMock(return_value=rows)
    pool.database_type = database_type
    return pool


def _make_sentiment_analyzer(
    *,
    avg_shift: float = 0.3,
    trend_direction: str = "up",
    has_shifts: bool = True,
) -> MagicMock:
    """Build a mock SentimentTrendProtocol for TrendDetector dependency.

    Args:
        avg_shift: Mean sentiment shift to return.
        trend_direction: Direction label ('up'/'down'/'stable').
        has_shifts: If True, shifts list is non-empty (sentiment data
            available). If False, shifts=[] signals no sentiment data
            for the entity — TrendDetector should treat this as
            sentiment_change=0.0 and NOT degrade to freq-only (R-trend-005
            says "no sentiment_shifts" degrades; empty shifts means the
            analyzer found no data for this entity, which is the same
            condition).
    """
    analyzer = MagicMock()
    shifts = [{"article_id": "art-1", "shift_value": avg_shift}] if has_shifts else []
    analyzer.analyze_trend = AsyncMock(
        return_value=SentimentTrendResult(
            entity_name=None,
            window_days=7,
            shifts=shifts,
            list=[],
            avg_shift=avg_shift,
            trend_direction=trend_direction,
        )
    )
    return analyzer


def _build_sufficient_rows(
    *,
    current_count: int = 30,
    previous_count: int = 20,
    name: str = "OpenAI",
    database_type: str = "neo4j",
) -> list[dict]:
    """Build >=50 EventNode rows split across current + previous windows.

    Current window: [now - window_days, now) — days_ago in [0, 7).
    Previous window: [now - 2*window_days, now - window_days) — days_ago in [7, 14).
    Total = current_count + previous_count (>= 50 when default 30+20).
    """
    rows: list[dict] = []
    # Current window: spread across 7 days
    for i in range(current_count):
        days_ago = float(i % 7) + 0.5  # avoid exact boundary
        rows.append(_make_event_row(name=name, days_ago=days_ago, database_type=database_type))
    # Previous window: spread across days [7, 14)
    for i in range(previous_count):
        days_ago = 7.0 + float(i % 7) + 0.5
        rows.append(_make_event_row(name=name, days_ago=days_ago, database_type=database_type))
    return rows


# ────────────────────────────────────────────────────────────
# Protocol Compliance
# ────────────────────────────────────────────────────────────


class TestTrendDetectorProtocolCompliance:
    """Verify TrendDetector satisfies TrendDetectionProtocol (R-trend-001)."""

    def test_detector_satisfies_protocol(self) -> None:
        """TrendDetector instance MUST satisfy TrendDetectionProtocol."""
        from modules.trend.detection import TrendDetector

        pool = _make_graph_pool_with_rows([])
        detector = TrendDetector(graph_pool=pool)
        assert isinstance(detector, TrendDetectionProtocol)

    def test_detector_satisfies_protocol_with_analyzer(self) -> None:
        """TrendDetector with sentiment_analyzer also satisfies Protocol."""
        from modules.trend.detection import TrendDetector

        pool = _make_graph_pool_with_rows([])
        analyzer = _make_sentiment_analyzer()
        detector = TrendDetector(graph_pool=pool, sentiment_analyzer=analyzer)
        assert isinstance(detector, TrendDetectionProtocol)


# ────────────────────────────────────────────────────────────
# Scenario 1: Sufficient data + sentiment available
# ────────────────────────────────────────────────────────────


class TestDetectTrendsSufficientDataWithSentiment:
    """Scenario 1: >=50 EventNode + sentiment analyzer available (R-trend-002/005)."""

    @pytest.mark.asyncio
    async def test_up_trend_with_sentiment_contribution(self) -> None:
        """trend_score = 0.6 * freq_change + 0.4 * sentiment_change → 'up'.

        Setup:
        - current_count=30, previous_count=20 → freq_change = 10/20 = 0.5
        - sentiment avg_shift=0.3 → sentiment_change = 0.3
        - trend_score = 0.6*0.5 + 0.4*0.3 = 0.30 + 0.12 = 0.42
        - 0.42 > 0.2 → direction='up'
        """
        from modules.trend.detection import TrendDetector

        rows = _build_sufficient_rows(current_count=30, previous_count=20)
        pool = _make_graph_pool_with_rows(rows)
        analyzer = _make_sentiment_analyzer(avg_shift=0.3, trend_direction="up")
        detector = TrendDetector(graph_pool=pool, sentiment_analyzer=analyzer)

        result = await detector.detect_trends(window_days=7)

        assert isinstance(result, TrendDetectionResult)
        assert result.status == "ok"
        assert result.window_days == 7
        assert len(result.trends) >= 1

        openai_trend = next(t for t in result.trends if t["entity_name"] == "OpenAI")
        assert openai_trend["frequency_change"] == pytest.approx(0.5, abs=1e-6)
        assert openai_trend["trend_score"] == pytest.approx(0.42, abs=1e-6)
        assert openai_trend["direction"] == "up"
        # Sentiment analyzer was called for the entity.
        analyzer.analyze_trend.assert_called_once()

    @pytest.mark.asyncio
    async def test_down_trend_when_freq_and_sentiment_both_negative(self) -> None:
        """direction='down' when trend_score < -0.2.

        Setup:
        - current_count=20, previous_count=40 → freq_change = -20/40 = -0.5
        - sentiment avg_shift=-0.4 → sentiment_change = -0.4
        - trend_score = 0.6*(-0.5) + 0.4*(-0.4) = -0.300 - 0.160 = -0.460
        - -0.460 < -0.2 → direction='down'
        """
        from modules.trend.detection import TrendDetector

        rows = _build_sufficient_rows(current_count=20, previous_count=40)
        pool = _make_graph_pool_with_rows(rows)
        analyzer = _make_sentiment_analyzer(avg_shift=-0.4, trend_direction="down")
        detector = TrendDetector(graph_pool=pool, sentiment_analyzer=analyzer)

        result = await detector.detect_trends(window_days=7)

        assert result.status == "ok"
        openai_trend = next(t for t in result.trends if t["entity_name"] == "OpenAI")
        assert openai_trend["frequency_change"] == pytest.approx(-0.5, abs=1e-3)
        assert openai_trend["trend_score"] < -0.2
        assert openai_trend["direction"] == "down"

    @pytest.mark.asyncio
    async def test_stable_trend_when_score_within_threshold(self) -> None:
        """direction='stable' when |trend_score| <= 0.2.

        Setup:
        - current_count=26, previous_count=25 → freq_change = 1/25 = 0.04
        - sentiment avg_shift=0.0 → sentiment_change = 0.0
        - trend_score = 0.6*0.04 + 0.4*0.0 = 0.024 → 'stable'
        """
        from modules.trend.detection import TrendDetector

        rows = _build_sufficient_rows(current_count=26, previous_count=25)
        pool = _make_graph_pool_with_rows(rows)
        analyzer = _make_sentiment_analyzer(avg_shift=0.0, trend_direction="stable")
        detector = TrendDetector(graph_pool=pool, sentiment_analyzer=analyzer)

        result = await detector.detect_trends(window_days=7)

        assert result.status == "ok"
        openai_trend = next(t for t in result.trends if t["entity_name"] == "OpenAI")
        assert openai_trend["trend_score"] == pytest.approx(0.024, abs=1e-3)
        assert openai_trend["direction"] == "stable"


# ────────────────────────────────────────────────────────────
# Scenario 2: Sufficient data + sentiment unavailable (degradation)
# ────────────────────────────────────────────────────────────


class TestDetectTrendsSufficientDataWithoutSentiment:
    """Scenario 2: analyzer=None → trend_score degenerates to freq_change (R-trend-005)."""

    @pytest.mark.asyncio
    async def test_trend_score_degrades_to_frequency_when_analyzer_none(self) -> None:
        """analyzer=None → trend_score = freq_change (no sentiment contribution).

        Setup:
        - current_count=30, previous_count=20 → freq_change = 0.5
        - trend_score = 0.5 (degraded, no sentiment)
        - 0.5 > 0.2 → direction='up'
        """
        from modules.trend.detection import TrendDetector

        rows = _build_sufficient_rows(current_count=30, previous_count=20)
        pool = _make_graph_pool_with_rows(rows)
        detector = TrendDetector(graph_pool=pool, sentiment_analyzer=None)

        result = await detector.detect_trends(window_days=7)

        assert result.status == "ok"
        openai_trend = next(t for t in result.trends if t["entity_name"] == "OpenAI")
        assert openai_trend["frequency_change"] == pytest.approx(0.5, abs=1e-6)
        assert openai_trend["trend_score"] == pytest.approx(0.5, abs=1e-6)
        assert openai_trend["direction"] == "up"

    @pytest.mark.asyncio
    async def test_down_direction_when_freq_decreases_without_sentiment(self) -> None:
        """analyzer=None + freq drop → direction='down'.

        Setup:
        - current_count=20, previous_count=40 → freq_change = -20/40 = -0.5
        - trend_score = -0.5 (degraded, no sentiment)
        - -0.5 < -0.2 → direction='down'
        """
        from modules.trend.detection import TrendDetector

        rows = _build_sufficient_rows(current_count=20, previous_count=40)
        pool = _make_graph_pool_with_rows(rows)
        detector = TrendDetector(graph_pool=pool, sentiment_analyzer=None)

        result = await detector.detect_trends(window_days=7)

        assert result.status == "ok"
        openai_trend = next(t for t in result.trends if t["entity_name"] == "OpenAI")
        assert openai_trend["trend_score"] < -0.2
        assert openai_trend["direction"] == "down"


# ────────────────────────────────────────────────────────────
# Scenario 3: Insufficient data (< 50 EventNode)
# ────────────────────────────────────────────────────────────


class TestDetectTrendsInsufficientData:
    """Scenario 3: EventNode count < 50 → status='insufficient_data' (R-trend-003)."""

    @pytest.mark.asyncio
    async def test_insufficient_data_returns_empty_trends(self) -> None:
        """<50 EventNode → status='insufficient_data', trends=[], list=[].

        Does NOT raise — data insufficiency is a legitimate state, not an
        error (R-trend-003). API returns HTTP 200 (R-trend-004).
        """
        from modules.trend.detection import TrendDetector

        # 30 EventNode (< 50 threshold)
        rows = _build_sufficient_rows(current_count=20, previous_count=10)
        assert len(rows) == 30
        pool = _make_graph_pool_with_rows(rows)
        analyzer = _make_sentiment_analyzer()
        detector = TrendDetector(graph_pool=pool, sentiment_analyzer=analyzer)

        result = await detector.detect_trends(window_days=7)

        assert result.status == "insufficient_data"
        assert result.trends == []
        assert result.list == []
        assert result.window_days == 7
        # Sentiment analyzer MUST NOT be called when data is insufficient.
        analyzer.analyze_trend.assert_not_called()

    @pytest.mark.asyncio
    async def test_insufficient_data_boundary_49_events(self) -> None:
        """49 EventNode (just below threshold) → insufficient_data."""
        from modules.trend.detection import TrendDetector

        rows = _build_sufficient_rows(current_count=30, previous_count=19)
        assert len(rows) == 49
        pool = _make_graph_pool_with_rows(rows)
        detector = TrendDetector(graph_pool=pool)

        result = await detector.detect_trends(window_days=7)

        assert result.status == "insufficient_data"
        assert result.trends == []


# ────────────────────────────────────────────────────────────
# Scenario 4: Empty data (0 EventNode)
# ────────────────────────────────────────────────────────────


class TestDetectTrendsEmptyData:
    """Scenario 4: 0 EventNode → status='insufficient_data' (R-trend-003)."""

    @pytest.mark.asyncio
    async def test_empty_data_returns_insufficient_status(self) -> None:
        """0 EventNode → status='insufficient_data', trends=[], list=[]."""
        from modules.trend.detection import TrendDetector

        pool = _make_graph_pool_with_rows([])
        detector = TrendDetector(graph_pool=pool)

        result = await detector.detect_trends(window_days=7)

        assert result.status == "insufficient_data"
        assert result.trends == []
        assert result.list == []
        assert result.window_days == 7

    @pytest.mark.asyncio
    async def test_empty_data_with_entity_type_filter(self) -> None:
        """0 EventNode with entity_type filter → insufficient_data (not error)."""
        from modules.trend.detection import TrendDetector

        pool = _make_graph_pool_with_rows([])
        detector = TrendDetector(graph_pool=pool)

        result = await detector.detect_trends(window_days=7, entity_type="Nonexistent")

        assert result.status == "insufficient_data"
        assert result.entity_type == "Nonexistent"


# ────────────────────────────────────────────────────────────
# Validation
# ────────────────────────────────────────────────────────────


class TestDetectTrendsValidation:
    """Test input validation (spec constraints)."""

    @pytest.mark.asyncio
    async def test_raises_value_error_for_invalid_window_days(self) -> None:
        """window_days not in {7, 30} → ValueError."""
        from modules.trend.detection import TrendDetector

        pool = _make_graph_pool_with_rows([])
        detector = TrendDetector(graph_pool=pool)

        with pytest.raises(ValueError, match="window_days"):
            await detector.detect_trends(window_days=14)

    @pytest.mark.asyncio
    async def test_raises_value_error_for_window_days_zero(self) -> None:
        """window_days=0 → ValueError."""
        from modules.trend.detection import TrendDetector

        pool = _make_graph_pool_with_rows([])
        detector = TrendDetector(graph_pool=pool)

        with pytest.raises(ValueError, match="window_days"):
            await detector.detect_trends(window_days=0)

    @pytest.mark.asyncio
    async def test_raises_value_error_for_negative_window_days(self) -> None:
        """window_days=-1 → ValueError."""
        from modules.trend.detection import TrendDetector

        pool = _make_graph_pool_with_rows([])
        detector = TrendDetector(graph_pool=pool)

        with pytest.raises(ValueError, match="window_days"):
            await detector.detect_trends(window_days=-1)

    @pytest.mark.asyncio
    async def test_window_days_30_supported(self) -> None:
        """window_days=30 is supported and propagated to result."""
        from modules.trend.detection import TrendDetector

        # 50+ rows across 30-day window (current + previous 30d)
        rows = _build_sufficient_rows(current_count=30, previous_count=20)
        pool = _make_graph_pool_with_rows(rows)
        detector = TrendDetector(graph_pool=pool)

        result = await detector.detect_trends(window_days=30)

        assert result.window_days == 30


# ────────────────────────────────────────────────────────────
# Error Propagation (Rule 12: fail loud)
# ────────────────────────────────────────────────────────────


class TestDetectTrendsErrorPropagation:
    """Test DB errors propagate (Rule 12: fail loud)."""

    @pytest.mark.asyncio
    async def test_graph_db_error_propagates(self) -> None:
        """Graph DB error during query propagates to caller (Rule 12)."""
        from modules.trend.detection import TrendDetector

        pool = MagicMock()
        pool.execute_query = AsyncMock(side_effect=RuntimeError("Graph DB connection lost"))
        pool.database_type = "neo4j"
        detector = TrendDetector(graph_pool=pool)

        with pytest.raises(RuntimeError, match="Graph DB connection lost"):
            await detector.detect_trends(window_days=7)

    @pytest.mark.asyncio
    async def test_sentiment_analyzer_error_propagates(self) -> None:
        """Sentiment analyzer error propagates (Rule 12 — fail loud).

        When sentiment_analyzer raises, TrendDetector MUST NOT swallow it
        — the error propagates to the caller. Distinguishes DB errors
        from the no-data contract (which returns insufficient_data).
        """
        from modules.trend.detection import TrendDetector

        rows = _build_sufficient_rows(current_count=30, previous_count=20)
        pool = _make_graph_pool_with_rows(rows)
        analyzer = MagicMock()
        analyzer.analyze_trend = AsyncMock(side_effect=RuntimeError("Sentiment DB down"))
        detector = TrendDetector(graph_pool=pool, sentiment_analyzer=analyzer)

        with pytest.raises(RuntimeError, match="Sentiment DB down"):
            await detector.detect_trends(window_days=7)


# ────────────────────────────────────────────────────────────
# Cross-database compatibility (LadybugDB)
# ────────────────────────────────────────────────────────────


class TestDetectTrendsLadybugCompatibility:
    """LadybugDB uses INT64 epoch created_at (temporal.py pattern)."""

    @pytest.mark.asyncio
    async def test_ladybug_int64_timestamps_processed_correctly(self) -> None:
        """LadybugDB rows with INT64 created_at are bucketed correctly.

        LadybugDB stores created_at as INT64 epoch seconds (ladybug_schema.py).
        TrendDetector MUST detect pool.database_type=='ladybug' and parse
        INT64 timestamps (not datetime objects).
        """
        from modules.trend.detection import TrendDetector

        rows = _build_sufficient_rows(current_count=30, previous_count=20, database_type="ladybug")
        pool = _make_graph_pool_with_rows(rows, database_type="ladybug")
        detector = TrendDetector(graph_pool=pool)

        result = await detector.detect_trends(window_days=7)

        assert result.status == "ok"
        assert len(result.trends) >= 1
        openai_trend = next(t for t in result.trends if t["entity_name"] == "OpenAI")
        assert openai_trend["frequency_change"] == pytest.approx(0.5, abs=1e-6)

    @pytest.mark.asyncio
    async def test_ladybug_empty_data_returns_insufficient(self) -> None:
        """LadybugDB with 0 rows → insufficient_data (cross-db consistency)."""
        from modules.trend.detection import TrendDetector

        pool = _make_graph_pool_with_rows([], database_type="ladybug")
        detector = TrendDetector(graph_pool=pool)

        result = await detector.detect_trends(window_days=7)

        assert result.status == "insufficient_data"
        assert result.trends == []


# ────────────────────────────────────────────────────────────
# entity_type filter + list field
# ────────────────────────────────────────────────────────────


class TestDetectTrendsEntityTypeFilter:
    """entity_type filter (EventNode.name) + result shape (R-trend-002)."""

    @pytest.mark.asyncio
    async def test_entity_type_filter_propagated_to_result(self) -> None:
        """entity_type param is echoed in result.entity_type."""
        from modules.trend.detection import TrendDetector

        rows = _build_sufficient_rows(current_count=30, previous_count=20, name="OpenAI")
        pool = _make_graph_pool_with_rows(rows)
        detector = TrendDetector(graph_pool=pool)

        result = await detector.detect_trends(window_days=7, entity_type="OpenAI")

        assert result.entity_type == "OpenAI"
        assert result.status == "ok"

    @pytest.mark.asyncio
    async def test_no_entity_type_aggregates_all(self) -> None:
        """entity_type=None aggregates across all entity types."""
        from modules.trend.detection import TrendDetector

        # Mix of two entities, both in sufficient quantity
        rows = _build_sufficient_rows(current_count=30, previous_count=20, name="OpenAI")
        rows += _build_sufficient_rows(current_count=25, previous_count=20, name="TechCorp")
        pool = _make_graph_pool_with_rows(rows)
        detector = TrendDetector(graph_pool=pool)

        result = await detector.detect_trends(window_days=7)

        assert result.status == "ok"
        assert len(result.trends) >= 2
        entity_names = {t["entity_name"] for t in result.trends}
        assert "OpenAI" in entity_names
        assert "TechCorp" in entity_names


class TestDetectTrendsListField:
    """list field: aggregated MENTIONS heat time-series (R-trend-002)."""

    @pytest.mark.asyncio
    async def test_list_field_contains_daily_buckets(self) -> None:
        """list field is populated with per-day MENTIONS aggregation."""
        from modules.trend.detection import TrendDetector

        rows = _build_sufficient_rows(current_count=30, previous_count=20)
        pool = _make_graph_pool_with_rows(rows)
        detector = TrendDetector(graph_pool=pool)

        result = await detector.detect_trends(window_days=7)

        assert result.status == "ok"
        # list field MUST be non-empty when data is sufficient.
        assert len(result.list) >= 1
        for bucket in result.list:
            assert isinstance(bucket, dict)
            # Each bucket has day + mentions/count fields (aggregation output).
            assert "day" in bucket
            assert "mentions" in bucket

    @pytest.mark.asyncio
    async def test_list_field_empty_when_insufficient_data(self) -> None:
        """list field is [] when status='insufficient_data'."""
        from modules.trend.detection import TrendDetector

        pool = _make_graph_pool_with_rows([])
        detector = TrendDetector(graph_pool=pool)

        result = await detector.detect_trends(window_days=7)

        assert result.status == "insufficient_data"
        assert result.list == []


# ────────────────────────────────────────────────────────────
# Threshold boundaries
# ────────────────────────────────────────────────────────────


class TestDetectTrendsThresholdBoundaries:
    """direction threshold boundaries (R-trend-005)."""

    @pytest.mark.asyncio
    async def test_up_boundary_at_0_2(self) -> None:
        """trend_score exactly 0.2 → 'stable' (spec: > 0.2, not >=).

        Setup (degraded — analyzer returns shifts=[] → freq-only):
        - current=30, previous=25 → freq_change = 5/25 = 0.2
        - trend_score = 0.2 (degraded, no sentiment contribution)
        - 0.2 is NOT > 0.2 → direction='stable'
        """
        from modules.trend.detection import TrendDetector

        rows = _build_sufficient_rows(current_count=30, previous_count=25)
        pool = _make_graph_pool_with_rows(rows)
        # analyzer returns shifts=[] (no sentiment data) → degrade to freq-only
        analyzer = _make_sentiment_analyzer(avg_shift=0.0, has_shifts=False)
        detector = TrendDetector(graph_pool=pool, sentiment_analyzer=analyzer)

        result = await detector.detect_trends(window_days=7)

        openai_trend = next(t for t in result.trends if t["entity_name"] == "OpenAI")
        # trend_score should be exactly 0.2 at boundary (degraded: freq only)
        assert openai_trend["trend_score"] == pytest.approx(0.2, abs=1e-3)
        # spec: > 0.2 is 'up'; 0.2 exactly is 'stable'
        assert openai_trend["direction"] == "stable"

    @pytest.mark.asyncio
    async def test_down_boundary_at_minus_0_2(self) -> None:
        """trend_score exactly -0.2 → 'stable' (spec: < -0.2, not <=).

        Setup (degraded — analyzer returns shifts=[] → freq-only):
        - current=24, previous=30 → freq_change = -6/30 = -0.2
        - trend_score = -0.2 (degraded, no sentiment contribution)
        - -0.2 is NOT < -0.2 → direction='stable'
        """
        from modules.trend.detection import TrendDetector

        rows = _build_sufficient_rows(current_count=24, previous_count=30)
        pool = _make_graph_pool_with_rows(rows)
        analyzer = _make_sentiment_analyzer(avg_shift=0.0, has_shifts=False)
        detector = TrendDetector(graph_pool=pool, sentiment_analyzer=analyzer)

        result = await detector.detect_trends(window_days=7)

        openai_trend = next(t for t in result.trends if t["entity_name"] == "OpenAI")
        assert openai_trend["trend_score"] == pytest.approx(-0.2, abs=1e-3)
        assert openai_trend["direction"] == "stable"
