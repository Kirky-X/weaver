# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for DailyBriefingService narrative_mode integration (T021 / R-briefing-008).

Verifies R-briefing-008 acceptance:
- narrative_mode=False (default): delegates to BriefingGenerator (T004).
- narrative_mode=True: delegates to NarrativeBriefingGenerator (T020).
- InsufficientNarrativeError caught: degrades to BriefingGenerator + log warning.
- BriefingResult.narrative_mode reflects actual mode used (False on degrade,
  even if request was True — spec R-briefing-008).

Constructor change (T021):
    DailyBriefingService now accepts optional narrative_generator parameter.
    None means narrative mode is unavailable — narrative_mode=True raises
    ValueError (Rule 12: fail loud rather than silently falling back).
    The T009 endpoint constructs DailyBriefingService without narrative_generator;
    T022 removes the 501 挡板 and updates _get_briefing_service() to inject
    NarrativeBriefingGenerator.

Service does NOT re-implement NarrativeBriefingGenerator logic — it delegates
(Rule 8: reuse existing implementations). The try/except InsufficientNarrativeError
is the explicit degradation boundary per spec R-briefing-008.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.briefing.models import BriefingResult
from modules.briefing.narrative import InsufficientNarrativeError
from modules.briefing.service import DailyBriefingService


def _make_generator_return(
    briefing_date: date,
    category: str,
    briefing_id: int | None = 42,
    summary: str | None = "template summary",
    items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a dict matching BriefingGenerator.generate() return shape."""
    return {
        "id": briefing_id,
        "briefing_date": briefing_date,
        "category": category,
        "summary": summary,
        "items": items if items is not None else [],
        "total_items": len(items) if items is not None else 0,
        "generated_at": datetime.now(UTC),
    }


def _make_narrative_generator_return(
    briefing_date: date,
    category: str,
    briefing_id: int | None = 100,
    summary: str | None = "narrative summary",
    items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a dict matching NarrativeBriefingGenerator.generate() return shape."""
    return {
        "id": briefing_id,
        "briefing_date": briefing_date,
        "category": category,
        "summary": summary,
        "items": items if items is not None else [],
        "total_items": len(items) if items is not None else 0,
        "generated_at": datetime.now(UTC),
    }


def _make_mock_generator(return_value: dict[str, Any]) -> MagicMock:
    """Build a mock BriefingGenerator with .generate AsyncMock."""
    gen = MagicMock()
    gen.generate = AsyncMock(return_value=return_value)
    return gen


def _make_mock_narrative_generator(return_value: dict[str, Any]) -> MagicMock:
    """Build a mock NarrativeBriefingGenerator with .generate AsyncMock."""
    gen = MagicMock()
    gen.generate = AsyncMock(return_value=return_value)
    return gen


def _make_mock_storage() -> MagicMock:
    """Build a mock AnalyticsStorage with all 4 Protocol methods."""
    storage = MagicMock()
    for method in (
        "fetch_articles_for_briefing",
        "save_briefing",
        "get_briefing",
        "list_briefings",
    ):
        setattr(storage, method, AsyncMock())
    return storage


class TestNarrativeModeParameter:
    """Verify generate_briefing accepts narrative_mode parameter (R-briefing-008)."""

    @pytest.mark.asyncio
    async def test_narrative_mode_false_defaults_to_template_generator(self) -> None:
        """narrative_mode=False (default) → BriefingGenerator is called."""
        target_date = date(2026, 7, 17)
        mock_template = _make_mock_generator(
            _make_generator_return(target_date, "finance", summary="template")
        )
        mock_narrative = _make_mock_narrative_generator(
            _make_narrative_generator_return(target_date, "finance", summary="narrative")
        )
        service = DailyBriefingService(
            generator=mock_template,
            storage=_make_mock_storage(),
            narrative_generator=mock_narrative,
        )

        result = await service.generate_briefing(
            date=target_date, category="finance", narrative_mode=False
        )

        mock_template.generate.assert_awaited_once_with(target_date, "finance")
        mock_narrative.generate.assert_not_awaited()
        assert isinstance(result, BriefingResult)
        assert result.summary == "template"
        assert result.narrative_mode is False

    @pytest.mark.asyncio
    async def test_narrative_mode_true_uses_narrative_generator(self) -> None:
        """narrative_mode=True → NarrativeBriefingGenerator is called."""
        target_date = date(2026, 7, 17)
        mock_template = _make_mock_generator(
            _make_generator_return(target_date, "finance", summary="template")
        )
        mock_narrative = _make_mock_narrative_generator(
            _make_narrative_generator_return(target_date, "finance", summary="narrative")
        )
        service = DailyBriefingService(
            generator=mock_template,
            storage=_make_mock_storage(),
            narrative_generator=mock_narrative,
        )

        result = await service.generate_briefing(
            date=target_date, category="finance", narrative_mode=True
        )

        mock_narrative.generate.assert_awaited_once_with(target_date, "finance")
        mock_template.generate.assert_not_awaited()
        assert isinstance(result, BriefingResult)
        assert result.summary == "narrative"
        assert result.narrative_mode is True

    @pytest.mark.asyncio
    async def test_default_narrative_mode_is_false(self) -> None:
        """Default narrative_mode is False (R-briefing-008)."""
        target_date = date(2026, 7, 17)
        mock_template = _make_mock_generator(
            _make_generator_return(target_date, "general", summary="template")
        )
        service = DailyBriefingService(
            generator=mock_template,
            storage=_make_mock_storage(),
        )

        result = await service.generate_briefing(date=target_date, category=None)

        mock_template.generate.assert_awaited_once()
        assert result.narrative_mode is False


class TestNarrativeModeDegradation:
    """Verify InsufficientNarrativeError triggers fallback to template mode."""

    @pytest.mark.asyncio
    async def test_insufficient_narrative_falls_back_to_template(self) -> None:
        """InsufficientNarrativeError → degrades to BriefingGenerator + narrative_mode=False."""
        target_date = date(2026, 7, 17)
        # Narrative generator raises InsufficientNarrativeError.
        mock_narrative = MagicMock()
        mock_narrative.generate = AsyncMock(
            side_effect=InsufficientNarrativeError(
                narrative_count=2,
                threshold=3,
                briefing_date=target_date,
                category="finance",
                reason="insufficient NarrativeNode count",
            )
        )
        # Template generator succeeds.
        mock_template = _make_mock_generator(
            _make_generator_return(target_date, "finance", summary="template fallback")
        )
        service = DailyBriefingService(
            generator=mock_template,
            storage=_make_mock_storage(),
            narrative_generator=mock_narrative,
        )

        result = await service.generate_briefing(
            date=target_date, category="finance", narrative_mode=True
        )

        # Both generators called (narrative failed, template succeeded).
        mock_narrative.generate.assert_awaited_once_with(target_date, "finance")
        mock_template.generate.assert_awaited_once_with(target_date, "finance")
        # BriefingResult reflects fallback (narrative_mode=False despite request=True).
        assert result.summary == "template fallback"
        assert result.narrative_mode is False

    @pytest.mark.asyncio
    async def test_degradation_logs_warning_with_reason(self) -> None:
        """InsufficientNarrativeError triggers warning log with reason (Rule 12).

        Project uses loguru (not stdlib logging), so caplog cannot capture
        loguru output. Instead, add a sink to loguru and capture its output.
        """
        from io import StringIO

        from loguru import logger

        target_date = date(2026, 7, 17)
        mock_narrative = MagicMock()
        mock_narrative.generate = AsyncMock(
            side_effect=InsufficientNarrativeError(
                narrative_count=0,
                threshold=3,
                briefing_date=target_date,
                category="tech",
                reason="no articles found for date+category",
            )
        )
        mock_template = _make_mock_generator(
            _make_generator_return(target_date, "tech", summary="template")
        )
        service = DailyBriefingService(
            generator=mock_template,
            storage=_make_mock_storage(),
            narrative_generator=mock_narrative,
        )

        log_buffer = StringIO()
        # Format: level | message — extract level for filtering, message for assert.
        handler_id = logger.add(
            log_buffer,
            level="WARNING",
            format="{level.name} | {message}",
        )
        try:
            await service.generate_briefing(date=target_date, category="tech", narrative_mode=True)
        finally:
            logger.remove(handler_id)

        # Rule 12: failure must be visible — warning log must contain reason.
        captured = log_buffer.getvalue()
        assert "WARNING" in captured, f"expected WARNING in log, got: {captured!r}"
        # The warning must reference narrative/insufficient/fallback/degradation.
        msg = captured.lower()
        assert (
            "narrative" in msg or "insufficient" in msg or "fallback" in msg or "degrad" in msg
        ), f"warning must reference narrative/fallback, got: {captured!r}"

    @pytest.mark.asyncio
    async def test_narrative_generator_unexpected_error_propagates(self) -> None:
        """Non-InsufficientNarrativeError errors propagate (Rule 12 — fail loud).

        InsufficientNarrativeError is the ONLY expected failure mode for
        narrative generation (data insufficiency → degrade). Other exceptions
        (RuntimeError from graph DB, TypeError from bugs) must propagate
        rather than be silently caught.
        """
        target_date = date(2026, 7, 17)
        mock_narrative = MagicMock()
        mock_narrative.generate = AsyncMock(side_effect=RuntimeError("graph DB connection lost"))
        mock_template = _make_mock_generator(
            _make_generator_return(target_date, "finance", summary="template")
        )
        service = DailyBriefingService(
            generator=mock_template,
            storage=_make_mock_storage(),
            narrative_generator=mock_narrative,
        )

        with pytest.raises(RuntimeError, match="graph DB connection lost"):
            await service.generate_briefing(
                date=target_date, category="finance", narrative_mode=True
            )

        # Template generator MUST NOT be called — degradation is only for
        # InsufficientNarrativeError, not for unexpected errors.
        mock_template.generate.assert_not_awaited()


class TestNarrativeGeneratorUnavailable:
    """Verify narrative_mode=True without narrative_generator fails loud."""

    @pytest.mark.asyncio
    async def test_narrative_mode_true_without_generator_raises_value_error(self) -> None:
        """narrative_mode=True + narrative_generator=None → ValueError (Rule 12).

        Caller (T009 endpoint in T022) MUST inject NarrativeBriefingGenerator
        when constructing DailyBriefingService if narrative_mode is supported.
        Requesting narrative mode without the generator is a programming error.
        """
        target_date = date(2026, 7, 17)
        mock_template = _make_mock_generator(
            _make_generator_return(target_date, "finance", summary="template")
        )
        service = DailyBriefingService(
            generator=mock_template,
            storage=_make_mock_storage(),
            narrative_generator=None,
        )

        with pytest.raises(ValueError, match="narrative_generator"):
            await service.generate_briefing(
                date=target_date, category="finance", narrative_mode=True
            )

        # Template generator MUST NOT be called — fail before any DB access.
        mock_template.generate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_narrative_mode_false_without_generator_succeeds(self) -> None:
        """narrative_mode=False + narrative_generator=None → works (backward compat).

        Existing T008/T009 code constructs DailyBriefingService without
        narrative_generator — this MUST continue to work for narrative_mode=False.
        """
        target_date = date(2026, 7, 17)
        mock_template = _make_mock_generator(
            _make_generator_return(target_date, "finance", summary="template")
        )
        service = DailyBriefingService(
            generator=mock_template,
            storage=_make_mock_storage(),
            # narrative_generator omitted → defaults to None
        )

        result = await service.generate_briefing(
            date=target_date, category="finance", narrative_mode=False
        )

        mock_template.generate.assert_awaited_once()
        assert result.narrative_mode is False


class TestNarrativeModeForwarding:
    """Verify generate_briefing forwards date + category to both generators."""

    @pytest.mark.asyncio
    async def test_narrative_generator_receives_date_and_category(self) -> None:
        """NarrativeBriefingGenerator.generate(date, category) called with same args."""
        target_date = date(2026, 7, 17)
        mock_template = _make_mock_generator(
            _make_generator_return(target_date, "tech", summary="template")
        )
        mock_narrative = _make_mock_narrative_generator(
            _make_narrative_generator_return(target_date, "tech", summary="narrative")
        )
        service = DailyBriefingService(
            generator=mock_template,
            storage=_make_mock_storage(),
            narrative_generator=mock_narrative,
        )

        await service.generate_briefing(date=target_date, category="tech", narrative_mode=True)

        # Verify both date and category forwarded (not None, not swapped).
        call_args = mock_narrative.generate.call_args.args
        assert call_args[0] == target_date
        assert call_args[1] == "tech"

    @pytest.mark.asyncio
    async def test_none_category_forwarded_as_is_to_narrative(self) -> None:
        """None category is forwarded as None (generators normalize internally)."""
        target_date = date(2026, 7, 17)
        mock_template = _make_mock_generator(
            _make_generator_return(target_date, "general", summary="template")
        )
        mock_narrative = _make_mock_narrative_generator(
            _make_narrative_generator_return(target_date, "general", summary="narrative")
        )
        service = DailyBriefingService(
            generator=mock_template,
            storage=_make_mock_storage(),
            narrative_generator=mock_narrative,
        )

        await service.generate_briefing(date=target_date, category=None, narrative_mode=True)

        call_args = mock_narrative.generate.call_args.args
        assert call_args[0] == target_date
        # category is None — NarrativeBriefingGenerator normalizes to 'general'.
        assert call_args[1] is None

    @pytest.mark.asyncio
    async def test_fallback_template_receives_same_date_and_category(self) -> None:
        """On degradation, BriefingGenerator receives same date + category."""
        target_date = date(2026, 7, 17)
        mock_narrative = MagicMock()
        mock_narrative.generate = AsyncMock(
            side_effect=InsufficientNarrativeError(
                narrative_count=1,
                threshold=3,
                briefing_date=target_date,
                category="ai",
                reason="insufficient",
            )
        )
        mock_template = _make_mock_generator(
            _make_generator_return(target_date, "ai", summary="template fallback")
        )
        service = DailyBriefingService(
            generator=mock_template,
            storage=_make_mock_storage(),
            narrative_generator=mock_narrative,
        )

        await service.generate_briefing(date=target_date, category="ai", narrative_mode=True)

        # Template generator receives the SAME date + category as narrative.
        template_call_args = mock_template.generate.call_args.args
        assert template_call_args[0] == target_date
        assert template_call_args[1] == "ai"


class TestBriefingResultNarrativeModeField:
    """Verify BriefingResult.narrative_mode reflects actual mode used."""

    @pytest.mark.asyncio
    async def test_narrative_success_sets_narrative_mode_true(self) -> None:
        """Successful narrative generation → BriefingResult.narrative_mode=True."""
        target_date = date(2026, 7, 17)
        mock_narrative = _make_mock_narrative_generator(
            _make_narrative_generator_return(target_date, "finance", summary="narrative")
        )
        service = DailyBriefingService(
            generator=_make_mock_generator(
                _make_generator_return(target_date, "finance", summary="template")
            ),
            storage=_make_mock_storage(),
            narrative_generator=mock_narrative,
        )

        result = await service.generate_briefing(
            date=target_date, category="finance", narrative_mode=True
        )

        assert result.narrative_mode is True

    @pytest.mark.asyncio
    async def test_degradation_sets_narrative_mode_false(self) -> None:
        """Degradation → BriefingResult.narrative_mode=False (R-briefing-008)."""
        target_date = date(2026, 7, 17)
        mock_narrative = MagicMock()
        mock_narrative.generate = AsyncMock(
            side_effect=InsufficientNarrativeError(
                narrative_count=2,
                threshold=3,
                briefing_date=target_date,
                category="finance",
                reason="insufficient",
            )
        )
        mock_template = _make_mock_generator(
            _make_generator_return(target_date, "finance", summary="template")
        )
        service = DailyBriefingService(
            generator=mock_template,
            storage=_make_mock_storage(),
            narrative_generator=mock_narrative,
        )

        result = await service.generate_briefing(
            date=target_date, category="finance", narrative_mode=True
        )

        # Spec R-briefing-008: 降级发生时 BriefingResult.narrative_mode 字段为 False
        # (即使请求是 True)
        assert result.narrative_mode is False

    @pytest.mark.asyncio
    async def test_template_mode_sets_narrative_mode_false(self) -> None:
        """narrative_mode=False → BriefingResult.narrative_mode=False."""
        target_date = date(2026, 7, 17)
        mock_template = _make_mock_generator(
            _make_generator_return(target_date, "finance", summary="template")
        )
        service = DailyBriefingService(
            generator=mock_template,
            storage=_make_mock_storage(),
        )

        result = await service.generate_briefing(
            date=target_date, category="finance", narrative_mode=False
        )

        assert result.narrative_mode is False
