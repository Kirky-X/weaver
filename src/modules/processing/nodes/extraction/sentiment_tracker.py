# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Article-level sentiment tracker pipeline node (T003).

Computes per-entity sentiment shifts between consecutive articles. For each
entity mentioned in the current article, the node queries the previous
article-level ``sentiment_shifts`` record for that entity, computes
``shift_value = current_sentiment - previous_after_avg``, and persists a
new article-level shift record.

This node is a pure computation node — it does NOT call the LLM. The
current sentiment_score is read from ``state["sentiment"]["sentiment_score"]``
(populated by AnalyzeNode); entities are read from ``state["entities"]``
(populated by EntityExtractorNode).

Failure handling follows Rule 12 (失败显性化): any repo error marks
``"sentiment_shift"`` in ``state["degraded_fields"]`` without blocking
the pipeline. Missing prerequisites (terminal/merged/no article_id/no
sentiment_score/no entities) result in a silent no-op — these are not
failures, just nothing-to-do.

Schema mapping (migration 30 + existing sentiment_shifts columns):
- ``community_id`` ← ``entity_name`` (reused as entity identifier for
  article-level records; community-level records use real community id).
- ``shift_type`` ← ``"mean_shift"`` (article-level shifts are always
  mean shifts between two consecutive articles).
- ``direction`` ← ``"up"`` / ``"down"`` / ``"stable"`` based on sign.
- ``magnitude`` ← ``abs(shift_value)``.
- ``confidence`` ← ``1.0`` (pure computation, no model uncertainty).
- ``detected_at`` / ``window_start`` / ``window_end`` ← now (UTC).
- ``before_avg`` ← previous record's ``after_avg`` (or current sentiment
  when seeding the first record for an entity).
- ``after_avg`` ← current article's ``sentiment_score``.
- ``article_id`` / ``entity_name`` / ``shift_value`` ← migration 30 fields.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from core.observability import get_logger
from modules.processing.pipeline.state import PipelineState

if TYPE_CHECKING:
    from modules.analytics.storage import AnalyticsStorage

log = get_logger(__name__)


class SentimentTrackerNode:
    """Pipeline node: track article-level sentiment shifts per entity.

    For each entity mentioned in the current article, queries the previous
    article-level shift record for that entity and writes a new shift
    record capturing the sentiment delta.

    Implements:
        SentimentTrackerNode: Pure-computation pipeline node (no LLM)
        with repo failure degradation.

    Args:
        shift_repo: AnalyticsStorage for reading previous shifts and
            writing new ones. Typed as AnalyticsStorage (concrete class)
            because the analytics module does not currently expose a
            Protocol — see project notes on the analytics-module
            Protocol gap.
    """

    def __init__(self, shift_repo: AnalyticsStorage) -> None:
        self._shift_repo = shift_repo

    async def execute(self, state: PipelineState) -> PipelineState:
        """Compute and persist article-level sentiment shifts per entity.

        Args:
            state: Pipeline state. Reads ``article_id``, ``sentiment``,
                ``entities``. Writes ``degraded_fields`` on repo failure.

        Returns:
            The same state object (in-place update).
        """
        # Skip terminal (non-news) and merged articles — same guard as
        # other extraction nodes.
        if state.get("terminal") or state.get("is_merged"):
            return state

        article_id = state.get("article_id")
        sentiment_score = state.get("sentiment", {}).get("sentiment_score")
        entities = state.get("entities", [])

        # Missing prerequisites = nothing to do (not a failure).
        if not article_id or sentiment_score is None or not entities:
            return state

        for entity in entities:
            entity_name = entity.get("canonical_name")
            # Skip entities without a usable name (empty string or None).
            if not entity_name:
                continue

            try:
                await self._track_single_entity(
                    article_id=article_id,
                    entity_name=entity_name,
                    current_sentiment=float(sentiment_score),
                )
            except Exception as exc:
                # Repo failure for this entity — log loudly (Rule 12),
                # mark degraded, continue to next entity.
                log.warning(
                    "sentiment_shift_track_failed_degraded",
                    exc_type=type(exc).__name__,
                    error=str(exc),
                    entity_name=entity_name,
                    article_id=str(article_id),
                )
                state.setdefault("degraded_fields", []).append("sentiment_shift")

        return state

    async def _track_single_entity(
        self,
        article_id: str,
        entity_name: str,
        current_sentiment: float,
    ) -> None:
        """Query previous shift for entity and persist new article-level shift.

        Raises:
            Exception: Propagates repo errors to caller, which marks the
                degraded_fields flag. Either get_last_article_shift or
                save_shift can fail.
        """
        previous = await self._shift_repo.get_last_article_shift(entity_name)

        if previous is None:
            # Seed record — first article for this entity. Use current
            # sentiment as both before_avg and after_avg so the next
            # article can compute a real shift.
            before_avg = current_sentiment
            shift_value = 0.0
            direction = "stable"
        else:
            before_avg = float(previous["after_avg"])
            shift_value = current_sentiment - before_avg
            if shift_value > 0:
                direction = "up"
            elif shift_value < 0:
                direction = "down"
            else:
                direction = "stable"

        now = datetime.now(UTC)
        shift_record: dict[str, Any] = {
            # Existing schema (community-level) fields — reused for
            # article-level records. community_id stores the entity_name
            # as the grouping key for article-level tracking.
            "community_id": entity_name,
            "shift_type": "mean_shift",
            "direction": direction,
            "magnitude": abs(shift_value),
            "confidence": 1.0,
            "detected_at": now,
            "window_start": now,
            "window_end": now,
            "before_avg": before_avg,
            "after_avg": current_sentiment,
            # Migration 30 article-level fields
            "article_id": article_id,
            "entity_name": entity_name,
            "shift_value": shift_value,
        }

        await self._shift_repo.save_shift(shift_record)

        log.debug(
            "sentiment_shift_tracked",
            entity_name=entity_name,
            article_id=str(article_id),
            shift_value=shift_value,
            direction=direction,
        )
