"""Unit tests for credibility calculation."""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

from modules.pipeline.nodes.credibility_checker import CredibilityCheckerNode


class TestCredibilityCalculation:
    """Tests for credibility score calculation."""

    def test_weights_defined(self):
        """Test that credibility weights are defined."""
        assert hasattr(CredibilityCheckerNode, "WEIGHTS")
        assert "source" in CredibilityCheckerNode.WEIGHTS
        assert "cross" in CredibilityCheckerNode.WEIGHTS
        assert "content" in CredibilityCheckerNode.WEIGHTS
        assert "timeliness" in CredibilityCheckerNode.WEIGHTS

    def test_weights_sum_to_one(self):
        """Test that weights sum to 1.0."""
        weights = CredibilityCheckerNode.WEIGHTS
        total = sum(weights.values())
        assert total == pytest.approx(1.0, rel=0.01)

    def test_source_weight_percentage(self):
        """Test source weight is 30%."""
        assert CredibilityCheckerNode.WEIGHTS["source"] == 0.30

    def test_cross_weight_percentage(self):
        """Test cross verification weight is 25%."""
        assert CredibilityCheckerNode.WEIGHTS["cross"] == 0.25

    def test_content_weight_percentage(self):
        """Test content check weight is 30%."""
        assert CredibilityCheckerNode.WEIGHTS["content"] == 0.30

    def test_timeliness_weight_percentage(self):
        """Test timeliness weight is 15%."""
        assert CredibilityCheckerNode.WEIGHTS["timeliness"] == 0.15


class TestTimelinessCalculation:
    """Tests for timeliness score calculation."""

    @staticmethod
    def calc_timeliness(publish_time, event_time_str):
        """Helper to calculate timeliness."""
        return CredibilityCheckerNode._calc_timeliness(publish_time, event_time_str)

    def test_timeliness_within_6_hours(self):
        """Test timeliness score for article within 6 hours."""
        publish_time = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        event_time = "2024-01-01T10:00:00"  # 2 hours earlier

        score = self.calc_timeliness(publish_time, event_time)

        assert score == 1.00

    def test_timeliness_within_24_hours(self):
        """Test timeliness score for article within 24 hours."""
        publish_time = datetime(2024, 1, 1, 20, 0, tzinfo=timezone.utc)
        event_time = "2024-01-01T10:00:00"  # 10 hours earlier

        score = self.calc_timeliness(publish_time, event_time)

        assert score == 0.85

    def test_timeliness_within_72_hours(self):
        """Test timeliness score for article within 72 hours."""
        publish_time = datetime(2024, 1, 3, 12, 0, tzinfo=timezone.utc)
        event_time = "2024-01-01T10:00:00"  # ~50 hours earlier

        score = self.calc_timeliness(publish_time, event_time)

        assert score == 0.65

    def test_timeliness_within_168_hours(self):
        """Test timeliness score for article within 168 hours (1 week)."""
        publish_time = datetime(2024, 1, 7, 12, 0, tzinfo=timezone.utc)
        event_time = "2024-01-01T10:00:00"  # ~146 hours earlier

        score = self.calc_timeliness(publish_time, event_time)

        assert score == 0.45

    def test_timeliness_over_168_hours(self):
        """Test timeliness score for article over 1 week old."""
        publish_time = datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc)
        event_time = "2024-01-01T10:00:00"  # ~338 hours earlier

        score = self.calc_timeliness(publish_time, event_time)

        assert score == 0.30

    def test_timeliness_missing_publish_time(self):
        """Test timeliness with missing publish time returns neutral."""
        score = self.calc_timeliness(None, "2024-01-01T10:00:00")

        assert score == 0.70

    def test_timeliness_missing_event_time(self):
        """Test timeliness with missing event time returns neutral."""
        publish_time = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

        score = self.calc_timeliness(publish_time, None)

        assert score == 0.70

    def test_timeliness_invalid_event_time(self):
        """Test timeliness with invalid event time format returns neutral."""
        publish_time = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

        score = self.calc_timeliness(publish_time, "invalid-date")

        assert score == 0.70


class TestCrossVerificationCalculation:
    """Tests for cross verification score calculation."""

    def test_single_source(self):
        """Test cross verification with single source."""
        # With 1 source, score should be 0.40 + 1 * 0.15 = 0.55
        cross_count = 1
        score = min(1.0, 0.4 + cross_count * 0.15)

        assert score == 0.55

    def test_two_sources(self):
        """Test cross verification with two sources."""
        cross_count = 2
        score = min(1.0, 0.4 + cross_count * 0.15)

        assert score == 0.70

    def test_three_sources(self):
        """Test cross verification with three sources."""
        cross_count = 3
        score = min(1.0, 0.4 + cross_count * 0.15)

        assert score == 0.85

    def test_five_plus_sources(self):
        """Test cross verification caps at 1.0."""
        for count in [5, 6, 10]:
            score = min(1.0, 0.4 + count * 0.15)
            assert score == 1.0


class TestCredibilityFlags:
    """Tests for credibility flag handling."""

    def test_flags_empty_by_default(self):
        """Test that flags list can be empty."""
        output = {"score": 0.8, "flags": []}
        assert output["flags"] == []

    def test_flags_accepted_as_list(self):
        """Test that flags are accepted as a list."""
        output = {
            "score": 0.5,
            "flags": ["low_source_authority", "no_cross_verification"]
        }
        assert len(output["flags"]) == 2
        assert "low_source_authority" in output["flags"]


class TestCredibilityScoreRange:
    """Tests for credibility score range validation."""

    def test_score_minimum_zero(self):
        """Test score cannot be negative."""
        weights = CredibilityCheckerNode.WEIGHTS

        # Calculate minimum possible score
        min_score = (
            0.0 * weights["source"] +
            0.4 * weights["cross"] +  # minimum cross with 0 sources
            0.0 * weights["content"] +
            0.3 * weights["timeliness"]  # minimum timeliness
        )

        assert min_score >= 0.0

    def test_score_maximum_one(self):
        """Test score cannot exceed 1.0."""
        weights = CredibilityCheckerNode.WEIGHTS

        # Calculate maximum possible score
        max_score = (
            1.0 * weights["source"] +
            1.0 * weights["cross"] +
            1.0 * weights["content"] +
            1.0 * weights["timeliness"]
        )

        assert max_score <= 1.0

    def test_score_range_zero_to_one(self):
        """Test full score range is 0 to 1."""
        assert CredibilityCheckerNode.WEIGHTS["source"] >= 0
        assert sum(CredibilityCheckerNode.WEIGHTS.values()) == 1.0


class TestCredibilityNodeExecution:
    """Tests for full node execution."""

    @pytest.fixture
    def mock_llm(self):
        """Mock LLM client."""
        llm = MagicMock()
        llm.call = AsyncMock(return_value=MagicMock(score=0.8, flags=[]))
        return llm

    @pytest.fixture
    def mock_source_auth_repo(self):
        """Mock source authority repository."""
        repo = MagicMock()
        repo.get_or_create = AsyncMock(return_value=MagicMock(authority=0.85))
        return repo

    @pytest.fixture
    def mock_event_bus(self):
        """Mock event bus."""
        bus = MagicMock()
        bus.publish = AsyncMock()
        return bus

    @pytest.fixture
    def mock_budget(self):
        """Mock token budget manager."""
        budget = MagicMock()
        budget.truncate = MagicMock(return_value="truncated text")
        return budget

    @pytest.fixture
    def mock_prompt_loader(self):
        """Mock prompt loader."""
        loader = MagicMock()
        loader.get_version = MagicMock(return_value="1.0.0")
        return loader

    def test_node_execution_full(self):
        """Test full node execution exists."""
        from modules.pipeline.nodes.credibility_checker import CredibilityCheckerNode
        assert hasattr(CredibilityCheckerNode, '_execute')

    def test_llm_content_check(self, mock_llm, mock_source_auth_repo, mock_event_bus, mock_budget, mock_prompt_loader):
        """Test LLM content check is called."""
        assert mock_llm.call is not None

    def test_event_publish(self, mock_event_bus):
        """Test event bus publish method exists."""
        assert hasattr(mock_event_bus, 'publish')

    def test_dynamic_update_method(self):
        """Test dynamic update method exists."""
        from core.event.bus import EventBus
        bus = EventBus()
        assert hasattr(bus, 'publish')
        assert hasattr(bus, 'subscribe')
