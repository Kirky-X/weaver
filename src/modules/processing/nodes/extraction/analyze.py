# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Analyze pipeline node — combined summarizer + scorer + sentiment."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.constants import SentimentType
from core.llm.client import LLMClient
from core.llm.config.token_budget import TokenBudgetManager
from core.llm.types import CallPoint
from core.llm.validation.output_validator import AnalyzeOutput
from core.observability.logging import get_logger
from core.prompt.loader import PromptLoader
from modules.processing.nodes.classification.categorizer import normalize_emotion
from modules.processing.pipeline.state import PipelineState

if TYPE_CHECKING:
    from core.evidence.mc_sampler import MCSampler

log = get_logger(__name__)


class AnalyzeNode:
    """Pipeline node: single LLM call for summary + score + sentiment.

    Combines three analyses into one call to save tokens and latency.
    Supports Monte Carlo sampling for long documents (>10K characters).
    """

    def __init__(
        self,
        llm: LLMClient,
        budget: TokenBudgetManager,
        prompt_loader: PromptLoader,
        mc_sampler: MCSampler | None = None,
        mc_threshold: int = 10000,
        mc_confidence_threshold: float = 0.4,
    ) -> None:
        self._llm = llm
        self._budget = budget
        self._prompt_loader = prompt_loader
        self._mc_sampler = mc_sampler
        self._mc_threshold = mc_threshold
        self._mc_confidence_threshold = mc_confidence_threshold

    async def execute(self, state: PipelineState) -> PipelineState:
        """Analyze the article for summary, score, and sentiment."""
        if state.get("terminal") or state.get("is_merged"):
            return state

        original_body = state["cleaned"]["body"]
        body = original_body

        # Apply Monte Carlo sampling for long documents
        if len(body) > self._mc_threshold and self._mc_sampler:
            try:
                sampled_body, confidence = await self._mc_sampler.sample_evidence(
                    document=body,
                    title=state["cleaned"]["title"],
                )
                if confidence >= self._mc_confidence_threshold:
                    body = sampled_body
                    log.info(
                        "mc_sampling_applied",
                        original_len=len(original_body),
                        sampled_len=len(body),
                        confidence=confidence,
                        url=state["raw"].url,
                    )
                else:
                    log.warning(
                        "mc_sampling_low_confidence_fallback",
                        confidence=confidence,
                        threshold=self._mc_confidence_threshold,
                        url=state["raw"].url,
                    )
            except Exception as e:
                log.warning(
                    "mc_sampling_failed_fallback",
                    error=str(e),
                    url=state["raw"].url,
                )
        elif len(body) > self._mc_threshold:
            log.debug(
                "mc_sampling_disabled_using_truncation",
                body_len=len(body),
                threshold=self._mc_threshold,
                url=state["raw"].url,
            )

        # Apply token budget truncation
        body = self._budget.truncate(body, CallPoint.ANALYZE)

        try:
            result: AnalyzeOutput = await self._llm.call_at(
                CallPoint.ANALYZE,
                {
                    "title": state["cleaned"]["title"],
                    "body": body,
                    "article_id": state.get("article_id"),
                    "task_id": state.get("task_id"),
                },
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
                "sentiment": SentimentType.NEUTRAL.value,
                "sentiment_score": 0.0,
                "primary_emotion": "客观",
                "emotion_targets": [],
            }
            state["score"] = 0.5

        state.setdefault("prompt_versions", {})["analyze"] = self._prompt_loader.get_version(
            "analyze"
        )

        log.info(
            "analyzed",
            url=state["raw"].url,
            score=state.get("score"),
            sentiment=state.get("sentiment", {}).get("sentiment"),
        )
        return state