# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Daily briefing service — implements DailyBriefingProtocol (T008 / R-briefing-002).

DailyBriefingService is the service-layer entry point for briefing operations:
- generate_briefing: delegates to BriefingGenerator (T004) and maps the
  returned dict to BriefingResult. Does NOT re-implement generation logic
  (Rule 8: reuse existing implementations).
- get_briefing: queries AnalyticsStorage.get_briefing for a single briefing.
- list_briefings: queries AnalyticsStorage.list_briefings for a date range.

T008 scope (Rule 24 — no simplified implementation):
- narrative_mode is always False in T008 (T021 will implement narrative mode
  via NarrativeBriefingGenerator). BriefingResult.narrative_mode is hardcoded
  to False — this is a deliberate T008 boundary, not a simplification.
- category=None is normalized to 'general' before calling storage, consistent
  with BriefingGenerator.generate() normalization (spec R-briefing-001).
- Storage failures propagate (Rule 12: fail loud). Generator failures
  (LLM degrade) are reflected in the returned BriefingResult.summary=None,
  not raised — this matches BriefingGenerator's spec R-briefing-002 contract.

Templates (R-briefing-003) are defined in templates.py but not consumed by
T008 — BriefingGenerator uses generic briefing.toml prompt. Templates will
be consumed by T021+ narrative mode for category-specific prompt injection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.observability import get_logger
from modules.briefing.models import BriefingResult

if TYPE_CHECKING:
    from datetime import date

    from core.protocols import AnalyticsStorageProtocol
    from modules.briefing.generator import BriefingGenerator

log = get_logger(__name__)

# Normalized category for None input (spec R-briefing-001: None 表示综合).
_DEFAULT_CATEGORY: str = "general"


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
    ) -> None:
        self._generator = generator
        self._storage = storage

    async def generate_briefing(
        self,
        date: date,
        category: str | None = None,
    ) -> BriefingResult:
        """Generate (or regenerate) a daily briefing.

        Delegates to BriefingGenerator.generate(date, category) which:
        1. Fetches articles filtered by category
        2. Calls LLM via CallPoint.BRIEFING (degrades to None on LLM failure)
        3. Persists briefing + items via storage.save_briefing
        4. Returns dict with id/briefing_date/category/summary/items/

        Maps the returned dict to BriefingResult. narrative_mode is always
        False in T008 (T021 will implement narrative mode).

        Args:
            date: The date to generate the briefing for.
            category: Briefing category — one of {finance, tech, ai, general}.
                None means "综合" (general, no article filter).

        Returns:
            BriefingResult with all fields populated from generator output.

        Raises:
            ValueError: If category is invalid (propagated from generator).
            Exception: Storage failures propagate (Rule 12).
        """
        result_dict = await self._generator.generate(date, category)
        return self._map_to_briefing_result(result_dict)

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
    def _map_to_briefing_result(result_dict: dict[str, Any]) -> BriefingResult:
        """Map a generator/storage dict to BriefingResult.

        Handles both shapes:
        - BriefingGenerator.generate() return: id/briefing_date/category/
          summary/items/total_items/generated_at
        - AnalyticsStorage.get_briefing() return: id/briefing_date/category/
          summary/items/generated_at

        Missing fields fall back to safe defaults (empty list / None).

        narrative_mode is always False in T008 — T021+ narrative mode will
        set this field based on whether NarrativeBriefingGenerator was used.
        """
        return BriefingResult(
            date=result_dict["briefing_date"],
            category=result_dict.get("category"),
            summary=result_dict.get("summary"),
            items=result_dict.get("items", []) or [],
            generated_at=result_dict.get("generated_at"),
            narrative_mode=False,  # T008 boundary — T021 will implement
            briefing_id=result_dict.get("id"),
        )


__all__ = ["DailyBriefingService"]
