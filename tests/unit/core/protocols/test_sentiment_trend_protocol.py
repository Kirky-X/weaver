# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for SentimentTrendProtocol and SentimentTrendResult (T011).

Verifies:
- R-sentiment-001: Protocol defines analyze_trend method
- SentimentTrendResult dataclass has 6 fields per spec
- Protocol is @runtime_checkable
- Dataclass shape matches spec (entity_name/window_days/shifts/list/
  avg_shift/trend_direction)
- Default values reflect "no data" state (R-sentiment-002):
  shifts=[], list=[], avg_shift=0.0, trend_direction='stable'
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.protocols.services import SentimentTrendProtocol
from modules.trend.models import SentimentTrendResult


class TestSentimentTrendProtocolStructure:
    """Verify SentimentTrendProtocol is defined correctly (R-sentiment-001)."""

    def test_protocol_is_runtime_checkable(self) -> None:
        """SentimentTrendProtocol MUST be @runtime_checkable per spec."""
        mock_impl = MagicMock(spec=SentimentTrendProtocol)
        assert isinstance(mock_impl, SentimentTrendProtocol)

    def test_protocol_has_analyze_trend_method(self) -> None:
        """analyze_trend method exists on the Protocol."""
        assert hasattr(SentimentTrendProtocol, "analyze_trend")

    def test_protocol_has_exactly_one_method(self) -> None:
        """Protocol defines exactly 1 method (no extra surface)."""
        protocol_methods = {
            name
            for name in dir(SentimentTrendProtocol)
            if not name.startswith("_") and callable(getattr(SentimentTrendProtocol, name))
        }
        expected = {"analyze_trend"}
        assert protocol_methods == expected, f"Expected exactly {expected}, got {protocol_methods}"


class TestSentimentTrendProtocolMockCompliance:
    """Verify mock implementations satisfy the Protocol (R-sentiment-001)."""

    def test_mock_with_analyze_trend_satisfies_protocol(self) -> None:
        """A class implementing analyze_trend should satisfy the Protocol."""
        mock_service = MagicMock(spec=SentimentTrendProtocol)
        mock_service.analyze_trend = AsyncMock()
        assert isinstance(mock_service, SentimentTrendProtocol)

    @pytest.mark.asyncio
    async def test_analyze_trend_returns_sentiment_trend_result(self) -> None:
        """analyze_trend(...) returns SentimentTrendResult."""
        mock_service = MagicMock(spec=SentimentTrendProtocol)
        expected = SentimentTrendResult(
            entity_name="Company X",
            window_days=7,
            shifts=[{"shift_value": 0.2}],
            list=[{"day": "2026-07-17", "avg_shift": 0.2}],
            avg_shift=0.2,
            trend_direction="up",
        )
        mock_service.analyze_trend = AsyncMock(return_value=expected)
        result = await mock_service.analyze_trend(entity_name="Company X", window_days=7)
        assert isinstance(result, SentimentTrendResult)
        assert result.entity_name == "Company X"
        assert result.trend_direction == "up"

    @pytest.mark.asyncio
    async def test_analyze_trend_no_data_returns_stable(self) -> None:
        """No data scenario: trend_direction='stable', avg_shift=0.0, shifts=[]."""
        mock_service = MagicMock(spec=SentimentTrendProtocol)
        no_data = SentimentTrendResult(
            entity_name="Unknown",
            window_days=7,
            shifts=[],
            list=[],
            avg_shift=0.0,
            trend_direction="stable",
        )
        mock_service.analyze_trend = AsyncMock(return_value=no_data)
        result = await mock_service.analyze_trend(entity_name="Unknown")
        assert result.trend_direction == "stable"
        assert result.avg_shift == 0.0
        assert result.shifts == []


class TestSentimentTrendResultDataclass:
    """Verify SentimentTrendResult dataclass shape (R-sentiment-001)."""

    def test_is_dataclass(self) -> None:
        assert is_dataclass(SentimentTrendResult)

    def test_has_required_fields(self) -> None:
        """SentimentTrendResult MUST have all 6 fields per spec:
        entity_name / window_days / shifts / list / avg_shift / trend_direction.
        """
        field_names = {f.name for f in fields(SentimentTrendResult)}
        required = {
            "entity_name",
            "window_days",
            "shifts",
            "list",
            "avg_shift",
            "trend_direction",
        }
        assert required.issubset(field_names), f"Missing fields: {required - field_names}"

    def test_default_values_reflect_no_data_state(self) -> None:
        """R-sentiment-002: no-data defaults — shifts=[], list=[],
        avg_shift=0.0, trend_direction='stable'.
        """
        result = SentimentTrendResult(entity_name="X", window_days=7)
        assert result.shifts == []
        assert result.list == []
        assert result.avg_shift == 0.0
        assert result.trend_direction == "stable"

    def test_can_construct_with_all_fields(self) -> None:
        """SentimentTrendResult should be constructible with all fields."""
        result = SentimentTrendResult(
            entity_name="Company X",
            window_days=30,
            shifts=[{"entity_name": "Company X", "shift_value": 0.15}],
            list=[{"day": "2026-07-17", "avg_shift": 0.15}],
            avg_shift=0.15,
            trend_direction="up",
        )
        assert result.entity_name == "Company X"
        assert result.window_days == 30
        assert len(result.shifts) == 1
        assert len(result.list) == 1
        assert result.avg_shift == 0.15
        assert result.trend_direction == "up"

    def test_trend_direction_valid_values(self) -> None:
        """trend_direction must accept the 3 spec-defined values."""
        for direction in ("up", "down", "stable"):
            result = SentimentTrendResult(
                entity_name="X",
                window_days=7,
                trend_direction=direction,
            )
            assert result.trend_direction == direction


class TestExports:
    """Verify SentimentTrendProtocol and SentimentTrendResult are exported."""

    def test_protocol_in_services_all(self) -> None:
        from core.protocols import services

        assert "SentimentTrendProtocol" in services.__all__

    def test_protocol_in_core_protocols_all(self) -> None:
        from core.protocols import __all__ as core_all

        assert "SentimentTrendProtocol" in core_all

    def test_result_in_trend_module_all(self) -> None:
        from modules.trend import __all__ as trend_all

        assert "SentimentTrendResult" in trend_all


class TestProtocolMethodSignatures:
    """Verify Protocol method signatures match spec (R-sentiment-001) — strict."""

    def test_analyze_trend_signature(self) -> None:
        """analyze_trend(entity_name=None, community_id=None, window_days=7)
        per spec R-sentiment-001.
        """
        import inspect

        sig = inspect.signature(SentimentTrendProtocol.analyze_trend)
        params = list(sig.parameters.keys())
        assert params == [
            "self",
            "entity_name",
            "community_id",
            "window_days",
        ], f"Expected [self, entity_name, community_id, window_days], got {params}"
        # entity_name / community_id default to None
        assert sig.parameters["entity_name"].default is None
        assert sig.parameters["community_id"].default is None
        # window_days defaults to 7 (spec R-sentiment-001)
        assert sig.parameters["window_days"].default == 7
