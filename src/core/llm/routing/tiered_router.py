# Copyright (c) 2026 KirkyX. All Rights Reserved
"""TieredRouter: difficulty-based tiered LLM routing.

Routes based on difficulty score to tiered LLM providers using
Label objects (e.g., Label("chat.fasttext.classifier")) instead
of abstract tier strings.

Implements: standalone router, no protocol yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.llm.routing.difficulty_estimator import DifficultyEstimator
from core.llm.types import Label


@dataclass
class TierConfig:
    """A single tier entry in the routing table.

    Attributes:
        label: Full Label string (e.g., "chat.fasttext.classifier").
        max_difficulty: Upper bound of difficulty for this tier (0.0-1.0).
        input_truncation: Maximum input tokens for this tier, or None for no limit.
    """

    label: str
    max_difficulty: float
    input_truncation: int | None = None


@dataclass
class TieredRouter:
    """Routes based on difficulty score to tiered LLM providers.

    Uses DifficultyEstimator to score input text difficulty, then
    selects the appropriate tier based on max_difficulty thresholds.

    Args:
        estimator: DifficultyEstimator instance for scoring text.
        tiers: Optional unified tiers list applied to all call points.
        tiers_by_call_point: Optional per-call-point tier configuration.
            When both tiers and tiers_by_call_point are provided,
            tiers takes precedence.

    Implements: standalone router, no protocol yet.
    """

    estimator: DifficultyEstimator = field(default_factory=DifficultyEstimator)
    tiers: list[TierConfig] | None = None
    tiers_by_call_point: dict[str, list[TierConfig]] = field(default_factory=dict)

    def _get_tiers(self, call_point: str) -> list[TierConfig] | None:
        """Get the tiers list for a call point.

        Priority: self.tiers (unified) > tiers_by_call_point > None.
        """
        if self.tiers is not None:
            return self.tiers
        return self.tiers_by_call_point.get(call_point)

    def _find_tier(self, call_point: str, difficulty: float) -> TierConfig | None:
        """Find the matching tier for a given difficulty."""
        tiers = self._get_tiers(call_point)
        if tiers is None:
            return None
        for tier in tiers:
            if difficulty < tier.max_difficulty:
                return tier
        # Fallback to last tier (should always match if max_difficulty=1.0)
        return tiers[-1]

    def route(self, call_point: str, text: str, entity_count: int = 0) -> Label | None:
        """Route to a provider based on call_point and input text.

        Estimates difficulty from the text, then selects the appropriate
        tier and returns the corresponding Label.

        Args:
            call_point: Pipeline stage name (e.g., "classifier").
            text: Input text to route.
            entity_count: Optional entity count for difficulty estimation.

        Returns:
            Label for the selected tier, or None if no tiers configured.
        """
        difficulty = self.estimator.estimate(call_point, text, entity_count=entity_count)
        tier = self._find_tier(call_point, difficulty)
        if tier is None:
            return None
        return Label.parse(tier.label)

    def get_input_truncation(self, call_point: str, text: str, entity_count: int = 0) -> int | None:
        """Get the input truncation limit for the matched tier.

        Args:
            call_point: Pipeline stage name.
            text: Input text to route.
            entity_count: Optional entity count for difficulty estimation.

        Returns:
            Maximum input token count, or None if no truncation or no tiers.
        """
        difficulty = self.estimator.estimate(call_point, text, entity_count=entity_count)
        tier = self._find_tier(call_point, difficulty)
        if tier is None:
            return None
        return tier.input_truncation
