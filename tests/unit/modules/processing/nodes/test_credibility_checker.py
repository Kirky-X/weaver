# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for processing CredibilityCheckerNode."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.llm.output_validator import CredibilityOutput
from core.llm.types import CallPoint
from modules.ingestion.domain.models import ArticleRaw
from modules.processing.nodes.credibility_checker import CredibilityCheckerNode
from modules.processing.pipeline.state import PipelineState


@pytest.fixture
def sample_raw():
    return ArticleRaw(
        url="https://example.com/credible-article",
        title="Research Study Confirms New Treatment Efficacy",
        body="A comprehensive research study has confirmed the efficacy of a new treatment.",
        source="medical_journal",
        publish_time=datetime.now(UTC),
        source_host="example.com",
    )


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def mock_budget():
    budget = MagicMock()
    budget.truncate = lambda text, call_point: text
    return budget


@pytest.fixture
def mock_event_bus():
    bus = MagicMock()
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def mock_source_auth_repo():
    repo = AsyncMock()
    mock_auth = MagicMock()
    mock_auth.authority = 0.85
    repo.get_or_create = AsyncMock(return_value=mock_auth)
    return repo


@pytest.fixture
def mock_source_config_repo():
    repo = AsyncMock()
    repo.get_credibility = AsyncMock(return_value=None)
    return repo


class TestCalcTimeliness:
    """Tests for _calc_timeliness static method."""

    def test_timeliness_within_6_hours(self):
        publish_time = datetime.now(UTC)
        event_time = (publish_time - timedelta(hours=3)).isoformat()
        score = CredibilityCheckerNode._calc_timeliness(publish_time, event_time)
        assert score == 1.00

    def test_timeliness_within_24_hours(self):
        publish_time = datetime.now(UTC)
        event_time = (publish_time - timedelta(hours=12)).isoformat()
        score = CredibilityCheckerNode._calc_timeliness(publish_time, event_time)
        assert score == 0.85

    def test_timeliness_within_72_hours(self):
        publish_time = datetime.now(UTC)
        event_time = (publish_time - timedelta(hours=48)).isoformat()
        score = CredibilityCheckerNode._calc_timeliness(publish_time, event_time)
        assert score == 0.65

    def test_timeliness_within_week(self):
        publish_time = datetime.now(UTC)
        event_time = (publish_time - timedelta(hours=100)).isoformat()
        score = CredibilityCheckerNode._calc_timeliness(publish_time, event_time)
        assert score == 0.45

    def test_timeliness_older_than_week(self):
        publish_time = datetime.now(UTC)
        event_time = (publish_time - timedelta(hours=200)).isoformat()
        score = CredibilityCheckerNode._calc_timeliness(publish_time, event_time)
        assert score == 0.30

    def test_timeliness_missing_publish_time(self):
        event_time = datetime.now(UTC).isoformat()
        score = CredibilityCheckerNode._calc_timeliness(None, event_time)
        assert score == 0.7

    def test_timeliness_missing_event_time(self):
        publish_time = datetime.now(UTC)
        score = CredibilityCheckerNode._calc_timeliness(publish_time, None)
        assert score == 0.7

    def test_timeliness_invalid_event_time(self):
        publish_time = datetime.now(UTC)
        score = CredibilityCheckerNode._calc_timeliness(publish_time, "invalid-date")
        assert score == 0.7

    def test_timeliness_future_event(self):
        publish_time = datetime.now(UTC)
        event_time = (publish_time + timedelta(hours=10)).isoformat()
        score = CredibilityCheckerNode._calc_timeliness(publish_time, event_time)
        assert score == 0.85


class TestCategoryWeights:
    """Tests for category-adaptive weight selection."""

    def test_breaking_news_weights(self):
        for category in ["政治", "国际", "军事"]:
            weights = CredibilityCheckerNode.CATEGORY_WEIGHTS.get(
                category, CredibilityCheckerNode.DEFAULT_WEIGHTS
            )
            assert weights["timeliness"] == 0.50
            assert weights["source"] == 0.25
            assert weights["content"] == 0.25

    def test_economic_news_weights(self):
        weights = CredibilityCheckerNode.CATEGORY_WEIGHTS.get(
            "经济", CredibilityCheckerNode.DEFAULT_WEIGHTS
        )
        assert weights["source"] == 0.45
        assert weights["content"] == 0.35
        assert weights["timeliness"] == 0.20

    def test_tech_news_weights(self):
        weights = CredibilityCheckerNode.CATEGORY_WEIGHTS.get(
            "科技", CredibilityCheckerNode.DEFAULT_WEIGHTS
        )
        assert weights["content"] == 0.50
        assert weights["source"] == 0.30
        assert weights["timeliness"] == 0.20

    def test_default_weights(self):
        for category in ["社会", "文化", "体育"]:
            weights = CredibilityCheckerNode.CATEGORY_WEIGHTS.get(
                category, CredibilityCheckerNode.DEFAULT_WEIGHTS
            )
            assert weights["source"] == 0.40
            assert weights["content"] == 0.40
            assert weights["timeliness"] == 0.20

    def test_unknown_category_uses_default(self):
        weights = CredibilityCheckerNode.CATEGORY_WEIGHTS.get(
            "unknown_category", CredibilityCheckerNode.DEFAULT_WEIGHTS
        )
        assert weights == CredibilityCheckerNode.DEFAULT_WEIGHTS

    def test_all_weights_sum_to_one(self):
        for category, weights in CredibilityCheckerNode.CATEGORY_WEIGHTS.items():
            total = sum(weights.values())
            assert abs(total - 1.0) < 0.001, f"Weights for {category} don't sum to 1.0: {total}"


class TestSourceAuthorityPriority:
    """Tests for three-level priority source authority lookup."""

    @pytest.mark.asyncio
    async def test_priority_1_preset_credibility(
        self,
        mock_llm,
        mock_budget,
        mock_event_bus,
        mock_source_auth_repo,
        mock_source_config_repo,
        sample_raw,
    ):
        mock_source_config_repo.get_credibility = AsyncMock(return_value=0.95)
        mock_llm.call_at = AsyncMock(return_value=CredibilityOutput(score=0.7, flags=[]))

        node = CredibilityCheckerNode(
            llm=mock_llm,
            budget=mock_budget,
            event_bus=mock_event_bus,
            source_auth_repo=mock_source_auth_repo,
            source_config_repo=mock_source_config_repo,
        )
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {
            "title": sample_raw.title,
            "body": sample_raw.body,
            "publish_time": None,
        }
        result = await node.execute(state)
        assert result["credibility"]["source_credibility"] == 0.95
        mock_source_auth_repo.get_or_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_priority_2_auto_calculated(
        self,
        mock_llm,
        mock_budget,
        mock_event_bus,
        mock_source_auth_repo,
        mock_source_config_repo,
        sample_raw,
    ):
        mock_source_config_repo.get_credibility = AsyncMock(return_value=None)
        mock_llm.call_at = AsyncMock(return_value=CredibilityOutput(score=0.7, flags=[]))
        node = CredibilityCheckerNode(
            llm=mock_llm,
            budget=mock_budget,
            event_bus=mock_event_bus,
            source_auth_repo=mock_source_auth_repo,
            source_config_repo=mock_source_config_repo,
        )
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {
            "title": sample_raw.title,
            "body": sample_raw.body,
            "publish_time": None,
        }
        result = await node.execute(state)
        assert result["credibility"]["source_credibility"] == 0.85
        mock_source_auth_repo.get_or_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_priority_3_default(self, mock_llm, mock_budget, mock_event_bus, sample_raw):
        mock_llm.call_at = AsyncMock(return_value=CredibilityOutput(score=0.7, flags=[]))
        node = CredibilityCheckerNode(
            llm=mock_llm,
            budget=mock_budget,
            event_bus=mock_event_bus,
            source_auth_repo=None,
            source_config_repo=None,
        )
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {
            "title": sample_raw.title,
            "body": sample_raw.body,
            "publish_time": None,
        }
        result = await node.execute(state)
        assert result["credibility"]["source_credibility"] == 0.50


class TestCredibilityCheckerNodeBasic:
    """Basic functionality tests for CredibilityCheckerNode."""

    @pytest.mark.asyncio
    async def test_credibility_successful_computation(
        self, mock_llm, mock_budget, mock_event_bus, mock_source_auth_repo, sample_raw
    ):
        mock_llm.call_at = AsyncMock(
            return_value=CredibilityOutput(score=0.75, flags=["well_sourced"])
        )
        node = CredibilityCheckerNode(
            llm=mock_llm,
            budget=mock_budget,
            event_bus=mock_event_bus,
            source_auth_repo=mock_source_auth_repo,
        )
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {
            "title": sample_raw.title,
            "body": sample_raw.body,
            "publish_time": sample_raw.publish_time,
        }
        state["summary_info"] = {"summary": "Test summary", "event_time": None}
        result = await node.execute(state)
        assert "credibility" in result
        assert 0.0 <= result["credibility"]["score"] <= 1.0
        assert "source_credibility" in result["credibility"]
        assert "content_check" in result["credibility"]
        assert "timeliness" in result["credibility"]
        assert "flags" in result["credibility"]

        assert "cross_verification" not in result["credibility"]
        assert "verified_by_sources" not in result["credibility"]

    @pytest.mark.asyncio
    async def test_credibility_publishes_event(
        self, mock_llm, mock_budget, mock_event_bus, mock_source_auth_repo, sample_raw
    ):
        mock_llm.call_at = AsyncMock(return_value=CredibilityOutput(score=0.8, flags=[]))
        node = CredibilityCheckerNode(
            llm=mock_llm,
            budget=mock_budget,
            event_bus=mock_event_bus,
            source_auth_repo=mock_source_auth_repo,
        )
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {
            "title": sample_raw.title,
            "body": sample_raw.body,
            "publish_time": None,
        }
        await node.execute(state)
        mock_event_bus.publish.assert_called_once()


class TestCredibilityCheckerNodeEdgeCases:
    """Edge case tests for CredibilityCheckerNode."""

    @pytest.mark.asyncio
    async def test_credibility_skips_terminal_state(
        self, mock_llm, mock_budget, mock_event_bus, sample_raw
    ):
        node = CredibilityCheckerNode(
            llm=mock_llm,
            budget=mock_budget,
            event_bus=mock_event_bus,
        )
        state = PipelineState(raw=sample_raw)
        state["terminal"] = True
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}
        result = await node.execute(state)
        assert "credibility" not in result
        mock_llm.call_at.assert_not_called()

    @pytest.mark.asyncio
    async def test_credibility_skips_merged_articles(
        self, mock_llm, mock_budget, mock_event_bus, sample_raw
    ):
        node = CredibilityCheckerNode(
            llm=mock_llm,
            budget=mock_budget,
            event_bus=mock_event_bus,
        )
        state = PipelineState(raw=sample_raw)
        state["is_merged"] = True
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}
        result = await node.execute(state)
        assert "credibility" not in result
        mock_llm.call_at.assert_not_called()

    @pytest.mark.asyncio
    async def test_credibility_without_source_repo(
        self, mock_llm, mock_budget, mock_event_bus, sample_raw
    ):
        mock_llm.call_at = AsyncMock(return_value=CredibilityOutput(score=0.7, flags=[]))
        node = CredibilityCheckerNode(
            llm=mock_llm,
            budget=mock_budget,
            event_bus=mock_event_bus,
            source_auth_repo=None,
        )
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {
            "title": sample_raw.title,
            "body": sample_raw.body,
            "publish_time": None,
        }
        result = await node.execute(state)
        assert result["credibility"]["source_credibility"] == 0.50


class TestCredibilityCheckerNodeErrorHandling:
    """Error handling tests for CredibilityCheckerNode."""

    @pytest.mark.asyncio
    async def test_credibility_handles_llm_error(
        self, mock_llm, mock_budget, mock_event_bus, sample_raw
    ):
        mock_llm.call_at = AsyncMock(side_effect=Exception("LLM service unavailable"))
        node = CredibilityCheckerNode(
            llm=mock_llm,
            budget=mock_budget,
            event_bus=mock_event_bus,
        )
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {
            "title": sample_raw.title,
            "body": sample_raw.body,
            "publish_time": None,
        }
        result = await node.execute(state)
        assert result["credibility"]["content_check"] == 0.5
        assert result["credibility"]["flags"] == []

    @pytest.mark.asyncio
    async def test_credibility_handles_source_repo_error(
        self, mock_llm, mock_budget, mock_event_bus, mock_source_auth_repo, sample_raw
    ):
        mock_source_auth_repo.get_or_create = AsyncMock(
            side_effect=Exception("Database connection failed")
        )
        mock_llm.call_at = AsyncMock(return_value=CredibilityOutput(score=0.7, flags=[]))
        node = CredibilityCheckerNode(
            llm=mock_llm,
            budget=mock_budget,
            event_bus=mock_event_bus,
            source_auth_repo=mock_source_auth_repo,
        )
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {
            "title": sample_raw.title,
            "body": sample_raw.body,
            "publish_time": None,
        }
        result = await node.execute(state)
        assert result["credibility"]["source_credibility"] == 0.50


class TestCredibilityCheckerNodeIntegration:
    """Integration tests for CredibilityCheckerNode."""

    @pytest.mark.asyncio
    async def test_credibility_weighted_aggregation_with_category(
        self, mock_llm, mock_budget, mock_event_bus, mock_source_auth_repo
    ):
        mock_source_auth_repo.get_or_create = AsyncMock(return_value=MagicMock(authority=1.0))
        mock_llm.call_at = AsyncMock(return_value=CredibilityOutput(score=1.0, flags=[]))
        node = CredibilityCheckerNode(
            llm=mock_llm,
            budget=mock_budget,
            event_bus=mock_event_bus,
            source_auth_repo=mock_source_auth_repo,
        )
        raw = ArticleRaw(
            url="https://example.com/test",
            title="Test",
            body="Test",
            source="test",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )
        state = PipelineState(raw=raw)
        state["cleaned"] = {
            "title": "Test",
            "body": "Test",
            "publish_time": datetime.now(UTC),
        }
        state["summary_info"] = {"event_time": datetime.now(UTC).isoformat()}
        state["category"] = "政治"

        result = await node.execute(state)
        # For 政治: source=0.25, content=0.25, timeliness=0.50
        # Expected: 1.0*0.25 + 1.0*0.25 + 1.0*0.50 = 1.0
        expected = 1.0 * 0.25 + 1.0 * 0.25 + 1.0 * 0.50
        assert abs(result["credibility"]["score"] - expected) < 0.01

    @pytest.mark.asyncio
    async def test_credibility_economic_category_weights(
        self, mock_llm, mock_budget, mock_event_bus, mock_source_auth_repo
    ):
        mock_source_auth_repo.get_or_create = AsyncMock(return_value=MagicMock(authority=0.90))
        mock_llm.call_at = AsyncMock(return_value=CredibilityOutput(score=0.50, flags=[]))
        node = CredibilityCheckerNode(
            llm=mock_llm,
            budget=mock_budget,
            event_bus=mock_event_bus,
            source_auth_repo=mock_source_auth_repo,
        )
        raw = ArticleRaw(
            url="https://example.com/economic",
            title="Market Update",
            body="Test",
            source="test",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )
        state = PipelineState(raw=raw)
        state["cleaned"] = {
            "title": "Market Update",
            "body": "Test",
            "publish_time": None,
        }
        state["category"] = "经济"
        result = await node.execute(state)
        # For 经济: source=0.45, content=0.35, timeliness=0.20
        # Expected: 0.90*0.45 + 0.50*0.35 + 0.70*0.20 = 0.72
        expected = 0.90 * 0.45 + 0.50 * 0.35 + 0.70 * 0.20
        assert abs(result["credibility"]["score"] - expected) < 0.01

    @pytest.mark.asyncio
    async def test_credibility_calls_llm_with_correct_params(
        self, mock_llm, mock_budget, mock_event_bus, sample_raw
    ):
        mock_llm.call_at = AsyncMock(return_value=CredibilityOutput(score=0.7, flags=[]))
        node = CredibilityCheckerNode(
            llm=mock_llm,
            budget=mock_budget,
            event_bus=mock_event_bus,
        )
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": "Test Title", "body": "Test Body", "publish_time": None}
        state["summary_info"] = {"summary": "Test Summary"}
        await node.execute(state)
        mock_llm.call_at.assert_called_once()
        call_args = mock_llm.call_at.call_args
        assert call_args[0][0] == CallPoint.CREDIBILITY_CHECKER
        input_data = call_args[0][1]
        assert input_data["title"] == "Test Title"
        assert "body" in input_data
        assert input_data["summary"] == "Test Summary"
