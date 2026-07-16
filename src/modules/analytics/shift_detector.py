# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Sentiment shift detector using PELT + CUSUM dual-layer detection."""

from __future__ import annotations

from typing import Any

import numpy as np
import ruptures as rpt

from core.observability import get_logger

log = get_logger(__name__)


class ShiftConfig:
    """Configuration for shift detection.

    Implements: ShiftConfig — ADD §3.4
    """

    def __init__(
        self,
        window_days: int = 14,
        pel_penalty: float = 5.0,
        pel_model: str = "rbf",
        min_size: int = 2,
        magnitude_threshold: float = 0.05,
        cusum_threshold: float = 5.0,
        cusum_drift: float = 0.0,
        cusum_min_observations: int = 10,
        cooldown_hours: int = 24,
    ):
        self.window_days = window_days
        self.pel_penalty = pel_penalty
        self.pel_model = pel_model
        self.min_size = min_size
        self.magnitude_threshold = magnitude_threshold
        self.cusum_threshold = cusum_threshold
        self.cusum_drift = cusum_drift
        self.cusum_min_observations = cusum_min_observations
        self.cooldown_hours = cooldown_hours


class SentimentShiftDetector:
    """Detect sentiment shifts using PELT + CUSUM dual-layer detection.

    PELT detects abrupt mean shifts; CUSUM detects gradual cumulative
    deviations. Results are merged with cooldown-based deduplication.

    Implements: ShiftDetector — ADD §3.4
    """

    def __init__(self, config: ShiftConfig | None = None):
        self._config = config or ShiftConfig()

    def detect(self, signal: list[float]) -> list[dict[str, Any]]:
        """Detect shift points in a sentiment signal.

        Args:
            signal: List of daily sentiment scores (0.0-1.0).

        Returns:
            List of detected shift points with detection_method, magnitude, etc.
        """
        if len(signal) < self._config.min_size * 2:
            return []

        arr = np.array(signal, dtype=np.float64)

        # Layer 1: PELT for abrupt shifts
        pelt_shifts = self._detect_pelt(signal, arr)

        # Layer 2: CUSUM for gradual cumulative deviations
        cusum_shifts = self._detect_cusum(signal, arr)

        # Merge with cooldown deduplication
        shifts = self._merge_results(pelt_shifts, cusum_shifts)
        return shifts

    def _detect_pelt(self, signal: list[float], arr: np.ndarray) -> list[dict[str, Any]]:
        """Run PELT algorithm for abrupt shift detection."""
        algo = rpt.Pelt(
            model=self._config.pel_model,
            min_size=self._config.min_size,
            jump=1,
        )
        algo.fit(arr)
        breakpoints = algo.predict(pen=self._config.pel_penalty)

        shifts = []
        for bp in breakpoints:
            if bp >= len(signal):
                continue
            before_avg = sum(signal[:bp]) / max(len(signal[:bp]), 1)
            after_avg = sum(signal[bp:]) / max(len(signal[bp:]), 1)
            magnitude = abs(after_avg - before_avg)
            if magnitude < self._config.magnitude_threshold:
                continue
            shifts.append(
                {
                    "shift_type": "pelt",
                    "detection_method": "pelt",
                    "direction": "positive" if after_avg > before_avg else "negative",
                    "magnitude": round(magnitude, 4),
                    "confidence": 0.7,
                    "breakpoint": bp,
                    "before_avg": round(before_avg, 4),
                    "after_avg": round(after_avg, 4),
                }
            )
        return shifts

    def _detect_cusum(self, signal: list[float], arr: np.ndarray) -> list[dict[str, Any]]:
        """Run CUSUM algorithm for gradual cumulative deviation detection.

        CUSUM tracks cumulative sum of deviations from the mean.
        When the cumulative sum exceeds the threshold (in σ units),
        a shift point is reported at the point of maximum deviation.
        """
        if len(signal) < self._config.cusum_min_observations:
            return []

        mean = float(np.mean(arr))
        std = float(np.std(arr))
        if std == 0:
            return []

        # Normalize deviations
        deviations = (arr - mean) / std
        drift = self._config.cusum_drift

        # Compute cumulative sums (positive and negative)
        s_pos = np.zeros(len(arr))
        s_neg = np.zeros(len(arr))
        for i in range(1, len(arr)):
            s_pos[i] = max(0, s_pos[i - 1] + deviations[i] - drift)
            s_neg[i] = max(0, s_neg[i - 1] - deviations[i] - drift)

        threshold = self._config.cusum_threshold
        shifts = []

        # Find shift points where cumulative sum exceeds threshold
        i = 0
        while i < len(arr):
            if s_pos[i] > threshold or s_neg[i] > threshold:
                # Find the start of this deviation (where cumulative sum started rising)
                is_positive = s_pos[i] > threshold
                start_idx = i
                cum_arr = s_pos if is_positive else s_neg
                for j in range(i - 1, -1, -1):
                    if cum_arr[j] == 0:
                        start_idx = j + 1
                        break
                else:
                    start_idx = 0

                bp = start_idx

                # Skip if breakpoint is at signal boundary
                if bp <= 0 or bp >= len(signal):
                    # Advance past this detection
                    i += 1
                    while i < len(arr) and (s_pos[i] > threshold or s_neg[i] > threshold):
                        i += 1
                    continue

                before_avg = sum(signal[:bp]) / max(len(signal[:bp]), 1)
                after_avg = sum(signal[bp:]) / max(len(signal[bp:]), 1)
                magnitude = abs(after_avg - before_avg)

                if magnitude >= self._config.magnitude_threshold:
                    shifts.append(
                        {
                            "shift_type": "cusum",
                            "detection_method": "cusum",
                            "direction": "positive" if after_avg > before_avg else "negative",
                            "magnitude": round(magnitude, 4),
                            "confidence": round(
                                min(s_pos[i] if is_positive else s_neg[i], 10.0) / 10.0,
                                4,
                            ),
                            "breakpoint": bp,
                            "before_avg": round(before_avg, 4),
                            "after_avg": round(after_avg, 4),
                        }
                    )

                # Advance past this detection
                i += 1
                while i < len(arr) and (s_pos[i] > threshold or s_neg[i] > threshold):
                    i += 1
            else:
                i += 1

        return shifts

    def _merge_results(
        self,
        pelt_shifts: list[dict[str, Any]],
        cusum_shifts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Merge PELT and CUSUM results with cooldown deduplication.

        Shift points within cooldown_hours of each other are merged.
        When both algorithms detect the same shift, detection_method
        is set to 'pelt+cusum'.
        """
        # Combine all shifts
        all_shifts = list(pelt_shifts) + list(cusum_shifts)
        if not all_shifts:
            return []

        # Sort by breakpoint
        all_shifts.sort(key=lambda s: s["breakpoint"])

        # Deduplicate within cooldown (in index units, approximated by signal position)
        # cooldown_hours maps to index distance: 1 index ≈ 1 day
        cooldown_indices = self._config.cooldown_hours // 24  # Convert hours to days/indices
        if cooldown_indices < 1:
            cooldown_indices = 1

        merged = []
        for shift in all_shifts:
            bp = shift["breakpoint"]
            # Find if there's an existing merged shift within cooldown
            found = False
            for existing in merged:
                if abs(existing["breakpoint"] - bp) <= cooldown_indices:
                    # Merge: combine detection methods
                    if (
                        "cusum" in shift["detection_method"]
                        and "pelt" in existing["detection_method"]
                    ):
                        existing["detection_method"] = "pelt+cusum"
                        existing["shift_type"] = "pelt+cusum"
                        # Keep the higher confidence
                        existing["confidence"] = max(existing["confidence"], shift["confidence"])
                    elif (
                        "pelt" in shift["detection_method"]
                        and "cusum" in existing["detection_method"]
                    ):
                        existing["detection_method"] = "pelt+cusum"
                        existing["shift_type"] = "pelt+cusum"
                        existing["confidence"] = max(existing["confidence"], shift["confidence"])
                    found = True
                    break

            if not found:
                merged.append(dict(shift))

        return merged
