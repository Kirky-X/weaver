# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Tests for TieredRouter threshold validation and documentation.

Verifies that TierConfig lists cover the full difficulty range (0.0-1.0)
without gaps, and that routing decisions are clear and documented.
"""

from __future__ import annotations

import pytest

from core.llm.routing.difficulty_estimator import DifficultyEstimator
from core.llm.routing.tiered_router import TieredRouter
from core.llm.types import TierConfig, describe_routing, validate_tiers

# ── TierConfig Validation ───────────────────────────────────────────


class TestTierConfigValidation:
    """Test validate_tiers() class method."""

    def test_valid_tiers_pass(self) -> None:
        """Tiers covering 0.0-1.0 with ascending max_difficulty should pass."""
        tiers = [
            TierConfig(label="chat.fast.classifier", max_difficulty=0.3),
            TierConfig(label="chat.medium.classifier", max_difficulty=0.7),
            TierConfig(label="chat.best.classifier", max_difficulty=1.0),
        ]
        errors = validate_tiers(tiers)
        assert errors == []

    def test_empty_tiers_pass(self) -> None:
        """Empty tiers list should pass (no tiers = no routing)."""
        errors = validate_tiers([])
        assert errors == []

    def test_single_tier_pass(self) -> None:
        """Single tier with max_difficulty=1.0 should pass."""
        tiers = [TierConfig(label="chat.default", max_difficulty=1.0)]
        errors = validate_tiers(tiers)
        assert errors == []

    def test_non_ascending_max_difficulty_fails(self) -> None:
        """Tiers with non-ascending max_difficulty should fail."""
        tiers = [
            TierConfig(label="chat.medium", max_difficulty=0.7),
            TierConfig(label="chat.fast", max_difficulty=0.3),
        ]
        errors = validate_tiers(tiers)
        assert len(errors) > 0
        assert any("ascending" in e.lower() or "non-ascending" in e.lower() for e in errors)

    def test_max_difficulty_out_of_range_fails(self) -> None:
        """Tiers with max_difficulty outside 0.0-1.0 should fail."""
        tiers = [
            TierConfig(label="chat.fast", max_difficulty=0.5),
            TierConfig(label="chat.best", max_difficulty=1.5),
        ]
        errors = validate_tiers(tiers)
        assert len(errors) > 0
        assert any("range" in e.lower() for e in errors)

    def test_duplicate_max_difficulty_fails(self) -> None:
        """Tiers with duplicate max_difficulty should fail."""
        tiers = [
            TierConfig(label="chat.fast", max_difficulty=0.5),
            TierConfig(label="chat.medium", max_difficulty=0.5),
            TierConfig(label="chat.best", max_difficulty=1.0),
        ]
        errors = validate_tiers(tiers)
        assert len(errors) > 0
        assert any("duplicate" in e.lower() for e in errors)

    def test_last_tier_not_1_warns(self) -> None:
        """Last tier with max_difficulty < 1.0 should generate a warning."""
        tiers = [
            TierConfig(label="chat.fast", max_difficulty=0.3),
            TierConfig(label="chat.medium", max_difficulty=0.7),
        ]
        errors = validate_tiers(tiers)
        assert len(errors) > 0
        assert any("1.0" in e or "coverage" in e.lower() for e in errors)


# ── TierConfig Describe Routing ─────────────────────────────────────


class TestTierConfigDescribeRouting:
    """Test describe_routing() method."""

    def test_describe_routing_returns_string(self) -> None:
        """describe_routing() should return a human-readable string."""
        tiers = [
            TierConfig(label="chat.fast.classifier", max_difficulty=0.3),
            TierConfig(label="chat.medium.classifier", max_difficulty=0.7),
            TierConfig(label="chat.best.classifier", max_difficulty=1.0),
        ]
        description = describe_routing(tiers)
        assert isinstance(description, str)
        assert "0.3" in description
        assert "0.7" in description
        assert "1.0" in description
        assert "chat.fast.classifier" in description

    def test_describe_empty_tiers(self) -> None:
        """describe_routing() with empty tiers should indicate no routing."""
        description = describe_routing([])
        assert "no tiers" in description.lower() or "empty" in description.lower()


# ── Routing Boundary Tests ──────────────────────────────────────────


class TestTieredRouterBoundaryRouting:
    """Test that difficulty boundary values route to correct tiers."""

    def _make_router(self) -> TieredRouter:
        """Create a TieredRouter with known tiers."""
        tiers = [
            TierConfig(label="chat.fast.classifier", max_difficulty=0.3),
            TierConfig(label="chat.medium.classifier", max_difficulty=0.7),
            TierConfig(label="chat.best.classifier", max_difficulty=1.0),
        ]
        return TieredRouter(
            estimator=DifficultyEstimator(),
            tiers=tiers,
        )

    def test_low_difficulty_routes_to_first_tier(self) -> None:
        """Difficulty 0.0 should route to first tier."""
        router = self._make_router()
        tier = router._find_tier("classifier", 0.0)
        assert tier is not None
        assert tier.label == "chat.fast.classifier"

    def test_boundary_below_threshold(self) -> None:
        """Difficulty just below 0.3 should route to first tier."""
        router = self._make_router()
        tier = router._find_tier("classifier", 0.29)
        assert tier is not None
        assert tier.label == "chat.fast.classifier"

    def test_boundary_at_threshold(self) -> None:
        """Difficulty at 0.3 should route to second tier (strict <)."""
        router = self._make_router()
        tier = router._find_tier("classifier", 0.3)
        assert tier is not None
        assert tier.label == "chat.medium.classifier"

    def test_medium_difficulty_routes_to_second_tier(self) -> None:
        """Difficulty 0.5 should route to second tier."""
        router = self._make_router()
        tier = router._find_tier("classifier", 0.5)
        assert tier is not None
        assert tier.label == "chat.medium.classifier"

    def test_high_difficulty_routes_to_last_tier(self) -> None:
        """Difficulty 0.9 should route to last tier."""
        router = self._make_router()
        tier = router._find_tier("classifier", 0.9)
        assert tier is not None
        assert tier.label == "chat.best.classifier"

    def test_max_difficulty_routes_to_last_tier(self) -> None:
        """Difficulty 1.0 should route to last tier (fallback)."""
        router = self._make_router()
        tier = router._find_tier("classifier", 1.0)
        assert tier is not None
        assert tier.label == "chat.best.classifier"

    def test_no_tiers_returns_none(self) -> None:
        """No tiers configured should return None."""
        router = TieredRouter(estimator=DifficultyEstimator())
        tier = router._find_tier("classifier", 0.5)
        assert tier is None


# ── Config-Driven Tiers ─────────────────────────────────────────────


class TestConfigDrivenTiers:
    """Test that tiers can be driven from configuration."""

    def test_tiers_from_config(self) -> None:
        """Tiers should be creatable from configuration dicts."""
        config_tiers = [
            {"label": "chat.fast.classifier", "max_difficulty": 0.3, "input_truncation": 512},
            {"label": "chat.medium.classifier", "max_difficulty": 0.7, "input_truncation": 2048},
            {"label": "chat.best.classifier", "max_difficulty": 1.0, "input_truncation": 8192},
        ]
        tiers = [TierConfig(**t) for t in config_tiers]
        assert len(tiers) == 3
        assert tiers[0].input_truncation == 512
        assert tiers[2].max_difficulty == 1.0

    def test_validate_config_tiers(self) -> None:
        """Config-driven tiers should pass validation."""
        config_tiers = [
            {"label": "chat.fast.classifier", "max_difficulty": 0.3},
            {"label": "chat.best.classifier", "max_difficulty": 1.0},
        ]
        tiers = [TierConfig(**t) for t in config_tiers]
        errors = validate_tiers(tiers)
        assert errors == []
