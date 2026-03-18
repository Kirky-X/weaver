# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Cleaner pipeline node — LLM-based article content cleaning."""

from __future__ import annotations

from core.llm.client import LLMClient
from core.llm.output_validator import CleanerOutput
from core.llm.token_budget import TokenBudgetManager
from core.llm.types import CallPoint
from core.observability.logging import get_logger
from core.prompt.loader import PromptLoader
from modules.pipeline.state import PipelineState

log = get_logger("node.cleaner")


class CleanerNode:
    """Pipeline node: clean article content via LLM."""

    def __init__(
        self,
        llm: LLMClient,
        budget: TokenBudgetManager,
        prompt_loader: PromptLoader,
    ) -> None:
        self._llm = llm
        self._budget = budget
        self._prompt_loader = prompt_loader

    async def execute(self, state: PipelineState) -> PipelineState:
        """Clean article content."""
        if state.get("terminal"):
            return state

        raw = state["raw"]
        body_trunc = self._budget.truncate(raw.body, CallPoint.CLEANER)

        try:
            result: CleanerOutput = await self._llm.call(
                CallPoint.CLEANER,
                {"title": raw.title, "body": body_trunc},
                output_model=CleanerOutput,
            )

            state["cleaned"] = {
                "title": result.content.title,
                "subtitle": result.content.subtitle,
                "summary": result.content.summary,
                "body": result.content.body,
                "publish_time": raw.publish_time,
                "source_host": raw.source_host,
            }
            if result.publish_time:
                state["cleaned"]["llm_publish_time"] = result.publish_time
            if result.author:
                state["cleaned"]["author"] = result.author
            state["tags"] = result.tags
            state["cleaner_entities"] = [
                {
                    "name": e.name,
                    "type": e.type,
                    "description": e.description,
                }
                for e in result.entities
            ]
        except Exception as e:
            log.warning("cleaner_failed_using_original", error=str(e), url=raw.url)
            state["cleaned"] = {
                "title": raw.title,
                "body": raw.body,
                "publish_time": raw.publish_time,
                "source_host": raw.source_host,
            }
            state["tags"] = []
            state["cleaner_entities"] = []

        state.setdefault("prompt_versions", {})["cleaner"] = self._prompt_loader.get_version(
            "cleaner"
        )

        log.info("cleaned", url=raw.url, tags_count=len(state.get("tags", [])))
        return state
