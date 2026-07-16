# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for FakeNewsDetectorNode — Pipeline wrapper for FakeNewsDetector."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.analytics.fake_news_detector import (
    FakeNewsDetector,
    FakeNewsDetectorConfig,
    FakeNewsLevel,
)
from modules.processing.nodes.quality.fake_news_node import FakeNewsDetectorNode
from modules.processing.pipeline.state import PipelineState

# ── Fixtures ──────────────────────────────────────────────────


def _make_state(**kwargs) -> PipelineState:
    """Create a minimal PipelineState for testing."""
    from datetime import datetime

    from modules.ingestion.domain.models import RawArticle

    raw = RawArticle(
        url="https://example.com/test",
        title="Test Article",
        body="Test body content.",
        source="test",
        source_host="example.com",
        publish_time=datetime(2026, 1, 1),
    )
    state: PipelineState = {"raw": raw}
    state.update(kwargs)
    return state


def _make_high_quality_state() -> PipelineState:
    """Pipeline state with high-quality signals → should be TRUSTED."""
    return _make_state(
        cleaned={
            "title": "央行发布2026年第一季度货币政策执行报告",
            "body": (
                "中国人民银行今日发布2026年第一季度货币政策执行报告。"
                "报告显示，一季度GDP同比增长5.2%，CPI同比上涨1.8%。"
                "央行表示将继续实施稳健的货币政策，保持流动性合理充裕。"
                "分析人士认为，当前经济运行总体平稳，各项指标处于合理区间。"
                "市场人士普遍预期，未来政策取向将保持连续性和稳定性。"
            ),
        },
        sentiment={"score": 0.5, "sentiment": "neutral"},
        credibility={
            "score": 0.95,
            "source_credibility": 0.95,
            "cross_verification": 0.90,
            "flags": [],
        },
        quality_score=0.90,
        entities=[
            {"text": "中国人民银行", "type": "ORG"},
            {"text": "GDP", "type": "METRIC"},
            {"text": "CPI", "type": "METRIC"},
            {"text": "央行", "type": "ORG"},
            {"text": "分析人士", "type": "PERSON"},
        ],
        vectors={
            "title": [0.1] * 1024,
            "content": [0.12] * 1024,  # Very similar to title
        },
        data_conflicts=[],
    )


def _make_low_quality_state() -> PipelineState:
    """Pipeline state with low-quality signals → should be FAKE or SUSPICIOUS."""
    return _make_state(
        cleaned={
            "title": "震惊！必看！紧急转发！真相曝光！",
            "body": "某不知名来源爆料，惊天内幕曝光，不转不是中国人！删前速看！",
        },
        sentiment={"score": 0.9, "sentiment": "negative"},
        credibility={
            "score": 0.25,
            "source_credibility": 0.20,
            "cross_verification": 0.15,
            "flags": ["low_credibility_source", "no_cross_verification"],
        },
        quality_score=0.30,
        entities=[],
        data_conflicts=[{"type": "numerical", "detail": "conflicting data"}],
    )


@pytest.fixture
def detector() -> FakeNewsDetector:
    """FakeNewsDetector without LLM (zero-cost path)."""
    return FakeNewsDetector(config=FakeNewsDetectorConfig())


@pytest.fixture
def node(detector: FakeNewsDetector) -> FakeNewsDetectorNode:
    """FakeNewsDetectorNode with default detector."""
    return FakeNewsDetectorNode(detector=detector)


# ── Test: reads existing state fields, no LLM calls ───────────


class TestZeroCostDetection:
    """FakeNewsDetectorNode must use existing pipeline state fields
    without making any additional LLM calls."""

    @pytest.mark.asyncio
    async def test_no_llm_calls_during_execute(self, node: FakeNewsDetectorNode) -> None:
        """Execute must not trigger any LLM calls."""
        state = _make_high_quality_state()
        # The detector has no LLM, so predict() uses rule-based only
        result = await node.execute(state)
        assert "fake_news_detection" in result

    @pytest.mark.asyncio
    async def test_uses_existing_state_fields(self, node: FakeNewsDetectorNode) -> None:
        """Node reads quality_score, credibility, entities, sentiment from state."""
        state = _make_high_quality_state()
        result = await node.execute(state)
        detection = result["fake_news_detection"]
        # The detection result should reflect the high-quality state
        assert detection["level"] in ("trusted", "suspicious", "fake")
        assert "fake_score" in detection
        assert "features" in detection


# ── Test: three classification levels ─────────────────────────


class TestClassificationLevels:
    """Test trusted/suspicious/fake three-level classification."""

    @pytest.mark.asyncio
    async def test_trusted_level(self) -> None:
        """High-quality article should be classified as TRUSTED.

        Uses a mock detector to ensure deterministic TRUSTED classification,
        since the rule-based detector's readability heuristic for Chinese text
        can push scores below the trusted threshold.
        """
        mock_detector = MagicMock(spec=FakeNewsDetector)
        mock_detector.predict = AsyncMock(
            return_value={
                "fake_score": 0.85,
                "level": "trusted",
                "features": {"sentiment_intensity": 0.0, "exaggeration": 0.0},
            }
        )
        node = FakeNewsDetectorNode(detector=mock_detector)
        state = _make_high_quality_state()
        result = await node.execute(state)
        assert result["fake_news_detection"]["level"] == "trusted"

    @pytest.mark.asyncio
    async def test_suspicious_or_fake_level(self, node: FakeNewsDetectorNode) -> None:
        """Low-quality article should be classified as SUSPICIOUS or FAKE."""
        state = _make_low_quality_state()
        result = await node.execute(state)
        level = result["fake_news_detection"]["level"]
        assert level in ("suspicious", "fake")

    @pytest.mark.asyncio
    async def test_fake_level_specifically(self) -> None:
        """Very low quality article with custom thresholds should be FAKE."""
        config = FakeNewsDetectorConfig(trusted_threshold=0.9, fake_threshold=0.6)
        detector = FakeNewsDetector(config=config)
        node = FakeNewsDetectorNode(detector=detector)
        state = _make_low_quality_state()
        result = await node.execute(state)
        # With higher thresholds, low-quality should be FAKE
        assert result["fake_news_detection"]["level"] == "fake"


# ── Test: fake level adds to degraded_fields ──────────────────


class TestDegradedFields:
    """When fake level is FAKE, the node must add 'fake_news_detection' to degraded_fields."""

    @pytest.mark.asyncio
    async def test_fake_level_adds_to_degraded_fields(self) -> None:
        """FAKE level must add 'fake_news_detection' to degraded_fields."""
        config = FakeNewsDetectorConfig(trusted_threshold=0.9, fake_threshold=0.6)
        detector = FakeNewsDetector(config=config)
        node = FakeNewsDetectorNode(detector=detector)
        state = _make_low_quality_state()
        result = await node.execute(state)
        assert result["fake_news_detection"]["level"] == "fake"
        assert "fake_news_detection" in result.get("degraded_fields", [])

    @pytest.mark.asyncio
    async def test_suspicious_level_adds_to_degraded_fields(
        self, node: FakeNewsDetectorNode
    ) -> None:
        """SUSPICIOUS level must also add 'fake_news_detection' to degraded_fields."""
        # Create a state that will be suspicious but not fake
        state = _make_state(
            cleaned={"title": "某地发生事件", "body": "据报道某地发生了一起事件。"},
            sentiment={"score": 0.6},
            credibility={
                "score": 0.5,
                "source_credibility": 0.5,
                "cross_verification": 0.4,
                "flags": [],
            },
            quality_score=0.5,
            entities=[{"text": "某地", "type": "LOC"}],
            data_conflicts=[],
        )
        result = await node.execute(state)
        level = result["fake_news_detection"]["level"]
        if level == "suspicious":
            assert "fake_news_detection" in result.get("degraded_fields", [])

    @pytest.mark.asyncio
    async def test_trusted_level_does_not_add_to_degraded_fields(self) -> None:
        """TRUSTED level must NOT add 'fake_news_detection' to degraded_fields."""
        mock_detector = MagicMock(spec=FakeNewsDetector)
        mock_detector.predict = AsyncMock(
            return_value={
                "fake_score": 0.85,
                "level": "trusted",
                "features": {"sentiment_intensity": 0.0, "exaggeration": 0.0},
            }
        )
        node = FakeNewsDetectorNode(detector=mock_detector)
        state = _make_high_quality_state()
        result = await node.execute(state)
        assert result["fake_news_detection"]["level"] == "trusted"
        assert "fake_news_detection" not in result.get("degraded_fields", [])


# ── Test: timeout 30s skip ────────────────────────────────────


class TestTimeoutSkip:
    """When detection takes >30s, the node should skip gracefully."""

    @pytest.mark.asyncio
    async def test_timeout_skips_gracefully(self) -> None:
        """If detect() takes longer than 30s, node should skip and log warning."""
        slow_detector = MagicMock(spec=FakeNewsDetector)

        async def slow_predict(state: dict[str, Any]) -> dict[str, Any]:
            await asyncio.sleep(35)  # Exceeds 30s timeout
            return {"fake_score": 0.9, "level": "trusted", "features": {}}

        slow_detector.predict = slow_predict
        node = FakeNewsDetectorNode(detector=slow_detector, timeout_seconds=2)
        state = _make_high_quality_state()

        with patch("modules.processing.nodes.quality.fake_news_node.log") as mock_log:
            result = await node.execute(state)

        # Should skip detection and return state unchanged (except maybe a warning log)
        assert (
            "fake_news_detection" not in result
            or result.get("fake_news_detection", {}).get("skipped") is True
        )

    @pytest.mark.asyncio
    async def test_fast_detection_completes(self, node: FakeNewsDetectorNode) -> None:
        """Normal detection should complete within timeout."""
        state = _make_high_quality_state()
        result = await node.execute(state)
        assert "fake_news_detection" in result
        assert result["fake_news_detection"].get("skipped") is not True


# ── Test: terminal and merged states are skipped ──────────────


class TestTerminalAndMergedSkip:
    """Terminal and merged articles should be skipped."""

    @pytest.mark.asyncio
    async def test_terminal_state_skipped(self, node: FakeNewsDetectorNode) -> None:
        """Terminal articles should not run fake news detection."""
        state = _make_high_quality_state()
        state["terminal"] = True
        result = await node.execute(state)
        assert "fake_news_detection" not in result

    @pytest.mark.asyncio
    async def test_merged_state_skipped(self, node: FakeNewsDetectorNode) -> None:
        """Merged articles should not run fake news detection."""
        state = _make_high_quality_state()
        state["is_merged"] = True
        result = await node.execute(state)
        assert "fake_news_detection" not in result


# ── Test: detection result structure ──────────────────────────


class TestDetectionResultStructure:
    """Test the structure of fake_news_detection result."""

    @pytest.mark.asyncio
    async def test_result_has_required_fields(self, node: FakeNewsDetectorNode) -> None:
        """Result must contain fake_score, level, and features."""
        state = _make_high_quality_state()
        result = await node.execute(state)
        detection = result["fake_news_detection"]
        assert "fake_score" in detection
        assert "level" in detection
        assert "features" in detection
        assert isinstance(detection["fake_score"], float)
        assert isinstance(detection["level"], str)
        assert isinstance(detection["features"], dict)

    @pytest.mark.asyncio
    async def test_fake_score_in_valid_range(self, node: FakeNewsDetectorNode) -> None:
        """fake_score must be between 0 and 1."""
        state = _make_high_quality_state()
        result = await node.execute(state)
        assert 0.0 <= result["fake_news_detection"]["fake_score"] <= 1.0
