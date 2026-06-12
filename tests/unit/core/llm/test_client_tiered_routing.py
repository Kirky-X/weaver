# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for TieredRouter integration with LLMClient.call_at.

Covers:
- Low difficulty request uses tiered label (bypasses SmartRouter)
- High difficulty request uses tiered label (cloud provider)
- TieredRouter returns None -> falls through to SmartRouter/LabelRouter
- Tiered routing disabled for call point -> falls through
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.llm.routing.difficulty_estimator import DifficultyEstimator
from core.llm.routing.tiered_router import TierConfig as RoutingTierConfig, TieredRouter
from core.llm.types import GlobalConfig, Label, RoutingConfig, TierConfig


def _make_tiers() -> list[TierConfig]:
    return [
        TierConfig(label="chat.fasttext.classifier", max_difficulty=0.3),
        TierConfig(label="chat.ollama.gemma4:e4b", max_difficulty=0.7),
        TierConfig(label="chat.aiping.GLM-4-9B-0414", max_difficulty=1.0),
    ]


def _make_routing_tiers() -> list[RoutingTierConfig]:
    """Routing-tier TierConfig for TieredRouter."""
    return [
        RoutingTierConfig(label="chat.fasttext.classifier", max_difficulty=0.3),
        RoutingTierConfig(label="chat.ollama.gemma4:e4b", max_difficulty=0.7),
        RoutingTierConfig(label="chat.aiping.GLM-4-9B-0414", max_difficulty=1.0),
    ]


def _make_global_config(
    tiered_routing: bool = True,
) -> GlobalConfig:
    """Build a GlobalConfig with call points that support tiered routing."""
    classifier_config = RoutingConfig(
        primary="chat.ollama.gemma4:e4b",
        fallbacks=[],
        tiered_routing=tiered_routing,
        tiers=_make_tiers() if tiered_routing else [],
    )
    cleaner_config = RoutingConfig(
        primary="chat.ollama.gemma4:e4b",
        fallbacks=[],
        tiered_routing=False,
    )
    return GlobalConfig(
        defaults={},
        call_points={"classifier": classifier_config, "cleaner": cleaner_config},
        circuit_breaker_threshold=5,
        circuit_breaker_timeout=60.0,
    )


def _make_client(
    tiered_router: TieredRouter | None = None,
    smart_router: MagicMock | None = None,
) -> tuple[MagicMock, GlobalConfig]:
    """Build a mock LLMClient-like object for testing _try_tiered_routing."""
    from core.llm.client import LLMClient

    global_config = _make_global_config()

    # Create a minimal client with just enough to test _try_tiered_routing
    # We mock the call method to avoid needing real providers
    client = MagicMock(spec=LLMClient)
    client._tiered_router = tiered_router
    client._router = MagicMock()
    client._router.get_call_point_config = lambda cp: global_config.call_points.get(cp)

    # Bind the real method to the mock
    client._try_tiered_routing = LLMClient._try_tiered_routing.__get__(client, LLMClient)

    return client, global_config


class TestTieredRoutingIntegration:
    """Test _try_tiered_routing in LLMClient context."""

    def test_low_difficulty_returns_fasttext_label(self) -> None:
        """Short text should route to fasttext tier."""
        estimator = DifficultyEstimator()
        router = TieredRouter(estimator=estimator, tiers=_make_routing_tiers())
        client, _ = _make_client(tiered_router=router)

        result = client._try_tiered_routing("classifier", {"body": "a" * 50})
        assert result is not None
        assert result.provider == "fasttext"

    def test_high_difficulty_returns_cloud_label(self) -> None:
        """Long text should route to cloud tier."""
        estimator = DifficultyEstimator()
        router = TieredRouter(estimator=estimator, tiers=_make_routing_tiers())
        client, _ = _make_client(tiered_router=router)

        result = client._try_tiered_routing("classifier", {"body": "a" * 9000})
        assert result is not None
        assert result.provider == "aiping"

    def test_no_tiered_router_returns_none(self) -> None:
        """Without TieredRouter, returns None (falls through to SmartRouter)."""
        client, _ = _make_client(tiered_router=None)
        result = client._try_tiered_routing("classifier", {"body": "some text"})
        assert result is None

    def test_tiered_routing_disabled_returns_none(self) -> None:
        """When tiered_routing=False for call point, returns None."""
        estimator = DifficultyEstimator()
        router = TieredRouter(estimator=estimator, tiers=_make_routing_tiers())
        client, _ = _make_client(tiered_router=router)

        # cleaner has tiered_routing=False
        result = client._try_tiered_routing("cleaner", {"body": "a" * 50})
        assert result is None

    def test_empty_text_returns_none(self) -> None:
        """Empty text in payload returns None."""
        estimator = DifficultyEstimator()
        router = TieredRouter(estimator=estimator, tiers=_make_routing_tiers())
        client, _ = _make_client(tiered_router=router)

        result = client._try_tiered_routing("classifier", {"body": ""})
        assert result is None

    def test_unconfigured_call_point_returns_none(self) -> None:
        """Call point not in config returns None."""
        estimator = DifficultyEstimator()
        router = TieredRouter(estimator=estimator, tiers=_make_routing_tiers())
        client, _ = _make_client(tiered_router=router)

        result = client._try_tiered_routing("unknown_call_point", {"body": "some text"})
        assert result is None

    def test_user_content_fallback(self) -> None:
        """When 'body' is missing, falls back to 'user_content'."""
        estimator = DifficultyEstimator()
        router = TieredRouter(estimator=estimator, tiers=_make_routing_tiers())
        client, _ = _make_client(tiered_router=router)

        result = client._try_tiered_routing("classifier", {"user_content": "a" * 50})
        assert result is not None
        assert result.provider == "fasttext"
