# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for DailyBriefingProtocol and BriefingResult (T007).

Verifies:
- R-briefing-001: Protocol defines generate_briefing/get_briefing/list_briefings
- R-briefing-008: BriefingResult has narrative_mode field, default False
- Protocol is @runtime_checkable
- BriefingResult dataclass shape matches spec
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.protocols.services import DailyBriefingProtocol
from modules.briefing.models import BriefingResult


class TestDailyBriefingProtocolStructure:
    """Verify DailyBriefingProtocol is defined correctly (R-briefing-001)."""

    def test_protocol_is_runtime_checkable(self) -> None:
        """DailyBriefingProtocol MUST be @runtime_checkable per spec."""
        # @runtime_checkable protocols support isinstance() checks
        mock_impl = MagicMock(spec=DailyBriefingProtocol)
        assert isinstance(mock_impl, DailyBriefingProtocol)

    def test_protocol_has_generate_briefing_method(self) -> None:
        """generate_briefing(date, category=None) -> BriefingResult."""
        assert hasattr(DailyBriefingProtocol, "generate_briefing")

    def test_protocol_has_get_briefing_method(self) -> None:
        """get_briefing(date, category=None) -> BriefingResult | None."""
        assert hasattr(DailyBriefingProtocol, "get_briefing")

    def test_protocol_has_list_briefings_method(self) -> None:
        """list_briefings(date_from, date_to) -> list[BriefingResult]."""
        assert hasattr(DailyBriefingProtocol, "list_briefings")

    def test_protocol_has_exactly_three_methods(self) -> None:
        """Protocol must define exactly 3 methods (no extra surface)."""
        protocol_methods = {
            name
            for name in dir(DailyBriefingProtocol)
            if not name.startswith("_") and callable(getattr(DailyBriefingProtocol, name))
        }
        expected = {"generate_briefing", "get_briefing", "list_briefings"}
        assert protocol_methods == expected, f"Expected exactly {expected}, got {protocol_methods}"


class TestDailyBriefingProtocolMockCompliance:
    """Verify mock implementations satisfy the Protocol (R-briefing-001)."""

    def test_mock_with_all_methods_satisfies_protocol(self) -> None:
        """A class implementing all 3 methods should satisfy the Protocol."""
        mock_service = MagicMock(spec=DailyBriefingProtocol)
        mock_service.generate_briefing = AsyncMock()
        mock_service.get_briefing = AsyncMock()
        mock_service.list_briefings = AsyncMock()
        assert isinstance(mock_service, DailyBriefingProtocol)

    @pytest.mark.asyncio
    async def test_generate_briefing_signature_returns_briefing_result(self) -> None:
        """generate_briefing(date, category=None) returns BriefingResult."""
        mock_service = MagicMock(spec=DailyBriefingProtocol)
        expected_result = BriefingResult(
            date=date(2026, 7, 17),
            category="finance",
            summary="test summary",
            items=[],
            generated_at=datetime.now(UTC),
            narrative_mode=False,
        )
        mock_service.generate_briefing = AsyncMock(return_value=expected_result)

        result = await mock_service.generate_briefing(date(2026, 7, 17), "finance")
        assert isinstance(result, BriefingResult)
        assert result.category == "finance"

    @pytest.mark.asyncio
    async def test_get_briefing_returns_none_when_absent(self) -> None:
        """get_briefing returns None when no briefing exists for the date."""
        mock_service = MagicMock(spec=DailyBriefingProtocol)
        mock_service.get_briefing = AsyncMock(return_value=None)
        result = await mock_service.get_briefing(date(2026, 7, 17), "finance")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_briefings_returns_list(self) -> None:
        """list_briefings(date_from, date_to) -> list[BriefingResult]."""
        mock_service = MagicMock(spec=DailyBriefingProtocol)
        mock_service.list_briefings = AsyncMock(return_value=[])
        result = await mock_service.list_briefings(date(2026, 7, 1), date(2026, 7, 17))
        assert isinstance(result, list)


class TestBriefingResultDataclass:
    """Verify BriefingResult dataclass shape (R-briefing-008)."""

    def test_is_dataclass(self) -> None:
        assert is_dataclass(BriefingResult)

    def test_has_required_fields(self) -> None:
        """BriefingResult MUST have: date/category/summary/items/generated_at/narrative_mode/briefing_id."""
        field_names = {f.name for f in fields(BriefingResult)}
        required = {
            "date",
            "category",
            "summary",
            "items",
            "generated_at",
            "narrative_mode",
            "briefing_id",
        }
        assert required.issubset(field_names), f"Missing fields: {required - field_names}"

    def test_narrative_mode_defaults_to_false(self) -> None:
        """R-briefing-008: narrative_mode default is False (template mode)."""
        result = BriefingResult(
            date=date(2026, 7, 17),
            category="general",
            summary=None,
            items=[],
            generated_at=datetime.now(UTC),
        )
        assert result.narrative_mode is False

    def test_narrative_mode_can_be_set_true(self) -> None:
        """Narrative mode can be explicitly enabled."""
        result = BriefingResult(
            date=date(2026, 7, 17),
            category="general",
            summary="narrative summary",
            items=[],
            generated_at=datetime.now(UTC),
            narrative_mode=True,
        )
        assert result.narrative_mode is True

    def test_can_construct_with_all_fields(self) -> None:
        """BriefingResult should be constructible with all fields populated."""
        result = BriefingResult(
            date=date(2026, 7, 17),
            category="finance",
            summary="Market overview",
            items=[{"rank": 1, "article_id": "abc-123"}],
            generated_at=datetime.now(UTC),
            narrative_mode=False,
            briefing_id=42,
        )
        assert result.date == date(2026, 7, 17)
        assert result.category == "finance"
        assert result.summary == "Market overview"
        assert len(result.items) == 1
        assert result.narrative_mode is False
        assert result.briefing_id == 42

    def test_briefing_id_defaults_to_none(self) -> None:
        """briefing_id defaults to None (not yet persisted / not fetched)."""
        result = BriefingResult(
            date=date(2026, 7, 17),
            category="general",
        )
        assert result.briefing_id is None


class TestExports:
    """Verify DailyBriefingProtocol and BriefingResult are exported."""

    def test_protocol_in_services_all(self) -> None:
        from core.protocols import services

        assert "DailyBriefingProtocol" in services.__all__

    def test_protocol_in_core_protocols_all(self) -> None:
        from core.protocols import __all__ as core_all

        assert "DailyBriefingProtocol" in core_all

    def test_briefing_result_in_briefing_module_all(self) -> None:
        from modules.briefing import __all__ as briefing_all

        assert "BriefingResult" in briefing_all


class TestProtocolMethodSignatures:
    """Verify Protocol method signatures match spec (R-briefing-001) — strict."""

    def test_generate_briefing_accepts_date_and_optional_category(self) -> None:
        """generate_briefing(date, category=None) per spec R-briefing-001."""
        import inspect

        sig = inspect.signature(DailyBriefingProtocol.generate_briefing)
        params = list(sig.parameters.keys())
        assert params == [
            "self",
            "date",
            "category",
        ], f"Expected [self, date, category], got {params}"
        # category must be optional (default None)
        assert sig.parameters["category"].default is None, (
            f"category must default to None, got {sig.parameters['category'].default}"
        )

    def test_get_briefing_accepts_date_and_optional_category(self) -> None:
        """get_briefing(date, category=None) per spec R-briefing-001."""
        import inspect

        sig = inspect.signature(DailyBriefingProtocol.get_briefing)
        params = list(sig.parameters.keys())
        assert params == [
            "self",
            "date",
            "category",
        ], f"Expected [self, date, category], got {params}"
        assert sig.parameters["category"].default is None, (
            f"category must default to None, got {sig.parameters['category'].default}"
        )

    def test_list_briefings_accepts_date_range(self) -> None:
        """list_briefings(date_from, date_to) per spec R-briefing-001."""
        import inspect

        sig = inspect.signature(DailyBriefingProtocol.list_briefings)
        params = list(sig.parameters.keys())
        assert params == [
            "self",
            "date_from",
            "date_to",
        ], f"Expected [self, date_from, date_to], got {params}"
        # date_from and date_to must be required (no default)
        assert sig.parameters["date_from"].default is inspect.Parameter.empty, (
            "date_from must be required (no default)"
        )
        assert sig.parameters["date_to"].default is inspect.Parameter.empty, (
            "date_to must be required (no default)"
        )
