# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Rule-based credibility checker — no LLM dependency.

Three signals:
1. Source authority          (weight: category-adaptive)
2. Cross-verification        (weight: category-adaptive, body-length proxy)
3. Timeliness                (weight: category-adaptive)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from core.event.bus import CredibilityComputedEvent, EventBus
from core.observability.logging import get_logger

if TYPE_CHECKING:
    from modules.ingestion.scheduling.source_config_repo import SourceConfigRepo
    from modules.storage import SourceAuthorityRepo

from modules.processing.pipeline.state import PipelineState

log = get_logger(__name__)


class RuleBasedCredibilityCheckerNode:
    """Pipeline node: compute credibility score from 3 signals via rules (no LLM).

    Signals:
    1. Source authority          (weight: category-adaptive, 3-level priority lookup)
    2. Cross-verification        (weight: category-adaptive, body-length proxy)
    3. Timeliness                (weight: category-adaptive, publish/event gap)

    Implements: CredibilityCheckerNode (backward-compatible alias)
    """

    CATEGORY_WEIGHTS: dict[str, dict[str, float]] = {
        "政治": {"source": 0.25, "content": 0.25, "timeliness": 0.50},
        "国际": {"source": 0.25, "content": 0.25, "timeliness": 0.50},
        "军事": {"source": 0.25, "content": 0.25, "timeliness": 0.50},
        "经济": {"source": 0.45, "content": 0.35, "timeliness": 0.20},
        "科技": {"source": 0.30, "content": 0.50, "timeliness": 0.20},
        "社会": {"source": 0.40, "content": 0.40, "timeliness": 0.20},
        "文化": {"source": 0.40, "content": 0.40, "timeliness": 0.20},
        "体育": {"source": 0.40, "content": 0.40, "timeliness": 0.20},
    }

    DEFAULT_WEIGHTS = {"source": 0.40, "content": 0.40, "timeliness": 0.20}

    def __init__(
        self,
        llm: Any = None,
        budget: Any = None,
        event_bus: EventBus | None = None,
        source_auth_repo: SourceAuthorityRepo | None = None,
        source_config_repo: SourceConfigRepo | None = None,
    ) -> None:
        """Initialize rule-based credibility checker.

        Note: llm and budget are accepted for backward compatibility
        but no longer used. All scoring is rule-based.

        Args:
            llm: Ignored (backward compatibility).
            budget: Ignored (backward compatibility).
            event_bus: Event bus for publishing events.
            source_auth_repo: Repository for source authority scores.
            source_config_repo: Repository for source preset credibility.
        """
        self._event_bus = event_bus
        self._source_auth_repo = source_auth_repo
        self._source_config_repo = source_config_repo

    async def execute(self, state: PipelineState) -> PipelineState:
        """Compute credibility score using three rule-based signals.

        Uses three-level priority for source authority:
        1. SourceConfig.credibility (preset by admin)
        2. SourceAuthority.authority (auto-calculated from history)
        3. Default 0.50
        """
        if state.get("terminal") or state.get("is_merged"):
            return state

        category = state.get("category")
        weights = self.CATEGORY_WEIGHTS.get(category, self.DEFAULT_WEIGHTS)

        # Signal 1: Source authority (three-level priority)
        s1 = await self._get_source_authority(state["raw"].source_host)

        # Signal 2: Cross-verification via body length (no LLM)
        body = state.get("cleaned", {}).get("body", "")
        if len(body) > 3000:
            s2 = 0.8
        elif len(body) > 1000:
            s2 = 0.6
        else:
            s2 = 0.4

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
            "cross_verification": s2,
            "content_check": s2,
            "timeliness": s3,
            "flags": [],
        }

        if self._event_bus:
            await self._event_bus.publish(
                CredibilityComputedEvent(
                    url=state["raw"].url,
                    score=score,
                )
            )

        log.info(
            "credibility_checked",
            url=state["raw"].url,
            score=round(score, 2),
            flags=[],
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
        if self._source_config_repo:
            try:
                preset = await self._source_config_repo.get_credibility(host)
                if preset is not None:
                    log.debug("using_preset_credibility", host=host, value=preset)
                    return preset
            except Exception as exc:
                log.warning(
                    "preset_credibility_lookup_failed",
                    host=host,
                    exc_type=type(exc).__name__,
                    error=str(exc),
                )

        if self._source_auth_repo:
            try:
                source_auth = await self._source_auth_repo.get_or_create(
                    host=host,
                    auto_score=None,
                )
                return float(source_auth.authority)
            except Exception as exc:
                log.warning(
                    "source_auth_lookup_failed",
                    host=host,
                    exc_type=type(exc).__name__,
                    error=str(exc),
                )

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
            return 0.7

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


# Backward-compatible alias for Pipeline graph and __init__ exports
CredibilityCheckerNode = RuleBasedCredibilityCheckerNode
