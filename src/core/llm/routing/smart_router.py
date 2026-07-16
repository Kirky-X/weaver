# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""SmartRouter: unified routing facade for LLM model selection.

Coordinates the RoutingPipeline (rule-based filtering) and
ModelSelector (weighted scoring) to produce an optimal sorted
list of candidate labels for each call point.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.llm.routing.model_selector import ModelSelector
from core.llm.routing.router import LabelRouter
from core.llm.types import GlobalConfig, Label, RoutingMode
from core.observability import get_logger

if TYPE_CHECKING:
    from core.llm.config.config import LLMSettings
    from core.llm.evaluation.experience import ExperienceStore
    from core.llm.resilience.circuit_breaker import ProviderCircuitBreaker

log = get_logger(__name__)


class SmartRouter:
    """Unified routing facade.

    Combines:
    - Per-call-point routing mode resolution from LLMSettings
    - ModelSelector for weighted scoring and ranking
    - LabelRouter fallback when smart routing is disabled

    Usage:
        router = SmartRouter(llm_settings, experience, circuit_breakers)
        labels = router.route("classifier")
        # labels = [best_label, fallback1, fallback2, ...]
    """

    def __init__(
        self,
        settings: LLMSettings,
        experience: ExperienceStore,
        circuit_breakers: dict[str, ProviderCircuitBreaker],
    ) -> None:
        """Initialize the SmartRouter.

        Args:
            settings: LLMSettings with routing configuration.
            experience: ExperienceStore for model performance data.
            circuit_breakers: Map of provider name to circuit breaker.
        """
        self._settings = settings
        self._experience = experience
        self._circuit_breakers = circuit_breakers

        # Fallback to existing LabelRouter
        self._label_router = LabelRouter(
            GlobalConfig(
                circuit_breaker_threshold=settings.circuit_breaker_threshold,
                circuit_breaker_timeout=settings.circuit_breaker_timeout,
                default_timeout=settings.default_timeout,
                defaults=settings.defaults,
                call_points=settings.call_points,
            )
        )

        # Build ModelSelector
        self._selector = ModelSelector(
            experience=experience,
            circuit_breakers=circuit_breakers,
        )

    def route(
        self,
        call_point: str,
    ) -> list[Label]:
        """Route a call point to a sorted list of candidate labels.

        If smart routing is configured for this call point, uses
        ModelSelector to score and rank candidates. Otherwise falls
        back to the static LabelRouter primary/fallback chain.

        Args:
            call_point: The pipeline stage name.

        Returns:
            Sorted list of labels, highest-scoring first.
        """
        # Check if smart routing is configured for this call point
        routing_cfg = self._settings.routing.get(call_point)
        if not routing_cfg:
            # No smart routing config → fallback to static chain
            return self._fallback_route(call_point)

        # Resolve routing mode
        mode_str = routing_cfg.get("mode", "auto")
        try:
            mode = RoutingMode(mode_str)
        except ValueError:
            mode = RoutingMode.AUTO

        # Get candidate labels from static config
        static_labels = self._fallback_route(call_point)
        if not static_labels:
            return []

        # Score and rank via ModelSelector
        try:
            return self._selector.select(
                call_point=call_point,
                candidates=static_labels,
                mode=mode,
            )
        except Exception as exc:
            log.warning(
                "smart_router_fallback",
                call_point=call_point,
                error=str(exc),
            )
            return static_labels

    def _fallback_route(self, call_point: str) -> list[Label]:
        """Fallback to static LabelRouter primary/fallback chain."""
        try:
            return self._label_router.get_call_point_route(call_point)
        except (ValueError, KeyError):
            # Try defaults
            try:
                label = self._label_router.get_default(self._infer_llm_type(call_point))
                return [label]
            except ValueError:
                return []

    @staticmethod
    def _infer_llm_type(call_point: str) -> Any:
        """Infer LLMType from call point name."""
        from core.llm.types import LLMType

        if "embedding" in call_point:
            return LLMType.EMBEDDING
        if "rerank" in call_point:
            return LLMType.RERANK
        return LLMType.CHAT
