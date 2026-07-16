# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Fake news detector using five-dimensional feature fusion.

Implements a zero-cost fake news detection system that reuses existing
pipeline intermediate results (sentiment, credibility, quality scores)
to build a five-dimensional feature vector for classification.

Feature Dimensions:
1. Text Clues: sentiment intensity, exaggeration, title-body consistency, readability
2. Source Credibility: source authority, historical accuracy
3. Community Anomaly: community isolation, propagation path
4. Cross-Source Verification: cross-reference count, stance consistency
5. Quality Degradation: comprehensive quality score

Classification Levels:
- Trusted (fake_score >= 0.8): Normal processing
- Suspicious (0.4 <= fake_score < 0.8): Flag for review
- Fake (fake_score < 0.4): Block and alert
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np

from core.observability import get_logger

if __name__ != "__main__":
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from core.llm.client import LLMClient

log = get_logger(__name__)


class FakeNewsLevel(StrEnum):
    """Fake news classification levels."""

    TRUSTED = "trusted"
    SUSPICIOUS = "suspicious"
    FAKE = "fake"

    @classmethod
    def from_score(cls, score: float, trusted: float = 0.8, fake: float = 0.4) -> FakeNewsLevel:
        """Convert fake_score to classification level.

        Args:
            score: Fake news score (0-1). Higher = more trustworthy.
            trusted: Threshold for trusted classification.
            fake: Threshold for fake classification.

        Returns:
            Classification level.
        """
        if score >= trusted:
            return cls.TRUSTED
        elif score >= fake:
            return cls.SUSPICIOUS
        else:
            return cls.FAKE


@dataclass
class FakeNewsDetectorConfig:
    """Configuration for fake news detection.

    Attributes:
        weights: Feature weights for rule-based fusion (11 features).
        trusted_threshold: Score threshold for trusted classification.
        fake_threshold: Score threshold for fake classification.
        exaggeration_words: List of exaggeration marker words.
        embedding_model: Embedding model label for title-body consistency.
        lightgbm_model_path: Path to LightGBM model file (optional).
    """

    weights: list[float] = field(
        default_factory=lambda: [
            0.15,  # sentiment_intensity
            0.10,  # exaggeration
            0.10,  # title_body_consistency
            0.05,  # readability
            0.15,  # source_credibility
            0.10,  # historical_accuracy
            0.10,  # community_isolation
            0.05,  # propagation_path
            0.10,  # cross_reference_count
            0.10,  # stance_consistency
            0.10,  # quality_score
        ]
    )
    trusted_threshold: float = 0.8
    fake_threshold: float = 0.4
    exaggeration_words: list[str] = field(
        default_factory=lambda: [
            "震惊",
            "惊天",
            "紧急",
            "速看",
            "删前速看",
            "传疯了",
            "轰动",
            "必看",
            "不转不是",
            "真相",
            "曝光",
            "惊人",
            "绝对",
            "万分紧急",
            "速速扩散",
        ]
    )
    embedding_model: str | None = None
    lightgbm_model_path: str | None = None


class FakeNewsDetector:
    """Fake news detector using five-dimensional feature fusion.

    Reuses existing pipeline intermediate results to build feature vectors
    without additional LLM calls. Supports both rule-based baseline and
    LightGBM model prediction.

    Implements:
        FakeNewsDetector: Five-dimensional fake news detection
    """

    def __init__(
        self,
        config: FakeNewsDetectorConfig | None = None,
        llm: LLMClient | None = None,
    ) -> None:
        """Initialize FakeNewsDetector.

        Args:
            config: Detection configuration. Uses defaults if None.
            llm: LLM client for embedding generation (optional).
        """
        self._config = config or FakeNewsDetectorConfig()
        self._llm = llm
        self._model = None

        # Try to load LightGBM model if path is provided
        if self._config.lightgbm_model_path:
            self._load_model(self._config.lightgbm_model_path)

    def _load_model(self, model_path: str) -> None:
        """Load LightGBM model from file.

        Args:
            model_path: Path to LightGBM model file.
        """
        try:
            import lightgbm as lgb

            self._model = lgb.Booster(model_file=model_path)
            log.info("lightgbm_model_loaded", path=model_path)
        except Exception as exc:
            log.warning(
                "lightgbm_model_load_failed",
                path=model_path,
                error=str(exc),
            )
            self._model = None

    async def extract_features(self, state: dict[str, Any]) -> dict[str, float]:
        """Extract five-dimensional features from pipeline state.

        Args:
            state: Pipeline state dictionary.

        Returns:
            Dictionary of 11 normalized features (0-1).
        """
        features: dict[str, float] = {}

        # Dimension 1: Text Clues
        features["sentiment_intensity"] = self._extract_sentiment_intensity(state)
        features["exaggeration"] = self._extract_exaggeration(state)
        features["title_body_consistency"] = await self._extract_title_body_consistency(state)
        features["readability"] = self._extract_readability(state)

        # Dimension 2: Source Credibility
        features["source_credibility"] = self._extract_source_credibility(state)
        features["historical_accuracy"] = self._extract_historical_accuracy(state)

        # Dimension 3: Community Anomaly
        features["community_isolation"] = self._extract_community_isolation(state)
        features["propagation_path"] = self._extract_propagation_path(state)

        # Dimension 4: Cross-Source Verification
        features["cross_reference_count"] = self._extract_cross_reference_count(state)
        features["stance_consistency"] = self._extract_stance_consistency(state)

        # Dimension 5: Quality Degradation
        features["quality_score"] = self._extract_quality_score(state)

        # Normalize all features to [0, 1]
        for key in features:
            features[key] = max(0.0, min(1.0, features[key]))

        return features

    def _extract_sentiment_intensity(self, state: dict[str, Any]) -> float:
        """Extract sentiment intensity feature.

        Uses the sentiment score from analyze node.
        Higher absolute sentiment = more intense.
        """
        sentiment = state.get("sentiment", {})
        score = sentiment.get("score", 0.5)
        # Score is already in [0, 1], higher = more intense
        # If score is exactly 0.5 (neutral), intensity is 0
        # If score is 0 or 1 (extreme), intensity is 1
        return abs(score - 0.5) * 2  # Scale to [0, 1]

    def _extract_exaggeration(self, state: dict[str, Any]) -> float:
        """Extract exaggeration feature.

        Counts exaggeration marker words in title and body.
        """
        cleaned = state.get("cleaned", {})
        title = cleaned.get("title", "")
        body = cleaned.get("body", "")

        text = f"{title} {body}"
        count = self._count_exaggeration(text)
        return self._calculate_exaggeration_score(count)

    def _count_exaggeration(self, text: str) -> int:
        """Count exaggeration marker words in text.

        Args:
            text: Input text.

        Returns:
            Number of exaggeration words found.
        """
        count = 0
        for word in self._config.exaggeration_words:
            if word in text:
                count += 1
        return count

    def _calculate_exaggeration_score(self, count: int) -> float:
        """Calculate exaggeration score from word count.

        Args:
            count: Number of exaggeration words.

        Returns:
            Exaggeration score (0-1). Higher = more exaggerated.
        """
        if count == 0:
            return 0.0
        # Sigmoid-like scaling: 1 word -> ~0.2, 3 words -> ~0.6, 5+ words -> ~0.9
        return min(1.0, 1 / (1 + math.exp(-0.8 * (count - 2))))

    async def _extract_title_body_consistency(self, state: dict[str, Any]) -> float:
        """Extract title-body consistency feature.

        Uses existing vectors if available, otherwise generates embeddings.
        Higher score = more inconsistent (clickbait-like).
        """
        vectors = state.get("vectors", {})
        title_vec = vectors.get("title")
        body_vec = vectors.get("content")

        cleaned = state.get("cleaned", {})
        title = cleaned.get("title", "")
        body = cleaned.get("body", "")

        return await self._detect_clickbait(title, body, title_vec, body_vec)

    async def _detect_clickbait(
        self,
        title: str,
        body: str,
        title_vec: list[float] | None,
        body_vec: list[float] | None,
    ) -> float:
        """Detect clickbait using title-body semantic consistency.

        Args:
            title: Article title.
            body: Article body.
            title_vec: Pre-computed title embedding (optional).
            body_vec: Pre-computed body embedding (optional).

        Returns:
            Clickbait score (0-1). Higher = more likely clickbait.
        """
        if not title or not body:
            return 0.5  # Default for empty input

        # Use existing vectors if available
        if title_vec and body_vec:
            similarity = self._cosine_similarity(title_vec, body_vec)
            return max(0.0, 1 - similarity)

        # Fall back to LLM embedding if available
        if self._llm:
            try:
                embedding_model = self._config.embedding_model
                if embedding_model:
                    embeddings = await self._llm.embed(embedding_model, [title, body[:500]])
                else:
                    embeddings = await self._llm.embed_default([title, body[:500]])

                if len(embeddings) == 2:
                    similarity = self._cosine_similarity(embeddings[0], embeddings[1])
                    return max(0.0, 1 - similarity)
            except Exception as exc:
                log.warning("clickbait_embedding_failed", error=str(exc))

        return 0.5  # Default when unable to compute

    def _cosine_similarity(self, vec1: list[float], vec2: list[float]) -> float:
        """Calculate cosine similarity between two vectors.

        Args:
            vec1: First vector.
            vec2: Second vector.

        Returns:
            Cosine similarity (-1 to 1).
        """
        a = np.array(vec1)
        b = np.array(vec2)

        dot_product = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return float(dot_product / (norm_a * norm_b))

    def _extract_readability(self, state: dict[str, Any]) -> float:
        """Extract readability feature.

        Calculates based on average sentence length and complex word ratio.
        Higher score = less readable (more suspicious).
        """
        cleaned = state.get("cleaned", {})
        body = cleaned.get("body", "")

        if not body:
            return 0.5  # Default for empty input

        # Split into sentences
        sentences = [
            s.strip()
            for s in body.replace("。", ".").replace("！", ".").replace("？", ".").split(".")
            if s.strip()
        ]

        if not sentences:
            return 0.5

        # Calculate average sentence length
        avg_length = sum(len(s) for s in sentences) / len(sentences)

        # Normalize: very short (<10) or very long (>100) sentences are suspicious
        if avg_length < 10:
            length_score = 0.3  # Too short
        elif avg_length > 100:
            length_score = 0.8  # Too long
        else:
            # Normal range: scale linearly
            length_score = 0.3 + (avg_length - 10) / 90 * 0.5

        # Calculate complex word ratio (words > 4 characters)
        words = body.split()
        if not words:
            return length_score

        complex_words = sum(1 for w in words if len(w) > 4)
        complex_ratio = complex_words / len(words)

        # Higher complex ratio = less readable
        readability_score = (length_score + complex_ratio) / 2

        return min(1.0, max(0.0, readability_score))

    def _extract_source_credibility(self, state: dict[str, Any]) -> float:
        """Extract source credibility feature.

        Uses source_credibility from credibility checker.
        """
        credibility = state.get("credibility", {})
        return credibility.get("source_credibility", 0.5)

    def _extract_historical_accuracy(self, state: dict[str, Any]) -> float:
        """Extract historical accuracy feature.

        Based on credibility score and flags.
        Lower score = less accurate (more suspicious).
        """
        credibility = state.get("credibility", {})
        score = credibility.get("score", 0.5)
        flags = credibility.get("flags", [])

        # Reduce score based on number of flags
        flag_penalty = len(flags) * 0.1
        adjusted_score = max(0.0, score - flag_penalty)

        return adjusted_score

    def _extract_community_isolation(self, state: dict[str, Any]) -> float:
        """Extract community isolation feature.

        Based on entity count. More entities = less isolated.
        Higher score = more isolated (more suspicious).
        """
        entities = state.get("entities", [])
        entity_count = len(entities)

        # Sigmoid scaling: 0 entities -> ~0.9, 3 entities -> ~0.3, 5+ entities -> ~0.1
        if entity_count == 0:
            return 0.9
        elif entity_count == 1:
            return 0.6
        return max(0.1, 1 / (1 + math.exp(0.8 * (entity_count - 2))))

    def _extract_propagation_path(self, state: dict[str, Any]) -> float:
        """Extract propagation path feature.

        Based on cross-verification score.
        Higher score = more isolated (single source).
        """
        credibility = state.get("credibility", {})
        cross_verification = credibility.get("cross_verification", 0.5)

        # Invert: low cross-verification = high isolation
        return max(0.0, 1 - cross_verification)

    def _extract_cross_reference_count(self, state: dict[str, Any]) -> float:
        """Extract cross-reference count feature.

        Based on cross-verification score.
        Higher score = more cross-references (less suspicious).
        """
        credibility = state.get("credibility", {})
        cross_verification = credibility.get("cross_verification", 0.5)

        # Direct use: high cross-verification = good cross-references
        # But we need to invert for the feature (higher = more suspicious)
        # So we return 1 - cross_verification
        return max(0.0, 1 - cross_verification)

    def _extract_stance_consistency(self, state: dict[str, Any]) -> float:
        """Extract stance consistency feature.

        Based on data conflicts. More conflicts = less consistent.
        Higher score = less consistent (more suspicious).
        """
        conflicts = state.get("data_conflicts", [])
        conflict_count = len(conflicts)

        # Sigmoid scaling: 0 conflicts -> ~0.1, 2 conflicts -> ~0.5, 4+ conflicts -> ~0.9
        if conflict_count == 0:
            return 0.1
        return min(0.9, 1 / (1 + math.exp(-0.8 * (conflict_count - 2))))

    def _extract_quality_score(self, state: dict[str, Any]) -> float:
        """Extract quality score feature.

        Uses quality_score from quality scorer.
        """
        return state.get("quality_score", 0.5)

    async def predict(self, state: dict[str, Any]) -> dict[str, Any]:
        """Predict fake news probability.

        Args:
            state: Pipeline state dictionary.

        Returns:
            Dictionary with:
            - fake_score: Trustworthiness score (0-1). Higher = more trustworthy.
            - level: Classification level (trusted/suspicious/fake).
            - features: Extracted feature dictionary.
        """
        features = await self.extract_features(state)

        # Try LightGBM model first
        if self._model is not None:
            try:
                feature_array = np.array([list(features.values())])
                prediction = self._model.predict(feature_array)
                trust_score = float(prediction[0])
            except Exception as exc:
                log.warning("lightgbm_prediction_failed", error=str(exc))
                trust_score = self._rule_based_predict(features)
        else:
            trust_score = self._rule_based_predict(features)

        # trust_score is already "trustworthiness" from rule_based_predict
        # Higher = more trustworthy

        level = FakeNewsLevel.from_score(
            trust_score,
            trusted=self._config.trusted_threshold,
            fake=self._config.fake_threshold,
        )

        result = {
            "fake_score": round(trust_score, 4),
            "level": level.value,
            "features": features,
        }

        log.debug(
            "fake_news_prediction",
            fake_score=result["fake_score"],
            level=result["level"],
        )

        return result

    def _rule_based_predict(self, features: dict[str, float]) -> float:
        """Predict using rule-based weighted fusion.

        Args:
            features: Feature dictionary.

        Returns:
            Trustworthiness score (0-1). Higher = more trustworthy.
        """
        feature_values = list(features.values())
        weights = self._config.weights

        if len(feature_values) != len(weights):
            log.warning(
                "feature_weight_mismatch",
                feature_count=len(feature_values),
                weight_count=len(weights),
            )
            return 0.5

        # Weighted sum of suspicious indicators
        suspicious_score = sum(f * w for f, w in zip(feature_values, weights))

        # Invert to get trustworthiness (higher = more trustworthy)
        trust_score = 1.0 - suspicious_score

        return min(1.0, max(0.0, trust_score))
