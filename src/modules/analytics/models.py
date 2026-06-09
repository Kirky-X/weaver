# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Analytics data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SentimentShift:
    """A detected sentiment shift point."""

    community_id: str
    shift_type: str
    direction: str
    magnitude: float = 0.0
    confidence: float = 0.0
    detected_at: datetime = field(default_factory=datetime.now)
    before_avg: float | None = None
    after_avg: float | None = None
    trigger_article_ids: list[str] = field(default_factory=list)


@dataclass
class ShiftConfig:
    """Configuration for shift detection."""

    window_days: int = 14
    pel_penalty: float = 5.0
    binseg_penalty: float = 3.0
    pel_model: str = "rbf"
    binseg_model: str = "l2"
    min_size: int = 2
    magnitude_threshold: float = 0.05
