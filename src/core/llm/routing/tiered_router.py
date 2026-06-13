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

    @staticmethod
    def validate_tiers(tiers: list[TierConfig]) -> list[str]:
        """Validate a list of TierConfig entries for correctness.

        Checks:
        - max_difficulty values are in range [0.0, 1.0]
        - max_difficulty values are strictly ascending
        - No duplicate max_difficulty values
        - Last tier covers max_difficulty=1.0 (warning if not)

        Args:
            tiers: List of TierConfig entries to validate.

        Returns:
            List of error/warning strings. Empty list means valid.
        """
        errors: list[str] = []

        if not tiers:
            return errors

        for i, tier in enumerate(tiers):
            if not (0.0 <= tier.max_difficulty <= 1.0):
                errors.append(
                    f"Tier {i} ({tier.label}): max_difficulty={tier.max_difficulty} "
                    f"is out of range [0.0, 1.0]"
                )

        for i in range(1, len(tiers)):
            if tiers[i].max_difficulty <= tiers[i - 1].max_difficulty:
                errors.append(
                    f"Non-ascending max_difficulty: tier {i - 1} "
                    f"({tiers[i - 1].max_difficulty}) >= tier {i} "
                    f"({tiers[i].max_difficulty})"
                )

        # Check for duplicates
        difficulties = [t.max_difficulty for t in tiers]
        seen: set[float] = set()
        for d in difficulties:
            if d in seen:
                errors.append(f"Duplicate max_difficulty value: {d}")
            seen.add(d)

        # Check coverage
        if tiers[-1].max_difficulty < 1.0:
            errors.append(
                f"Last tier max_difficulty={tiers[-1].max_difficulty} < 1.0: "
                f"difficulty scores above this value will have no coverage"
            )

        return errors

    @staticmethod
    def describe_routing(tiers: list[TierConfig]) -> str:
        """Generate a human-readable description of the routing table.

        Args:
            tiers: List of TierConfig entries.

        Returns:
            Multi-line string describing the routing decisions.
        """
        if not tiers:
            return "No tiers configured — tiered routing is disabled."

        lines = ["Tiered routing configuration:"]
        prev_bound = 0.0
        for i, tier in enumerate(tiers):
            range_str = f"[{prev_bound:.1f}, {tier.max_difficulty:.1f})"
            truncation = f", truncation={tier.input_truncation}" if tier.input_truncation else ""
            lines.append(f"  Tier {i}: difficulty {range_str} → {tier.label}{truncation}")
            prev_bound = tier.max_difficulty

        # Validate and append warnings
        errors = TierConfig.validate_tiers(tiers)
        if errors:
            lines.append("")
            lines.append("Validation warnings:")
            for error in errors:
                lines.append(f"  ⚠ {error}")

        return "\n".join(lines)


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
