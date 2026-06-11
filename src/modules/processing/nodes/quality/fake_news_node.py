# Copyright (c) 2026 KirkyX. All Rights Reserved
"""FakeNewsDetectorNode — Pipeline wrapper for FakeNewsDetector.

Wraps FakeNewsDetector.predict() as a Pipeline Phase 3 node.
Uses existing pipeline state fields (quality_score, credibility_score,
entities, sentiment_score) — zero extra LLM cost.

Insertion point: Phase 3, after EntityExtractor, before ConflictDetector.

Implements: PipelineNode (convention-based)
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from core.observability import get_logger
from modules.processing.pipeline.state import PipelineState

if TYPE_CHECKING:
    from modules.analytics.fake_news_detector import FakeNewsDetector

log = get_logger(__name__)

# Default timeout for fake news detection (seconds)
DEFAULT_TIMEOUT_SECONDS = 30


class FakeNewsDetectorNode:
    """Pipeline node: detect fake news using five-dimensional feature fusion.

    Wraps FakeNewsDetector.predict() to run within the Pipeline DAG.
    Reads existing pipeline state fields — no additional LLM calls.

    Classification levels:
    - TRUSTED (fake_score >= 0.8): Normal processing, no degradation.
    - SUSPICIOUS (0.4 <= fake_score < 0.8): Flag for review, add to degraded_fields.
    - FAKE (fake_score < 0.4): Block and alert, add to degraded_fields.

    Implements: PipelineNode (convention-based)
    """

    def __init__(
        self,
        detector: FakeNewsDetector,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """Initialize FakeNewsDetectorNode.

        Args:
            detector: FakeNewsDetector instance.
            timeout_seconds: Maximum seconds for detection before skip.
        """
        self._detector = detector
        self._timeout_seconds = timeout_seconds

    async def execute(self, state: PipelineState) -> PipelineState:
        """Run fake news detection on the pipeline state.

        Skips for terminal or merged articles. On timeout, skips gracefully.
        On FAKE or SUSPICIOUS level, adds 'fake_news_detection' to degraded_fields.

        Args:
            state: Current pipeline state.

        Returns:
            Updated pipeline state with 'fake_news_detection' field.
        """
        if state.get("terminal") or state.get("is_merged"):
            return state

        try:
            result = await asyncio.wait_for(
                self._detector.predict(state),
                timeout=self._timeout_seconds,
            )
        except TimeoutError:
            log.warning(
                "fake_news_detection_timeout",
                timeout=self._timeout_seconds,
                url=getattr(state.get("raw"), "url", "unknown"),
            )
            state["fake_news_detection"] = {"skipped": True, "reason": "timeout"}
            return state
        except Exception as exc:
            log.warning(
                "fake_news_detection_failed",
                error=str(exc),
                exc_type=type(exc).__name__,
                url=getattr(state.get("raw"), "url", "unknown"),
            )
            state["fake_news_detection"] = {"skipped": True, "reason": "error"}
            return state

        state["fake_news_detection"] = result

        level = result.get("level", "trusted")
        if level in ("fake", "suspicious"):
            degraded = state.get("degraded_fields", [])
            if "fake_news_detection" not in degraded:
                degraded.append("fake_news_detection")
                state["degraded_fields"] = degraded
            reasons = state.get("degradation_reasons", {})
            if level == "fake":
                reasons["fake_news_detection"] = (
                    f"fake_news_level=fake, score={result.get('fake_score', 0)}"
                )
            else:
                reasons["fake_news_detection"] = (
                    f"fake_news_level=suspicious, score={result.get('fake_score', 0)}"
                )
            state["degradation_reasons"] = reasons

        log.info(
            "fake_news_detection_complete",
            level=level,
            fake_score=result.get("fake_score"),
            url=getattr(state.get("raw"), "url", "unknown"),
        )

        return state
