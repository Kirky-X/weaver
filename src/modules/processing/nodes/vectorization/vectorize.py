# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Vectorize pipeline node — generate title+content embeddings."""

from __future__ import annotations

from core.llm.client import LLMClient
from core.observability import get_logger
from modules.processing.pipeline.state import PipelineState

log = get_logger(__name__)


class VectorizeNode:
    """Pipeline node: generate title and content embeddings.

    The content vector drives Merger similarity queries. Both vectors plus
    the embedding model id must be present in ``state["vectors"]`` — the
    persistence layer only stores vectors that carry ``title`` AND
    ``content``, so fast-mode ingestion (which never reaches Phase 3
    re-vectorize) would otherwise silently lose all embeddings.
    """

    def __init__(self, llm: LLMClient, model_id: str | None = None) -> None:
        self._llm = llm
        self._model_id = model_id or "unknown"

    async def execute(self, state: PipelineState) -> PipelineState:
        """Generate title and content embeddings."""
        if state.get("terminal"):
            return state

        cleaned = state["cleaned"]
        texts = [
            cleaned["title"],
            f"{cleaned['title']}\n{cleaned['body'][:2000]}",
        ]

        # Use embed_default for embedding with configured providers
        embeddings = await self._llm.embed_default(
            texts,
            article_id=state.get("article_id"),
            task_id=state.get("task_id"),
        )
        state["vectors"] = {
            "title": embeddings[0],
            "content": embeddings[1],
            "model_id": self._model_id,
        }

        log.debug("vectorized", url=state["raw"].url)
        return state
