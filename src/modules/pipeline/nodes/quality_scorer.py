# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Quality scorer pipeline node — LLM-based article quality assessment."""

from __future__ import annotations

from core.llm.client import LLMClient
from core.llm.output_validator import QualityScorerOutput
from core.llm.token_budget import TokenBudgetManager
from core.llm.types import CallPoint
from core.observability.logging import get_logger
from core.prompt.loader import PromptLoader
from modules.pipeline.state import PipelineState

log = get_logger("node.quality_scorer")


class QualityScorerNode:
    """Pipeline node: assess article quality via LLM.

    Evaluates article quality across multiple dimensions:
    - Information completeness
    - Content credibility
    - Language quality
    - Originality
    - Timeliness

    Outputs a single score between 0.00 and 1.00.
    """

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
        """Assess article quality and update state with quality score."""
        if state.get("terminal") or state.get("is_merged"):
            return state

        body = self._budget.truncate(state["cleaned"]["body"], CallPoint.QUALITY_SCORER)

        try:
            result: QualityScorerOutput = await self._llm.call(
                CallPoint.QUALITY_SCORER,
                {"title": state["cleaned"]["title"], "body": body},
                output_model=QualityScorerOutput,
            )

            state["quality_score"] = result.score
            log.debug("quality_scored", score=result.score, url=state["raw"].url)
        except Exception as e:
            log.warning("quality_scorer_failed_using_default", error=str(e), url=state["raw"].url)
            state["quality_score"] = 0.5

        state.setdefault("prompt_versions", {})["quality_scorer"] = self._prompt_loader.get_version(
            "quality_scorer"
        )

        log.info(
            "quality_assessed",
            url=state["raw"].url,
            quality_score=state.get("quality_score"),
        )
        return state
