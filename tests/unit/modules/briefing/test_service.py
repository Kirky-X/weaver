# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for DailyBriefingService (T008).

Verifies R-briefing-002 (service implements DailyBriefingProtocol):
- generate_briefing delegates to BriefingGenerator + maps dict → BriefingResult
- get_briefing queries storage + maps dict → BriefingResult | None
- list_briefings queries storage + maps list[dict] → list[BriefingResult]
- narrative_mode is always False in T008 (T021 will implement narrative mode)

Service does NOT re-implement BriefingGenerator core logic — it delegates
(Rule 8: reuse existing implementations). Templates (R-briefing-003) are
defined in templates.py for future category-specific prompt usage (T021+
narrative mode); T008 generate_briefing reuses BriefingGenerator's generic
briefing.toml prompt.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.protocols.services import DailyBriefingProtocol
from modules.briefing.models import BriefingResult
from modules.briefing.service import BriefingAlreadyExistsError, DailyBriefingService


def _make_generator_return(
    briefing_date: date,
    category: str,
    briefing_id: int | None = 42,
    summary: str | None = "test summary",
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


def _make_storage_briefing_dict(
    briefing_date: date,
    category: str,
    briefing_id: int = 42,
    summary: str | None = "persisted summary",
    items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a dict matching AnalyticsStorage.get_briefing() return shape."""
    return {
        "id": briefing_id,
        "briefing_date": briefing_date,
        "category": category,
        "summary": summary,
        "items": items if items is not None else [],
        "generated_at": datetime.now(UTC),
    }


class TestDailyBriefingServiceImplementsProtocol:
    """Verify DailyBriefingService satisfies DailyBriefingProtocol (R-briefing-002)."""

    def test_service_satisfies_protocol(self) -> None:
        """DailyBriefingService MUST satisfy DailyBriefingProtocol."""
        mock_generator = MagicMock()
        mock_storage = MagicMock()
        # Provide AsyncMock for all 4 storage methods (Protocol members)
        for method in (
            "fetch_articles_for_briefing",
            "save_briefing",
            "get_briefing",
            "list_briefings",
        ):
            setattr(mock_storage, method, AsyncMock())

        service = DailyBriefingService(generator=mock_generator, storage=mock_storage)
        assert isinstance(service, DailyBriefingProtocol)


class TestGenerateBriefing:
    """Test DailyBriefingService.generate_briefing (R-briefing-002)."""

    @pytest.mark.asyncio
    async def test_delegates_to_generator_and_maps_to_briefing_result(self) -> None:
        """generate_briefing calls generator.generate(date, category) and maps dict → BriefingResult."""
        target_date = date(2026, 7, 17)
        mock_generator = MagicMock()
        mock_generator.generate = AsyncMock(
            return_value=_make_generator_return(
                briefing_date=target_date,
                category="finance",
                briefing_id=42,
                summary="Market overview",
                items=[{"article_id": "abc-123", "rank": 1, "score": 0.9}],
            )
        )
        mock_storage = MagicMock()
        mock_storage.get_briefing = AsyncMock(return_value=None)

        service = DailyBriefingService(generator=mock_generator, storage=mock_storage)
        result = await service.generate_briefing(target_date, "finance")

        mock_generator.generate.assert_awaited_once_with(target_date, "finance")
        assert isinstance(result, BriefingResult)
        assert result.date == target_date
        assert result.category == "finance"
        assert result.summary == "Market overview"
        assert result.briefing_id == 42
        assert len(result.items) == 1
        assert result.items[0]["article_id"] == "abc-123"

    @pytest.mark.asyncio
    async def test_default_category_none_is_passed_through(self) -> None:
        """category=None is passed to generator (generator normalizes to 'general')."""
        target_date = date(2026, 7, 17)
        mock_generator = MagicMock()
        mock_generator.generate = AsyncMock(
            return_value=_make_generator_return(
                briefing_date=target_date,
                category="general",  # generator normalizes None → 'general'
                briefing_id=None,
                summary=None,
                items=[],
            )
        )
        mock_storage = MagicMock()
        mock_storage.get_briefing = AsyncMock(return_value=None)

        service = DailyBriefingService(generator=mock_generator, storage=mock_storage)
        result = await service.generate_briefing(target_date, None)

        mock_generator.generate.assert_awaited_once_with(target_date, None)
        assert result.category == "general"
        assert result.briefing_id is None
        assert result.summary is None
        assert result.items == []

    @pytest.mark.asyncio
    async def test_narrative_mode_always_false_in_t008(self) -> None:
        """T008 does not implement narrative mode — BriefingResult.narrative_mode is always False.

        Per spec R-briefing-008 + T021 (future): narrative_mode=True requires
        NarrativeBriefingGenerator which is not implemented in T008. T008
        generate_briefing does not accept narrative_mode parameter; the
        BriefingResult returned always has narrative_mode=False.
        """
        target_date = date(2026, 7, 17)
        mock_generator = MagicMock()
        mock_generator.generate = AsyncMock(
            return_value=_make_generator_return(
                briefing_date=target_date,
                category="general",
                briefing_id=1,
                summary="x",
                items=[],
            )
        )
        mock_storage = MagicMock()
        mock_storage.get_briefing = AsyncMock(return_value=None)

        service = DailyBriefingService(generator=mock_generator, storage=mock_storage)
        result = await service.generate_briefing(target_date)

        assert result.narrative_mode is False

    @pytest.mark.asyncio
    async def test_generated_at_preserved_from_generator(self) -> None:
        """generated_at field is mapped from generator's dict (not regenerated)."""
        target_date = date(2026, 7, 17)
        fixed_ts = datetime(2026, 7, 17, 8, 0, 0, tzinfo=UTC)
        mock_generator = MagicMock()
        mock_generator.generate = AsyncMock(
            return_value={
                "id": 1,
                "briefing_date": target_date,
                "category": "general",
                "summary": "x",
                "items": [],
                "total_items": 0,
                "generated_at": fixed_ts,
            }
        )
        mock_storage = MagicMock()
        mock_storage.get_briefing = AsyncMock(return_value=None)

        service = DailyBriefingService(generator=mock_generator, storage=mock_storage)
        result = await service.generate_briefing(target_date)

        assert result.generated_at == fixed_ts

    @pytest.mark.asyncio
    async def test_propagates_generator_value_error_for_invalid_category(self) -> None:
        """Invalid category raises ValueError from generator (Rule 12: fail loud).

        Note: existence check (storage.get_briefing) is performed before
        generator.generate(). Invalid category raises ValueError only when
        generator is reached — so this test mocks storage.get_briefing to
        return None (no existing briefing) before generator raises.
        """
        target_date = date(2026, 7, 17)
        mock_generator = MagicMock()
        mock_generator.generate = AsyncMock(side_effect=ValueError("Invalid category 'sports'"))
        mock_storage = MagicMock()
        mock_storage.get_briefing = AsyncMock(return_value=None)

        service = DailyBriefingService(generator=mock_generator, storage=mock_storage)
        with pytest.raises(ValueError, match="Invalid category"):
            await service.generate_briefing(target_date, "sports")


class TestGetBriefing:
    """Test DailyBriefingService.get_briefing (R-briefing-002)."""

    @pytest.mark.asyncio
    async def test_returns_none_when_storage_returns_none(self) -> None:
        """get_briefing returns None when no persisted briefing exists."""
        target_date = date(2026, 7, 17)
        mock_generator = MagicMock()
        mock_storage = MagicMock()
        mock_storage.get_briefing = AsyncMock(return_value=None)

        service = DailyBriefingService(generator=mock_generator, storage=mock_storage)
        result = await service.get_briefing(target_date, "finance")

        mock_storage.get_briefing.assert_awaited_once_with(
            briefing_date=target_date, category="finance"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_briefing_result_when_found(self) -> None:
        """get_briefing maps storage dict → BriefingResult when found."""
        target_date = date(2026, 7, 17)
        mock_generator = MagicMock()
        mock_storage = MagicMock()
        mock_storage.get_briefing = AsyncMock(
            return_value=_make_storage_briefing_dict(
                briefing_date=target_date,
                category="finance",
                briefing_id=42,
                summary="Persisted market overview",
                items=[{"article_id": "abc-123", "rank": 1, "score": 0.9}],
            )
        )

        service = DailyBriefingService(generator=mock_generator, storage=mock_storage)
        result = await service.get_briefing(target_date, "finance")

        assert isinstance(result, BriefingResult)
        assert result.date == target_date
        assert result.category == "finance"
        assert result.summary == "Persisted market overview"
        assert result.briefing_id == 42
        assert len(result.items) == 1
        assert result.narrative_mode is False  # storage doesn't track narrative_mode

    @pytest.mark.asyncio
    async def test_default_category_none_normalized_to_general(self) -> None:
        """category=None is normalized to 'general' before calling storage.

        Spec R-briefing-001: category=None means 综合 (general). Service
        normalizes None → 'general' before calling storage.get_briefing,
        consistent with BriefingGenerator.generate() normalization.
        """
        target_date = date(2026, 7, 17)
        mock_generator = MagicMock()
        mock_storage = MagicMock()
        mock_storage.get_briefing = AsyncMock(
            return_value=_make_storage_briefing_dict(
                briefing_date=target_date,
                category="general",
            )
        )

        service = DailyBriefingService(generator=mock_generator, storage=mock_storage)
        await service.get_briefing(target_date, None)

        # storage receives normalized 'general', not None
        mock_storage.get_briefing.assert_awaited_once_with(
            briefing_date=target_date, category="general"
        )


class TestListBriefings:
    """Test DailyBriefingService.list_briefings (R-briefing-002)."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_briefings(self) -> None:
        """list_briefings returns [] when storage returns []."""
        date_from = date(2026, 7, 1)
        date_to = date(2026, 7, 17)
        mock_generator = MagicMock()
        mock_storage = MagicMock()
        mock_storage.list_briefings = AsyncMock(return_value=[])

        service = DailyBriefingService(generator=mock_generator, storage=mock_storage)
        result = await service.list_briefings(date_from, date_to)

        mock_storage.list_briefings.assert_awaited_once_with(date_from=date_from, date_to=date_to)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_list_of_briefing_results(self) -> None:
        """list_briefings maps list[dict] → list[BriefingResult]."""
        date_from = date(2026, 7, 1)
        date_to = date(2026, 7, 17)
        d1 = date(2026, 7, 17)
        d2 = date(2026, 7, 16)
        mock_generator = MagicMock()
        mock_storage = MagicMock()
        mock_storage.list_briefings = AsyncMock(
            return_value=[
                _make_storage_briefing_dict(briefing_date=d1, category="finance"),
                _make_storage_briefing_dict(briefing_date=d2, category="tech"),
            ]
        )

        service = DailyBriefingService(generator=mock_generator, storage=mock_storage)
        result = await service.list_briefings(date_from, date_to)

        assert len(result) == 2
        assert all(isinstance(r, BriefingResult) for r in result)
        assert result[0].date == d1
        assert result[0].category == "finance"
        assert result[1].date == d2
        assert result[1].category == "tech"

    @pytest.mark.asyncio
    async def test_passes_date_range_to_storage(self) -> None:
        """date_from and date_to are passed through to storage."""
        date_from = date(2026, 7, 1)
        date_to = date(2026, 7, 31)
        mock_generator = MagicMock()
        mock_storage = MagicMock()
        mock_storage.list_briefings = AsyncMock(return_value=[])

        service = DailyBriefingService(generator=mock_generator, storage=mock_storage)
        await service.list_briefings(date_from, date_to)

        mock_storage.list_briefings.assert_awaited_once_with(date_from=date_from, date_to=date_to)


class TestGenerateBriefingAlreadyExists:
    """Test DailyBriefingService.generate_briefing existence check (R-briefing-005 fix).

    修复场景：当日已有简报时，POST /api/v1/briefings/daily/generate 之前返回
    HTTP 500（DuckDB ConstraintException: Duplicate key）。现引入业务异常
    BriefingAlreadyExistsError，service 层在调用 generator 之前先检查存在性，
    endpoint 层捕获并返回 409 Conflict。

    同时处理 race condition：并发请求可能同时通过存在性检查，generator 内部
    INSERT 仍会抛 SQLAlchemy IntegrityError → service 转换为 BriefingAlreadyExistsError。

    覆盖场景（Rule 24 — 不简化实现）：
    1. storage.get_briefing 返回已存在 briefing → 抛 BriefingAlreadyExistsError
    2. category=None 在存在性检查前归一化为 'general'
    3. storage.get_briefing 返回 None → 正常调用 generator
    4. generator 抛 SQLAlchemy IntegrityError（race condition）→ 转 BriefingAlreadyExistsError
    5. 非 IntegrityError 的存储错误 → 直接传播（Rule 12）
    6. 存在性检查本身的存储错误 → 直接传播（Rule 12）
    """

    @pytest.mark.asyncio
    async def test_raises_briefing_already_exists_when_existing_briefing_found(self) -> None:
        """Storage 返回已存在的 briefing → 抛 BriefingAlreadyExistsError，不调用 generator。"""
        target_date = date(2026, 7, 19)
        mock_storage = MagicMock()
        mock_storage.get_briefing = AsyncMock(
            return_value=_make_storage_briefing_dict(
                briefing_date=target_date,
                category="general",
                briefing_id=99,
            )
        )
        mock_generator = MagicMock()
        mock_generator.generate = AsyncMock(
            return_value=_make_generator_return(
                briefing_date=target_date,
                category="general",
                briefing_id=42,
            )
        )

        service = DailyBriefingService(generator=mock_generator, storage=mock_storage)

        with pytest.raises(BriefingAlreadyExistsError) as exc_info:
            await service.generate_briefing(target_date, "general")

        # 异常携带冲突的 date + category 信息，供 endpoint 构造 409 响应
        assert exc_info.value.briefing_date == target_date
        assert exc_info.value.category == "general"
        # 关键：已存在时 generator MUST NOT 被调用，避免触发 Duplicate key 错误
        mock_generator.generate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_normalizes_category_none_to_general_before_existence_check(self) -> None:
        """category=None 在存在性检查前归一化为 'general'（spec R-briefing-001）。

        与 get_briefing 的归一化保持一致：避免 None 与 'general' 视为不同
        category，导致存在性检查漏判（已存在 general 简报但被当成 None 检查）。
        """
        target_date = date(2026, 7, 19)
        mock_storage = MagicMock()
        mock_storage.get_briefing = AsyncMock(
            return_value=_make_storage_briefing_dict(
                briefing_date=target_date,
                category="general",
            )
        )
        mock_generator = MagicMock()
        mock_generator.generate = AsyncMock(
            return_value=_make_generator_return(
                briefing_date=target_date,
                category="general",
            )
        )

        service = DailyBriefingService(generator=mock_generator, storage=mock_storage)

        with pytest.raises(BriefingAlreadyExistsError):
            await service.generate_briefing(target_date, None)

        # storage.get_briefing 收到归一化后的 'general'，不是 None
        mock_storage.get_briefing.assert_awaited_once_with(
            briefing_date=target_date, category="general"
        )

    @pytest.mark.asyncio
    async def test_no_existing_briefing_proceeds_with_generation(self) -> None:
        """Storage 返回 None → 正常调用 generator 生成（happy path）。"""
        target_date = date(2026, 7, 19)
        mock_storage = MagicMock()
        mock_storage.get_briefing = AsyncMock(return_value=None)
        mock_generator = MagicMock()
        mock_generator.generate = AsyncMock(
            return_value=_make_generator_return(
                briefing_date=target_date,
                category="general",
                briefing_id=42,
                summary="Daily summary",
            )
        )

        service = DailyBriefingService(generator=mock_generator, storage=mock_storage)
        result = await service.generate_briefing(target_date, "general")

        mock_storage.get_briefing.assert_awaited_once_with(
            briefing_date=target_date, category="general"
        )
        mock_generator.generate.assert_awaited_once_with(target_date, "general")
        assert isinstance(result, BriefingResult)
        assert result.briefing_id == 42
        assert result.summary == "Daily summary"

    @pytest.mark.asyncio
    async def test_integrity_error_during_generation_converted_to_briefing_already_exists(
        self,
    ) -> None:
        """Race condition: INSERT 抛 SQLAlchemy IntegrityError → 转 BriefingAlreadyExistsError.

        场景：两个并发请求同时通过存在性检查（都看到无已有简报），
        其中一个先 INSERT 成功，另一个 INSERT 时触发 unique constraint
        violation（DuckDB ConstraintException / PostgreSQL UniqueViolation），
        SQLAlchemy 包装为 IntegrityError。Service 捕获并转换为
        BriefingAlreadyExistsError，避免 endpoint 层返回 500。
        """
        from sqlalchemy.exc import IntegrityError

        target_date = date(2026, 7, 19)
        mock_storage = MagicMock()
        # 存在性检查通过（无已存在）— race condition 场景
        mock_storage.get_briefing = AsyncMock(return_value=None)
        mock_generator = MagicMock()
        mock_generator.generate = AsyncMock(
            side_effect=IntegrityError(
                "INSERT INTO daily_briefings ... Duplicate key",
                params=None,
                orig=Exception('Duplicate key "briefing_date: 2026-07-19, category: general"'),
            )
        )

        service = DailyBriefingService(generator=mock_generator, storage=mock_storage)

        with pytest.raises(BriefingAlreadyExistsError) as exc_info:
            await service.generate_briefing(target_date, "general")

        assert exc_info.value.briefing_date == target_date
        assert exc_info.value.category == "general"
        # 原 IntegrityError 作为 __cause__ 保留，便于排查
        assert isinstance(exc_info.value.__cause__, IntegrityError)

    @pytest.mark.asyncio
    async def test_other_storage_errors_propagate_not_converted(self) -> None:
        """非 IntegrityError 的存储错误必须传播（Rule 12），不转换为 BriefingAlreadyExistsError。

        例如：DB 连接断开、序列化错误等。这些错误是真正的 500 错误，
        不应被错误地映射为 409。
        """
        target_date = date(2026, 7, 19)
        mock_storage = MagicMock()
        mock_storage.get_briefing = AsyncMock(return_value=None)
        mock_generator = MagicMock()
        mock_generator.generate = AsyncMock(side_effect=RuntimeError("DB connection lost"))

        service = DailyBriefingService(generator=mock_generator, storage=mock_storage)

        with pytest.raises(RuntimeError, match="DB connection lost"):
            await service.generate_briefing(target_date, "general")

    @pytest.mark.asyncio
    async def test_existence_check_storage_failure_propagates(self) -> None:
        """存在性检查本身的存储错误必须传播（Rule 12），不调用 generator。

        存在性检查失败时无法判断是否已有简报，应让 endpoint 返回 500，
        而不是猜测成功或失败。Generator MUST NOT 被调用，避免在不确定
        状态下进行 INSERT。
        """
        target_date = date(2026, 7, 19)
        mock_storage = MagicMock()
        mock_storage.get_briefing = AsyncMock(side_effect=RuntimeError("storage down"))
        mock_generator = MagicMock()
        mock_generator.generate = AsyncMock(
            return_value=_make_generator_return(
                briefing_date=target_date,
                category="general",
            )
        )

        service = DailyBriefingService(generator=mock_generator, storage=mock_storage)

        with pytest.raises(RuntimeError, match="storage down"):
            await service.generate_briefing(target_date, "general")

        # 存在性检查失败时 generator MUST NOT 被调用
        mock_generator.generate.assert_not_awaited()
