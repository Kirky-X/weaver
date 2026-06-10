# Copyright (c) 2026 KirkyX. All Rights Reserved
"""TieredRouter: difficulty-based tiered LLM routing.

Routes based on difficulty score to tiered LLM providers:
- easy (< low_threshold) → fast/local models
- medium (low_threshold - high_threshold) → local models
- hard (> high_threshold) → cloud models
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass
class TieredRouter:
    """Routes based on difficulty score to tiered LLM providers.

    Implements: standalone router, no protocol yet.
    """

    ROUTING_TABLE: ClassVar[dict[str, dict]] = {
        "classifier": {
            "low": 0.3,
            "high": 0.7,
            "easy": "fast",
            "medium": "local",
            "hard": "cloud",
        },
        "categorizer": {
            "low": 0.3,
            "high": 0.7,
            "easy": "fast",
            "medium": "local",
            "hard": "cloud",
        },
        "analyze": {
            "low": 0.5,
            "high": 0.7,
            "easy": "local",
            "medium": "local",
            "hard": "cloud",
        },
        "entity_extractor": {
            "low": 0.4,
            "high": 0.7,
            "easy": "local",
            "medium": "local",
            "hard": "cloud",
        },
    }

    DEFAULT_TIER: ClassVar[dict] = {
        "low": 0.3,
        "high": 0.7,
        "easy": "local",
        "medium": "local",
        "hard": "cloud",
    }

    def route(self, call_point: str, difficulty: float) -> str:
        """Route to a tier based on call_point and difficulty score."""
        tier_config = self.ROUTING_TABLE.get(call_point, self.DEFAULT_TIER)
        if difficulty < tier_config["low"]:
            return tier_config["easy"]
        if difficulty < tier_config["high"]:
            return tier_config["medium"]
        return tier_config["hard"]
