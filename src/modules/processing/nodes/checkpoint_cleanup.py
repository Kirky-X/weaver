# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Checkpoint cleanup pipeline node — clean up LangGraph checkpoints after completion."""

from __future__ import annotations

import hashlib
from typing import Any

from core.observability.logging import get_logger
from modules.processing.pipeline.state import PipelineState

log = get_logger("node.checkpoint_cleanup")


class CheckpointCleanupNode:
    """Pipeline node: clean up LangGraph checkpoints after completion.

    Removes checkpoint data from Redis to free up storage after
    the pipeline has successfully processed an article.
    """

    CHECKPOINT_KEY_PREFIX = "langgraph:checkpoint"

    def __init__(self, redis_client: Any = None) -> None:
        self._redis = redis_client

    async def execute(self, state: PipelineState) -> PipelineState:
        """Clean up checkpoint for the processed article.

        Args:
            state: Pipeline state containing raw article URL.

        Returns:
            The unchanged pipeline state (cleanup is a side effect).
        """
        if state.get("terminal"):
            return state

        if not self._redis:
            log.debug("checkpoint_cleanup_skipped_no_redis")
            return state

        try:
            url = state["raw"].url
            url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
            checkpoint_key = f"{self.CHECKPOINT_KEY_PREFIX}:{url_hash}"

            await self._redis.client.delete(checkpoint_key)

            log.debug(
                "checkpoint_cleaned",
                url=url,
                checkpoint_key=checkpoint_key,
            )
        except Exception as exc:
            log.warning(
                "checkpoint_cleanup_failed",
                url=state["raw"].url if "raw" in state else "unknown",
                error=str(exc),
            )

        return state
