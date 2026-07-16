# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for TieredRouter: difficulty-based tiered LLM routing.

Covers:
- Low difficulty -> fasttext label
- Medium difficulty -> ollama label
- High difficulty -> cloud label
- Config-driven routing tiers
- Returns None when no tiers configured for call_point
- Returns Label | None
"""

from __future__ import annotations

import pytest

from core.llm.routing.difficulty_estimator import DifficultyEstimator
from core.llm.routing.tiered_router import TierConfig, TieredRouter
from core.llm.types import Label, LLMType

# ── Fixtures ──────────────────────────────────────────────────────


def _make_estimator() -> DifficultyEstimator:
    return DifficultyEstimator()


def _make_tiers() -> list[TierConfig]:
    """Standard 3-tier configuration: fasttext / ollama / cloud."""
    return [
        TierConfig(label="chat.fasttext.classifier", max_difficulty=0.3),
        TierConfig(label="chat.ollama.gemma4:e4b", max_difficulty=0.7),
        TierConfig(label="chat.aiping.GLM-4-9B", max_difficulty=1.0),
    ]


def _make_router(tiers: list[TierConfig] | None = None) -> TieredRouter:
    estimator = _make_estimator()
    return TieredRouter(estimator=estimator, tiers=tiers)


# ── Tests ─────────────────────────────────────────────────────────


class TestTieredRouterLowDifficulty:
    """Low difficulty should route to fasttext tier."""

    def test_short_text_routes_to_fasttext(self) -> None:
        router = _make_router(_make_tiers())
        short_text = "a" * 50  # < 200 chars -> low difficulty
        result = router.route("classifier", short_text)
        assert result is not None
        assert result.provider == "fasttext"

    def test_low_difficulty_returns_label_type(self) -> None:
        router = _make_router(_make_tiers())
        short_text = "a" * 50
        result = router.route("classifier", short_text)
        assert isinstance(result, Label)
        assert result.llm_type == LLMType.CHAT


class TestTieredRouterMediumDifficulty:
    """Medium difficulty should route to ollama tier."""

    def test_medium_text_routes_to_ollama(self) -> None:
        router = _make_router(_make_tiers())
        medium_text = "a" * 2000  # 2000 chars -> medium difficulty
        result = router.route("classifier", medium_text)
        assert result is not None
        assert result.provider == "ollama"


class TestTieredRouterHighDifficulty:
    """High difficulty should route to cloud tier."""

    def test_long_text_routes_to_cloud(self) -> None:
        router = _make_router(_make_tiers())
        long_text = "a" * 9000  # > 8000 chars -> high difficulty
        result = router.route("classifier", long_text)
        assert result is not None
        assert result.provider == "aiping"


class TestTieredRouterNoTiers:
    """When no tiers configured, route returns None."""

    def test_returns_none_without_tiers(self) -> None:
        router = _make_router(tiers=None)
        result = router.route("classifier", "some text")
        assert result is None

    def test_returns_none_for_unconfigured_call_point(self) -> None:
        """Per-call-point config: unconfigured call_point returns None."""
        estimator = _make_estimator()
        tiers_by_cp = {"classifier": _make_tiers()}
        router = TieredRouter(estimator=estimator, tiers_by_call_point=tiers_by_cp)
        result = router.route("unknown_call_point", "some text")
        assert result is None


class TestTieredRouterConfigDriven:
    """Config-driven routing tiers."""

    def test_per_call_point_tiers(self) -> None:
        """Different call points can have different tier configurations."""
        estimator = _make_estimator()
        tiers_by_cp = {
            "classifier": [
                TierConfig(label="chat.fasttext.classifier", max_difficulty=0.5),
                TierConfig(label="chat.aiping.GLM-4-9B", max_difficulty=1.0),
            ],
            "entity_extractor": [
                TierConfig(label="chat.ollama.gemma4:e4b", max_difficulty=0.6),
                TierConfig(label="chat.aiping.GLM-4-9B", max_difficulty=1.0),
            ],
        }
        router = TieredRouter(estimator=estimator, tiers_by_call_point=tiers_by_cp)

        # Short text with classifier -> fasttext
        result = router.route("classifier", "a" * 50)
        assert result is not None
        assert result.provider == "fasttext"

        # Short text with entity_extractor -> ollama (no fasttext tier)
        result = router.route("entity_extractor", "a" * 50)
        assert result is not None
        assert result.provider == "ollama"

    def test_custom_tiers_override_call_point_config(self) -> None:
        """When both custom tiers and per-call-point config exist,
        custom tiers take precedence."""
        estimator = _make_estimator()
        custom_tiers = [
            TierConfig(label="chat.ollama.gemma4:e4b", max_difficulty=1.0),
        ]
        tiers_by_cp = {"classifier": _make_tiers()}
        router = TieredRouter(
            estimator=estimator, tiers=custom_tiers, tiers_by_call_point=tiers_by_cp
        )
        # All texts should route to ollama (only tier)
        result = router.route("classifier", "a" * 50)
        assert result is not None
        assert result.provider == "ollama"


class TestTieredRouterFallback:
    """Last tier catches all remaining difficulty levels."""

    def test_difficulty_above_all_thresholds_uses_last_tier(self) -> None:
        router = _make_router(_make_tiers())
        # Even extremely long text should use the last tier (cloud)
        very_long_text = "a" * 50000
        result = router.route("classifier", very_long_text)
        assert result is not None
        assert result.provider == "aiping"


class TestTieredRouterGetInputTruncation:
    """get_input_truncation returns the correct truncation limit."""

    def test_returns_truncation_for_matched_tier(self) -> None:
        tiers = [
            TierConfig(label="chat.fasttext.classifier", max_difficulty=0.3, input_truncation=512),
            TierConfig(label="chat.ollama.gemma4:e4b", max_difficulty=0.7, input_truncation=2048),
            TierConfig(label="chat.aiping.GLM-4-9B", max_difficulty=1.0, input_truncation=None),
        ]
        router = _make_router(tiers)
        short_text = "a" * 50
        truncation = router.get_input_truncation("classifier", short_text)
        assert truncation == 512

    def test_returns_none_when_no_truncation(self) -> None:
        tiers = _make_tiers()
        router = _make_router(tiers)
        long_text = "a" * 9000
        truncation = router.get_input_truncation("classifier", long_text)
        assert truncation is None

    def test_returns_none_without_tiers(self) -> None:
        router = _make_router(tiers=None)
        truncation = router.get_input_truncation("classifier", "some text")
        assert truncation is None
