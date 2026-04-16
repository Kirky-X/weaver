# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Multi-dimensional weighted model selector for smart routing.

Scores candidate models using editorial, reliability, cost, and latency
dimensions, with Thompson Sampling exploration bonus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from core.llm.types import (
    Capability,
    Label,
    LLMType,
    RoutingInfeasibleError,
    RoutingMode,
)
from core.observability.logging import get_logger

if TYPE_CHECKING:
    from core.llm.evaluation.experience import ExperienceStore
    from core.llm.resilience.circuit_breaker import ProviderCircuitBreaker

log = get_logger(__name__)


# Default weights per routing mode
DEFAULT_WEIGHTS: dict[RoutingMode, dict[str, float]] = {
    RoutingMode.AUTO: {
        "editorial": 0.35,
        "reliability": 0.25,
        "cost": 0.15,
        "latency": 0.10,
    },
    RoutingMode.FAST: {
        "editorial": 0.20,
        "reliability": 0.15,
        "cost": 0.30,
        "latency": 0.25,
    },
    RoutingMode.BEST: {
        "editorial": 0.30,
        "reliability": 0.40,
        "cost": 0.05,
        "latency": 0.05,
    },
}


@dataclass(frozen=True, slots=True)
class WeightConfig:
    """Configurable scoring weights."""

    editorial: float = 0.35
    reliability: float = 0.25
    cost: float = 0.15
    latency: float = 0.10

    def get(self, key: str) -> float:
        """Get weight by key name."""
        return {
            "editorial": self.editorial,
            "reliability": self.reliability,
            "cost": self.cost,
            "latency": self.latency,
        }.get(key, 0.0)


@dataclass
class ModelSelector:
    """Multi-dimensional weighted model selector.

    Scores candidates on editorial priority, historical reliability,
    estimated cost, and historical latency. Returns sorted list with
    the highest-scoring model first.
    """

    experience: ExperienceStore
    circuit_breakers: dict[str, ProviderCircuitBreaker] = field(default_factory=dict)
    weights: dict[RoutingMode, WeightConfig] = field(
        default_factory=lambda: {mode: WeightConfig(**w) for mode, w in DEFAULT_WEIGHTS.items()}
    )
    cost_per_model: dict[str, float] = field(default_factory=dict)

    def select(
        self,
        call_point: str,
        candidates: list[Label],
        mode: RoutingMode = RoutingMode.AUTO,
        required_capability: Capability | None = None,
    ) -> list[Label]:
        """Select and rank candidate models.

        Args:
            call_point: The pipeline stage requesting this model.
            candidates: List of candidate labels from routing config.
            mode: Routing mode controlling weight configuration.
            required_capability: Required model capability (chat/embedding/rerank).

        Returns:
            Sorted list of labels, highest-scoring first.

        Raises:
            RoutingInfeasibleError: If no candidates pass all filters.
        """
        # Phase 1: Filter by circuit breaker state
        active = self._filter_by_circuit_breaker(candidates)

        # Phase 2: Filter by capability
        capable = self._filter_by_capability(active, required_capability)

        if not capable:
            raise RoutingInfeasibleError(
                f"No available candidates for call_point={call_point}",
                reason="no_available_models",
            )

        # Phase 3: Score and sort
        return self._score_and_rank(call_point, capable, mode)

    def _filter_by_circuit_breaker(self, candidates: list[Label]) -> list[Label]:
        """Exclude labels belonging to providers with OPEN circuit breakers."""
        active: list[Label] = []
        for label in candidates:
            cb = self.circuit_breakers.get(label.provider)
            if cb is not None and cb.is_open:
                log.debug(
                    "selector_exclude_circuit_open",
                    provider=label.provider,
                    label=str(label),
                )
                continue
            active.append(label)
        return active

    @staticmethod
    def _filter_by_capability(
        candidates: list[Label],
        required: Capability | None,
    ) -> list[Label]:
        """Filter out labels that don't match the required LLM type."""
        if required is None:
            return candidates

        type_to_cap = {
            LLMType.CHAT: Capability.CHAT,
            LLMType.EMBEDDING: Capability.EMBEDDING,
            LLMType.RERANK: Capability.RERANK,
        }
        required_cap = type_to_cap.get(required)
        if required_cap is None:
            return candidates

        return [label for label in candidates if label.llm_type == _cap_to_type(required_cap)]

    def _score_and_rank(
        self,
        call_point: str,
        candidates: list[Label],
        mode: RoutingMode,
    ) -> list[Label]:
        """Score each candidate and return sorted list."""
        weight_cfg = self.weights.get(mode, self.weights[RoutingMode.AUTO])

        # Collect raw scores for normalization
        costs: dict[str, float] = {}
        latencies: dict[str, float] = {}
        for label in candidates:
            key = str(label)
            costs[key] = self.cost_per_model.get(key, 0.0)
            latencies[key] = self.experience.avg_latency(call_point, label.provider, label.model)

        # Normalize to [0, 1] (inverse for cost/latency: lower is better)
        norm_costs = _normalize_inverse(costs)
        norm_latencies = _normalize_inverse(latencies)

        scored: list[tuple[float, Label]] = []
        for label in candidates:
            key = str(label)
            reliability = self.experience.reliability(call_point, label.provider, label.model)
            # Editorial: inverse position in candidate list (first = highest)
            idx = candidates.index(label)
            editorial = 1.0 / (idx + 1)

            # Circuit breaker slow request degradation
            cb = self.circuit_breakers.get(label.provider)
            if cb is not None and cb.is_slow:
                editorial *= 0.5
                log.debug(
                    "selector_editorial_degraded_slow",
                    provider=label.provider,
                    label=key,
                    original_editorial=round(1.0 / (idx + 1), 4),
                    degraded_editorial=round(editorial, 4),
                )

            # Thompson Sampling exploration bonus
            ts_bonus = self.experience.thompson_sample(call_point, label.provider, label.model)

            total = (
                weight_cfg.editorial * editorial
                + weight_cfg.reliability * reliability
                + weight_cfg.cost * norm_costs[key]
                + weight_cfg.latency * norm_latencies[key]
                + 0.15 * ts_bonus  # Fixed bonus weight
            )

            scored.append((total, label))
            log.debug(
                "selector_scored_candidate",
                label=key,
                total=round(total, 4),
                editorial=round(editorial, 4),
                reliability=round(reliability, 4),
                cost=round(norm_costs[key], 4),
                latency=round(norm_latencies[key], 4),
                thompson=round(ts_bonus, 4),
            )

        scored.sort(key=lambda x: x[0], reverse=True)
        return [label for _, label in scored]


def _normalize_inverse(values: dict[str, float]) -> dict[str, float]:
    """Inverse min-max normalization: lowest value gets 1.0, highest gets 0.0."""
    if not values:
        return {}
    min_val = min(values.values())
    max_val = max(values.values())
    if max_val <= min_val or max_val == 0:
        return dict.fromkeys(values, 0.5)
    return {k: 1.0 - (v - min_val) / (max_val - min_val) for k, v in values.items()}


def _cap_to_type(cap: Capability) -> LLMType:
    """Map Capability to LLMType."""
    mapping = {
        Capability.CHAT: LLMType.CHAT,
        Capability.EMBEDDING: LLMType.EMBEDDING,
        Capability.RERANK: LLMType.RERANK,
    }
    return mapping.get(cap, LLMType.CHAT)
