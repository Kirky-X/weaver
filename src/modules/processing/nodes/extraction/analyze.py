# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Analyze pipeline node — combined summarizer + scorer + sentiment."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.constants import SentimentType
from core.llm.client import LLMClient
from core.llm.config.token_budget import TokenBudgetManager
from core.llm.resilience.circuit_breaker import CircuitOpenError
from core.llm.resilience.pool import AllProvidersFailedError
from core.llm.types import CallPoint
from core.llm.validation.output_validator import AnalyzeNarrativeOutput, AnalyzeOutput
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
        merge_narrative: bool = False,
    ) -> None:
        self._llm = llm
        self._budget = budget
        self._prompt_loader = prompt_loader
        self._mc_sampler = mc_sampler
        self._mc_threshold = mc_threshold
        self._mc_confidence_threshold = mc_confidence_threshold
        self._sentiment_analyzer = sentiment_analyzer
        # 合并调用开关（config/pipeline.toml [phase3]
        # merge_analyze_narrative）：开启时本节点发一次
        # ANALYZE_NARRATIVE 合并调用，narrative 部分暂存 state 供
        # NarrativeSchemaExtractorNode 持久化——后者不再产生 chat 调用。
        self._merge_narrative = merge_narrative

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

        # Apply token budget truncation（合并调用点取 narrative 侧 8000 预算）
        body = self._budget.truncate(
            body, CallPoint.ANALYZE_NARRATIVE if self._merge_narrative else CallPoint.ANALYZE
        )

        try:
            payload = {
                "title": state["cleaned"]["title"],
                "body": body,
                "article_id": state.get("article_id"),
                "task_id": state.get("task_id"),
            }
            if self._merge_narrative:
                merged: AnalyzeNarrativeOutput = await self._llm.call_at(
                    CallPoint.ANALYZE_NARRATIVE,
                    payload,
                    output_model=AnalyzeNarrativeOutput,
                    article_id=state.get("article_id"),
                    task_id=state.get("task_id"),
                )
                self._apply_analyze_fields(state, merged)
                # 暂存 narrative 部分：NarrativeSchemaExtractorNode 从
                # state 读取并写图，自身不再发起 LLM 调用。
                state["_narrative_schema_payload"] = merged.to_narrative_payload()
            else:
                result: AnalyzeOutput = await self._llm.call_at(
                    CallPoint.ANALYZE,
                    payload,
                    output_model=AnalyzeOutput,
                    article_id=state.get("article_id"),
                    task_id=state.get("task_id"),
                )
                self._apply_analyze_fields(state, result)

            # Override sentiment with SKEP if available and confident
            if self._sentiment_analyzer is not None:
                try:
                    text = f"{state['cleaned']['title']} {body}"
                    skep_result = await self._sentiment_analyzer.analyze(text)
                    if skep_result.get("source") in ("skep", "llm"):
                        # SKEP 结果可用（source=skep），或 SKEP 回落到自身 LLM
                        # 结果（source=llm）——两种来源都覆盖 LLM 分析的情感值。
                        # primary_emotion/emotion_targets 沿用 analyze 结果
                        # 已归一化的 state 值（SKEP 不产生这两个维度）。
                        state["sentiment"] = {
                            "sentiment": skep_result["sentiment"],
                            "sentiment_score": skep_result["sentiment_score"],
                            "primary_emotion": state["sentiment"]["primary_emotion"],
                            "emotion_targets": state["sentiment"]["emotion_targets"],
                        }
                        log.debug(
                            "analyze_sentiment_skep_override",
                            sentiment=state["sentiment"],
                            source=skep_result.get("source"),
                        )
                    # Other sources (skep_fallback, default, error) — keep LLM result
                except Exception as e:
                    log.warning(
                        "analyze_skep_override_failed",
                        exc_type=type(e).__name__,
                        error=str(e),
                    )
        except Exception as e:  # incl. AllProvidersFailedError/CircuitOpenError/ValueError
            # Fallback: use default values if LLM fails
            log.warning(
                "analyze_failed_using_defaults",
                exc_type=type(e).__name__,
                error=str(e),
                url=state["raw"].url,
            )
            self._apply_analyze_defaults(state)
            if self._merge_narrative:
                # 合并调用失败 → narrative/schema 一并丢失（单次失败影响面
                # 扩大是方案 A 已知权衡）；narrative 节点在合并模式下跳过
                # 自有调用，不做拆分重试（会抵消调用收益）。
                state.setdefault("degraded_fields", []).extend(["narrative", "schema"])
                state.setdefault("degradation_reasons", {}).update(
                    {
                        "narrative": f"analyze_narrative merge failed: {e!s}",
                        "schema": f"analyze_narrative merge failed: {e!s}",
                    }
                )

        prompt_versions = state.setdefault("prompt_versions", {})
        try:
            if self._merge_narrative:
                prompt_versions["analyze_narrative"] = self._prompt_loader.get_version(
                    "analyze_narrative"
                )
            else:
                prompt_versions["analyze"] = self._prompt_loader.get_version("analyze")
        except Exception as exc:
            # 观测留痕失败不放大为主流程失败（模板缺失时 LLM 调用本身
            # 会 fail-loud，这里只是版本号记录失败）。
            log.warning(
                "analyze_prompt_version_record_failed",
                exc_type=type(exc).__name__,
                error=str(exc),
            )

        log.info(
            "analyzed",
            url=state["raw"].url,
            score=state.get("score"),
            sentiment=state.get("sentiment", {}).get("sentiment"),
        )
        return state

    def _apply_analyze_fields(self, state: PipelineState, result: AnalyzeOutput) -> None:
        """Apply LLM analysis output to pipeline state (summary/sentiment/score)."""
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

    @staticmethod
    def _apply_analyze_defaults(state: PipelineState) -> None:
        """Apply fallback defaults when the analysis LLM call fails."""
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
