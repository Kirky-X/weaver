# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Briefing data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID


@dataclass
class BriefingConfig:
    """Configuration for briefing generation."""

    max_items: int = 10
    max_per_category: int = 3
    lookback_hours: int = 24


@dataclass
class Briefing:
    """A generated daily briefing."""

    id: int = 0
    briefing_date: date = field(default_factory=date.today)
    total_items: int = 0
    generated_at: datetime = field(default_factory=datetime.now)
    items: list = field(default_factory=list)


@dataclass
class BriefingItem:
    """An item within a daily briefing."""

    rank: int = 0
    article_id: UUID | None = None
    category: str | None = None
    reason: str | None = None


@dataclass
class BriefingResult:
    """Result returned by DailyBriefingProtocol methods (R-briefing-001, R-briefing-008).

    Used by:
        - DailyBriefingService.generate_briefing / get_briefing / list_briefings
        - T009 briefings API endpoint (serialized to APIResponse[BriefingResult])

    Fields:
        date: The briefing date (YYYY-MM-DD).
        category: Briefing category — one of {finance, tech, ai, general}.
            None means "综合" (general).
        summary: LLM-generated summary. None on LLM failure (degraded mode,
            spec R-briefing-002) or before generation.
        items: List of briefing item dicts (article_id/rank/score/category/reason).
            Empty list when no articles found.
        generated_at: UTC timestamp when the briefing was generated.
        narrative_mode: True if summary was produced by NarrativeBriefingGenerator
            (T020). False for template-mode briefings or when narrative mode
            was requested but degraded to template mode due to
            InsufficientNarrativeError (spec R-briefing-008).
        briefing_id: Database row id of the persisted daily_briefings record.
            None when not persisted (LLM failure with no row, or
            get_briefing returning None — though None is returned at the
            Protocol level in that case). Allows callers (T009 API) to
            reference the briefing for re-generation, tracking, audit.

    Naming conflict (Rule 7 — exposed):
        Legacy `Briefing` dataclass uses `briefing_date` field name; this
        DTO uses `date` per spec R-briefing-001. The conflict is documented
        here; legacy Briefing is a DB entity, BriefingResult is a DTO —
        they serve different layers and should not be unified in T007.
    """

    date: date
    category: str | None = None
    summary: str | None = None
    items: list[dict[str, Any]] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    narrative_mode: bool = False
    briefing_id: int | None = None
