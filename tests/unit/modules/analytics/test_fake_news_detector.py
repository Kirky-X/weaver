# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for FakeNewsDetector five-dimensional feature extraction."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.analytics.fake_news_detector import (
    FakeNewsDetector,
    FakeNewsDetectorConfig,
    FakeNewsLevel,
)


@pytest.fixture
def config() -> FakeNewsDetectorConfig:
    """Default configuration for tests."""
    return FakeNewsDetectorConfig()


@pytest.fixture
def detector(config: FakeNewsDetectorConfig) -> FakeNewsDetector:
    """FakeNewsDetector instance without LLM."""
    return FakeNewsDetector(config=config)


@pytest.fixture
def detector_with_llm(config: FakeNewsDetectorConfig) -> FakeNewsDetector:
    """FakeNewsDetector instance with mocked LLM."""
    llm = AsyncMock()
    llm.embed_default = AsyncMock(return_value=[[0.1] * 1024, [0.2] * 1024])
    return FakeNewsDetector(config=config, llm=llm)


@pytest.fixture
def high_quality_state() -> dict[str, Any]:
    """Pipeline state representing a high-quality article."""
    return {
        "cleaned": {
            "title": "央行发布2026年第一季度货币政策执行报告",
            "body": (
                "中国人民银行今日发布2026年第一季度货币政策执行报告。报告显示，一季度GDP同比增长5.2%，CPI同比上涨1.8%。"
            ),
        },
        "sentiment": {"score": 0.5, "sentiment": "neutral"},
        "credibility": {
            "score": 0.85,
            "source_credibility": 0.90,
            "cross_verification": 0.80,
            "flags": [],
        },
        "quality_score": 0.82,
        "entities": [
            {"text": "中国人民银行", "type": "ORG"},
            {"text": "GDP", "type": "METRIC"},
        ],
        "vectors": {
            "title": [0.1] * 1024,
            "content": [0.2] * 1024,
        },
        "data_conflicts": [],
    }


@pytest.fixture
def low_quality_state() -> dict[str, Any]:
    """Pipeline state representing a low-quality/suspicious article."""
    return {
        "cleaned": {
            "title": "震惊！必看！紧急转发！真相曝光！",
            "body": "某不知名来源爆料，惊天内幕曝光，不转不是中国人！删前速看！",
        },
        "sentiment": {"score": 0.9, "sentiment": "negative"},
        "credibility": {
            "score": 0.25,
            "source_credibility": 0.20,
            "cross_verification": 0.15,
            "flags": ["low_credibility_source", "no_cross_verification"],
        },
        "quality_score": 0.30,
        "entities": [],
        "vectors": {
            "title": [0.3] * 1024,
            "content": [0.9] * 1024,  # Very different from title
        },
        "data_conflicts": [{"type": "numerical", "detail": "conflicting data"}],
    }


class TestFakeNewsDetectorConfig:
    """Test FakeNewsDetectorConfig defaults."""

    def test_default_weights(self, config: FakeNewsDetectorConfig) -> None:
        """Test that default weights are set correctly."""
        assert len(config.weights) == 11
        assert config.weights[0] == 0.15  # sentiment_intensity
        assert config.weights[1] == 0.10  # exaggeration
        assert config.weights[2] == 0.10  # title_body_consistency
        assert config.weights[3] == 0.05  # readability
        assert config.weights[4] == 0.15  # source_credibility
        assert config.weights[5] == 0.10  # historical_accuracy
        assert config.weights[6] == 0.10  # community_isolation
        assert config.weights[7] == 0.05  # propagation_path
        assert config.weights[8] == 0.10  # cross_reference_count
        assert config.weights[9] == 0.10  # stance_consistency
        assert config.weights[10] == 0.10  # quality_score

    def test_default_thresholds(self, config: FakeNewsDetectorConfig) -> None:
        """Test that default thresholds are set correctly."""
        assert config.trusted_threshold == 0.8
        assert config.fake_threshold == 0.4

    def test_default_exaggeration_words(self, config: FakeNewsDetectorConfig) -> None:
        """Test that default exaggeration words are set."""
        assert "震惊" in config.exaggeration_words
        assert "必看" in config.exaggeration_words
        assert "紧急" in config.exaggeration_words
        assert "速看" in config.exaggeration_words


class TestFiveDimensionFeatures:
    """Test five-dimensional feature extraction."""

    @pytest.mark.asyncio
    async def test_extract_all_features(
        self, detector: FakeNewsDetector, high_quality_state: dict[str, Any]
    ) -> None:
        """Test that all 11 features are extracted."""
        features = await detector.extract_features(high_quality_state)

        assert "sentiment_intensity" in features
        assert "exaggeration" in features
        assert "title_body_consistency" in features
        assert "readability" in features
        assert "source_credibility" in features
        assert "historical_accuracy" in features
        assert "community_isolation" in features
        assert "propagation_path" in features
        assert "cross_reference_count" in features
        assert "stance_consistency" in features
        assert "quality_score" in features
        assert len(features) == 11

    @pytest.mark.asyncio
    async def test_features_are_normalized(
        self, detector: FakeNewsDetector, high_quality_state: dict[str, Any]
    ) -> None:
        """Test that all features are in [0, 1] range."""
        features = await detector.extract_features(high_quality_state)

        for name, value in features.items():
            assert 0.0 <= value <= 1.0, f"Feature {name} = {value} is out of [0, 1] range"

    @pytest.mark.asyncio
    async def test_high_quality_features(
        self, detector: FakeNewsDetector, high_quality_state: dict[str, Any]
    ) -> None:
        """Test that high-quality article has good feature values."""
        features = await detector.extract_features(high_quality_state)

        # High quality should have low exaggeration
        assert features["exaggeration"] < 0.3
        # High quality should have high source credibility
        assert features["source_credibility"] > 0.7
        # High quality should have high quality score
        assert features["quality_score"] > 0.7

    @pytest.mark.asyncio
    async def test_low_quality_features(
        self, detector: FakeNewsDetector, low_quality_state: dict[str, Any]
    ) -> None:
        """Test that low-quality article has suspicious feature values."""
        features = await detector.extract_features(low_quality_state)

        # Low quality should have high exaggeration
        assert features["exaggeration"] > 0.5
        # Low quality should have low source credibility
        assert features["source_credibility"] < 0.3
        # Low quality should have low quality score
        assert features["quality_score"] < 0.4


class TestTextClueFeatures:
    """Test text clue dimension features."""

    @pytest.mark.asyncio
    async def test_sentiment_intensity(self, detector: FakeNewsDetector) -> None:
        """Test sentiment intensity extraction."""
        state = {"sentiment": {"score": 0.8}}
        features = await detector.extract_features(state)
        # Score 0.8 -> distance from 0.5 is 0.3 -> * 2 = 0.6
        assert features["sentiment_intensity"] == pytest.approx(0.6)

    @pytest.mark.asyncio
    async def test_sentiment_intensity_default(self, detector: FakeNewsDetector) -> None:
        """Test sentiment intensity defaults to 0 when missing (neutral)."""
        state: dict[str, Any] = {}
        features = await detector.extract_features(state)
        # Default score 0.5 -> distance from 0.5 is 0 -> * 2 = 0
        assert features["sentiment_intensity"] == 0.0

    @pytest.mark.asyncio
    async def test_exaggeration_detection(self, detector: FakeNewsDetector) -> None:
        """Test exaggeration word detection."""
        state = {
            "cleaned": {
                "title": "震惊！必看！紧急转发！",
                "body": "普通内容",
            }
        }
        features = await detector.extract_features(state)
        # 3 exaggeration words should give high score
        assert features["exaggeration"] > 0.5

    @pytest.mark.asyncio
    async def test_no_exaggeration(self, detector: FakeNewsDetector) -> None:
        """Test no exaggeration in normal content."""
        state = {
            "cleaned": {
                "title": "央行发布2026年第一季度货币政策执行报告",
                "body": "中国人民银行今日发布报告。",
            }
        }
        features = await detector.extract_features(state)
        assert features["exaggeration"] == 0.0

    @pytest.mark.asyncio
    async def test_title_body_consistency_with_vectors(
        self, detector_with_llm: FakeNewsDetector
    ) -> None:
        """Test title-body consistency using existing vectors."""
        state = {
            "cleaned": {
                "title": "测试标题",
                "body": "测试内容",
            },
            "vectors": {
                "title": [1.0] + [0.0] * 1023,
                "content": [1.0] + [0.0] * 1023,  # Same as title
            },
        }
        features = await detector_with_llm.extract_features(state)
        # Same vectors should have high consistency (low score = more consistent)
        # Note: feature is "suspicious indicator", so low = good
        assert features["title_body_consistency"] < 0.3

    @pytest.mark.asyncio
    async def test_title_body_consistency_without_vectors(
        self, detector_with_llm: FakeNewsDetector
    ) -> None:
        """Test title-body consistency falls back to LLM embedding."""
        state = {
            "cleaned": {
                "title": "测试标题",
                "body": "测试内容",
            }
        }
        features = await detector_with_llm.extract_features(state)
        # Should use LLM embedding
        assert 0.0 <= features["title_body_consistency"] <= 1.0

    @pytest.mark.asyncio
    async def test_readability(self, detector: FakeNewsDetector) -> None:
        """Test readability calculation."""
        state = {
            "cleaned": {
                "body": "这是一句短话。这是另一句短话。这是第三句短话。",
            }
        }
        features = await detector.extract_features(state)
        assert 0.0 <= features["readability"] <= 1.0


class TestSourceCredibilityFeatures:
    """Test source credibility dimension features."""

    @pytest.mark.asyncio
    async def test_source_credibility(self, detector: FakeNewsDetector) -> None:
        """Test source credibility extraction."""
        state = {
            "credibility": {
                "source_credibility": 0.85,
            }
        }
        features = await detector.extract_features(state)
        assert features["source_credibility"] == 0.85

    @pytest.mark.asyncio
    async def test_source_credibility_default(self, detector: FakeNewsDetector) -> None:
        """Test source credibility defaults to 0.5 when missing."""
        state: dict[str, Any] = {}
        features = await detector.extract_features(state)
        assert features["source_credibility"] == 0.5

    @pytest.mark.asyncio
    async def test_historical_accuracy(self, detector: FakeNewsDetector) -> None:
        """Test historical accuracy calculation."""
        state = {
            "credibility": {
                "score": 0.80,
                "flags": [],
            }
        }
        features = await detector.extract_features(state)
        # No flags should give high accuracy
        assert features["historical_accuracy"] > 0.7

    @pytest.mark.asyncio
    async def test_historical_accuracy_with_flags(self, detector: FakeNewsDetector) -> None:
        """Test historical accuracy with credibility flags."""
        state = {
            "credibility": {
                "score": 0.50,
                "flags": ["low_credibility_source", "no_cross_verification"],
            }
        }
        features = await detector.extract_features(state)
        # Multiple flags should reduce accuracy
        assert features["historical_accuracy"] < 0.5


class TestCommunityAnomalyFeatures:
    """Test community anomaly dimension features."""

    @pytest.mark.asyncio
    async def test_community_isolation(self, detector: FakeNewsDetector) -> None:
        """Test community isolation calculation."""
        state = {
            "entities": [
                {"text": "Entity1", "type": "ORG"},
                {"text": "Entity2", "type": "PERSON"},
                {"text": "Entity3", "type": "LOCATION"},
            ]
        }
        features = await detector.extract_features(state)
        # More entities should mean less isolation
        assert features["community_isolation"] < 0.5

    @pytest.mark.asyncio
    async def test_community_isolation_no_entities(self, detector: FakeNewsDetector) -> None:
        """Test community isolation with no entities."""
        state: dict[str, Any] = {"entities": []}
        features = await detector.extract_features(state)
        # No entities should mean high isolation
        assert features["community_isolation"] > 0.5

    @pytest.mark.asyncio
    async def test_propagation_path(self, detector: FakeNewsDetector) -> None:
        """Test propagation path calculation."""
        state = {
            "credibility": {
                "cross_verification": 0.80,
            }
        }
        features = await detector.extract_features(state)
        # High cross-verification should mean good propagation
        assert features["propagation_path"] < 0.3

    @pytest.mark.asyncio
    async def test_propagation_path_isolated(self, detector: FakeNewsDetector) -> None:
        """Test propagation path for isolated source."""
        state = {
            "credibility": {
                "cross_verification": 0.10,
            }
        }
        features = await detector.extract_features(state)
        # Low cross-verification should mean isolated
        assert features["propagation_path"] > 0.7


class TestCrossSourceVerificationFeatures:
    """Test cross-source verification dimension features."""

    @pytest.mark.asyncio
    async def test_cross_reference_count(self, detector: FakeNewsDetector) -> None:
        """Test cross-reference count calculation."""
        state = {
            "credibility": {
                "cross_verification": 0.75,
            }
        }
        features = await detector.extract_features(state)
        # High cross-verification (0.75) -> inverted = 0.25 (low suspicious score)
        assert features["cross_reference_count"] == 0.25

    @pytest.mark.asyncio
    async def test_stance_consistency(self, detector: FakeNewsDetector) -> None:
        """Test stance consistency calculation."""
        state = {
            "data_conflicts": [],
        }
        features = await detector.extract_features(state)
        # No conflicts should mean low suspicious score
        assert features["stance_consistency"] < 0.2

    @pytest.mark.asyncio
    async def test_stance_consistency_with_conflicts(self, detector: FakeNewsDetector) -> None:
        """Test stance consistency with data conflicts."""
        state = {
            "data_conflicts": [
                {"type": "numerical", "detail": "conflict1"},
                {"type": "factual", "detail": "conflict2"},
                {"type": "factual", "detail": "conflict3"},
            ],
        }
        features = await detector.extract_features(state)
        # Multiple conflicts should increase suspicious score
        assert features["stance_consistency"] > 0.4


class TestQualityDegradationFeatures:
    """Test quality degradation dimension features."""

    @pytest.mark.asyncio
    async def test_quality_score(self, detector: FakeNewsDetector) -> None:
        """Test quality score extraction."""
        state = {
            "quality_score": 0.85,
        }
        features = await detector.extract_features(state)
        assert features["quality_score"] == 0.85

    @pytest.mark.asyncio
    async def test_quality_score_default(self, detector: FakeNewsDetector) -> None:
        """Test quality score defaults to 0.5 when missing."""
        state: dict[str, Any] = {}
        features = await detector.extract_features(state)
        assert features["quality_score"] == 0.5


class TestFakeNewsLevel:
    """Test fake news level classification."""

    def test_trusted_level(self) -> None:
        """Test trusted level classification."""
        assert FakeNewsLevel.from_score(0.9) == FakeNewsLevel.TRUSTED
        assert FakeNewsLevel.from_score(0.8) == FakeNewsLevel.TRUSTED

    def test_suspicious_level(self) -> None:
        """Test suspicious level classification."""
        assert FakeNewsLevel.from_score(0.7) == FakeNewsLevel.SUSPICIOUS
        assert FakeNewsLevel.from_score(0.5) == FakeNewsLevel.SUSPICIOUS
        assert FakeNewsLevel.from_score(0.4) == FakeNewsLevel.SUSPICIOUS

    def test_fake_level(self) -> None:
        """Test fake level classification."""
        assert FakeNewsLevel.from_score(0.3) == FakeNewsLevel.FAKE
        assert FakeNewsLevel.from_score(0.1) == FakeNewsLevel.FAKE
        assert FakeNewsLevel.from_score(0.0) == FakeNewsLevel.FAKE


class TestRuleWeightBaseline:
    """Test rule weight baseline prediction."""

    @pytest.mark.asyncio
    async def test_predict_without_model(
        self, detector: FakeNewsDetector, high_quality_state: dict[str, Any]
    ) -> None:
        """Test prediction using rule weights when no model is loaded."""
        result = await detector.predict(high_quality_state)

        assert "fake_score" in result
        assert "level" in result
        assert "features" in result
        assert result["level"] in ["trusted", "suspicious", "fake"]

    @pytest.mark.asyncio
    async def test_predict_high_quality(
        self, detector: FakeNewsDetector, high_quality_state: dict[str, Any]
    ) -> None:
        """Test that high-quality article gets high fake_score."""
        result = await detector.predict(high_quality_state)
        # High quality should have trust score > 0.5
        assert result["fake_score"] > 0.5

    @pytest.mark.asyncio
    async def test_predict_low_quality(
        self, detector: FakeNewsDetector, low_quality_state: dict[str, Any]
    ) -> None:
        """Test that low-quality article gets low fake_score."""
        result = await detector.predict(low_quality_state)
        # Low quality should have trust score < 0.5
        assert result["fake_score"] < 0.5

    @pytest.mark.asyncio
    async def test_predict_returns_features(
        self, detector: FakeNewsDetector, high_quality_state: dict[str, Any]
    ) -> None:
        """Test that predict returns all features."""
        result = await detector.predict(high_quality_state)
        assert len(result["features"]) == 11


class TestClickbaitDetection:
    """Test title-body consistency (clickbait) detection."""

    @pytest.mark.asyncio
    async def test_detect_clickbait_with_vectors(self, detector_with_llm: FakeNewsDetector) -> None:
        """Test clickbait detection using existing vectors."""
        title_vec = [1.0] + [0.0] * 1023
        body_vec = [1.0] + [0.0] * 1023  # Same as title

        score = await detector_with_llm._detect_clickbait(
            title="测试标题",
            body="测试内容",
            title_vec=title_vec,
            body_vec=body_vec,
        )
        # Same vectors should have low clickbait score
        assert score < 0.2

    @pytest.mark.asyncio
    async def test_detect_clickbait_different_vectors(
        self, detector_with_llm: FakeNewsDetector
    ) -> None:
        """Test clickbait detection with different title/body vectors."""
        title_vec = [1.0] + [0.0] * 1023
        body_vec = [0.0] * 1024  # Completely different

        score = await detector_with_llm._detect_clickbait(
            title="震惊！必看！",
            body="普通内容",
            title_vec=title_vec,
            body_vec=body_vec,
        )
        # Different vectors should have high clickbait score
        assert score > 0.5

    @pytest.mark.asyncio
    async def test_detect_clickbait_empty_input(self, detector: FakeNewsDetector) -> None:
        """Test clickbait detection with empty input."""
        score = await detector._detect_clickbait(
            title="",
            body="",
            title_vec=None,
            body_vec=None,
        )
        assert score == 0.5  # Default for empty input


class TestExaggerationDetection:
    """Test exaggeration word detection."""

    def test_count_exaggeration(self, detector: FakeNewsDetector) -> None:
        """Test exaggeration word counting."""
        text = "震惊！必看！紧急转发！删前速看！传疯了！"
        count = detector._count_exaggeration(text)
        # Note: "传疯了" is counted, and "删前速看" contains "速看"
        assert count >= 5

    def test_count_exaggeration_none(self, detector: FakeNewsDetector) -> None:
        """Test no exaggeration words."""
        text = "央行发布2026年第一季度货币政策执行报告"
        count = detector._count_exaggeration(text)
        assert count == 0

    def test_exaggeration_score(self, detector: FakeNewsDetector) -> None:
        """Test exaggeration score calculation."""
        # 3+ words should give score > 0.5
        score = detector._calculate_exaggeration_score(3)
        assert score > 0.5

        # 0 words should give score 0
        score = detector._calculate_exaggeration_score(0)
        assert score == 0.0

        # 1 word should give low score
        score = detector._calculate_exaggeration_score(1)
        assert score < 0.35
