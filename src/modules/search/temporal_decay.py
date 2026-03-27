# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Temporal decay utilities for search result scoring.

Implements exponential decay based on document age, allowing newer
content to receive higher relevance scores. This is particularly useful
for news and time-sensitive content where freshness matters.

The decay follows an exponential formula:
    decay_multiplier = exp(-λ * age_in_days)
    where λ = ln(2) / half_life_days

With a half-life of 30 days:
- A 30-day old document has its score reduced to 50%
- A 60-day old document has its score reduced to 25%
- A 90-day old document has its score reduced to 12.5%
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class TemporalDecayConfig:
    """Configuration for temporal decay."""

    enabled: bool = False
    """Whether temporal decay is enabled."""

    half_life_days: float = 30.0
    """Half-life in days. After this period, the decay multiplier reaches 0.5."""


def calculate_decay_multiplier(
    age_in_days: float,
    half_life_days: float,
) -> float:
    """Calculate the decay multiplier using exponential decay.

    Formula: exp(-λ * age), where λ = ln(2) / half_life_days

    Args:
        age_in_days: Document age in days (non-negative).
        half_life_days: Half-life period in days (positive).

    Returns:
        Decay multiplier between 0 and 1. Returns 1.0 if inputs are invalid.
    """
    # Guard against invalid inputs
    if half_life_days <= 0 or not math.isfinite(half_life_days):
        return 1.0

    if age_in_days < 0 or not math.isfinite(age_in_days):
        return 1.0

    # Calculate decay constant λ = ln(2) / half_life
    lambda_decay = math.log(2) / half_life_days

    # Calculate multiplier: exp(-λ * age)
    return math.exp(-lambda_decay * age_in_days)


def apply_temporal_decay(
    score: float,
    age_in_days: float,
    half_life_days: float,
) -> float:
    """Apply temporal decay to a relevance score.

    Args:
        score: Original relevance score.
        age_in_days: Document age in days.
        half_life_days: Half-life period in days.

    Returns:
        Decay-adjusted score. Returns original score if decay is disabled.
    """
    multiplier = calculate_decay_multiplier(age_in_days, half_life_days)
    return score * multiplier


def calculate_age_in_days(
    timestamp: datetime | None,
    now: datetime | None = None,
) -> float:
    """Calculate age in days from a timestamp.

    Args:
        timestamp: Document timestamp (e.g., publish_time or created_at).
        now: Current time for comparison. Defaults to UTC now.

    Returns:
        Age in days as a float. Returns 0.0 if timestamp is None.
    """
    if timestamp is None:
        return 0.0

    if now is None:
        now = datetime.now(UTC)

    # Calculate time difference
    age_delta = now - timestamp

    # Convert to days (86400 seconds per day)
    return max(0.0, age_delta.total_seconds() / 86400.0)
