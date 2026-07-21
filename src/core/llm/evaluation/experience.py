# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Model experience tracking for smart routing.

Subscribes to LLMUsageEvent to track per-model performance,
supports Thompson Sampling for exploration bonuses.
"""

from __future__ import annotations

import asyncio
import random
from collections import deque
from dataclasses import dataclass, field
from time import monotonic
from typing import Any

from core.event import EventBus, LLMUsageEvent
from core.llm.types import ExperienceData
from core.observability import get_logger

log = get_logger(__name__)

# Beta distribution prior parameters (Beta(2,2) is a weak prior centered at 0.5)
BETA_PRIOR_ALPHA = 2.0
BETA_PRIOR_BETA = 2.0
# Beta prior floor: never let alpha/beta drop below this
BETA_PRIOR_FLOOR = 2.0

# Warmup defaults
WARMUP_CALLS_DEFAULT = 20
EXPLORATION_WEIGHT_DEFAULT = 0.15

# Time window constants (in seconds)
RECENT_WINDOW_SECONDS = 24 * 3600  # 24 hours
OLDER_WINDOW_SECONDS = 7 * 24 * 3600  # 7 days
CALL_HISTORY_TTL_SECONDS = 7 * 24 * 3600  # 7 days

# Time-weighted scoring weights
RECENT_WINDOW_WEIGHT = 1.0  # <24h
OLDER_WINDOW_WEIGHT = 0.5  # 24h-7d

# Synthetic history distribution ratio (70% recent, 30% older)
RECENT_CALLS_RATIO = 0.7

# Call history capacity (prevent unbounded memory growth)
MAX_CALL_HISTORY = 10000


@dataclass
class _ModelExperience:
    """Internal counter for a single model at a call point."""

    call_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_latency_ms: float = 0.0
    last_call_time: float = 0.0
    # Thompson Sampling Beta distribution params (prior: Beta(2,2))
    alpha: float = BETA_PRIOR_ALPHA
    beta: float = BETA_PRIOR_BETA
    last_error_type: str = ""
    # Time-weighted tracking: deque of (timestamp, latency_ms, success) tuples
    call_history: deque[tuple[float, float, bool]] = field(
        default_factory=lambda: deque(maxlen=MAX_CALL_HISTORY)
    )


class ExperienceStore:
    """Track per-(call_point, provider, model) experience.

    Subscribes to LLMUsageEvent for real-time updates.
    Provides experience snapshots for model scoring.
    """

    def __init__(
        self,
        event_bus: EventBus,
        warmup_data: dict[str, dict[str, Any]] | None = None,
        warmup_calls: int = WARMUP_CALLS_DEFAULT,
        exploration_weight: float = EXPLORATION_WEIGHT_DEFAULT,
    ) -> None:
        """Initialize the experience store.

        Args:
            event_bus: Event bus to subscribe to LLMUsageEvent.
            warmup_data: Pre-loaded experience data from relational_pool.
                Format: {"{call_point}.{provider}.{model}": {"call_count": ..., ...}}
            warmup_calls: Number of calls per call_point before switching
                from round-robin to Thompson Sampling. Default: 20.
            exploration_weight: Probability of random exploration after warmup.
                Default: 0.15 (15%).
        """
        self._experiences: dict[str, _ModelExperience] = {}
        self._lock = asyncio.Lock()
        self._event_bus = event_bus
        self._warmup_calls = warmup_calls
        self._warmup_counts: dict[str, int] = {}
        self._round_robin_indices: dict[str, int] = {}
        self._exploration_weight = exploration_weight

        # Warmup from historical data
        if warmup_data:
            for key, data in warmup_data.items():
                call_count = data.get("call_count", 0)
                success_count = data.get("success_count", 0)
                failure_count = data.get("failure_count", 0)
                total_latency_ms = data.get("total_latency_ms", 0.0)

                # Generate synthetic call history for time-weighted calculations
                # Distribute calls across the last 7 days with realistic timestamps
                call_history: deque[tuple[float, float, bool]] = deque(maxlen=MAX_CALL_HISTORY)
                if call_count > 0:
                    avg_latency = total_latency_ms / call_count if call_count > 0 else 0.0
                    now = monotonic()
                    # Create synthetic calls: RECENT_CALLS_RATIO in last 24h, rest in 24h-7d
                    recent_calls = int(call_count * RECENT_CALLS_RATIO)
                    old_calls = call_count - recent_calls

                    # Distribute successes proportionally
                    recent_successes = int(success_count * RECENT_CALLS_RATIO)
                    old_successes = success_count - recent_successes

                    # Recent calls (0-24h ago)
                    for i in range(recent_calls):
                        # 模拟数据非安全用途
                        timestamp = now - random.uniform(0, RECENT_WINDOW_SECONDS)  # nosec B311
                        success = i < recent_successes
                        call_history.append((timestamp, avg_latency, success))

                    # Older calls (24h-7d ago)
                    for i in range(old_calls):
                        # 模拟数据非安全用途
                        timestamp = now - random.uniform(  # nosec B311
                            RECENT_WINDOW_SECONDS, OLDER_WINDOW_SECONDS
                        )
                        success = i < old_successes
                        call_history.append((timestamp, avg_latency, success))

                exp = _ModelExperience(
                    call_count=call_count,
                    success_count=success_count,
                    failure_count=failure_count,
                    total_latency_ms=total_latency_ms,
                    last_call_time=monotonic(),
                    last_error_type=data.get("last_error_type", ""),
                    call_history=call_history,
                )
                exp.alpha = max(BETA_PRIOR_FLOOR, exp.success_count + BETA_PRIOR_ALPHA)
                exp.beta = max(BETA_PRIOR_FLOOR, exp.failure_count + BETA_PRIOR_BETA)
                self._experiences[key] = exp

        # Subscribe to events
        event_bus.subscribe(LLMUsageEvent, self._on_usage_event)

    async def _on_usage_event(self, event: LLMUsageEvent) -> None:
        """Handle LLMUsageEvent — update experience counters."""
        key = f"{event.call_point}.{event.provider}.{event.model}"
        now = monotonic()
        async with self._lock:
            exp = self._experiences.get(key)
            if exp is None:
                exp = _ModelExperience()
                self._experiences[key] = exp

            exp.call_count += 1
            exp.last_call_time = now
            exp.total_latency_ms += event.latency_ms

            if event.success:
                exp.success_count += 1
                exp.alpha += 1.0
            else:
                exp.failure_count += 1
                exp.beta += 1.0
                exp.last_error_type = event.error_type or ""

            # Record call history for time-weighted scoring
            exp.call_history.append((now, event.latency_ms, event.success))

            # Periodic cleanup: remove calls older than TTL to bound memory
            self._cleanup_old_calls(exp, now)

    def get_experience(self, call_point: str, provider: str, model: str) -> ExperienceData:
        """Get experience data for a specific model at a call point."""
        key = f"{call_point}.{provider}.{model}"
        exp = self._experiences.get(key)
        if exp is None:
            return ExperienceData()

        return ExperienceData(
            call_count=exp.call_count,
            success_count=exp.success_count,
            failure_count=exp.failure_count,
            total_latency_ms=exp.total_latency_ms,
            avg_latency_ms=exp.total_latency_ms / exp.call_count if exp.call_count > 0 else 0.0,
            last_call_time=exp.last_call_time,
            thompson_alpha=exp.alpha,
            thompson_beta=exp.beta,
            last_error_type=exp.last_error_type,
        )

    @staticmethod
    def _calculate_time_weight(timestamp: float, current_time: float) -> float:
        """Calculate time-based weight for a historical call.

        Args:
            timestamp: When the call occurred (monotonic time).
            current_time: Current monotonic time.

        Returns:
            Weight: RECENT_WINDOW_WEIGHT for <24h, OLDER_WINDOW_WEIGHT for 24h-7d, 0.0 for >7d.
        """
        age_seconds = current_time - timestamp

        if age_seconds > OLDER_WINDOW_SECONDS:
            return 0.0
        elif age_seconds > RECENT_WINDOW_SECONDS:
            return OLDER_WINDOW_WEIGHT
        else:
            return RECENT_WINDOW_WEIGHT

    def _cleanup_old_calls(self, exp: _ModelExperience, current_time: float) -> None:
        """Remove calls older than TTL to prevent memory growth."""
        # Keep only calls within last TTL window (in-place filter for deque)
        retained = deque(
            (ts, lat, succ)
            for ts, lat, succ in exp.call_history
            if current_time - ts <= CALL_HISTORY_TTL_SECONDS
        )
        exp.call_history.clear()
        exp.call_history.extend(retained)

    def reliability(self, call_point: str, provider: str, model: str) -> float:
        """Get time-weighted reliability score (success rate). Returns 1.0 for new models.

        Applies time decay:
        - Calls <24h: weight = 1.0
        - Calls 24h-7d: weight = 0.5
        - Calls >7d: excluded (weight = 0.0)
        """
        key = f"{call_point}.{provider}.{model}"
        exp = self._experiences.get(key)
        if exp is None or not exp.call_history:
            return 1.0

        now = monotonic()
        self._cleanup_old_calls(exp, now)

        weighted_success = 0.0
        weighted_total = 0.0

        for timestamp, _latency, success in exp.call_history:
            weight = self._calculate_time_weight(timestamp, now)
            if weight > 0.0:
                weighted_total += weight
                if success:
                    weighted_success += weight

        if weighted_total == 0.0:
            return 1.0

        return weighted_success / weighted_total

    def avg_latency(self, call_point: str, provider: str, model: str) -> float:
        """Get time-weighted average latency in ms. Returns 0.0 for new models.

        Applies time decay:
        - Calls <24h: weight = 1.0
        - Calls 24h-7d: weight = 0.5
        - Calls >7d: excluded (weight = 0.0)
        """
        key = f"{call_point}.{provider}.{model}"
        exp = self._experiences.get(key)
        if exp is None or not exp.call_history:
            return 0.0

        now = monotonic()
        self._cleanup_old_calls(exp, now)

        weighted_latency = 0.0
        weighted_total = 0.0

        for timestamp, latency, _success in exp.call_history:
            weight = self._calculate_time_weight(timestamp, now)
            if weight > 0.0:
                weighted_total += weight
                weighted_latency += weight * latency

        if weighted_total == 0.0:
            return 0.0

        return weighted_latency / weighted_total

    def thompson_sample(self, call_point: str, provider: str, model: str) -> float:
        """Sample from Beta distribution for Thompson Sampling exploration bonus.

        New models (few samples) return values with high variance.
        Mature models return values tightly clustered around success rate.
        """
        key = f"{call_point}.{provider}.{model}"
        exp = self._experiences.get(key)
        if exp is None:
            return random.betavariate(BETA_PRIOR_ALPHA, BETA_PRIOR_BETA)
        return random.betavariate(exp.alpha, exp.beta)

    def select_provider(self, call_point: str, providers: list[str], model: str) -> str:
        """Select a provider using round-robin during warmup, Thompson Sampling after.

        After warmup, uses Thompson Sampling scores to select the best provider.
        With exploration_weight=0.15 probability, randomly selects a provider
        instead of the best-scoring one to encourage exploration.

        Args:
            call_point: The call point identifier.
            providers: List of available provider names.
            model: The model name.

        Returns:
            Selected provider name.
        """
        if not providers:
            raise ValueError("providers list must not be empty")

        warmup_key = call_point
        current_count = self._warmup_counts.get(warmup_key, 0)

        if current_count < self._warmup_calls:
            # Round-robin during warmup
            idx = self._round_robin_indices.get(warmup_key, 0)
            selected = providers[idx % len(providers)]
            self._round_robin_indices[warmup_key] = (idx + 1) % len(providers)
            self._warmup_counts[warmup_key] = current_count + 1
            return selected

        # Random exploration probability
        # ε-greedy 探索非密码学
        if random.random() < self._exploration_weight:  # nosec B311
            return random.choice(providers)  # nosec B311

        # Thompson Sampling after warmup
        best_provider = providers[0]
        best_score = -1.0
        for provider in providers:
            score = self.thompson_sample(call_point, provider, model)
            if score > best_score:
                best_score = score
                best_provider = provider
        return best_provider

    def warmup_complete(self, call_point: str) -> bool:
        """Check if warmup period is complete for a given call point."""
        return self._warmup_counts.get(call_point, 0) >= self._warmup_calls

    @property
    def experience_count(self) -> int:
        """Number of tracked (call_point, provider, model) triplets."""
        return len(self._experiences)
