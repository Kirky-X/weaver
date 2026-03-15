"""Analyze pipeline node — combined summarizer + scorer + sentiment."""

from __future__ import annotations

from core.llm.client import LLMClient
from core.llm.types import CallPoint
from core.llm.token_budget import TokenBudgetManager
from core.llm.output_validator import AnalyzeOutput
from core.prompt.loader import PromptLoader
from core.observability.logging import get_logger
from modules.pipeline.state import PipelineState
from modules.pipeline.nodes.categorizer import normalize_emotion

log = get_logger("node.analyze")


class AnalyzeNode:
    """Pipeline node: single LLM call for summary + score + sentiment.

    Combines three analyses into one call to save tokens and latency.
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
        """Analyze the article for summary, score, and sentiment."""
        if state.get("terminal") or state.get("is_merged"):
            return state

        body = self._budget.truncate(state["cleaned"]["body"], CallPoint.ANALYZE)

        try:
            result: AnalyzeOutput = await self._llm.call(
                CallPoint.ANALYZE,
                {"title": state["cleaned"]["title"], "body": body},
                output_model=AnalyzeOutput,
            )

            state["summary_info"] = {
                "summary": result.summary,
                "event_time": result.event_time,
                "subjects": result.subjects,
                "key_data": result.key_data,
                "impact": result.impact,
                "has_data": result.has_data,
            }
            state["sentiment"] = {
                "sentiment": result.sentiment,
                "sentiment_score": result.sentiment_score,
                "primary_emotion": normalize_emotion(result.primary_emotion),
                "emotion_targets": result.emotion_targets,
            }
            log.debug("analyze_sentiment_set", sentiment=state["sentiment"])
            state["score"] = result.score
        except Exception as e:
            # Fallback: use default values if LLM fails
            log.warning("analyze_failed_using_defaults", error=str(e), url=state["raw"].url)
            state["summary_info"] = {
                "summary": state["cleaned"]["title"],
                "event_time": None,
                "subjects": [],
                "key_data": [],
                "impact": "",
                "has_data": False,
            }
            state["sentiment"] = {
                "sentiment": "neutral",
                "sentiment_score": 0.0,
                "primary_emotion": "客观",
                "emotion_targets": [],
            }
            state["score"] = 0.5

        state.setdefault("prompt_versions", {})["analyze"] = (
            self._prompt_loader.get_version("analyze")
        )

        log.info(
            "analyzed",
            url=state["raw"].url,
            score=state.get("score"),
            sentiment=state.get("sentiment", {}).get("sentiment"),
        )
        return state
