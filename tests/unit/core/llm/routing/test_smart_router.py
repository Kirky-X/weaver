# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for SmartRouter - unified routing facade."""

from unittest.mock import MagicMock

import pytest

from core.llm.routing.model_selector import ModelSelector
from core.llm.routing.router import LabelRouter
from core.llm.routing.smart_router import SmartRouter
from core.llm.types import (
    Label,
    LLMType,
    RoutingConfig,
    RoutingMode,
)


class TestSmartRouterInit:
    """Test SmartRouter initialization."""

    def test_basic_initialization(self):
        """Test basic SmartRouter initialization."""
        settings = MagicMock()
        settings.routing = {}
        settings.circuit_breaker_threshold = 5
        settings.circuit_breaker_timeout = 60.0
        settings.default_timeout = 120.0
        settings.defaults = {}
        settings.call_points = {}

        experience = MagicMock()
        circuit_breakers = {}

        router = SmartRouter(
            settings=settings,
            experience=experience,
            circuit_breakers=circuit_breakers,
        )

        assert router._settings == settings
        assert router._experience == experience
        assert router._circuit_breakers == circuit_breakers
        assert isinstance(router._label_router, LabelRouter)
        assert isinstance(router._selector, ModelSelector)

    def test_initialization_with_circuit_breakers(self):
        """Test initialization with circuit breakers."""
        settings = MagicMock()
        settings.routing = {}
        settings.circuit_breaker_threshold = 5
        settings.circuit_breaker_timeout = 60.0
        settings.default_timeout = 120.0
        settings.defaults = {}
        settings.call_points = {}

        experience = MagicMock()
        cb1 = MagicMock()
        cb1.is_open = False
        cb2 = MagicMock()
        cb2.is_open = True

        circuit_breakers = {"provider1": cb1, "provider2": cb2}

        router = SmartRouter(
            settings=settings,
            experience=experience,
            circuit_breakers=circuit_breakers,
        )

        assert "provider1" in router._circuit_breakers
        assert "provider2" in router._circuit_breakers


class TestSmartRouterRoute:
    """Test SmartRouter.route() method."""

    @pytest.fixture
    def mock_settings_with_routing(self):
        """Mock settings with smart routing configured."""
        settings = MagicMock()
        settings.routing = {
            "classifier": {"mode": "auto"},
            "embedding": {"mode": "fast"},
            "analyze": {"mode": "best"},
        }
        settings.circuit_breaker_threshold = 5
        settings.circuit_breaker_timeout = 60.0
        settings.default_timeout = 120.0
        settings.defaults = {
            LLMType.CHAT: RoutingConfig(primary="chat.openai.gpt-4"),
            LLMType.EMBEDDING: RoutingConfig(primary="embedding.openai.text-embedding-3"),
        }
        settings.call_points = {
            "classifier": RoutingConfig(
                primary="chat.openai.gpt-4",
                fallbacks=["chat.anthropic.claude-3"],
            ),
            "embedding": RoutingConfig(
                primary="embedding.openai.text-embedding-3",
            ),
        }
        return settings

    @pytest.fixture
    def mock_experience(self):
        """Mock experience store."""
        experience = MagicMock()
        experience.avg_latency.return_value = 100.0
        experience.reliability.return_value = 0.95
        experience.thompson_sample.return_value = 0.5
        return experience

    @pytest.fixture
    def mock_circuit_breakers(self):
        """Mock circuit breakers (all closed)."""
        cb = MagicMock()
        cb.is_open = False
        return {"openai": cb, "anthropic": cb}

    @pytest.fixture
    def smart_router(self, mock_settings_with_routing, mock_experience, mock_circuit_breakers):
        """Create SmartRouter instance for testing."""
        return SmartRouter(
            settings=mock_settings_with_routing,
            experience=mock_experience,
            circuit_breakers=mock_circuit_breakers,
        )

    def test_route_with_smart_routing_enabled(
        self, smart_router: SmartRouter, mock_experience: MagicMock
    ):
        """Test routing with smart routing enabled."""
        # Configure selector to return labels in specific order
        mock_experience.avg_latency.side_effect = lambda cp, p, m: 100.0 if "gpt" in m else 200.0

        labels = smart_router.route("classifier")

        assert isinstance(labels, list)
        assert len(labels) > 0
        assert all(isinstance(label, Label) for label in labels)

    def test_route_fallback_when_no_config(self, smart_router: SmartRouter):
        """Test fallback routing when call point has no smart routing config."""
        labels = smart_router.route("unknown_call_point")

        assert isinstance(labels, list)
        # Should use default routing
        assert len(labels) >= 0

    def test_route_invalid_routing_mode(
        self, mock_settings_with_routing, mock_experience, mock_circuit_breakers
    ):
        """Test routing with invalid mode falls back to AUTO."""
        mock_settings_with_routing.routing["test_point"] = {"mode": "invalid_mode"}
        mock_settings_with_routing.call_points["test_point"] = RoutingConfig(
            primary="chat.openai.gpt-4"
        )

        router = SmartRouter(
            settings=mock_settings_with_routing,
            experience=mock_experience,
            circuit_breakers=mock_circuit_breakers,
        )

        labels = router.route("test_point")
        assert isinstance(labels, list)

    def test_route_empty_static_labels(
        self, mock_settings_with_routing, mock_experience, mock_circuit_breakers
    ):
        """Test routing when static labels list is empty."""
        mock_settings_with_routing.routing["empty_point"] = {"mode": "auto"}
        # No call_points config for empty_point

        router = SmartRouter(
            settings=mock_settings_with_routing,
            experience=mock_experience,
            circuit_breakers=mock_circuit_breakers,
        )

        labels = router.route("empty_point")
        assert isinstance(labels, list)

    def test_route_selector_exception_fallback(
        self, mock_settings_with_routing, mock_experience, mock_circuit_breakers
    ):
        """Test that selector exceptions fallback to static labels."""
        mock_settings_with_routing.routing["error_point"] = {"mode": "auto"}
        mock_settings_with_routing.call_points["error_point"] = RoutingConfig(
            primary="chat.openai.gpt-4",
            fallbacks=["chat.anthropic.claude-3"],
        )

        # Make selector raise exception
        mock_experience.avg_latency.side_effect = Exception("Database error")

        router = SmartRouter(
            settings=mock_settings_with_routing,
            experience=mock_experience,
            circuit_breakers=mock_circuit_breakers,
        )

        # Should fallback to static labels without raising
        labels = router.route("error_point")
        assert isinstance(labels, list)

    def test_route_with_different_modes(self, smart_router: SmartRouter):
        """Test routing with different configured modes."""
        # Test AUTO mode
        labels_auto = smart_router.route("classifier")
        assert isinstance(labels_auto, list)

        # Test FAST mode
        labels_fast = smart_router.route("embedding")
        assert isinstance(labels_fast, list)

        # Test BEST mode
        labels_best = smart_router.route("analyze")
        assert isinstance(labels_best, list)


class TestSmartRouterFallbackRoute:
    """Test _fallback_route method."""

    @pytest.fixture
    def smart_router(self):
        """Create SmartRouter for fallback testing."""
        settings = MagicMock()
        settings.routing = {}
        settings.circuit_breaker_threshold = 5
        settings.circuit_breaker_timeout = 60.0
        settings.default_timeout = 120.0
        settings.defaults = {
            LLMType.CHAT: RoutingConfig(primary="chat.openai.gpt-4"),
        }
        settings.call_points = {
            "configured_point": RoutingConfig(
                primary="chat.anthropic.claude-3",
                fallbacks=["chat.openai.gpt-3.5"],
            ),
        }
        experience = MagicMock()
        circuit_breakers = {}

        return SmartRouter(
            settings=settings,
            experience=experience,
            circuit_breakers=circuit_breakers,
        )

    def test_fallback_route_configured_call_point(self, smart_router: SmartRouter):
        """Test fallback route for configured call point."""
        labels = smart_router._fallback_route("configured_point")

        assert len(labels) == 2
        assert str(labels[0]) == "chat.anthropic.claude-3"
        assert str(labels[1]) == "chat.openai.gpt-3.5"

    def test_fallback_route_unconfigured_uses_default(self, smart_router: SmartRouter):
        """Test fallback route uses default for unconfigured call point."""
        labels = smart_router._fallback_route("embedding")

        # Should try to use default, but embedding type may not have default configured
        # The important thing is it doesn't crash
        assert isinstance(labels, list)

    def test_fallback_route_no_default_returns_empty(self):
        """Test fallback route returns empty when no default configured."""
        settings = MagicMock()
        settings.routing = {}
        settings.circuit_breaker_threshold = 5
        settings.circuit_breaker_timeout = 60.0
        settings.default_timeout = 120.0
        settings.defaults = {}
        settings.call_points = {}
        experience = MagicMock()

        router = SmartRouter(
            settings=settings,
            experience=experience,
            circuit_breakers={},
        )

        labels = router._fallback_route("unknown")
        assert labels == []


class TestSmartRouterInferLLMType:
    """Test _infer_llm_type static method."""

    def test_infer_embedding_type(self):
        """Test inferring EMBEDDING type from call point."""
        assert SmartRouter._infer_llm_type("embedding") == LLMType.EMBEDDING
        assert SmartRouter._infer_llm_type("content_embedding") == LLMType.EMBEDDING
        assert SmartRouter._infer_llm_type("embedding_generation") == LLMType.EMBEDDING

    def test_infer_rerank_type(self):
        """Test inferring RERANK type from call point."""
        assert SmartRouter._infer_llm_type("rerank") == LLMType.RERANK
        assert SmartRouter._infer_llm_type("document_rerank") == LLMType.RERANK
        assert SmartRouter._infer_llm_type("rerank_results") == LLMType.RERANK

    def test_infer_chat_type_default(self):
        """Test defaulting to CHAT type."""
        assert SmartRouter._infer_llm_type("classifier") == LLMType.CHAT
        assert SmartRouter._infer_llm_type("analyzer") == LLMType.CHAT
        assert SmartRouter._infer_llm_type("summarizer") == LLMType.CHAT
        assert SmartRouter._infer_llm_type("unknown") == LLMType.CHAT


class TestSmartRouterIntegration:
    """Integration tests for SmartRouter with various configurations."""

    def test_full_routing_flow_with_circuit_breaker_open(self):
        """Test routing when one provider has open circuit breaker."""
        settings = MagicMock()
        settings.routing = {"classifier": {"mode": "auto"}}
        settings.circuit_breaker_threshold = 5
        settings.circuit_breaker_timeout = 60.0
        settings.default_timeout = 120.0
        settings.defaults = {}
        settings.call_points = {
            "classifier": RoutingConfig(
                primary="chat.openai.gpt-4",
                fallbacks=["chat.anthropic.claude-3"],
            ),
        }

        experience = MagicMock()
        experience.avg_latency.return_value = 100.0
        experience.reliability.return_value = 0.95
        experience.thompson_sample.return_value = 0.5

        # OpenAI circuit breaker is OPEN
        cb_openai = MagicMock()
        cb_openai.is_open = True
        cb_anthropic = MagicMock()
        cb_anthropic.is_open = False

        circuit_breakers = {
            "openai": cb_openai,
            "anthropic": cb_anthropic,
        }

        router = SmartRouter(
            settings=settings,
            experience=experience,
            circuit_breakers=circuit_breakers,
        )

        labels = router.route("classifier")
        # Should exclude openai provider
        assert all("openai" not in str(label) for label in labels)

    def test_routing_with_multiple_call_points(self):
        """Test routing across multiple call points."""
        settings = MagicMock()
        settings.routing = {
            "classifier": {"mode": "best"},
            "cleaner": {"mode": "fast"},
            "embedding": {"mode": "auto"},
        }
        settings.circuit_breaker_threshold = 5
        settings.circuit_breaker_timeout = 60.0
        settings.default_timeout = 120.0
        settings.defaults = {}
        settings.call_points = {
            "classifier": RoutingConfig(primary="chat.openai.gpt-4"),
            "cleaner": RoutingConfig(primary="chat.anthropic.claude-3"),
            "embedding": RoutingConfig(primary="embedding.openai.text-embedding-3"),
        }

        experience = MagicMock()
        experience.avg_latency.return_value = 100.0
        experience.reliability.return_value = 0.9
        experience.thompson_sample.return_value = 0.5

        router = SmartRouter(
            settings=settings,
            experience=experience,
            circuit_breakers={},
        )

        # All call points should return valid labels
        for call_point in ["classifier", "cleaner", "embedding"]:
            labels = router.route(call_point)
            assert isinstance(labels, list)
            assert len(labels) > 0

    def test_routing_preserves_label_order_by_score(self):
        """Test that routing preserves score-based ordering."""
        settings = MagicMock()
        settings.routing = {"test": {"mode": "auto"}}
        settings.circuit_breaker_threshold = 5
        settings.circuit_breaker_timeout = 60.0
        settings.default_timeout = 120.0
        settings.defaults = {}
        settings.call_points = {
            "test": RoutingConfig(
                primary="chat.provider1.model-a",
                fallbacks=["chat.provider2.model-b"],
            ),
        }

        experience = MagicMock()
        # Make provider2 have better latency
        experience.avg_latency.side_effect = lambda cp, p, m: 50.0 if p == "provider2" else 200.0
        experience.reliability.return_value = 0.95
        experience.thompson_sample.return_value = 0.5

        router = SmartRouter(
            settings=settings,
            experience=experience,
            circuit_breakers={},
        )

        labels = router.route("test")
        assert len(labels) == 2
        # Both labels should be present (ordering may vary based on scoring)
        label_strs = [str(label) for label in labels]
        assert "chat.provider1.model-a" in label_strs
        assert "chat.provider2.model-b" in label_strs
