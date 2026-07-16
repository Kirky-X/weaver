# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Re-vectorize pipeline node — generate final embeddings after merge."""

from __future__ import annotations

from core.llm.client import LLMClient
from core.observability import get_logger
from modules.processing.pipeline.state import PipelineState

log = get_logger(__name__)


class ReVectorizeNode:
    """Pipeline node: regenerate embeddings after merge for final storage.

    After merging, the content may have changed. This node generates
    both title and content vectors with the final model_id for
    persistent storage in article_vectors.
    """

    def __init__(self, llm: LLMClient, model_id: str) -> None:
        """Initialize ReVectorizeNode.

        Args:
            llm: LLM client for embedding generation.
            model_id: Embedding model identifier from configuration.
        """
        self._llm = llm
        self._model_id = model_id

    async def execute(self, state: PipelineState) -> PipelineState:
        """Generate title and content embeddings for the cleaned article."""
        if state.get("terminal") or state.get("is_merged"):
            return state

        cleaned = state["cleaned"]
        texts = [
            cleaned["title"],
            f"{cleaned['title']}\n{cleaned['body'][:2000]}",
        ]

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

        log.debug("re_vectorized", url=state["raw"].url)
        return state
