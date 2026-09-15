# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""DifficultyEstimator: 4-factor difficulty scoring for LLM routing.

Factors:
- Input length: text character count (primary, acts as soft gate)
- Entity density: named entities per 1000 chars
- Language complexity: average sentence length
- Call point baseline: inherent difficulty of the pipeline stage

Guarantees:
- Short text (<200 chars) -> score < 0.3
- Long text (>8000 chars) -> score > 0.7
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar

from core.observability import get_logger

log = get_logger(__name__)


@dataclass
class DifficultyEstimator:
    """4-factor difficulty estimator for LLM routing.

    Uses a weighted formula where length is the primary signal (weight 0.75)
    and contextual factors (density + complexity + baseline) share the
    remaining weight (0.25). This guarantees:
    - Short text (<200 chars) always scores < 0.3
    - Long text (>8000 chars) always scores > 0.7

    Implements: standalone estimator, no protocol yet.
    """

    # 只读基线表：用 MappingProxyType 包裹，防止 `CALL_POINT_BASELINES["x"] = y`
    # 这类原地写入静默污染所有实例的打分（ClassVar 为共享可变状态）。
    CALL_POINT_BASELINES: ClassVar[Mapping[str, float]] = MappingProxyType(
        {
            "classifier": 0.2,
            "categorizer": 0.3,
            "analyze": 0.6,
            "entity_extractor": 0.7,
            "quality_scorer": 0.5,
        }
    )

    # Length weight dominates to guarantee bounds
    _LENGTH_WEIGHT: ClassVar[float] = 0.75
    _CONTEXT_WEIGHT: ClassVar[float] = 0.25

    def estimate(self, call_point: str, text: str, entity_count: int = 0) -> float:
        """Estimate difficulty score [0, 1] for a given input.

        Args:
            call_point: Pipeline stage name (e.g., "classifier").
            text: Input text to score.
            entity_count: Number of named entities in the text.

        Returns:
            Difficulty score in [0, 1].
        """
        length_factor = self._length_factor(len(text))
        density_factor = self._density_factor(entity_count, len(text))
        complexity_factor = self._complexity_factor(text)
        baseline = self.CALL_POINT_BASELINES.get(call_point)
        if baseline is None:
            # 未登记的 call_point 会静默使用中性基线，可能掩盖拼写错误或
            # 配置漂移（例如 "categoriser" vs "categorizer"）。
            log.warning(
                "difficulty_call_point_unknown",
                call_point=call_point,
                fallback_baseline=0.5,
            )
            baseline = 0.5

        contextual = (density_factor + complexity_factor + baseline) / 3.0
        score = self._LENGTH_WEIGHT * length_factor + self._CONTEXT_WEIGHT * contextual
        return max(0.0, min(1.0, score))

    @staticmethod
    def _length_factor(char_count: int) -> float:
        if char_count < 200:
            return 0.1
        if char_count < 2000:
            return 0.4
        if char_count < 8000:
            return 0.7
        return 0.95

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
        # Split on common CJK + Latin sentence terminators so English and
        # mixed-language texts do not degenerate into a single "sentence".
        sentences = [s for s in re.split(r"[.!?。！？;；]+", text) if s.strip()]
        if not sentences:
            return 0.5
        avg_len = sum(len(s) for s in sentences) / len(sentences)
        if avg_len < 50:
            return 0.1
        if avg_len < 100:
            return 0.4
        return 0.7
