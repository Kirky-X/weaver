# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Temporal-aware retriever for search result scoring.

Implements a mixed scoring formula that blends base relevance with
temporal decay, ensuring older documents are penalized but never
drop below 60% of their base score.

Formula: score = base_score * (0.6 + 0.4 * time_decay)
Where time_decay = exp(-λ * age_in_days), λ = ln(2) / half_life_days

Implements: TemporalAwareRetriever — ADD §3.6
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class TemporalDecayConfig:
    """Configuration for temporal decay."""

    enabled: bool = True
    """Whether temporal decay is enabled."""

    half_life_days: float = 30.0
    """Half-life in days. After this period, the decay multiplier reaches 0.5."""


class TemporalAwareRetriever:
    """Score search results with temporal decay blending.

    Uses a mixed formula that ensures older documents retain at least
    60% of their base score, while newer documents get full weight:

        score = base_score * (0.6 + 0.4 * time_decay)

    When enabled=False, returns base_score unchanged.

    Implements: TemporalAwareRetriever — ADD §3.6
    """

    def __init__(
        self,
        enabled: bool = True,
        half_life_days: float = 30.0,
    ) -> None:
        self._enabled = enabled
        self._half_life_days = half_life_days

    def score(
        self,
        base_score: float,
        age_in_days: float,
    ) -> float:
        """Apply temporal-aware scoring to a base relevance score.

        Args:
            base_score: Original relevance score.
            age_in_days: Document age in days (non-negative).

        Returns:
            Temporal-adjusted score. When disabled, returns base_score.
            When enabled, returns base_score * (0.6 + 0.4 * time_decay).
        """
        if not self._enabled:
            return base_score

        time_decay = self._calculate_decay(age_in_days)
        return base_score * (0.6 + 0.4 * time_decay)

    def _calculate_decay(self, age_in_days: float) -> float:
        """Calculate exponential decay multiplier.

        Formula: exp(-λ * age), where λ = ln(2) / half_life_days

        Returns:
            Decay multiplier between 0 and 1.
        """
        if self._half_life_days <= 0 or not math.isfinite(self._half_life_days):
            return 1.0

        if age_in_days < 0 or not math.isfinite(age_in_days):
            return 1.0

        lambda_decay = math.log(2) / self._half_life_days
        return math.exp(-lambda_decay * age_in_days)

    @staticmethod
    def calculate_age_in_days(
        timestamp: datetime | None,
        now: datetime | None = None,
    ) -> float:
        """Calculate age in days from a timestamp.

        Args:
            timestamp: Document timestamp.
            now: Current time. Defaults to UTC now.

        Returns:
            Age in days. Returns 0.0 if timestamp is None.
        """
        if timestamp is None:
            return 0.0

        if now is None:
            now = datetime.now(UTC)

        age_delta = now - timestamp
        return max(0.0, age_delta.total_seconds() / 86400.0)


# Backward-compatible function wrappers
def calculate_decay_multiplier(
    age_in_days: float,
    half_life_days: float,
) -> float:
    """Calculate the decay multiplier using exponential decay.

    Backward-compatible wrapper around TemporalAwareRetriever.
    """
    retriever = TemporalAwareRetriever(enabled=True, half_life_days=half_life_days)
    return retriever._calculate_decay(age_in_days)


def apply_temporal_decay(
    score: float,
    age_in_days: float,
    half_life_days: float,
) -> float:
    """Apply temporal decay to a relevance score.

    Backward-compatible wrapper. Uses the old formula (score * decay)
    for compatibility. New code should use TemporalAwareRetriever.score().
    """
    multiplier = calculate_decay_multiplier(age_in_days, half_life_days)
    return score * multiplier


def calculate_age_in_days(
    timestamp: datetime | None,
    now: datetime | None = None,
) -> float:
    """Calculate age in days from a timestamp.

    Backward-compatible wrapper around TemporalAwareRetriever.
    """
    return TemporalAwareRetriever.calculate_age_in_days(timestamp, now)
