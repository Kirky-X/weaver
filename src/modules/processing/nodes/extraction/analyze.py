# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Analyze pipeline node — combined summarizer + scorer + sentiment."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.constants import SentimentType
from core.llm.client import LLMClient
from core.llm.config.token_budget import TokenBudgetManager
from core.llm.resilience.circuit_breaker import CircuitOpenError
from core.llm.resilience.pool import AllProvidersFailedError
from core.llm.types import CallPoint
from core.llm.validation.output_validator import AnalyzeOutput
from core.observability import get_logger
from core.prompt.loader import PromptLoader
from modules.processing.nodes.classification.categorizer import normalize_emotion
from modules.processing.pipeline.state import PipelineState

if TYPE_CHECKING:
    from core.evidence.mc_sampler import MCSampler
    from modules.analytics.sentiment_analyzer import SentimentAnalyzer

log = get_logger(__name__)


class AnalyzeNode:
    """Pipeline node: single LLM call for summary + score + sentiment.

    Combines three analyses into one call to save tokens and latency.
    Supports Monte Carlo sampling for long documents (>10K characters).

    When a SentimentAnalyzer (SKEP) is provided, sentiment analysis
    prioritizes SKEP results. If SKEP confidence is high (>= threshold),
    the SKEP result overrides the LLM sentiment. If SKEP confidence is
    low, the LLM sentiment result is kept.

    Implements:
        AnalyzeNode: Pipeline analysis node with SKEP sentiment integration
    """

    def __init__(
        self,
        llm: LLMClient,
        budget: TokenBudgetManager,
        prompt_loader: PromptLoader,
        mc_sampler: MCSampler | None = None,
        mc_threshold: int = 10000,
        mc_confidence_threshold: float = 0.4,
        sentiment_analyzer: SentimentAnalyzer | None = None,
    ) -> None:
        self._llm = llm
        self._budget = budget
        self._prompt_loader = prompt_loader
        self._mc_sampler = mc_sampler
        self._mc_threshold = mc_threshold
        self._mc_confidence_threshold = mc_confidence_threshold
        self._sentiment_analyzer = sentiment_analyzer

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
            except (AllProvidersFailedError, CircuitOpenError, ValueError) as e:
                log.warning(
                    "mc_sampling_failed_fallback",
                    exc_type=type(e).__name__,
                    error=str(e),
                    url=state["raw"].url,
                )
            except Exception as e:
                log.error(
                    "mc_sampling_unexpected_error",
                    exc_type=type(e).__name__,
                    error=str(e),
                    url=state["raw"].url,
                )
                raise
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
                article_id=state.get("article_id"),
                task_id=state.get("task_id"),
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

            # Override sentiment with SKEP if available and confident
            if self._sentiment_analyzer is not None:
                try:
                    text = f"{state['cleaned']['title']} {body}"
                    skep_result = await self._sentiment_analyzer.analyze(text)
                    if skep_result.get("source") == "skep":
                        state["sentiment"] = {
                            "sentiment": skep_result["sentiment"],
                            "sentiment_score": skep_result["sentiment_score"],
                            "primary_emotion": normalize_emotion(result.primary_emotion),
                            "emotion_targets": result.emotion_targets,
                        }
                        log.debug(
                            "analyze_sentiment_skep_override",
                            sentiment=state["sentiment"],
                            source="skep",
                        )
                    elif skep_result.get("source") == "llm":
                        # SKEP fell back to LLM — use SKEP's LLM result
                        state["sentiment"] = {
                            "sentiment": skep_result["sentiment"],
                            "sentiment_score": skep_result["sentiment_score"],
                            "primary_emotion": normalize_emotion(result.primary_emotion),
                            "emotion_targets": result.emotion_targets,
                        }
                        log.debug(
                            "analyze_sentiment_skep_llm_fallback",
                            sentiment=state["sentiment"],
                            source="skep_llm",
                        )
                    # Other sources (skep_fallback, default, error) — keep LLM result
                except Exception as e:
                    log.warning(
                        "analyze_skep_override_failed",
                        exc_type=type(e).__name__,
                        error=str(e),
                    )
        except (AllProvidersFailedError, CircuitOpenError, ValueError, Exception) as e:
            # Fallback: use default values if LLM fails
            log.warning(
                "analyze_failed_using_defaults",
                exc_type=type(e).__name__,
                error=str(e),
                url=state["raw"].url,
            )
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
