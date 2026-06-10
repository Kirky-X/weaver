# Copyright (c) 2026 KirkyX. All Rights Reserved
"""DifficultyEstimator: 4-factor difficulty scoring for LLM routing.

Factors:
- Input length: text character count
- Entity density: named entities per 1000 chars
- Language complexity: average sentence length
- Call point baseline: inherent difficulty of the pipeline stage
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass
class DifficultyEstimator:
    """4-factor difficulty estimator for LLM routing.

    Implements: standalone estimator, no protocol yet.
    """

    CALL_POINT_BASELINES: ClassVar[dict[str, float]] = {
        "classifier": 0.2,
        "categorizer": 0.3,
        "analyze": 0.6,
        "entity_extractor": 0.7,
        "quality_scorer": 0.5,
    }

    def estimate(self, text: str, call_point: str, entity_count: int = 0) -> float:
        """Estimate difficulty score [0, 1] for a given input."""
        length_factor = self._length_factor(len(text))
        density_factor = self._density_factor(entity_count, len(text))
        complexity_factor = self._complexity_factor(text)
        baseline = self.CALL_POINT_BASELINES.get(call_point, 0.5)
        return (length_factor + density_factor + complexity_factor + baseline) / 4.0

    @staticmethod
    def _length_factor(char_count: int) -> float:
        if char_count < 200:
            return 0.1
        if char_count < 2000:
            return 0.4
        if char_count < 8000:
            return 0.7
        return 0.9

    @staticmethod
    def _density_factor(entity_count: int, char_count: int) -> float:
        if char_count == 0:
            return 0.1
        per_k = entity_count / (char_count / 1000)
        if per_k < 1:
            return 0.1
        if per_k < 3:
            return 0.4
        if per_k < 5:
            return 0.6
        return 0.7

    @staticmethod
    def _complexity_factor(text: str) -> float:
        sentences = [s.strip() for s in text.split("。") if s.strip()]
        if not sentences:
            return 0.5
        avg_len = sum(len(s) for s in sentences) / len(sentences)
        if avg_len < 50:
            return 0.1
        if avg_len < 100:
            return 0.4
        return 0.7
