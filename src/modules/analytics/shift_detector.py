# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Sentiment shift detector using ruptures PELT + Binseg."""

from __future__ import annotations

from typing import Any

import numpy as np
import ruptures as rpt

from core.observability.logging import get_logger

log = get_logger(__name__)


class ShiftConfig:
    """Configuration for shift detection."""

    def __init__(
        self,
        window_days: int = 14,
        pel_penalty: float = 5.0,
        binseg_penalty: float = 3.0,
        pel_model: str = "rbf",
        binseg_model: str = "l2",
        min_size: int = 2,
        magnitude_threshold: float = 0.05,
    ):
        self.window_days = window_days
        self.pel_penalty = pel_penalty
        self.binseg_penalty = binseg_penalty
        self.pel_model = pel_model
        self.binseg_model = binseg_model
        self.min_size = min_size
        self.magnitude_threshold = magnitude_threshold


class SentimentShiftDetector:
    """Detect sentiment shifts using PELT + Binseg (ruptures).

    Implements: ShiftDetector
    """

    def __init__(self, config: ShiftConfig | None = None):
        self._config = config or ShiftConfig()

    def detect(self, signal: list[float]) -> list[dict[str, Any]]:
        """Detect shift points in a sentiment signal.

        Args:
            signal: List of daily sentiment scores (0.0-1.0).

        Returns:
            List of detected shift points with shift_type, magnitude, etc.
        """
        if len(signal) < self._config.min_size * 2:
            return []

        arr = np.array(signal, dtype=np.float64)

        algo_pelt = rpt.Pelt(
            model=self._config.pel_model,
            min_size=self._config.min_size,
            jump=1,
        )
        algo_pelt.fit(arr)
        pel_breakpoints = algo_pelt.predict(pen=self._config.pel_penalty)

        algo_binseg = rpt.Binseg(
            model=self._config.binseg_model,
            min_size=self._config.min_size,
            jump=1,
        )
        algo_binseg.fit(arr)
        binseg_breakpoints = algo_binseg.predict(pen=self._config.binseg_penalty)

        shifts = self._merge_results(signal, pel_breakpoints, binseg_breakpoints)
        return shifts

    def _merge_results(
        self,
        signal: list[float],
        pel_bps: list[int],
        binseg_bps: list[int],
    ) -> list[dict[str, Any]]:
        """Merge PELT and Binseg results into unified shift list."""
        shifts = []
        for bp in pel_bps:
            if bp >= len(signal):
                continue
            before = sum(signal[:bp]) / max(len(signal[:bp]), 1)
            after = sum(signal[bp:]) / max(len(signal[bp:]), 1)
            magnitude = abs(after - before)
            if magnitude < self._config.magnitude_threshold:
                continue
            shifts.append(
                {
                    "shift_type": "pel",
                    "direction": "positive" if after > before else "negative",
                    "magnitude": round(magnitude, 4),
                    "confidence": 0.7,
                    "breakpoint": bp,
                }
            )
        for bp in binseg_bps:
            if bp >= len(signal):
                continue
            before = sum(signal[:bp]) / max(len(signal[:bp]), 1)
            after = sum(signal[bp:]) / max(len(signal[bp:]), 1)
            magnitude = abs(after - before)
            if magnitude < self._config.magnitude_threshold:
                continue
            shifts.append(
                {
                    "shift_type": "binseg",
                    "direction": "positive" if after > before else "negative",
                    "magnitude": round(magnitude, 4),
                    "confidence": 0.8,
                    "breakpoint": bp,
                }
            )
        return shifts
