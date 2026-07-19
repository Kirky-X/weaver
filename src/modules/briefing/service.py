# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Daily briefing service — implements DailyBriefingProtocol (T008 / T021 / R-briefing-002 / R-briefing-008).

DailyBriefingService is the service-layer entry point for briefing operations:
- generate_briefing: delegates to BriefingGenerator (T004, template mode)
  or NarrativeBriefingGenerator (T020, narrative mode) and maps the
  returned dict to BriefingResult. Does NOT re-implement generation logic
  (Rule 8: reuse existing implementations).
- get_briefing: queries AnalyticsStorage.get_briefing for a single briefing.
- list_briefings: queries AnalyticsStorage.list_briefings for a date range.

Narrative mode (T021 / R-briefing-008):
- narrative_mode=True routes to NarrativeBriefingGenerator (injected via
  __init__'s optional narrative_generator parameter).
- InsufficientNarrativeError (< 3 NarrativeNodes available) is caught:
  logs a warning and degrades to template mode (BriefingGenerator).
  BriefingResult.narrative_mode is False on degradation, even if the
  request was narrative_mode=True (spec R-briefing-008).
- narrative_mode=True without narrative_generator raises ValueError
  (Rule 12: fail loud). T022 wires NarrativeBriefingGenerator into the
  service factory used by the API endpoint.

Existence check (R-briefing-005 fix — Duplicate key 500 → 409 Conflict):
- generate_briefing 在调用 generator 之前，先调用 storage.get_briefing
  检查 (date, category) 是否已存在。已存在则抛 BriefingAlreadyExistsError，
  避免下游 generator.save_briefing 的 DELETE+INSERT 在 DuckDB 上触发
  ConstraintException（被 endpoint 兜底捕获为 500 错误）。
- 同时捕获 SQLAlchemy IntegrityError 作为 race condition 兜底：并发请求
  可能同时通过存在性检查，其中一个 INSERT 仍会触发 unique constraint
  violation。Service 将 IntegrityError 转换为 BriefingAlreadyExistsError，
  endpoint 层统一返回 409。
- 存在性检查或 generator 的其他存储错误（非 IntegrityError）必须传播
  （Rule 12 fail loud），由 endpoint 返回 500。

Other scope decisions (Rule 24 — no simplified implementation):
- category=None is normalized to 'general' before calling storage, consistent
  with BriefingGenerator.generate() normalization (spec R-briefing-001).
- Storage failures propagate (Rule 12: fail loud). Generator failures
  (LLM degrade) are reflected in the returned BriefingResult.summary=None,
  not raised — this matches BriefingGenerator's spec R-briefing-002 contract.

Templates (R-briefing-003) are defined in templates.py but not consumed by
T008/T021 — BriefingGenerator uses generic briefing.toml prompt. Templates
remain available for future category-specific prompt injection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import IntegrityError

from core.observability import get_logger
from modules.briefing.models import BriefingResult
from modules.briefing.narrative import InsufficientNarrativeError

if TYPE_CHECKING:
    from datetime import date

    from core.protocols import AnalyticsStorageProtocol
    from modules.briefing.generator import BriefingGenerator
    from modules.briefing.narrative import NarrativeBriefingGenerator

log = get_logger(__name__)

# Normalized category for None input (spec R-briefing-001: None 表示综合).
_DEFAULT_CATEGORY: str = "general"


class BriefingAlreadyExistsError(Exception):
    """业务异常：当日 (date, category) 简报已存在（R-briefing-005 fix）。

    抛出场景：
        1. generate_briefing 在调用 generator 之前，先检查 storage.get_briefing
           返回非 None（已存在）→ 直接抛出（业务层防护）。
        2. generate_briefing 在 generator 内部 INSERT 时收到 SQLAlchemy
           IntegrityError（race condition：并发请求同时通过存在性检查，
           后到者触发 unique constraint violation）→ 转换为本异常抛出。

    Endpoint 层（briefings.py generate_daily_briefing）捕获本异常并返回
    HTTP 409 Conflict，避免 DuckDB ConstraintException 被错误映射为 500。

    Attributes:
        briefing_date: 冲突的简报日期。
        category: 冲突的简报 category（normalized 'general' / 'finance' /
            'tech' / 'ai'）。
    """

    def __init__(self, briefing_date: date, category: str) -> None:
        self.briefing_date = briefing_date
        self.category = category
        super().__init__(f"Briefing already exists for date={briefing_date}, category={category}")


class DailyBriefingService:
    """Service-layer entry point for daily briefing operations.

    Implements: DailyBriefingProtocol (core.protocols.services)

    Args:
        generator: BriefingGenerator instance (T004) — used for
            generate_briefing. Generator holds its own storage reference
            for fetch_articles_for_briefing + save_briefing.
        storage: AnalyticsStorageProtocol implementation — used for
            get_briefing + list_briefings (query operations). In production,
            this is the same AnalyticsStorage instance as generator's
            storage; in tests, can be independently mocked.
    """

    def __init__(
        self,
        generator: BriefingGenerator,
        storage: AnalyticsStorageProtocol,
        narrative_generator: NarrativeBriefingGenerator | None = None,
    ) -> None:
        self._generator = generator
        self._storage = storage
        self._narrative_generator = narrative_generator

    async def generate_briefing(
        self,
        date: date,
        category: str | None = None,
        *,
        narrative_mode: bool = False,
    ) -> BriefingResult:
        """Generate (or regenerate) a daily briefing.

        Delegates to BriefingGenerator (template mode) or
        NarrativeBriefingGenerator (narrative mode) per R-briefing-008.

        Existence check (R-briefing-005 fix):
            在调用 generator 之前，先检查 (date, category) 是否已存在。
            已存在则抛 BriefingAlreadyExistsError，避免下游 generator.save_briefing
            的 DELETE+INSERT 在 DuckDB 上触发 ConstraintException（被 endpoint
            兜底捕获为 500）。同时由 ``_generate_with_race_guard`` 统一捕获
            generator 内 INSERT 的 SQLAlchemy IntegrityError（race condition）
            并转换为 BriefingAlreadyExistsError，narrative 与 template 两条
            路径共用同一守护逻辑（MEDIUM-3 DRY）。

        Template mode (narrative_mode=False, default):
            Delegates to BriefingGenerator.generate(date, category) which:
            1. Fetches articles filtered by category
            2. Calls LLM via CallPoint.BRIEFING (degrades to None on LLM failure)
            3. Persists briefing + items via storage.save_briefing
            4. Returns dict with id/briefing_date/category/summary/items/

        Narrative mode (narrative_mode=True):
            Delegates to NarrativeBriefingGenerator.generate(date, category)
            which aggregates NarrativeNode framing across articles (R-briefing-007).
            On InsufficientNarrativeError (< 3 NarrativeNodes available), the
            service logs a warning and degrades to template mode (R-briefing-008).
            BriefingResult.narrative_mode is False on degradation, even if
            the request was narrative_mode=True.

        Args:
            date: The date to generate the briefing for.
            category: Briefing category — one of {finance, tech, ai, general}.
                None means "综合" (general, no article filter).
            narrative_mode: If True, use NarrativeBriefingGenerator.
                Requires narrative_generator to be injected. Defaults to False.

        Returns:
            BriefingResult with all fields populated from generator output.
            narrative_mode field reflects the actual mode used (True only
            when narrative generation succeeded; False on template mode or
            degradation).

        Raises:
            BriefingAlreadyExistsError: If a briefing for (date, category)
                already exists (业务层防护)，或在 generator INSERT 时收到
                IntegrityError（race condition 兜底）。
            ValueError: If narrative_mode=True but narrative_generator is None,
                or if category is invalid (propagated from generator).
            Exception: Other storage failures propagate (Rule 12).
        """
        # Existence check (R-briefing-005 fix):
        # 在调用 generator 前先检查 (date, category) 是否已存在. 已存在则抛
        # BriefingAlreadyExistsError, 避免 generator.save_briefing 的
        # DELETE+INSERT 在 DuckDB 上触发 ConstraintException → endpoint 500.
        # category 在检查前归一化为 'general'(与 get_briefing 一致), 避免
        # None 与 'general' 视为不同 category 导致漏判.
        normalized_category = category or _DEFAULT_CATEGORY
        existing = await self._storage.get_briefing(
            briefing_date=date,
            category=normalized_category,
        )
        if existing is not None:
            log.warning(
                "briefing_already_exists_skip_generation",
                briefing_date=str(date),
                category=normalized_category,
                existing_id=existing.get("id"),
            )
            raise BriefingAlreadyExistsError(briefing_date=date, category=normalized_category)

        if narrative_mode:
            if self._narrative_generator is None:
                raise ValueError(
                    "narrative_mode=True requested but narrative_generator is None. "
                    "Caller must inject NarrativeBriefingGenerator when constructing "
                    "DailyBriefingService to use narrative mode (R-briefing-008)."
                )
            try:
                result_dict = await self._generate_with_race_guard(
                    self._narrative_generator.generate(date, category),
                    briefing_date=date,
                    category=normalized_category,
                    mode_label="narrative",
                )
                return self._map_to_briefing_result(result_dict, narrative_mode=True)
            except InsufficientNarrativeError as exc:
                log.warning(
                    "narrative_briefing_insufficient_fallback_to_template",
                    narrative_count=exc.narrative_count,
                    threshold=exc.threshold,
                    briefing_date=str(exc.briefing_date),
                    category=exc.category,
                    reason=exc.reason,
                )
                # Fall through to template mode (R-briefing-008 degradation).

        result_dict = await self._generate_with_race_guard(
            self._generator.generate(date, category),
            briefing_date=date,
            category=normalized_category,
            mode_label="template",
        )
        return self._map_to_briefing_result(result_dict, narrative_mode=False)

    async def _generate_with_race_guard(
        self,
        generator_coro: Any,
        *,
        briefing_date: date,
        category: str,
        mode_label: str,
    ) -> dict[str, Any]:
        """Run a generator coroutine with race-condition guard.

        Wraps the generator call so that SQLAlchemy ``IntegrityError`` (raised
        when a concurrent request wins the race and INSERTs the same
        (date, category) first) is converted to ``BriefingAlreadyExistsError``.
        This is the single place that translates IntegrityError → 409, so the
        narrative and template code paths share the same guard (MEDIUM-3 DRY
        fix). Non-IntegrityError exceptions propagate unchanged (Rule 12:
        fail loud).

        Args:
            generator_coro: Awaitable returned by ``generator.generate(...)``.
            briefing_date: Briefing date (used for log + exception payload).
            category: Normalized category (used for log + exception payload).
            mode_label: ``"narrative"`` or ``"template"`` — included in the
                log so operators can tell which path hit the race.

        Returns:
            The generator's dict result on success.

        Raises:
            BriefingAlreadyExistsError: If the generator raises
                SQLAlchemy ``IntegrityError`` (unique constraint violation).
            Exception: Any other exception from the generator propagates
                unchanged.
        """
        try:
            return await generator_coro
        except IntegrityError as exc:
            # Race condition: 并发请求同时通过存在性检查, generator INSERT
            # 触发 unique constraint violation(DuckDB ConstraintException
            # / PostgreSQL UniqueViolation, SQLAlchemy 统一为 IntegrityError).
            # 转换为 BriefingAlreadyExistsError, 让 endpoint 返回 409 而非 500.
            log.warning(
                "briefing_integrity_error_race_condition",
                briefing_date=str(briefing_date),
                category=category,
                mode=mode_label,
                error=str(exc),
            )
            raise BriefingAlreadyExistsError(
                briefing_date=briefing_date, category=category
            ) from exc

    async def get_briefing(
        self,
        date: date,
        category: str | None = None,
    ) -> BriefingResult | None:
        """Fetch an existing briefing by (date, category).

        Normalizes category=None → 'general' before querying storage,
        consistent with BriefingGenerator.generate() normalization.

        Args:
            date: The date to fetch.
            category: Briefing category. None means "综合" (general).

        Returns:
            BriefingResult if found, None otherwise.
        """
        normalized_category = category or _DEFAULT_CATEGORY
        result_dict = await self._storage.get_briefing(
            briefing_date=date,
            category=normalized_category,
        )
        if result_dict is None:
            return None
        return self._map_to_briefing_result(result_dict)

    async def list_briefings(
        self,
        date_from: date,
        date_to: date,
    ) -> list[BriefingResult]:
        """List briefings within a date range (inclusive).

        Args:
            date_from: Start date (inclusive).
            date_to: End date (inclusive).

        Returns:
            List of BriefingResult ordered by briefing_date descending.
            Empty list if no briefings in range.
        """
        result_dicts = await self._storage.list_briefings(
            date_from=date_from,
            date_to=date_to,
        )
        return [self._map_to_briefing_result(d) for d in result_dicts]

    @staticmethod
    def _map_to_briefing_result(
        result_dict: dict[str, Any],
        *,
        narrative_mode: bool = False,
    ) -> BriefingResult:
        """Map a generator/storage dict to BriefingResult.

        Handles both shapes:
        - BriefingGenerator.generate() return: id/briefing_date/category/
          summary/items/total_items/generated_at
        - AnalyticsStorage.get_briefing() return: id/briefing_date/category/
          summary/items/generated_at

        Missing fields fall back to safe defaults (empty list / None).

        Args:
            result_dict: Dict from generator or storage.
            narrative_mode: True if narrative generator was used successfully,
                False otherwise (template mode, degradation, or storage
                retrieval — storage doesn't track narrative_mode).
        """
        return BriefingResult(
            date=result_dict["briefing_date"],
            category=result_dict.get("category"),
            summary=result_dict.get("summary"),
            items=result_dict.get("items", []) or [],
            generated_at=result_dict.get("generated_at"),
            narrative_mode=narrative_mode,
            briefing_id=result_dict.get("id"),
        )


__all__ = ["BriefingAlreadyExistsError", "DailyBriefingService"]
