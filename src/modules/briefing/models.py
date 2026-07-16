# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Briefing data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
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
