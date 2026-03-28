# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Classifier pipeline node — determines if content is news."""

from __future__ import annotations

from core.llm.client import LLMClient
from core.llm.output_validator import ClassifierOutput
from core.llm.token_budget import TokenBudgetManager
from core.llm.types import CallPoint
from core.observability.logging import get_logger
from core.prompt.loader import PromptLoader
from modules.pipeline.state import PipelineState

log = get_logger("node.classifier")


class ClassifierNode:
    """Pipeline node: classify whether raw content is a news article."""

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
        """Classify the article.

        Sets `is_news` and `terminal` flags in state.
        """
        raw = state["raw"]
        payload = {
            "title": raw.title,
            "body_snippet": self._budget.truncate(raw.body, CallPoint.CLASSIFIER),
            "article_id": state.get("article_id"),
            "task_id": state.get("task_id"),
        }
        result: ClassifierOutput = await self._llm.call_at(
            CallPoint.CLASSIFIER, payload, output_model=ClassifierOutput
        )
        state["is_news"] = result.is_news
        state["terminal"] = not result.is_news

        state.setdefault("prompt_versions", {})["classifier"] = self._prompt_loader.get_version(
            "classifier"
        )

        log.info(
            "classified",
            url=raw.url,
            is_news=result.is_news,
            confidence=result.confidence,
        )
        return state
