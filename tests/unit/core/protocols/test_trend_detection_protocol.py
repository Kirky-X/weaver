# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for TrendDetectionProtocol and TrendDetectionResult (T014 / R-trend-001).

Verifies:
- R-trend-001: Protocol defines detect_trends method
- TrendDetectionResult dataclass has 5 fields per spec:
  window_days / entity_type / trends / list / status
- Protocol is @runtime_checkable
- status ∈ {'ok', 'insufficient_data'}
- Default values reflect "no data" state (R-trend-003):
  trends=[], list=[], status='insufficient_data' is the explicit no-data state;
  status='ok' represents the data-sufficient state.
- detect_trends signature: detect_trends(window_days=7, entity_type=None)
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.protocols.services import TrendDetectionProtocol
from modules.trend.models import TrendDetectionResult


class TestTrendDetectionProtocolStructure:
    """Verify TrendDetectionProtocol is defined correctly (R-trend-001)."""

    def test_protocol_is_runtime_checkable(self) -> None:
        """TrendDetectionProtocol MUST be @runtime_checkable per spec."""
        mock_impl = MagicMock(spec=TrendDetectionProtocol)
        assert isinstance(mock_impl, TrendDetectionProtocol)

    def test_protocol_has_detect_trends_method(self) -> None:
        """detect_trends method exists on the Protocol."""
        assert hasattr(TrendDetectionProtocol, "detect_trends")

    def test_protocol_has_exactly_one_method(self) -> None:
        """Protocol defines exactly 1 method (no extra surface)."""
        protocol_methods = {
            name
            for name in dir(TrendDetectionProtocol)
            if not name.startswith("_") and callable(getattr(TrendDetectionProtocol, name))
        }
        expected = {"detect_trends"}
        assert protocol_methods == expected, f"Expected exactly {expected}, got {protocol_methods}"


class TestTrendDetectionProtocolMockCompliance:
    """Verify mock implementations satisfy the Protocol (R-trend-001)."""

    def test_mock_with_detect_trends_satisfies_protocol(self) -> None:
        """A class implementing detect_trends should satisfy the Protocol."""
        mock_service = MagicMock(spec=TrendDetectionProtocol)
        mock_service.detect_trends = AsyncMock()
        assert isinstance(mock_service, TrendDetectionProtocol)

    @pytest.mark.asyncio
    async def test_detect_trends_returns_trend_detection_result(self) -> None:
        """detect_trends(...) returns TrendDetectionResult."""
        mock_service = MagicMock(spec=TrendDetectionProtocol)
        expected = TrendDetectionResult(
            window_days=7,
            entity_type="Person",
            trends=[
                {
                    "entity_name": "OpenAI",
                    "trend_score": 0.5,
                    "direction": "up",
                    "frequency_change": 0.6,
                }
            ],
            list=[{"day": "2026-07-17", "mentions": 12}],
            status="ok",
        )
        mock_service.detect_trends = AsyncMock(return_value=expected)
        result = await mock_service.detect_trends(window_days=7, entity_type="Person")
        assert isinstance(result, TrendDetectionResult)
        assert result.status == "ok"
        assert len(result.trends) == 1
        assert result.trends[0]["entity_name"] == "OpenAI"

    @pytest.mark.asyncio
    async def test_detect_trends_no_data_returns_insufficient_data(self) -> None:
        """R-trend-003: insufficient data scenario returns status='insufficient_data'."""
        mock_service = MagicMock(spec=TrendDetectionProtocol)
        no_data = TrendDetectionResult(
            window_days=7,
            entity_type=None,
            trends=[],
            list=[],
            status="insufficient_data",
        )
        mock_service.detect_trends = AsyncMock(return_value=no_data)
        result = await mock_service.detect_trends(window_days=7)
        assert result.status == "insufficient_data"
        assert result.trends == []
        assert result.list == []


class TestTrendDetectionResultDataclass:
    """Verify TrendDetectionResult dataclass shape (R-trend-001)."""

    def test_is_dataclass(self) -> None:
        assert is_dataclass(TrendDetectionResult)

    def test_has_required_fields(self) -> None:
        """TrendDetectionResult MUST have all 5 fields per spec:
        window_days / entity_type / trends / list / status.
        """
        field_names = {f.name for f in fields(TrendDetectionResult)}
        required = {
            "window_days",
            "entity_type",
            "trends",
            "list",
            "status",
        }
        assert required.issubset(field_names), f"Missing fields: {required - field_names}"

    def test_default_values_reflect_insufficient_data_state(self) -> None:
        """R-trend-003: no-data defaults — trends=[], list=[],
        status='insufficient_data' (explicitly NOT 'ok' to signal absence).
        """
        result = TrendDetectionResult()
        assert result.window_days == 7
        assert result.entity_type is None
        assert result.trends == []
        assert result.list == []
        assert result.status == "insufficient_data"

    def test_can_construct_with_ok_status(self) -> None:
        """TrendDetectionResult should be constructible with status='ok'."""
        result = TrendDetectionResult(
            window_days=30,
            entity_type="Organization",
            trends=[
                {
                    "entity_name": "Acme",
                    "trend_score": -0.5,
                    "direction": "down",
                    "frequency_change": -0.6,
                }
            ],
            list=[{"day": "2026-07-17", "mentions": 5}],
            status="ok",
        )
        assert result.window_days == 30
        assert result.entity_type == "Organization"
        assert len(result.trends) == 1
        assert len(result.list) == 1
        assert result.status == "ok"

    def test_status_valid_values(self) -> None:
        """status must accept the 2 spec-defined values."""
        for status in ("ok", "insufficient_data"):
            result = TrendDetectionResult(window_days=7, status=status)
            assert result.status == status


class TestProtocolMethodSignatures:
    """Verify Protocol method signatures match spec (R-trend-001) — strict."""

    def test_detect_trends_signature(self) -> None:
        """detect_trends(window_days=7, entity_type=None) per spec R-trend-001."""
        import inspect

        sig = inspect.signature(TrendDetectionProtocol.detect_trends)
        params = list(sig.parameters.keys())
        assert params == [
            "self",
            "window_days",
            "entity_type",
        ], f"Expected [self, window_days, entity_type], got {params}"
        # window_days defaults to 7 (spec R-trend-001)
        assert sig.parameters["window_days"].default == 7
        # entity_type defaults to None
        assert sig.parameters["entity_type"].default is None


class TestExports:
    """Verify TrendDetectionProtocol and TrendDetectionResult are exported."""

    def test_protocol_in_services_all(self) -> None:
        from core.protocols import services

        assert "TrendDetectionProtocol" in services.__all__

    def test_protocol_in_core_protocols_all(self) -> None:
        from core.protocols import __all__ as core_all

        assert "TrendDetectionProtocol" in core_all

    def test_result_in_trend_module_all(self) -> None:
        from modules.trend import __all__ as trend_all

        assert "TrendDetectionResult" in trend_all
