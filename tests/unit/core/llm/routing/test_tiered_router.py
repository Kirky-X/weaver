# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for TieredRouter: difficulty-based tiered LLM routing with Provider labels."""

from __future__ import annotations

import pytest

from core.llm.routing.tiered_router import TierConfig, TieredRouter


@pytest.fixture
def router() -> TieredRouter:
    return TieredRouter()


class TestRouteReturnsProviderLabels:
    """route() SHALL return concrete Provider labels, not abstract tier strings."""

    def test_classifier_easy_routes_to_fasttext(self, router: TieredRouter) -> None:
        """difficulty < 0.3 → fastText provider."""
        label = router.route(call_point="classifier", difficulty=0.2)
        assert label == "fastText"

    def test_classifier_medium_routes_to_ollama(self, router: TieredRouter) -> None:
        """0.3 <= difficulty < 0.7 → ollama provider."""
        label = router.route(call_point="classifier", difficulty=0.5)
        assert label == "ollama.gemma4:e4b"

    def test_classifier_hard_routes_to_cloud(self, router: TieredRouter) -> None:
        """difficulty >= 0.7 → cloud provider."""
        label = router.route(call_point="classifier", difficulty=0.8)
        assert label == "aiping.GLM-4-9B"

    def test_no_abstract_tier_strings(self, router: TieredRouter) -> None:
        """route() MUST NOT return abstract tier strings like 'fast', 'local', 'cloud'."""
        abstract_tiers = {"fast", "local", "cloud"}
        for cp in ("classifier", "categorizer", "analyze", "entity_extractor"):
            for d in (0.1, 0.5, 0.9):
                result = router.route(call_point=cp, difficulty=d)
                assert (
                    result not in abstract_tiers
                ), f"route('{cp}', {d}) returned abstract tier '{result}'"


class TestTiersListStructure:
    """Routing table SHALL use tiers list structure with backend/max_difficulty/provider."""

    def test_tiers_is_list(self, router: TieredRouter) -> None:
        """ROUTING_TABLE entries SHALL contain tiers as list."""
        for cp, config in router.ROUTING_TABLE.items():
            assert "tiers" in config, f"Missing 'tiers' in ROUTING_TABLE['{cp}']"
            assert isinstance(
                config["tiers"], list
            ), f"ROUTING_TABLE['{cp}']['tiers'] must be a list"

    def test_tier_entry_has_required_fields(self, router: TieredRouter) -> None:
        """Each tier entry SHALL contain backend, max_difficulty, provider."""
        for cp, config in router.ROUTING_TABLE.items():
            for i, tier in enumerate(config["tiers"]):
                assert "backend" in tier, f"ROUTING_TABLE['{cp}']['tiers'][{i}] missing 'backend'"
                assert (
                    "max_difficulty" in tier
                ), f"ROUTING_TABLE['{cp}']['tiers'][{i}] missing 'max_difficulty'"
                assert "provider" in tier, f"ROUTING_TABLE['{cp}']['tiers'][{i}] missing 'provider'"

    def test_tiers_max_difficulty_ascending(self, router: TieredRouter) -> None:
        """tiers list SHALL have max_difficulty in ascending order."""
        for cp, config in router.ROUTING_TABLE.items():
            difficulties = [t["max_difficulty"] for t in config["tiers"]]
            assert difficulties == sorted(
                difficulties
            ), f"ROUTING_TABLE['{cp}'] tiers not sorted by max_difficulty"

    def test_last_tier_max_difficulty_is_one(self, router: TieredRouter) -> None:
        """Last tier's max_difficulty SHALL be 1.0 (catches all remaining)."""
        for cp, config in router.ROUTING_TABLE.items():
            last = config["tiers"][-1]
            assert (
                last["max_difficulty"] == 1.0
            ), f"ROUTING_TABLE['{cp}'] last tier max_difficulty={last['max_difficulty']}, expected 1.0"

    def test_custom_tiers_routing(self) -> None:
        """Custom tiers config routes correctly by max_difficulty boundaries."""
        custom_router = TieredRouter(
            tiers=[
                TierConfig(backend="fastText", max_difficulty=0.3, provider={"model": "fasttext"}),
                TierConfig(
                    backend="ollama.gemma4:e4b", max_difficulty=0.7, provider={"model": "gemma4"}
                ),
                TierConfig(
                    backend="aiping.GLM-4-9B", max_difficulty=1.0, provider={"model": "glm4"}
                ),
            ]
        )
        assert custom_router.route(call_point="any", difficulty=0.2) == "fastText"
        assert custom_router.route(call_point="any", difficulty=0.3) == "ollama.gemma4:e4b"
        assert custom_router.route(call_point="any", difficulty=0.5) == "ollama.gemma4:e4b"
        assert custom_router.route(call_point="any", difficulty=0.7) == "aiping.GLM-4-9B"
        assert custom_router.route(call_point="any", difficulty=0.9) == "aiping.GLM-4-9B"


class TestInputTruncation:
    """TieredRouter SHALL support input_truncation configuration per tier."""

    def test_fast_tier_has_truncation(self, router: TieredRouter) -> None:
        """Fast tier SHALL have input_truncation=512."""
        truncation = router.get_input_truncation(call_point="classifier", difficulty=0.1)
        assert truncation == 512

    def test_medium_tier_has_truncation(self, router: TieredRouter) -> None:
        """Medium tier SHALL have input_truncation=2048."""
        truncation = router.get_input_truncation(call_point="classifier", difficulty=0.5)
        assert truncation == 2048

    def test_cloud_tier_no_truncation(self, router: TieredRouter) -> None:
        """Cloud tier SHALL have input_truncation=None (no truncation)."""
        truncation = router.get_input_truncation(call_point="classifier", difficulty=0.9)
        assert truncation is None

    def test_unknown_call_point_default_truncation(self, router: TieredRouter) -> None:
        """Unknown call_point uses default tiers truncation."""
        truncation = router.get_input_truncation(call_point="unknown", difficulty=0.1)
        assert truncation == 512


class TestAnalyzeRouting:
    """Tests for the analyze call-point routing with Provider labels."""

    def test_analyze_easy_routes_to_ollama(self, router: TieredRouter) -> None:
        """difficulty < 0.5 → ollama provider (analyze has higher low threshold)."""
        label = router.route(call_point="analyze", difficulty=0.3)
        assert label == "ollama.gemma4:e4b"

    def test_analyze_hard_routes_to_cloud(self, router: TieredRouter) -> None:
        """difficulty >= 0.7 → cloud provider."""
        label = router.route(call_point="analyze", difficulty=0.8)
        assert label == "aiping.GLM-4-9B"


class TestUnknownCallPoint:
    """Tests for unknown call-point default routing."""

    def test_unknown_call_point_default_tiers(self, router: TieredRouter) -> None:
        """unknown call_point uses default routing with Provider labels."""
        label_easy = router.route(call_point="unknown_stage", difficulty=0.1)
        assert label_easy == "fastText"

        label_medium = router.route(call_point="unknown_stage", difficulty=0.5)
        assert label_medium == "ollama.gemma4:e4b"

        label_hard = router.route(call_point="unknown_stage", difficulty=0.9)
        assert label_hard == "aiping.GLM-4-9B"


class TestTierConfig:
    """Tests for TierConfig dataclass."""

    def test_tier_config_creation(self) -> None:
        """TierConfig can be created with required fields."""
        tc = TierConfig(
            backend="fastText",
            max_difficulty=0.3,
            provider={"model": "fasttext"},
            input_truncation=512,
        )
        assert tc.backend == "fastText"
        assert tc.max_difficulty == 0.3
        assert tc.provider == {"model": "fasttext"}
        assert tc.input_truncation == 512

    def test_tier_config_default_truncation(self) -> None:
        """TierConfig input_truncation defaults to None."""
        tc = TierConfig(
            backend="aiping.GLM-4-9B",
            max_difficulty=1.0,
            provider={"model": "glm4"},
        )
        assert tc.input_truncation is None
