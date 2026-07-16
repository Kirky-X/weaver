# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for RuleBasedCredibilityCheckerNode — no LLM dependency."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.ingestion.domain.models import RawArticle
from modules.processing.nodes.classification.credibility_checker import (
    RuleBasedCredibilityCheckerNode,
)
from modules.processing.pipeline.state import PipelineState


@pytest.fixture
def sample_raw():
    return RawArticle(
        url="https://example.com/credible-article",
        title="Research Study Confirms New Treatment Efficacy",
        body="A " * 500,
        source="medical_journal",
        publish_time=datetime.now(UTC),
        source_host="example.com",
    )


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


class TestRuleBasedCredibilityCheckerBasic:
    """Basic functionality tests."""

    def test_no_llm_dependency(self):
        """Should not require LLMClient or any LLM dependency."""
        node = RuleBasedCredibilityCheckerNode()
        assert node is not None

    @pytest.mark.asyncio
    async def test_successful_execution(self, sample_raw, mock_event_bus, mock_source_auth_repo):
        """Should compute credibility and update state."""
        node = RuleBasedCredibilityCheckerNode(
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
        assert "cross_verification" in result["credibility"]
        assert "content_check" in result["credibility"]
        assert "timeliness" in result["credibility"]
        assert "flags" in result["credibility"]

    @pytest.mark.asyncio
    async def test_cross_verification_present(self, sample_raw, mock_event_bus):
        """Should include cross_verification in output."""
        node = RuleBasedCredibilityCheckerNode(event_bus=mock_event_bus)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {
            "title": sample_raw.title,
            "body": sample_raw.body,
            "publish_time": None,
        }
        result = await node.execute(state)
        assert "cross_verification" in result["credibility"]

    @pytest.mark.asyncio
    async def test_publishes_event(self, sample_raw, mock_event_bus, mock_source_auth_repo):
        """Should publish CredibilityComputedEvent."""
        node = RuleBasedCredibilityCheckerNode(
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

    @pytest.mark.asyncio
    async def test_handles_no_event_bus(self, sample_raw, mock_source_auth_repo):
        """Should work without event bus."""
        node = RuleBasedCredibilityCheckerNode(
            event_bus=None,
            source_auth_repo=mock_source_auth_repo,
        )
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {
            "title": sample_raw.title,
            "body": sample_raw.body,
            "publish_time": None,
        }

        result = await node.execute(state)

        assert "credibility" in result


class TestRuleBasedCredibilityCrossVerification:
    """Tests for body-length-based cross-verification (replaces LLM content check)."""

    @pytest.mark.asyncio
    async def test_long_body_high_score(self, sample_raw, mock_event_bus):
        """Body > 3000 chars should give cross_verification = 0.8."""
        node = RuleBasedCredibilityCheckerNode(event_bus=mock_event_bus)
        state = PipelineState(raw=sample_raw)
        body = "A " * 1600
        assert len(body) > 3000
        state["cleaned"] = {"title": "Test", "body": body, "publish_time": None}

        result = await node.execute(state)

        assert result["credibility"]["cross_verification"] == 0.8
        assert result["credibility"]["content_check"] == 0.8

    @pytest.mark.asyncio
    async def test_medium_body_medium_score(self, sample_raw, mock_event_bus):
        """Body between 1000-3000 chars should give cross_verification = 0.6."""
        node = RuleBasedCredibilityCheckerNode(event_bus=mock_event_bus)
        state = PipelineState(raw=sample_raw)
        body = "A " * 600
        assert 1000 < len(body) <= 3000
        state["cleaned"] = {"title": "Test", "body": body, "publish_time": None}

        result = await node.execute(state)

        assert result["credibility"]["cross_verification"] == 0.6
        assert result["credibility"]["content_check"] == 0.6

    @pytest.mark.asyncio
    async def test_short_body_low_score(self, sample_raw, mock_event_bus):
        """Body <= 1000 chars should give cross_verification = 0.4."""
        node = RuleBasedCredibilityCheckerNode(event_bus=mock_event_bus)
        state = PipelineState(raw=sample_raw)
        body = "Short body text"
        assert len(body) <= 1000
        state["cleaned"] = {"title": "Test", "body": body, "publish_time": None}

        result = await node.execute(state)

        assert result["credibility"]["cross_verification"] == 0.4
        assert result["credibility"]["content_check"] == 0.4

    @pytest.mark.asyncio
    async def test_empty_body_low_score(self, sample_raw, mock_event_bus):
        """Empty body should give cross_verification = 0.4."""
        node = RuleBasedCredibilityCheckerNode(event_bus=mock_event_bus)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": "Test", "body": "", "publish_time": None}

        result = await node.execute(state)

        assert result["credibility"]["cross_verification"] == 0.4


class TestSourceAuthorityPriority:
    """Tests for three-level priority source authority lookup."""

    @pytest.mark.asyncio
    async def test_priority_1_preset_credibility(
        self,
        sample_raw,
        mock_event_bus,
        mock_source_auth_repo,
        mock_source_config_repo,
    ):
        """Preset credibility from SourceConfig should take priority 1."""
        mock_source_config_repo.get_credibility = AsyncMock(return_value=0.95)

        node = RuleBasedCredibilityCheckerNode(
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
        sample_raw,
        mock_event_bus,
        mock_source_auth_repo,
        mock_source_config_repo,
    ):
        """Auto-calculated authority from SourceAuthorityRepo should be priority 2."""
        mock_source_config_repo.get_credibility = AsyncMock(return_value=None)

        node = RuleBasedCredibilityCheckerNode(
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
    async def test_priority_3_default(self, sample_raw, mock_event_bus):
        """No repos should give default score 0.50."""
        node = RuleBasedCredibilityCheckerNode(event_bus=mock_event_bus)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {
            "title": sample_raw.title,
            "body": sample_raw.body,
            "publish_time": None,
        }
        result = await node.execute(state)

        assert result["credibility"]["source_credibility"] == 0.50


class TestCalcTimeliness:
    """Tests for _calc_timeliness static method."""

    def test_timeliness_within_6_hours(self):
        publish_time = datetime.now(UTC)
        event_time = (publish_time - timedelta(hours=3)).isoformat()
        score = RuleBasedCredibilityCheckerNode._calc_timeliness(publish_time, event_time)
        assert score == 1.00

    def test_timeliness_within_24_hours(self):
        publish_time = datetime.now(UTC)
        event_time = (publish_time - timedelta(hours=12)).isoformat()
        score = RuleBasedCredibilityCheckerNode._calc_timeliness(publish_time, event_time)
        assert score == 0.85

    def test_timeliness_within_72_hours(self):
        publish_time = datetime.now(UTC)
        event_time = (publish_time - timedelta(hours=48)).isoformat()
        score = RuleBasedCredibilityCheckerNode._calc_timeliness(publish_time, event_time)
        assert score == 0.65

    def test_timeliness_within_week(self):
        publish_time = datetime.now(UTC)
        event_time = (publish_time - timedelta(hours=100)).isoformat()
        score = RuleBasedCredibilityCheckerNode._calc_timeliness(publish_time, event_time)
        assert score == 0.45

    def test_timeliness_older_than_week(self):
        publish_time = datetime.now(UTC)
        event_time = (publish_time - timedelta(hours=200)).isoformat()
        score = RuleBasedCredibilityCheckerNode._calc_timeliness(publish_time, event_time)
        assert score == 0.30

    def test_timeliness_missing_publish_time(self):
        event_time = datetime.now(UTC).isoformat()
        score = RuleBasedCredibilityCheckerNode._calc_timeliness(None, event_time)
        assert score == 0.7

    def test_timeliness_missing_event_time(self):
        publish_time = datetime.now(UTC)
        score = RuleBasedCredibilityCheckerNode._calc_timeliness(publish_time, None)
        assert score == 0.7

    def test_timeliness_invalid_event_time(self):
        publish_time = datetime.now(UTC)
        score = RuleBasedCredibilityCheckerNode._calc_timeliness(publish_time, "invalid-date")
        assert score == 0.7


class TestCategoryWeights:
    """Tests for category-adaptive weight selection."""

    def test_breaking_news_weights(self):
        for category in ["政治", "国际", "军事"]:
            weights = RuleBasedCredibilityCheckerNode.CATEGORY_WEIGHTS.get(
                category, RuleBasedCredibilityCheckerNode.DEFAULT_WEIGHTS
            )
            assert weights["timeliness"] == 0.50
            assert weights["source"] == 0.25
            assert weights["content"] == 0.25

    def test_economic_news_weights(self):
        weights = RuleBasedCredibilityCheckerNode.CATEGORY_WEIGHTS.get(
            "经济", RuleBasedCredibilityCheckerNode.DEFAULT_WEIGHTS
        )
        assert weights["source"] == 0.45
        assert weights["content"] == 0.35
        assert weights["timeliness"] == 0.20

    def test_tech_news_weights(self):
        weights = RuleBasedCredibilityCheckerNode.CATEGORY_WEIGHTS.get(
            "科技", RuleBasedCredibilityCheckerNode.DEFAULT_WEIGHTS
        )
        assert weights["content"] == 0.50
        assert weights["source"] == 0.30
        assert weights["timeliness"] == 0.20

    def test_default_weights(self):
        for category in ["社会", "文化", "体育"]:
            weights = RuleBasedCredibilityCheckerNode.CATEGORY_WEIGHTS.get(
                category, RuleBasedCredibilityCheckerNode.DEFAULT_WEIGHTS
            )
            assert weights["source"] == 0.40
            assert weights["content"] == 0.40
            assert weights["timeliness"] == 0.20

    def test_unknown_category_uses_default(self):
        weights = RuleBasedCredibilityCheckerNode.CATEGORY_WEIGHTS.get(
            "unknown_category", RuleBasedCredibilityCheckerNode.DEFAULT_WEIGHTS
        )
        assert weights == RuleBasedCredibilityCheckerNode.DEFAULT_WEIGHTS

    def test_all_weights_sum_to_one(self):
        for category, weights in RuleBasedCredibilityCheckerNode.CATEGORY_WEIGHTS.items():
            total = sum(weights.values())
            assert abs(total - 1.0) < 0.001, f"Weights for {category} don't sum to 1.0: {total}"


class TestRuleBasedCredibilityEdgeCases:
    """Edge case tests."""

    @pytest.mark.asyncio
    async def test_skips_terminal_state(self, sample_raw, mock_event_bus):
        node = RuleBasedCredibilityCheckerNode(event_bus=mock_event_bus)
        state = PipelineState(raw=sample_raw)
        state["terminal"] = True
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}
        result = await node.execute(state)
        assert "credibility" not in result

    @pytest.mark.asyncio
    async def test_skips_merged_articles(self, sample_raw, mock_event_bus):
        node = RuleBasedCredibilityCheckerNode(event_bus=mock_event_bus)
        state = PipelineState(raw=sample_raw)
        state["is_merged"] = True
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}
        result = await node.execute(state)
        assert "credibility" not in result

    @pytest.mark.asyncio
    async def test_without_source_repo(self, sample_raw, mock_event_bus):
        node = RuleBasedCredibilityCheckerNode(event_bus=mock_event_bus)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {
            "title": sample_raw.title,
            "body": sample_raw.body,
            "publish_time": None,
        }
        result = await node.execute(state)
        assert result["credibility"]["source_credibility"] == 0.50

    @pytest.mark.asyncio
    async def test_handles_source_repo_error(
        self, sample_raw, mock_event_bus, mock_source_auth_repo
    ):
        mock_source_auth_repo.get_or_create = AsyncMock(
            side_effect=Exception("Database connection failed")
        )
        node = RuleBasedCredibilityCheckerNode(
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


class TestRuleBasedCredibilityHighAuthority:
    """Tests for high-authority source scoring."""

    @pytest.mark.asyncio
    async def test_high_authority_source_high_score(
        self, sample_raw, mock_event_bus, mock_source_auth_repo
    ):
        mock_source_auth_repo.get_or_create = AsyncMock(return_value=MagicMock(authority=0.90))
        node = RuleBasedCredibilityCheckerNode(
            event_bus=mock_event_bus,
            source_auth_repo=mock_source_auth_repo,
        )
        state = PipelineState(raw=sample_raw)
        long_body = "A " * 1600
        assert len(long_body) > 3000
        state["cleaned"] = {
            "title": sample_raw.title,
            "body": long_body,
            "publish_time": sample_raw.publish_time,
        }
        state["summary_info"] = {"event_time": (datetime.now(UTC) - timedelta(hours=3)).isoformat()}

        result = await node.execute(state)

        assert result["credibility"]["source_credibility"] == 0.90
        assert result["credibility"]["score"] >= 0.80

    @pytest.mark.asyncio
    async def test_low_quality_content_penalty(self, sample_raw, mock_event_bus):
        node = RuleBasedCredibilityCheckerNode(event_bus=mock_event_bus)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {
            "title": sample_raw.title,
            "body": "",
            "publish_time": None,
        }

        result = await node.execute(state)

        assert result["credibility"]["cross_verification"] == 0.4
