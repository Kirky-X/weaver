# Copyright (c) 2026 KirkyX. All Rights Reserved
"""TieredRouter: difficulty-based tiered LLM routing.

Routes based on difficulty score to tiered LLM providers using
concrete Provider labels (e.g., "fastText", "ollama.gemma4:e4b",
"aiping.GLM-4-9B") instead of abstract tier strings.

Implements: standalone router, no protocol yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass
class TierConfig:
    """A single tier entry in the routing table.

    Attributes:
        backend: Concrete provider label (e.g., "fastText", "ollama.gemma4:e4b").
        max_difficulty: Upper bound of difficulty for this tier (0.0-1.0).
        provider: Provider configuration dict.
        input_truncation: Maximum input tokens for this tier, or None for no limit.
    """

    backend: str
    max_difficulty: float
    provider: dict[str, Any] = field(default_factory=dict)
    input_truncation: int | None = None


@dataclass
class TieredRouter:
    """Routes based on difficulty score to tiered LLM providers.

    Uses a tiers list structure where each tier entry contains:
    - backend: concrete provider label
    - max_difficulty: upper bound for this tier
    - provider: provider configuration
    - input_truncation: optional token limit

    Implements: standalone router, no protocol yet.
    """

    ROUTING_TABLE: ClassVar[dict[str, dict[str, Any]]] = {
        "classifier": {
            "tiers": [
                {
                    "backend": "fastText",
                    "max_difficulty": 0.3,
                    "provider": {"model": "fasttext"},
                    "input_truncation": 512,
                },
                {
                    "backend": "ollama.gemma4:e4b",
                    "max_difficulty": 0.7,
                    "provider": {"model": "gemma4"},
                    "input_truncation": 2048,
                },
                {
                    "backend": "aiping.GLM-4-9B",
                    "max_difficulty": 1.0,
                    "provider": {"model": "glm4"},
                    "input_truncation": None,
                },
            ],
        },
        "categorizer": {
            "tiers": [
                {
                    "backend": "fastText",
                    "max_difficulty": 0.3,
                    "provider": {"model": "fasttext"},
                    "input_truncation": 512,
                },
                {
                    "backend": "ollama.gemma4:e4b",
                    "max_difficulty": 0.7,
                    "provider": {"model": "gemma4"},
                    "input_truncation": 2048,
                },
                {
                    "backend": "aiping.GLM-4-9B",
                    "max_difficulty": 1.0,
                    "provider": {"model": "glm4"},
                    "input_truncation": None,
                },
            ],
        },
        "analyze": {
            "tiers": [
                {
                    "backend": "ollama.gemma4:e4b",
                    "max_difficulty": 0.5,
                    "provider": {"model": "gemma4"},
                    "input_truncation": 2048,
                },
                {
                    "backend": "ollama.gemma4:e4b",
                    "max_difficulty": 0.7,
                    "provider": {"model": "gemma4"},
                    "input_truncation": 2048,
                },
                {
                    "backend": "aiping.GLM-4-9B",
                    "max_difficulty": 1.0,
                    "provider": {"model": "glm4"},
                    "input_truncation": None,
                },
            ],
        },
        "entity_extractor": {
            "tiers": [
                {
                    "backend": "ollama.gemma4:e4b",
                    "max_difficulty": 0.4,
                    "provider": {"model": "gemma4"},
                    "input_truncation": 2048,
                },
                {
                    "backend": "ollama.gemma4:e4b",
                    "max_difficulty": 0.7,
                    "provider": {"model": "gemma4"},
                    "input_truncation": 2048,
                },
                {
                    "backend": "aiping.GLM-4-9B",
                    "max_difficulty": 1.0,
                    "provider": {"model": "glm4"},
                    "input_truncation": None,
                },
            ],
        },
    }

    DEFAULT_TIERS: ClassVar[list[dict[str, Any]]] = [
        {
            "backend": "fastText",
            "max_difficulty": 0.3,
            "provider": {"model": "fasttext"},
            "input_truncation": 512,
        },
        {
            "backend": "ollama.gemma4:e4b",
            "max_difficulty": 0.7,
            "provider": {"model": "gemma4"},
            "input_truncation": 2048,
        },
        {
            "backend": "aiping.GLM-4-9B",
            "max_difficulty": 1.0,
            "provider": {"model": "glm4"},
            "input_truncation": None,
        },
    ]

    def __init__(self, tiers: list[TierConfig] | None = None) -> None:
        """Initialize the TieredRouter.

        Args:
            tiers: Optional custom tiers list. When provided, overrides
                   the per-call-point routing table with a single unified
                   tiers configuration used for all call points.
        """
        self._custom_tiers = tiers

    def _get_tiers(self, call_point: str) -> list[dict[str, Any]]:
        """Get the tiers list for a call point."""
        if self._custom_tiers is not None:
            return [
                {
                    "backend": t.backend,
                    "max_difficulty": t.max_difficulty,
                    "provider": t.provider,
                    "input_truncation": t.input_truncation,
                }
                for t in self._custom_tiers
            ]
        config = self.ROUTING_TABLE.get(call_point)
        if config is not None:
            return config["tiers"]
        return self.DEFAULT_TIERS

    def _find_tier(self, call_point: str, difficulty: float) -> dict[str, Any]:
        """Find the matching tier for a given difficulty."""
        tiers = self._get_tiers(call_point)
        for tier in tiers:
            if difficulty < tier["max_difficulty"]:
                return tier
        # Fallback to last tier (should always match if max_difficulty=1.0)
        return tiers[-1]

    def route(self, call_point: str, difficulty: float) -> str:
        """Route to a provider based on call_point and difficulty score.

        Returns a concrete provider label (e.g., "fastText",
        "ollama.gemma4:e4b", "aiping.GLM-4-9B").
        """
        tier = self._find_tier(call_point, difficulty)
        return tier["backend"]

    def get_input_truncation(self, call_point: str, difficulty: float) -> int | None:
        """Get the input truncation limit for the matched tier.

        Returns the maximum input token count, or None if no truncation.
        """
        tier = self._find_tier(call_point, difficulty)
        return tier.get("input_truncation")
