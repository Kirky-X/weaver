# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for TieredRouter: difficulty-based tiered LLM routing."""

from __future__ import annotations

import pytest

from core.llm.routing.tiered_router import TieredRouter


@pytest.fixture
def router() -> TieredRouter:
    return TieredRouter()


class TestClassifierRouting:
    """Tests for the classifier call-point routing."""

    def test_classifier_easy_routes_to_fast(self, router: TieredRouter) -> None:
        """difficulty < 0.3 → fast tier."""
        tier = router.route(call_point="classifier", difficulty=0.2)
        assert tier == "fast"

    def test_classifier_medium_routes_to_local(self, router: TieredRouter) -> None:
        """0.3-0.7 → local LLM."""
        tier = router.route(call_point="classifier", difficulty=0.5)
        assert tier == "local"

    def test_classifier_hard_routes_to_cloud(self, router: TieredRouter) -> None:
        """> 0.7 → cloud LLM."""
        tier = router.route(call_point="classifier", difficulty=0.8)
        assert tier == "cloud"


class TestAnalyzeRouting:
    """Tests for the analyze call-point routing."""

    def test_analyze_easy_routes_to_local(self, router: TieredRouter) -> None:
        """difficulty < 0.5 → local."""
        tier = router.route(call_point="analyze", difficulty=0.3)
        assert tier == "local"

    def test_analyze_hard_routes_to_cloud(self, router: TieredRouter) -> None:
        """> 0.5 → cloud (via high threshold)."""
        # analyze: low=0.5, high=0.7
        # difficulty=0.8 > high=0.7 → "hard" → "cloud"
        tier = router.route(call_point="analyze", difficulty=0.8)
        assert tier == "cloud"


class TestUnknownCallPoint:
    """Tests for unknown call-point default routing."""

    def test_unknown_call_point_default_tiers(self, router: TieredRouter) -> None:
        """unknown call_point uses default routing."""
        # DEFAULT_TIER: low=0.3, high=0.7, easy="local", medium="local", hard="cloud"
        tier_easy = router.route(call_point="unknown_stage", difficulty=0.1)
        assert tier_easy == "local"

        tier_medium = router.route(call_point="unknown_stage", difficulty=0.5)
        assert tier_medium == "local"

        tier_hard = router.route(call_point="unknown_stage", difficulty=0.9)
        assert tier_hard == "cloud"
