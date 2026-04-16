# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for router module."""

from unittest.mock import MagicMock

import pytest

from core.llm.routing.router import LabelRouter
from core.llm.types import GlobalConfig, Label, LLMType, RoutingConfig


@pytest.fixture
def mock_global_config():
    """Create a mock GlobalConfig for testing."""
    config = MagicMock(spec=GlobalConfig)

    # Setup defaults
    config.defaults = {
        LLMType.CHAT: RoutingConfig(
            primary="chat.openai.GPT-4",
            fallbacks=["chat.openai.GPT-3.5", "chat.anthropic.Claude"],
        ),
        LLMType.EMBEDDING: RoutingConfig(
            primary="embed.openai.text-embedding-3",
            fallbacks=[],
        ),
    }

    # Setup call points
    config.call_points = {
        "classifier": RoutingConfig(
            primary="chat.openai.GPT-3.5",
            fallbacks=["chat.anthropic.Claude-Haiku"],
        ),
        "entity_extractor": RoutingConfig(
            primary="chat.openai.GPT-4",
            fallbacks=["chat.anthropic.Claude"],
        ),
    }

    return config


class TestLabelRouterInit:
    """Test LabelRouter initialization."""

    def test_init_stores_config(self, mock_global_config):
        """Test initialization stores config references."""
        router = LabelRouter(mock_global_config)
        assert router._defaults == mock_global_config.defaults
        assert router._call_points == mock_global_config.call_points


class TestResolve:
    """Test label resolution."""

    def test_resolve_with_routing_config(self, mock_global_config):
        """Test resolve returns chain when routing config exists."""
        router = LabelRouter(mock_global_config)
        label = Label.parse("chat.openai.GPT-4")

        chain = router.resolve(label)
        assert len(chain) == 3
        assert str(chain[0]) == "chat.openai.GPT-4"
        assert str(chain[1]) == "chat.openai.GPT-3.5"
        assert str(chain[2]) == "chat.anthropic.Claude"

    def test_resolve_without_routing_config(self, mock_global_config):
        """Test resolve returns single label when no routing config."""
        router = LabelRouter(mock_global_config)
        label = Label.parse("chat.unknown.Model")

        chain = router.resolve(label)
        assert len(chain) == 1
        assert chain[0] == label

    def test_resolve_with_fallbacks(self, mock_global_config):
        """Test resolve includes fallbacks in chain."""
        router = LabelRouter(mock_global_config)
        label = Label.parse("chat.openai.GPT-3.5")

        chain = router.resolve(label)
        assert len(chain) == 2
        assert str(chain[0]) == "chat.openai.GPT-3.5"
        assert str(chain[1]) == "chat.anthropic.Claude-Haiku"


class TestGetCallPointRoute:
    """Test call point route retrieval."""

    def test_get_configured_call_point(self, mock_global_config):
        """Test get_call_point_route for configured call point."""
        router = LabelRouter(mock_global_config)

        route = router.get_call_point_route("classifier")
        assert len(route) == 2
        assert str(route[0]) == "chat.openai.GPT-3.5"
        assert str(route[1]) == "chat.anthropic.Claude-Haiku"

    def test_get_call_point_raises_for_unconfigured(self, mock_global_config):
        """Test get_call_point_route raises ValueError for unconfigured call point."""
        router = LabelRouter(mock_global_config)

        with pytest.raises(ValueError, match="Call point not configured"):
            router.get_call_point_route("unknown_point")


class TestGetDefault:
    """Test default label retrieval."""

    def test_get_default_for_configured_type(self, mock_global_config):
        """Test get_default returns label for configured LLMType."""
        router = LabelRouter(mock_global_config)

        label = router.get_default(LLMType.CHAT)
        assert str(label) == "chat.openai.GPT-4"

    def test_get_default_raises_for_unconfigured_type(self, mock_global_config):
        """Test get_default raises ValueError for unconfigured LLMType."""
        router = LabelRouter(mock_global_config)

        with pytest.raises(ValueError, match="No default label configured"):
            router.get_default(LLMType.RERANK)


class TestListCallPoints:
    """Test call point listing."""

    def test_list_call_points(self, mock_global_config):
        """Test list_call_points returns all configured call points."""
        router = LabelRouter(mock_global_config)

        points = router.list_call_points()
        assert "classifier" in points
        assert "entity_extractor" in points
        assert len(points) == 2


class TestBuildChain:
    """Test chain building."""

    def test_build_chain_with_fallbacks(self, mock_global_config):
        """Test _build_chain creates list of Labels."""
        router = LabelRouter(mock_global_config)
        routing = RoutingConfig(
            primary="chat.openai.GPT-4",
            fallbacks=["chat.openai.GPT-3.5", "chat.anthropic.Claude"],
        )

        chain = router._build_chain(routing)
        assert len(chain) == 3
        assert all(isinstance(label, Label) for label in chain)

    def test_build_chain_without_fallbacks(self, mock_global_config):
        """Test _build_chain works with no fallbacks."""
        router = LabelRouter(mock_global_config)
        routing = RoutingConfig(
            primary="embedding.openai.text-embedding-3",
            fallbacks=[],
        )

        chain = router._build_chain(routing)
        assert len(chain) == 1
        assert str(chain[0]) == "embedding.openai.text-embedding-3"
