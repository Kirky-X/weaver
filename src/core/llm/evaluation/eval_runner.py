# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Shadow evaluation runner for model comparison.

Issues parallel shadow calls to candidate models without
blocking the main call path.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from time import monotonic
from typing import TYPE_CHECKING, Any

from core.event.bus import LLMCompareEvent
from core.llm.types import EvalConfig, Label, TokenUsage
from core.observability.logging import get_logger

if TYPE_CHECKING:
    from core.event.bus import EventBus
    from core.llm.client import LLMClient

log = get_logger(__name__)


@dataclass
class EvalRunnerConfig:
    """Configuration for shadow evaluation."""

    enabled: bool = False
    sample_rate: float = 0.1
    target_call_points: set[str] = field(default_factory=set)
    candidate_labels: list[Label] = field(default_factory=list)


class EvalRunner:
    """Shadow evaluation runner.

    Randomly samples LLM requests and issues parallel shadow calls
    to candidate models for comparison. Results are published as
    LLMCompareEvent to the EventBus.
    """

    def __init__(
        self,
        config: EvalRunnerConfig,
        llm_client: LLMClient,
        event_bus: EventBus,
    ) -> None:
        """Initialize the EvalRunner.

        Args:
            config: Shadow evaluation configuration.
            llm_client: LLM client for issuing shadow calls.
            event_bus: Event bus for publishing results.
        """
        self._config = config
        self._llm_client = llm_client
        self._event_bus = event_bus

    @classmethod
    def from_eval_config(
        cls,
        eval_cfg: EvalConfig,
        llm_client: LLMClient,
        event_bus: EventBus,
    ) -> EvalRunner:
        """Create EvalRunner from EvalConfig."""
        candidate_labels = []
        for label_str in eval_cfg.candidate_models:
            try:
                candidate_labels.append(Label.parse(label_str))
            except ValueError:
                log.warning("eval_invalid_candidate", label=label_str)

        return cls(
            config=EvalRunnerConfig(
                enabled=eval_cfg.enabled,
                sample_rate=eval_cfg.sample_rate,
                target_call_points=set(eval_cfg.target_call_points),
                candidate_labels=candidate_labels,
            ),
            llm_client=llm_client,
            event_bus=event_bus,
        )

    def should_trigger(self, call_point: str) -> bool:
        """Check if a shadow call should be triggered for this request."""
        if not self._config.enabled:
            return False
        if not self._config.target_call_points:
            return False
        if call_point not in self._config.target_call_points:
            return False
        return random.random() < self._config.sample_rate

    async def trigger_shadow_call(
        self,
        call_point: str,
        primary_label: Label,
        primary_result: Any,
        primary_latency: float,
        primary_success: bool,
        primary_tokens: TokenUsage,
        payload: dict[str, Any],
    ) -> None:
        """Trigger a shadow call — fire and forget.

        This method MUST NOT block or raise. All errors are caught and logged.

        Args:
            call_point: The pipeline call point.
            primary_label: The primary model label.
            primary_result: The primary model's output.
            primary_latency: The primary model's latency (ms).
            primary_success: Whether the primary call succeeded.
            primary_tokens: Token usage of the primary call.
            payload: The original LLM payload.
        """
        if not self._config.candidate_labels:
            return

        # Fire and forget — run in background task
        asyncio.create_task(
            self._run_shadow(
                call_point=call_point,
                primary_label=primary_label,
                primary_result=primary_result,
                primary_latency=primary_latency,
                primary_success=primary_success,
                primary_tokens=primary_tokens,
                payload=payload,
            ),
            name=f"shadow_eval_{call_point}",
        )

    async def _run_shadow(
        self,
        call_point: str,
        primary_label: Label,
        primary_result: Any,
        primary_latency: float,
        primary_success: bool,
        primary_tokens: TokenUsage,
        payload: dict[str, Any],
    ) -> None:
        """Execute shadow call and publish comparison event."""
        for candidate_label in self._config.candidate_labels:
            try:
                start = monotonic()
                candidate_result = await self._llm_client.call(
                    label=candidate_label,
                    payload=payload,
                )
                candidate_latency = (monotonic() - start) * 1000

                event = LLMCompareEvent(
                    call_point=call_point,
                    primary_model=str(primary_label),
                    candidate_model=str(candidate_label),
                    primary_latency=primary_latency,
                    candidate_latency=candidate_latency,
                    primary_success=primary_success,
                    candidate_success=True,
                    primary_output=str(primary_result) if primary_result else "",
                    candidate_output=str(candidate_result) if candidate_result else "",
                    primary_tokens=primary_tokens,
                )
                await self._event_bus.publish(event)

                log.info(
                    "eval_shadow_complete",
                    call_point=call_point,
                    primary=str(primary_label),
                    candidate=str(candidate_label),
                    latency_delta_ms=abs(primary_latency - candidate_latency),
                )

            except Exception as exc:
                log.warning(
                    "eval_shadow_failed",
                    call_point=call_point,
                    candidate=str(candidate_label),
                    error=str(exc),
                )

                event = LLMCompareEvent(
                    call_point=call_point,
                    primary_model=str(primary_label),
                    candidate_model=str(candidate_label),
                    primary_latency=primary_latency,
                    candidate_latency=0.0,
                    primary_success=primary_success,
                    candidate_success=False,
                    primary_output=str(primary_result) if primary_result else "",
                )
                await self._event_bus.publish(event)

    @property
    def is_enabled(self) -> bool:
        """Whether shadow evaluation is currently enabled."""
        return self._config.enabled and bool(self._config.candidate_labels)
