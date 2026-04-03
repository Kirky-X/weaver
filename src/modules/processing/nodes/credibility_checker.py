# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Credibility checker pipeline node — multi-signal credibility scoring."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from core.event.bus import CredibilityComputedEvent, EventBus
from core.llm.client import LLMClient
from core.llm.output_validator import CredibilityOutput
from core.llm.token_budget import TokenBudgetManager
from core.llm.types import CallPoint
from core.observability.logging import get_logger
from core.observability.metrics import MetricsCollector
from modules.processing.pipeline.state import PipelineState

if TYPE_CHECKING:
    from modules.ingestion.scheduling.source_config_repo import SourceConfigRepo
    from modules.storage.source_authority_repo import SourceAuthorityRepo

log = get_logger("node.credibility_checker")


class CredibilityCheckerNode:
    """Pipeline node: compute credibility score from 3 signals.

    Signals:
    1. Source authority          (weight: category-adaptive)
    2. LLM content check        (weight: category-adaptive)
    3. Timeliness               (weight: category-adaptive)

    Cross-verification signal removed: BatchMerger merges similar articles,
    so merged_source_ids cannot distinguish reprints from independent reports.
    """

    # Category-adaptive weights based on article type
    # Breaking news: timeliness is most important
    # Economic news: source authority is most important
    # Tech news: content quality is most important
    CATEGORY_WEIGHTS: dict[str, dict[str, float]] = {
        # Breaking news: timeliness priority
        "政治": {"source": 0.25, "content": 0.25, "timeliness": 0.50},
        "国际": {"source": 0.25, "content": 0.25, "timeliness": 0.50},
        "军事": {"source": 0.25, "content": 0.25, "timeliness": 0.50},
        # Economic: source authority priority
        "经济": {"source": 0.45, "content": 0.35, "timeliness": 0.20},
        # Tech: content quality priority
        "科技": {"source": 0.30, "content": 0.50, "timeliness": 0.20},
        # Default: balanced
        "社会": {"source": 0.40, "content": 0.40, "timeliness": 0.20},
        "文化": {"source": 0.40, "content": 0.40, "timeliness": 0.20},
        "体育": {"source": 0.40, "content": 0.40, "timeliness": 0.20},
    }

    DEFAULT_WEIGHTS = {"source": 0.40, "content": 0.40, "timeliness": 0.20}

    def __init__(
        self,
        llm: LLMClient,
        budget: TokenBudgetManager,
        event_bus: EventBus,
        source_auth_repo: SourceAuthorityRepo | None = None,
        source_config_repo: SourceConfigRepo | None = None,
    ) -> None:
        """Initialize credibility checker.

        Args:
            llm: LLM client for content analysis.
            budget: Token budget manager for truncation.
            event_bus: Event bus for publishing events.
            source_auth_repo: Repository for source authority scores.
            source_config_repo: Repository for source preset credibility.
        """
        self._llm = llm
        self._budget = budget
        self._event_bus = event_bus
        self._source_auth_repo = source_auth_repo
        self._source_config_repo = source_config_repo

    async def execute(self, state: PipelineState) -> PipelineState:
        """Compute credibility score.

        Uses three-level priority for source authority:
        1. SourceConfig.credibility (preset by admin)
        2. SourceAuthority.authority (auto-calculated from history)
        3. Default 0.50
        """
        if state.get("terminal") or state.get("is_merged"):
            return state

        # Get category-adaptive weights
        category = state.get("category")
        weights = self.CATEGORY_WEIGHTS.get(category, self.DEFAULT_WEIGHTS)

        # Signal 1: Source authority (three-level priority)
        s1 = await self._get_source_authority(state["raw"].source_host)

        # Signal 2: LLM content check
        body_trunc = self._budget.truncate(state["cleaned"]["body"], CallPoint.CREDIBILITY_CHECKER)
        try:
            llm_result: CredibilityOutput = await self._llm.call_at(
                CallPoint.CREDIBILITY_CHECKER,
                {
                    "title": state["cleaned"]["title"],
                    "body": body_trunc,
                    "summary": state.get("summary_info", {}).get("summary", ""),
                    "article_id": state.get("article_id"),
                    "task_id": state.get("task_id"),
                },
                output_model=CredibilityOutput,
            )
            s2 = llm_result.score
            flags = llm_result.flags
        except Exception as e:
            log.warning("credibility_llm_failed_using_default", error=str(e))
            s2 = 0.5
            flags = []

        # Signal 3: Timeliness
        s3 = self._calc_timeliness(
            state["cleaned"].get("publish_time"),
            state.get("summary_info", {}).get("event_time"),
        )

        # Weighted aggregation with category-adaptive weights
        score = s1 * weights["source"] + s2 * weights["content"] + s3 * weights["timeliness"]

        state["credibility"] = {
            "score": round(score, 2),
            "source_credibility": s1,
            "content_check": s2,
            "timeliness": s3,
            "flags": flags,
        }

        # Record metrics
        MetricsCollector.credibility_score_dist.observe(score)

        # Publish event
        await self._event_bus.publish(
            CredibilityComputedEvent(
                url=state["raw"].url,
                score=score,
                cross_count=0,  # No longer used
            )
        )

        log.info(
            "credibility_checked",
            url=state["raw"].url,
            score=round(score, 2),
            flags=flags,
            category=category,
        )
        return state

    async def _get_source_authority(self, host: str) -> float:
        """Get source authority with three-level priority.

        Priority:
        1. SourceConfig.credibility (preset by admin)
        2. SourceAuthority.authority (auto-calculated)
        3. Default 0.50

        Args:
            host: Source hostname.

        Returns:
            Source authority score.
        """
        # Priority 1: Check for preset credibility
        if self._source_config_repo:
            try:
                preset = await self._source_config_repo.get_credibility(host)
                if preset is not None:
                    log.debug("using_preset_credibility", host=host, value=preset)
                    return preset
            except Exception as exc:
                log.warning("preset_credibility_lookup_failed", host=host, error=str(exc))

        # Priority 2: Check auto-calculated authority
        if self._source_auth_repo:
            try:
                source_auth = await self._source_auth_repo.get_or_create(
                    host=host,
                    auto_score=None,
                )
                return float(source_auth.authority)
            except Exception as exc:
                log.warning("source_auth_lookup_failed", host=host, error=str(exc))

        # Priority 3: Default
        return 0.50

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
