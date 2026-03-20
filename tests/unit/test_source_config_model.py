# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for SourceConfig model with new credibility and tier fields."""

import pytest

from modules.source.models import SourceConfig


class TestSourceConfigModel:
    """Tests for SourceConfig dataclass."""

    def test_create_source_config_with_defaults(self):
        """Test creating a SourceConfig with default values."""
        config = SourceConfig(
            id="test-source",
            name="Test Source",
            url="https://example.com/feed.xml",
        )

        assert config.id == "test-source"
        assert config.name == "Test Source"
        assert config.url == "https://example.com/feed.xml"
        assert config.source_type == "rss"
        assert config.enabled is True
        assert config.interval_minutes == 30
        assert config.per_host_concurrency == 2
        assert config.credibility is None
        assert config.tier is None

    def test_create_source_config_with_credibility(self):
        """Test creating a SourceConfig with preset credibility."""
        config = SourceConfig(
            id="reuters",
            name="Reuters",
            url="https://reuters.com/feed.xml",
            credibility=0.95,
            tier=1,
        )

        assert config.credibility == 0.95
        assert config.tier == 1

    def test_credibility_validation_lower_bound(self):
        """Test that credibility below 0.0 raises ValueError."""
        with pytest.raises(ValueError, match="credibility must be in range"):
            SourceConfig(
                id="test",
                name="Test",
                url="https://example.com",
                credibility=-0.1,
            )

    def test_credibility_validation_upper_bound(self):
        """Test that credibility above 1.0 raises ValueError."""
        with pytest.raises(ValueError, match="credibility must be in range"):
            SourceConfig(
                id="test",
                name="Test",
                url="https://example.com",
                credibility=1.1,
            )

    def test_credibility_validation_valid_min(self):
        """Test credibility at minimum valid value."""
        config = SourceConfig(
            id="test",
            name="Test",
            url="https://example.com",
            credibility=0.0,
        )
        assert config.credibility == 0.0

    def test_credibility_validation_valid_max(self):
        """Test credibility at maximum valid value."""
        config = SourceConfig(
            id="test",
            name="Test",
            url="https://example.com",
            credibility=1.0,
        )
        assert config.credibility == 1.0

    def test_tier_validation_lower_bound(self):
        """Test that tier below 1 raises ValueError."""
        with pytest.raises(ValueError, match="tier must be in range"):
            SourceConfig(
                id="test",
                name="Test",
                url="https://example.com",
                tier=0,
            )

    def test_tier_validation_upper_bound(self):
        """Test that tier above 3 raises ValueError."""
        with pytest.raises(ValueError, match="tier must be in range"):
            SourceConfig(
                id="test",
                name="Test",
                url="https://example.com",
                tier=4,
            )

    def test_tier_validation_valid_values(self):
        """Test valid tier values 1, 2, 3."""
        for tier in [1, 2, 3]:
            config = SourceConfig(
                id=f"test-{tier}",
                name=f"Test {tier}",
                url="https://example.com",
                tier=tier,
            )
            assert config.tier == tier

    def test_tier_semantic_meaning(self):
        """Test tier semantic meaning (1=authoritative, 2=credible, 3=ordinary)."""
        # Tier 1: Authoritative sources (e.g., major news agencies)
        authoritative = SourceConfig(
            id="xinhua",
            name="Xinhua",
            url="https://xinhua.com/feed.xml",
            credibility=0.98,
            tier=1,
        )
        assert authoritative.tier == 1

        # Tier 2: Credible sources (e.g., established media)
        credible = SourceConfig(
            id="sina",
            name="Sina News",
            url="https://sina.com/feed.xml",
            credibility=0.80,
            tier=2,
        )
        assert credible.tier == 2

        # Tier 3: Ordinary sources (e.g., blogs, aggregators)
        ordinary = SourceConfig(
            id="blog",
            name="Some Blog",
            url="https://blog.example.com/feed.xml",
            credibility=0.50,
            tier=3,
        )
        assert ordinary.tier == 3

    def test_optional_fields_can_be_none(self):
        """Test that credibility and tier can be None."""
        config = SourceConfig(
            id="test",
            name="Test",
            url="https://example.com",
            credibility=None,
            tier=None,
        )
        assert config.credibility is None
        assert config.tier is None
