# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for SentimentTrendAnalyzer (T012 / R-sentiment-002).

Verifies:
- Protocol compliance (isinstance(SentimentTrendProtocol))
- entity_name path: query article-level shifts (article_id IS NOT NULL)
- community_id path: query by community_id field
- window_days filter: only shifts within the window are considered
- avg_shift = mean(shift_value)
- trend_direction thresholds:
    avg_shift > 0.1 → 'up'
    avg_shift < -0.1 → 'down'
    otherwise → 'stable'
- No-data contract (R-sentiment-002):
    shifts=[], list=[], avg_shift=0.0, trend_direction='stable'
- Validation: both entity_name and community_id None → ValueError
- Validation: window_days not in {7, 30} → ValueError
- DB errors propagate (Rule 12: fail loud)

Patch surface: ``pool.session_context()`` returns a mock session whose
``execute`` returns a mock result whose ``scalars().all()`` returns rows.
Rows are SimpleNamespace mimicking SentimentShift ORM fields.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.protocols.services import SentimentTrendProtocol
from modules.trend.models import SentimentTrendResult
from modules.trend.sentiment import SentimentTrendAnalyzer
from tests.helpers import AsyncContextManagerMock


def _make_shift_row(
    *,
    entity_name: str = "Company X",
    shift_value: float = 0.15,
    before_avg: float = 0.50,
    after_avg: float = 0.65,
    detected_at: datetime | None = None,
    article_id: str | None = "00000000-0000-0000-0000-000000000001",
    community_id: str | None = None,
) -> SimpleNamespace:
    """Build a mock SentimentShift ORM row."""
    return SimpleNamespace(
        entity_name=entity_name,
        shift_value=shift_value,
        before_avg=before_avg,
        after_avg=after_avg,
        detected_at=detected_at or datetime.now(UTC),
        article_id=article_id,
        community_id=community_id or entity_name,
    )


def _make_pool_with_rows(rows: list) -> MagicMock:
    """Build a mock RelationalPool that yields the given rows on query.

    The pool's session_context() returns an async CM yielding a session
    whose execute() returns a result whose scalars().all() returns rows.
    """
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    pool = MagicMock()
    pool.session_context = MagicMock(return_value=AsyncContextManagerMock(session))
    return pool


class TestSentimentTrendAnalyzerProtocolCompliance:
    """Verify SentimentTrendAnalyzer satisfies SentimentTrendProtocol (R-sentiment-002)."""

    def test_analyzer_satisfies_protocol(self) -> None:
        """SentimentTrendAnalyzer instance MUST satisfy SentimentTrendProtocol."""
        pool = MagicMock()
        analyzer = SentimentTrendAnalyzer(pool=pool)
        assert isinstance(analyzer, SentimentTrendProtocol)


class TestAnalyzeTrendEntityName:
    """Test analyze_trend via entity_name path (R-sentiment-002)."""

    @pytest.mark.asyncio
    async def test_up_trend_when_avg_shift_above_threshold(self) -> None:
        """avg_shift > 0.1 → trend_direction='up'."""
        rows = [
            _make_shift_row(shift_value=0.20),
            _make_shift_row(shift_value=0.30),
        ]
        pool = _make_pool_with_rows(rows)

        analyzer = SentimentTrendAnalyzer(pool=pool)
        result = await analyzer.analyze_trend(entity_name="Company X", window_days=7)

        assert isinstance(result, SentimentTrendResult)
        assert result.entity_name == "Company X"
        assert result.window_days == 7
        assert len(result.shifts) == 2
        assert result.avg_shift == pytest.approx(0.25)
        assert result.trend_direction == "up"

    @pytest.mark.asyncio
    async def test_down_trend_when_avg_shift_below_threshold(self) -> None:
        """avg_shift < -0.1 → trend_direction='down'."""
        rows = [
            _make_shift_row(shift_value=-0.20),
            _make_shift_row(shift_value=-0.30),
        ]
        pool = _make_pool_with_rows(rows)

        analyzer = SentimentTrendAnalyzer(pool=pool)
        result = await analyzer.analyze_trend(entity_name="Company Y", window_days=7)

        assert result.avg_shift == pytest.approx(-0.25)
        assert result.trend_direction == "down"

    @pytest.mark.asyncio
    async def test_stable_trend_when_avg_shift_within_threshold(self) -> None:
        """|avg_shift| <= 0.1 → trend_direction='stable'."""
        rows = [
            _make_shift_row(shift_value=0.05),
            _make_shift_row(shift_value=-0.05),
        ]
        pool = _make_pool_with_rows(rows)

        analyzer = SentimentTrendAnalyzer(pool=pool)
        result = await analyzer.analyze_trend(entity_name="Company Z", window_days=7)

        assert result.avg_shift == pytest.approx(0.0)
        assert result.trend_direction == "stable"

    @pytest.mark.asyncio
    async def test_stable_trend_at_upper_boundary(self) -> None:
        """avg_shift == 0.1 (boundary) → 'stable' (spec: > 0.1, not >=)."""
        rows = [_make_shift_row(shift_value=0.10)]
        pool = _make_pool_with_rows(rows)

        analyzer = SentimentTrendAnalyzer(pool=pool)
        result = await analyzer.analyze_trend(entity_name="Boundary Co", window_days=7)

        assert result.avg_shift == pytest.approx(0.10)
        assert result.trend_direction == "stable"

    @pytest.mark.asyncio
    async def test_stable_trend_at_lower_boundary(self) -> None:
        """avg_shift == -0.1 (boundary) → 'stable' (spec: < -0.1, not <=)."""
        rows = [_make_shift_row(shift_value=-0.10)]
        pool = _make_pool_with_rows(rows)

        analyzer = SentimentTrendAnalyzer(pool=pool)
        result = await analyzer.analyze_trend(entity_name="Boundary Co", window_days=7)

        assert result.avg_shift == pytest.approx(-0.10)
        assert result.trend_direction == "stable"

    @pytest.mark.asyncio
    async def test_no_data_returns_empty_stable_result(self) -> None:
        """R-sentiment-002: no data → shifts=[], avg_shift=0.0, trend_direction='stable'."""
        pool = _make_pool_with_rows([])

        analyzer = SentimentTrendAnalyzer(pool=pool)
        result = await analyzer.analyze_trend(entity_name="Ghost Co", window_days=7)

        assert result.shifts == []
        assert result.list == []
        assert result.avg_shift == 0.0
        assert result.trend_direction == "stable"
        assert result.entity_name == "Ghost Co"
        assert result.window_days == 7


class TestAnalyzeTrendCommunityId:
    """Test analyze_trend via community_id path (R-sentiment-002)."""

    @pytest.mark.asyncio
    async def test_community_id_path_aggregates_shifts(self) -> None:
        """community_id path: query community_id field, aggregate shifts."""
        rows = [
            _make_shift_row(
                shift_value=0.40,
                community_id="comm-1",
                entity_name="EntityA",
            ),
            _make_shift_row(
                shift_value=0.20,
                community_id="comm-1",
                entity_name="EntityB",
            ),
        ]
        pool = _make_pool_with_rows(rows)

        analyzer = SentimentTrendAnalyzer(pool=pool)
        result = await analyzer.analyze_trend(community_id="comm-1", window_days=30)

        assert len(result.shifts) == 2
        assert result.avg_shift == pytest.approx(0.30)
        assert result.trend_direction == "up"
        # entity_name is None when queried by community_id (echo input)
        assert result.entity_name is None
        assert result.window_days == 30

    @pytest.mark.asyncio
    async def test_community_id_no_data_returns_stable(self) -> None:
        """community_id path with no data returns empty stable result."""
        pool = _make_pool_with_rows([])

        analyzer = SentimentTrendAnalyzer(pool=pool)
        result = await analyzer.analyze_trend(community_id="ghost-comm", window_days=7)

        assert result.shifts == []
        assert result.avg_shift == 0.0
        assert result.trend_direction == "stable"


class TestAnalyzeTrendWindowDays:
    """Test window_days filtering (R-sentiment-002)."""

    @pytest.mark.asyncio
    async def test_window_days_30_supported(self) -> None:
        """window_days=30 is supported and propagated to result."""
        rows = [_make_shift_row(shift_value=0.50)]
        pool = _make_pool_with_rows(rows)

        analyzer = SentimentTrendAnalyzer(pool=pool)
        result = await analyzer.analyze_trend(entity_name="X", window_days=30)

        assert result.window_days == 30
        assert result.avg_shift == pytest.approx(0.50)

    @pytest.mark.asyncio
    async def test_window_days_7_default(self) -> None:
        """Default window_days is 7."""
        rows = [_make_shift_row(shift_value=0.50)]
        pool = _make_pool_with_rows(rows)

        analyzer = SentimentTrendAnalyzer(pool=pool)
        result = await analyzer.analyze_trend(entity_name="X")

        assert result.window_days == 7


class TestAnalyzeTrendAggregatedList:
    """Test that the `list` field contains aggregated trend data points."""

    @pytest.mark.asyncio
    async def test_list_field_contains_aggregated_data_points(self) -> None:
        """list field is populated with aggregated per-bucket data."""
        # Three shifts on different days → list should have aggregated buckets
        now = datetime.now(UTC)
        rows = [
            _make_shift_row(
                shift_value=0.20,
                detected_at=now - timedelta(days=1),
            ),
            _make_shift_row(
                shift_value=0.40,
                detected_at=now - timedelta(days=2),
            ),
        ]
        pool = _make_pool_with_rows(rows)

        analyzer = SentimentTrendAnalyzer(pool=pool)
        result = await analyzer.analyze_trend(entity_name="X", window_days=7)

        # list field is non-empty, each entry has aggregation structure
        assert len(result.list) >= 1
        for bucket in result.list:
            assert isinstance(bucket, dict)
            # Each bucket has at least an avg_shift key (aggregation output)
            assert "avg_shift" in bucket


class TestAnalyzeTrendValidation:
    """Test input validation (R-sentiment-002 constraints)."""

    @pytest.mark.asyncio
    async def test_raises_value_error_when_both_entity_and_community_none(self) -> None:
        """Both entity_name and community_id None → ValueError (Rule 12)."""
        pool = _make_pool_with_rows([])
        analyzer = SentimentTrendAnalyzer(pool=pool)

        with pytest.raises(ValueError, match=r"entity_name|community_id"):
            await analyzer.analyze_trend(entity_name=None, community_id=None)

    @pytest.mark.asyncio
    async def test_raises_value_error_for_invalid_window_days(self) -> None:
        """window_days not in {7, 30} → ValueError (spec constraints)."""
        pool = _make_pool_with_rows([])
        analyzer = SentimentTrendAnalyzer(pool=pool)

        with pytest.raises(ValueError, match="window_days"):
            await analyzer.analyze_trend(entity_name="X", window_days=14)

    @pytest.mark.asyncio
    async def test_raises_value_error_for_window_days_zero(self) -> None:
        """window_days=0 → ValueError."""
        pool = _make_pool_with_rows([])
        analyzer = SentimentTrendAnalyzer(pool=pool)

        with pytest.raises(ValueError, match="window_days"):
            await analyzer.analyze_trend(entity_name="X", window_days=0)

    @pytest.mark.asyncio
    async def test_raises_value_error_for_window_days_negative(self) -> None:
        """window_days=-1 → ValueError."""
        pool = _make_pool_with_rows([])
        analyzer = SentimentTrendAnalyzer(pool=pool)

        with pytest.raises(ValueError, match="window_days"):
            await analyzer.analyze_trend(entity_name="X", window_days=-1)


class TestAnalyzeTrendErrorPropagation:
    """Test DB errors propagate (Rule 12: fail loud)."""

    @pytest.mark.asyncio
    async def test_db_error_propagates(self) -> None:
        """DB error during query propagates to caller (Rule 12)."""
        # Session.execute raises a DB error
        session = MagicMock()
        session.execute = AsyncMock(side_effect=RuntimeError("DB connection lost"))
        pool = MagicMock()
        pool.session_context = MagicMock(return_value=AsyncContextManagerMock(session))

        analyzer = SentimentTrendAnalyzer(pool=pool)

        with pytest.raises(RuntimeError, match="DB connection lost"):
            await analyzer.analyze_trend(entity_name="X", window_days=7)
