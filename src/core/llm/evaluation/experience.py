# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Model experience tracking for smart routing.

Subscribes to LLMUsageEvent to track per-model performance,
supports Thompson Sampling for exploration bonuses.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from time import monotonic
from typing import Any

from core.event.bus import EventBus, LLMUsageEvent
from core.llm.types import ExperienceData
from core.observability.logging import get_logger

log = get_logger(__name__)


@dataclass
class _ModelExperience:
    """Internal counter for a single model at a call point."""

    call_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_latency_ms: float = 0.0
    last_call_time: float = 0.0
    # Thompson Sampling Beta distribution params
    alpha: float = 1.0
    beta: float = 1.0
    last_error_type: str = ""


class ExperienceStore:
    """Track per-(call_point, provider, model) experience.

    Subscribes to LLMUsageEvent for real-time updates.
    Provides experience snapshots for model scoring.
    """

    def __init__(
        self,
        event_bus: EventBus,
        warmup_data: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        """Initialize the experience store.

        Args:
            event_bus: Event bus to subscribe to LLMUsageEvent.
            warmup_data: Pre-loaded experience data from relational_pool.
                Format: {"{call_point}.{provider}.{model}": {"call_count": ..., ...}}
        """
        self._experiences: dict[str, _ModelExperience] = {}
        self._lock = asyncio.Lock()
        self._event_bus = event_bus

        # Warmup from historical data
        if warmup_data:
            for key, data in warmup_data.items():
                exp = _ModelExperience(
                    call_count=data.get("call_count", 0),
                    success_count=data.get("success_count", 0),
                    failure_count=data.get("failure_count", 0),
                    total_latency_ms=data.get("total_latency_ms", 0.0),
                    last_call_time=monotonic(),
                    last_error_type=data.get("last_error_type", ""),
                )
                exp.alpha = max(1.0, exp.success_count + 1.0)
                exp.beta = max(1.0, exp.failure_count + 1.0)
                self._experiences[key] = exp

        # Subscribe to events
        event_bus.subscribe(LLMUsageEvent, self._on_usage_event)

    async def _on_usage_event(self, event: LLMUsageEvent) -> None:
        """Handle LLMUsageEvent — update experience counters."""
        key = f"{event.call_point}.{event.provider}.{event.model}"
        async with self._lock:
            exp = self._experiences.get(key)
            if exp is None:
                exp = _ModelExperience()
                self._experiences[key] = exp

            exp.call_count += 1
            exp.last_call_time = monotonic()
            exp.total_latency_ms += event.latency_ms

            if event.success:
                exp.success_count += 1
                exp.alpha += 1.0
            else:
                exp.failure_count += 1
                exp.beta += 1.0
                exp.last_error_type = event.error_type or ""

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

    def reliability(self, call_point: str, provider: str, model: str) -> float:
        """Get reliability score (success rate). Returns 1.0 for new models."""
        key = f"{call_point}.{provider}.{model}"
        exp = self._experiences.get(key)
        if exp is None or exp.call_count == 0:
            return 1.0
        return exp.success_count / exp.call_count

    def avg_latency(self, call_point: str, provider: str, model: str) -> float:
        """Get average latency in ms. Returns 0.0 for new models."""
        key = f"{call_point}.{provider}.{model}"
        exp = self._experiences.get(key)
        if exp is None or exp.call_count == 0:
            return 0.0
        return exp.total_latency_ms / exp.call_count

    def thompson_sample(self, call_point: str, provider: str, model: str) -> float:
        """Sample from Beta distribution for Thompson Sampling exploration bonus.

        New models (few samples) return values with high variance.
        Mature models return values tightly clustered around success rate.
        """
        key = f"{call_point}.{provider}.{model}"
        exp = self._experiences.get(key)
        if exp is None:
            return random.betavariate(1.0, 1.0)
        return random.betavariate(exp.alpha, exp.beta)

    @property
    def experience_count(self) -> int:
        """Number of tracked (call_point, provider, model) triplets."""
        return len(self._experiences)
