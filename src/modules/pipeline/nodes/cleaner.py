"""Cleaner pipeline node — LLM-based article content cleaning."""

from __future__ import annotations

from core.llm.client import LLMClient
from core.llm.types import CallPoint
from core.llm.token_budget import TokenBudgetManager
from core.llm.output_validator import CleanerOutput
from core.prompt.loader import PromptLoader
from core.observability.logging import get_logger
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
                "title": result.title,
                "body": result.body,
                "publish_time": raw.publish_time,
                "source_host": raw.source_host,
            }
        except Exception as e:
            # Fallback: use original content if LLM fails
            log.warning("cleaner_failed_using_original", error=str(e), url=raw.url)
            state["cleaned"] = {
                "title": raw.title,
                "body": raw.body,
                "publish_time": raw.publish_time,
                "source_host": raw.source_host,
            }

        state.setdefault("prompt_versions", {})["cleaner"] = (
            self._prompt_loader.get_version("cleaner")
        )

        log.info("cleaned", url=raw.url)
        return state
