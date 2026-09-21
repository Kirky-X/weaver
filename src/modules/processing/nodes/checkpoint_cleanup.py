# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Checkpoint cleanup pipeline node — clean up pipeline checkpoints after completion."""

from __future__ import annotations

import hashlib
from typing import Any

from core.observability import get_logger
from modules.processing.pipeline.state import PipelineState

log = get_logger(__name__)


class CheckpointCleanupNode:
    """Pipeline node: clean up pipeline checkpoints after completion.

    Removes checkpoint data from Redis to free up storage after
    the pipeline has successfully processed an article.
    """

    CHECKPOINT_KEY_PREFIX = "pipeline:checkpoint"

    def __init__(self, cache_client: Any = None) -> None:
        self._redis = cache_client

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
            raw = state.get("raw")
            url = getattr(raw, "url", None)
            if not url:
                log.debug("checkpoint_cleanup_skipped_no_url")
                return state
            url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
            checkpoint_key = f"{self.CHECKPOINT_KEY_PREFIX}:{url_hash}"

            await self._redis.client.delete(checkpoint_key)

            log.debug(
                "checkpoint_cleaned",
                url=url,
                checkpoint_key=checkpoint_key,
            )
        except Exception as exc:
            # Do not touch state/raw here: the failing access may be the very
            # expression that raised, so re-accessing it in the handler could
            # mask the original failure with a second exception.
            log.warning(
                "checkpoint_cleanup_failed",
                error=str(exc),
                exc_type=type(exc).__name__,
            )

        return state
