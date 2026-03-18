# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Credibility checker pipeline node — multi-signal credibility scoring."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from core.event.bus import CredibilityComputedEvent, EventBus
from core.llm.client import LLMClient
from core.llm.output_validator import CredibilityOutput
from core.llm.token_budget import TokenBudgetManager
from core.llm.types import CallPoint
from core.observability.logging import get_logger
from core.observability.metrics import MetricsCollector
from modules.pipeline.state import PipelineState

log = get_logger("node.credibility_checker")


class CredibilityCheckerNode:
    """Pipeline node: compute credibility score from 4 signals.

    Signals:
    1. Source authority          (weight: 0.30)
    2. Cross-verification count (weight: 0.25)
    3. LLM content check        (weight: 0.30)
    4. Timeliness               (weight: 0.15)
    """

    WEIGHTS = {
        "source": 0.30,
        "cross": 0.25,
        "content": 0.30,
        "timeliness": 0.15,
    }

    def __init__(
        self,
        llm: LLMClient,
        budget: TokenBudgetManager,
        event_bus: EventBus,
        source_auth_repo: Any = None,
    ) -> None:
        self._llm = llm
        self._budget = budget
        self._event_bus = event_bus
        self._source_auth_repo = source_auth_repo

    async def execute(self, state: PipelineState) -> PipelineState:
        """Compute credibility score."""
        if state.get("terminal") or state.get("is_merged"):
            return state

        # Signal 1: Source authority
        s1 = 0.50  # default
        if self._source_auth_repo:
            try:
                source_auth = await self._source_auth_repo.get_or_create(
                    host=state["raw"].source_host,
                    auto_score=None,
                )
                s1 = float(source_auth.authority)
            except Exception as exc:
                log.warning("source_auth_lookup_failed", error=str(exc))

        # Signal 2: Cross-verification
        cross_count = len(state.get("merged_source_ids", []))
        s2 = min(1.0, 0.4 + cross_count * 0.15)

        # Signal 3: LLM content check
        body_trunc = self._budget.truncate(state["cleaned"]["body"], CallPoint.CREDIBILITY_CHECKER)
        try:
            llm_result: CredibilityOutput = await self._llm.call(
                CallPoint.CREDIBILITY_CHECKER,
                {
                    "title": state["cleaned"]["title"],
                    "body": body_trunc,
                    "summary": state.get("summary_info", {}).get("summary", ""),
                },
                output_model=CredibilityOutput,
            )
            s3 = llm_result.score
            flags = llm_result.flags
        except Exception as e:
            log.warning("credibility_llm_failed_using_default", error=str(e))
            s3 = 0.5
            flags = []

        # Signal 4: Timeliness
        s4 = self._calc_timeliness(
            state["cleaned"].get("publish_time"),
            state.get("summary_info", {}).get("event_time"),
        )

        # Weighted aggregation
        score = (
            s1 * self.WEIGHTS["source"]
            + s2 * self.WEIGHTS["cross"]
            + s3 * self.WEIGHTS["content"]
            + s4 * self.WEIGHTS["timeliness"]
        )

        state["credibility"] = {
            "score": round(score, 2),
            "source_credibility": s1,
            "cross_verification": s2,
            "content_check": s3,
            "timeliness": s4,
            "flags": flags,
            "verified_by_sources": cross_count,
        }

        # Record metrics
        MetricsCollector.credibility_score_dist.observe(score)

        # Publish event
        await self._event_bus.publish(
            CredibilityComputedEvent(
                url=state["raw"].url,
                score=score,
                cross_count=cross_count,
            )
        )

        log.info(
            "credibility_checked",
            url=state["raw"].url,
            score=round(score, 2),
            flags=flags,
        )
        return state

    @staticmethod
    def _calc_timeliness(
        publish_time: datetime | None,
        event_time_str: str | None,
    ) -> float:
        """Calculate timeliness score.

        Shorter gap between publish and event time = higher credibility.
        """
        if not publish_time or not event_time_str:
            return 0.7  # neutral if unknown

        try:
            event_time = datetime.fromisoformat(event_time_str)
            if event_time.tzinfo is None:
                event_time = event_time.replace(tzinfo=UTC)
        except ValueError:
            return 0.7

        delta_hours = abs((publish_time - event_time).total_seconds()) / 3600
        if delta_hours <= 6:
            return 1.00
        if delta_hours <= 24:
            return 0.85
        if delta_hours <= 72:
            return 0.65
        if delta_hours <= 168:
            return 0.45
        return 0.30
