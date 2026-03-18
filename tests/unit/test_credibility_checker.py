# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for CredibilityCheckerNode."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.llm.output_validator import CredibilityOutput
from core.llm.types import CallPoint
from modules.collector.models import ArticleRaw
from modules.pipeline.nodes.credibility_checker import CredibilityCheckerNode
from modules.pipeline.state import PipelineState


@pytest.fixture
def sample_raw():
    """Create sample raw article."""
    return ArticleRaw(
        url="https://example.com/credible-article",
        title="Research Study Confirms New Treatment Efficacy",
        body="A comprehensive research study has confirmed the efficacy of a new treatment. "
        "Multiple independent studies have verified these findings.",
        source="medical_journal",
        publish_time=datetime.now(UTC),
        source_host="example.com",
    )


@pytest.fixture
def mock_llm():
    """Mock LLM client."""
    return AsyncMock()


@pytest.fixture
def mock_budget():
    """Mock token budget manager."""
    budget = MagicMock()
    budget.truncate = lambda text, call_point: text
    return budget


@pytest.fixture
def mock_event_bus():
    """Mock event bus."""
    bus = MagicMock()
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def mock_source_auth_repo():
    """Mock source authority repository."""
    repo = AsyncMock()
    mock_auth = MagicMock()
    mock_auth.authority = 0.85
    repo.get_or_create = AsyncMock(return_value=mock_auth)
    return repo


class TestCalcTimeliness:
    """Tests for _calc_timeliness static method."""

    def test_timeliness_within_6_hours(self):
        """Test timeliness score for events within 6 hours."""
        publish_time = datetime.now(UTC)
        event_time = (publish_time - timedelta(hours=3)).isoformat()

        score = CredibilityCheckerNode._calc_timeliness(publish_time, event_time)
        assert score == 1.00

    def test_timeliness_within_24_hours(self):
        """Test timeliness score for events within 24 hours."""
        publish_time = datetime.now(UTC)
        event_time = (publish_time - timedelta(hours=12)).isoformat()

        score = CredibilityCheckerNode._calc_timeliness(publish_time, event_time)
        assert score == 0.85

    def test_timeliness_within_72_hours(self):
        """Test timeliness score for events within 72 hours."""
        publish_time = datetime.now(UTC)
        event_time = (publish_time - timedelta(hours=48)).isoformat()

        score = CredibilityCheckerNode._calc_timeliness(publish_time, event_time)
        assert score == 0.65

    def test_timeliness_within_week(self):
        """Test timeliness score for events within a week."""
        publish_time = datetime.now(UTC)
        event_time = (publish_time - timedelta(hours=100)).isoformat()

        score = CredibilityCheckerNode._calc_timeliness(publish_time, event_time)
        assert score == 0.45

    def test_timeliness_older_than_week(self):
        """Test timeliness score for events older than a week."""
        publish_time = datetime.now(UTC)
        event_time = (publish_time - timedelta(hours=200)).isoformat()

        score = CredibilityCheckerNode._calc_timeliness(publish_time, event_time)
        assert score == 0.30

    def test_timeliness_missing_publish_time(self):
        """Test timeliness with missing publish time."""
        event_time = datetime.now(UTC).isoformat()
        score = CredibilityCheckerNode._calc_timeliness(None, event_time)
        assert score == 0.7

    def test_timeliness_missing_event_time(self):
        """Test timeliness with missing event time."""
        publish_time = datetime.now(UTC)
        score = CredibilityCheckerNode._calc_timeliness(publish_time, None)
        assert score == 0.7

    def test_timeliness_invalid_event_time(self):
        """Test timeliness with invalid event time format."""
        publish_time = datetime.now(UTC)
        score = CredibilityCheckerNode._calc_timeliness(publish_time, "invalid-date")
        assert score == 0.7

    def test_timeliness_future_event(self):
        """Test timeliness with future event time."""
        publish_time = datetime.now(UTC)
        event_time = (publish_time + timedelta(hours=10)).isoformat()

        score = CredibilityCheckerNode._calc_timeliness(publish_time, event_time)
        assert score == 0.85  # 10 hours gap


class TestCredibilityCheckerNodeBasic:
    """Basic functionality tests for CredibilityCheckerNode."""

    @pytest.mark.asyncio
    async def test_credibility_successful_computation(
        self, mock_llm, mock_budget, mock_event_bus, mock_source_auth_repo, sample_raw
    ):
        """Test successful credibility computation with all signals."""
        mock_llm.call = AsyncMock(
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

        # Verify credibility dict is set
        assert "credibility" in result
        assert 0.0 <= result["credibility"]["score"] <= 1.0
        assert "source_credibility" in result["credibility"]
        assert "cross_verification" in result["credibility"]
        assert "content_check" in result["credibility"]
        assert "timeliness" in result["credibility"]
        assert "flags" in result["credibility"]

    @pytest.mark.asyncio
    async def test_credibility_publishes_event(
        self, mock_llm, mock_budget, mock_event_bus, mock_source_auth_repo, sample_raw
    ):
        """Test that credibility checker publishes CredibilityComputedEvent."""
        mock_llm.call = AsyncMock(return_value=CredibilityOutput(score=0.8, flags=[]))

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

        # Verify event was published
        mock_event_bus.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_credibility_without_source_repo(
        self, mock_llm, mock_budget, mock_event_bus, sample_raw
    ):
        """Test credibility computation without source authority repository."""
        mock_llm.call = AsyncMock(return_value=CredibilityOutput(score=0.7, flags=[]))

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

        # Should use default source score of 0.50
        assert result["credibility"]["source_credibility"] == 0.50


class TestCredibilityCheckerNodeEdgeCases:
    """Edge case tests for CredibilityCheckerNode."""

    @pytest.mark.asyncio
    async def test_credibility_skips_terminal_state(
        self, mock_llm, mock_budget, mock_event_bus, sample_raw
    ):
        """Test that credibility checker skips terminal articles."""
        node = CredibilityCheckerNode(
            llm=mock_llm,
            budget=mock_budget,
            event_bus=mock_event_bus,
        )
        state = PipelineState(raw=sample_raw)
        state["terminal"] = True
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        # Should return state unchanged
        assert "credibility" not in result
        mock_llm.call.assert_not_called()

    @pytest.mark.asyncio
    async def test_credibility_skips_merged_articles(
        self, mock_llm, mock_budget, mock_event_bus, sample_raw
    ):
        """Test that credibility checker skips merged articles."""
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
        mock_llm.call.assert_not_called()

    @pytest.mark.asyncio
    async def test_credibility_with_cross_verification(
        self, mock_llm, mock_budget, mock_event_bus, sample_raw
    ):
        """Test credibility with cross-verification from merged sources."""
        mock_llm.call = AsyncMock(return_value=CredibilityOutput(score=0.7, flags=[]))

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
        state["merged_source_ids"] = ["source1", "source2", "source3"]

        result = await node.execute(state)

        # Cross-verification should boost score
        assert result["credibility"]["cross_verification"] > 0.4
        assert result["credibility"]["verified_by_sources"] == 3


class TestCredibilityCheckerNodeErrorHandling:
    """Error handling tests for CredibilityCheckerNode."""

    @pytest.mark.asyncio
    async def test_credibility_handles_llm_error(
        self, mock_llm, mock_budget, mock_event_bus, sample_raw
    ):
        """Test that credibility checker handles LLM errors gracefully."""
        mock_llm.call = AsyncMock(side_effect=Exception("LLM service unavailable"))

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

        # Should use default LLM score of 0.5
        assert result["credibility"]["content_check"] == 0.5
        assert result["credibility"]["flags"] == []

    @pytest.mark.asyncio
    async def test_credibility_handles_source_repo_error(
        self, mock_llm, mock_budget, mock_event_bus, mock_source_auth_repo, sample_raw
    ):
        """Test that credibility checker handles source repo errors."""
        mock_source_auth_repo.get_or_create = AsyncMock(
            side_effect=Exception("Database connection failed")
        )
        mock_llm.call = AsyncMock(return_value=CredibilityOutput(score=0.7, flags=[]))

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

        # Should use default source score
        assert result["credibility"]["source_credibility"] == 0.50


class TestCredibilityCheckerNodeIntegration:
    """Integration tests for CredibilityCheckerNode."""

    @pytest.mark.asyncio
    async def test_credibility_weighted_aggregation(
        self, mock_llm, mock_budget, mock_event_bus, mock_source_auth_repo
    ):
        """Test that credibility score is correctly weighted."""
        # Set up known values for each signal
        mock_source_auth_repo.get_or_create = AsyncMock(
            return_value=MagicMock(authority=1.0)  # s1 = 1.0
        )
        mock_llm.call = AsyncMock(return_value=CredibilityOutput(score=1.0, flags=[]))  # s3 = 1.0

        node = CredibilityCheckerNode(
            llm=mock_llm,
            budget=mock_budget,
            event_bus=mock_event_bus,
            source_auth_repo=mock_source_auth_repo,
        )

        # Create state with cross-verification (s2 will be 0.85 with 3 sources)
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
        state["summary_info"] = {"event_time": datetime.now(UTC).isoformat()}  # s4 = 1.0
        state["merged_source_ids"] = ["a", "b", "c"]  # s2 = 0.85

        result = await node.execute(state)

        # Manually calculate expected score
        expected = (
            1.0 * 0.30  # source
            + 0.85 * 0.25  # cross
            + 1.0 * 0.30  # content
            + 1.0 * 0.15  # timeliness
        )

        assert abs(result["credibility"]["score"] - expected) < 0.01

    @pytest.mark.asyncio
    async def test_credibility_calls_llm_with_correct_params(
        self, mock_llm, mock_budget, mock_event_bus, sample_raw
    ):
        """Test that credibility checker calls LLM with correct parameters."""
        mock_llm.call = AsyncMock(return_value=CredibilityOutput(score=0.7, flags=[]))

        node = CredibilityCheckerNode(
            llm=mock_llm,
            budget=mock_budget,
            event_bus=mock_event_bus,
        )
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": "Test Title", "body": "Test Body", "publish_time": None}
        state["summary_info"] = {"summary": "Test Summary"}

        await node.execute(state)

        # Verify LLM was called with correct CallPoint
        mock_llm.call.assert_called_once()
        call_args = mock_llm.call.call_args
        assert call_args[0][0] == CallPoint.CREDIBILITY_CHECKER

        # Verify input data
        input_data = call_args[0][1]
        assert input_data["title"] == "Test Title"
        assert "body" in input_data
        assert input_data["summary"] == "Test Summary"
