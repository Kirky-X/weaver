# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Vectorize pipeline node — generate content embeddings for Merger."""

from __future__ import annotations

from core.llm.client import LLMClient
from core.observability.logging import get_logger
from modules.processing.pipeline.state import PipelineState

log = get_logger("node.vectorize")


class VectorizeNode:
    """Pipeline node: generate content embedding for Merger matching.

    These vectors are used only for Merger similarity queries
    and are NOT persisted to the database at this stage.
    """

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def execute(self, state: PipelineState) -> PipelineState:
        """Generate content embedding."""
        if state.get("terminal"):
            return state

        cleaned = state["cleaned"]
        text = f"{cleaned['title']}\n{cleaned['body'][:2000]}"

        # Use call_at for embedding with configured providers
        embeddings = await self._llm.embed("embedding.aiping.Qwen3-Embedding-0.6B", [text])
        state["vectors"] = {"content": embeddings[0]}

        log.debug("vectorized", url=state["raw"].url)
        return state
