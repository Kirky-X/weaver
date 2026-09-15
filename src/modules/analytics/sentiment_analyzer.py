# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""PaddleNLP SKEP sentiment analyzer.

Uses PaddleNLP SKEP Chinese sentiment model for high-precision sentiment analysis.
Falls back to LLM when confidence is below threshold.

Performance:
- Precision: >= 95%
- Latency: < 10ms per request
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from core.observability import get_logger

if __name__ != "__main__":
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from core.llm.client import LLMClient

log = get_logger(__name__)

# Max opening-brace candidates retried by _extract_json_from_text (#53).
_MAX_JSON_CANDIDATES = 128


@dataclass
class SentimentAnalyzerConfig:
    """Configuration for PaddleNLP SKEP sentiment analyzer.

    Attributes:
        enabled: Whether to use SKEP for sentiment analysis.
        model_name: PaddleNLP model name.
        max_input_length: Maximum input text length in tokens.
        confidence_threshold: Minimum confidence to use SKEP result directly.
        fallback_to_llm: Whether to fall back to LLM when confidence is low.
        llm_max_input_length: Maximum input text length (characters) for the
            LLM fallback path. Kept separate from ``max_input_length`` because
            SKEP (token-based) and LLM providers (character/token limits)
            have different budgets.
    """

    enabled: bool = True
    model_name: str = "skep_ernie_1.0_large_chinese"
    max_input_length: int = 512
    confidence_threshold: float = 0.6
    fallback_to_llm: bool = True
    llm_max_input_length: int = 2000


class SentimentAnalyzer:
    """PaddleNLP SKEP sentiment analyzer.

    Uses PaddleNLP SKEP Chinese sentiment model for high-precision sentiment analysis.
    Falls back to LLM when confidence is below threshold.

    Implements:
        SentimentAnalyzer: PaddleNLP SKEP sentiment analysis
    """

    def __init__(
        self,
        config: SentimentAnalyzerConfig | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        """Initialize SentimentAnalyzer.

        Args:
            config: Analyzer configuration. Uses defaults if None.
            llm_client: LLM client for fallback analysis (optional).
        """
        self._config = config or SentimentAnalyzerConfig()
        self._llm_client = llm_client
        self._skep = None

        # Initialize SKEP if enabled
        if self._config.enabled:
            self._init_skep()

    def _init_skep(self) -> None:
        """Initialize PaddleNLP SKEP model."""
        try:
            from paddlenlp import Taskflow

            self._skep = Taskflow("sentiment_analysis")
            log.info(
                "skep_model_initialized",
                model=self._config.model_name,
            )
        except Exception as exc:
            log.warning(
                "skep_model_init_failed",
                error=str(exc),
                exc_type=type(exc).__name__,
            )
            self._skep = None

    async def analyze(self, text: str) -> dict[str, Any]:
        """Analyze sentiment of text.

        Args:
            text: Input text to analyze.

        Returns:
            Dictionary with:
            - sentiment: Sentiment label (positive/negative/neutral).
            - sentiment_score: Confidence score (0-1).
            - source: Analysis source (skep/llm/skep_fallback/default/error).
            - degraded_fields: List of degraded fields (if LLM fallback).
        """
        if not text:
            return self._default_result("default")

        # Try SKEP analysis
        if self._skep is not None:
            try:
                return await self._analyze_with_skep(text)
            except Exception as exc:
                log.warning(
                    "skep_analysis_failed",
                    error=str(exc),
                    exc_type=type(exc).__name__,
                )

        # Fall back to LLM if available
        if self._llm_client and self._config.fallback_to_llm:
            try:
                return await self._analyze_with_llm(text)
            except Exception as exc:
                log.warning(
                    "llm_sentiment_analysis_failed",
                    error=str(exc),
                    exc_type=type(exc).__name__,
                )

        # Return default if all methods fail
        return self._default_result("error")

    async def _analyze_with_skep(self, text: str) -> dict[str, Any]:
        """Analyze sentiment using SKEP model.

        Args:
            text: Input text.

        Returns:
            Sentiment analysis result.
        """
        # Truncate text to max input length
        truncated_text = text[: self._config.max_input_length]

        # Run SKEP analysis in a thread executor: the Taskflow call is
        # CPU-bound and would otherwise stall the event loop.
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(None, self._skep, truncated_text)

        if not results:
            return self._default_result("default")

        result = results[0]
        confidence = result.get("score", 0.0)
        label = result.get("label", "neutral")

        # Type guard: a non-numeric score (None from a missing key or a
        # string from a misbehaving model) would raise TypeError on the
        # threshold comparison below (#222). Degrade to 0.0 so the request
        # falls through to the LLM fallback instead of dropping the result.
        if not isinstance(confidence, (int, float)):
            log.warning(
                "skep_score_not_numeric",
                score_type=type(confidence).__name__,
            )
            confidence = 0.0

        # Check confidence threshold
        if confidence >= self._config.confidence_threshold:
            # High confidence - use SKEP result directly
            return {
                "sentiment": self._map_label(label),
                "sentiment_score": self._normalize_score(confidence),
                "confidence": confidence,
                "source": "skep",
            }

        # Low confidence - fall back to LLM if enabled
        if self._llm_client and self._config.fallback_to_llm:
            log.debug(
                "skep_low_confidence_fallback",
                confidence=confidence,
                threshold=self._config.confidence_threshold,
            )
            return await self._analyze_with_llm(text, degraded=True)

        # No LLM fallback - use SKEP result with degraded flag
        return {
            "sentiment": self._map_label(label),
            "sentiment_score": self._normalize_score(confidence),
            "confidence": confidence,
            "source": "skep_fallback",
            "degraded_fields": ["sentiment"],
        }

    async def _analyze_with_llm(self, text: str, degraded: bool = False) -> dict[str, Any]:
        """Analyze sentiment using LLM.

        Args:
            text: Input text.
            degraded: Whether this is a fallback from SKEP.

        Returns:
            Sentiment analysis result.
        """
        if not self._llm_client:
            return self._default_result("default")

        # Call LLM for sentiment analysis
        result = await self._llm_client.call_at(
            "sentiment",
            {"text": text[: self._config.llm_max_input_length]},
        )

        # call_at may return a string (raw LLM response); parse JSON if needed
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except (json.JSONDecodeError, TypeError):
                # LLM may return thinking text before JSON; extract JSON block
                # Find the last balanced brace pair (handles nested objects)
                result = self._extract_json_from_text(result)
                if result is None:
                    return self._default_result("llm")

        # json.loads may succeed on a non-object JSON value (array, string,
        # number) — only dicts carry the sentiment fields we need.
        if not isinstance(result, dict):
            log.warning(
                "sentiment_llm_response_not_object",
                result_type=type(result).__name__,
            )
            return self._default_result("llm")

        sentiment = result.get("sentiment", "neutral")
        sentiment_score = result.get("sentiment_score", 0.5)

        response = {
            "sentiment": self._map_label(sentiment),
            "sentiment_score": self._normalize_score(sentiment_score),
            "source": "llm",
        }

        # Add degraded_fields if this is a fallback
        if degraded:
            response["degraded_fields"] = ["sentiment"]

        return response

    def _normalize_score(self, score: Any) -> float:
        """Normalize score to [0, 1] range.

        The LLM may return ``sentiment_score`` as a string (e.g. ``"0.8"``)
        or ``null``/``None`` — coerce before clamping instead of raising
        ``TypeError`` in ``min``/``max`` (#221).

        Args:
            score: Raw score (numeric, numeric string, or None).

        Returns:
            Normalized score; 0.5 when the value is not numeric.
        """
        try:
            value = float(score)
        except (TypeError, ValueError):
            log.warning(
                "sentiment_score_not_numeric",
                score_type=type(score).__name__,
            )
            return 0.5
        return max(0.0, min(1.0, value))

    def _map_label(self, label: str) -> str:
        """Map SKEP label to standard sentiment label.

        Args:
            label: SKEP label.

        Returns:
            Standard sentiment label.
        """
        label_lower = label.lower()
        if label_lower in ("positive", "negative", "neutral"):
            return label_lower
        return "neutral"

    def _extract_json_from_text(self, text: str) -> dict[str, Any] | None:
        """Extract JSON object from text that may contain thinking/reasoning.

        LLMs with think mode may return reasoning text before the JSON output.
        This method finds the last valid JSON object in the text by scanning
        for balanced braces.

        Args:
            text: Raw LLM response text.

        Returns:
            Parsed dict if JSON found, None otherwise.
        """
        # Collect opening-brace candidates, keeping only the most recent ones:
        # each failed candidate scans to end-of-text, so unbounded retries on
        # brace-heavy prose are O(N^2) (#53). LLM payloads are short; the cap
        # only bounds pathological inputs.
        starts = [i for i, ch in enumerate(text) if ch == "{"][-_MAX_JSON_CANDIDATES:]
        # Find all positions of opening braces
        for i in reversed(starts):
            # Try to parse from this position to end, tracking string state so
            # braces inside JSON string values (e.g. "note": "use {x}") do not
            # corrupt the depth count (#53).
            depth = 0
            in_string = False
            escaped = False
            for j in range(i, len(text)):
                ch = text[j]
                if in_string:
                    if escaped:
                        escaped = False
                    elif ch == "\\":
                        escaped = True
                    elif ch == '"':
                        in_string = False
                elif ch == '"':
                    in_string = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[i : j + 1])
                    except (json.JSONDecodeError, TypeError):
                        break
        log.warning("sentiment_llm_response_not_json", response_preview=text[:200])
        return None

    def _default_result(self, source: str) -> dict[str, Any]:
        """Return default sentiment result.

        Args:
            source: Source identifier.

        Returns:
            Default sentiment result.
        """
        return {
            "sentiment": "neutral",
            "sentiment_score": 0.5,
            "source": source,
        }
