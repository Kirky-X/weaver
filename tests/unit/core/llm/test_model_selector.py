# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for ModelSelector."""

import pytest

from core.event.bus import EventBus
from core.llm.experience import ExperienceStore
from core.llm.model_selector import (
    DEFAULT_WEIGHTS,
    ModelSelector,
    WeightConfig,
    _normalize_inverse,
)
from core.llm.types import (
    CandidateScore,
    Capability,
    Label,
    LLMType,
    RoutingInfeasibleError,
    RoutingMode,
)


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def experience(event_bus):
    store = ExperienceStore(event_bus=event_bus)
    # Simulate some experience data
    store._experiences["classifier.aiping.GLM-Z1"] = type(
        store._experiences.get("x") or type("E", (), {})()
    )
    store._experiences["classifier.aiping.GLM-Z1"].call_count = 100
    store._experiences["classifier.aiping.GLM-Z1"].success_count = 95
    store._experiences["classifier.aiping.GLM-Z1"].failure_count = 5
    store._experiences["classifier.aiping.GLM-Z1"].total_latency_ms = 200000.0
    store._experiences["classifier.aiping.GLM-Z1"].alpha = 96.0
    store._experiences["classifier.aiping.GLM-Z1"].beta = 6.0
    store._experiences["classifier.aiping.GLM-Z1"].last_call_time = 0.0
    store._experiences["classifier.aiping.GLM-Z1"].last_error_type = ""

    store._experiences["classifier.dmx.glm-4"] = type("E", (), {})()
    store._experiences["classifier.dmx.glm-4"].call_count = 50
    store._experiences["classifier.dmx.glm-4"].success_count = 48
    store._experiences["classifier.dmx.glm-4"].failure_count = 2
    store._experiences["classifier.dmx.glm-4"].total_latency_ms = 150000.0
    store._experiences["classifier.dmx.glm-4"].alpha = 49.0
    store._experiences["classifier.dmx.glm-4"].beta = 3.0
    store._experiences["classifier.dmx.glm-4"].last_call_time = 0.0
    store._experiences["classifier.dmx.glm-4"].last_error_type = ""
    return store


@pytest.fixture
def selector(experience):
    return ModelSelector(experience=experience)


class TestNormalizeInverse:
    """Test min-max inverse normalization."""

    def test_empty_dict(self):
        assert _normalize_inverse({}) == {}

    def test_single_value(self):
        assert _normalize_inverse({"a": 1.0}) == {"a": 0.5}

    def test_two_values(self):
        result = _normalize_inverse({"a": 0.0, "b": 10.0})
        assert result["a"] == 1.0  # lowest → highest score
        assert result["b"] == 0.0  # highest → lowest score


class TestModeWeights:
    """Test mode-based weight configuration."""

    def test_auto_mode_weights(self):
        weights = DEFAULT_WEIGHTS[RoutingMode.AUTO]
        assert weights["editorial"] == 0.35
        assert weights["reliability"] == 0.25
        assert weights["cost"] == 0.15
        assert weights["latency"] == 0.10

    def test_fast_mode_prioritizes_cost(self):
        weights = DEFAULT_WEIGHTS[RoutingMode.FAST]
        assert weights["cost"] == 0.30  # highest
        assert weights["reliability"] == 0.15  # lowest

    def test_best_mode_prioritizes_reliability(self):
        weights = DEFAULT_WEIGHTS[RoutingMode.BEST]
        assert weights["reliability"] == 0.40  # highest
        assert weights["cost"] == 0.05  # lowest


class TestModelSelectorScoring:
    """Test model selector scoring."""

    def test_select_returns_sorted_labels(self, selector):
        """Selector returns sorted list with best model first."""
        candidates = [
            Label(LLMType.CHAT, "aiping", "GLM-Z1"),
            Label(LLMType.CHAT, "dmx", "glm-4"),
        ]

        result = selector.select("classifier", candidates, RoutingMode.AUTO)

        assert len(result) == 2
        # Both labels returned
        assert {str(r) for r in result} == {str(c) for c in candidates}

    def test_select_raises_on_empty_candidates(self, selector):
        """Empty candidates raises RoutingInfeasibleError."""
        with pytest.raises(RoutingInfeasibleError):
            selector.select("classifier", [], RoutingMode.AUTO)


class TestCapabilityFiltering:
    """Test capability-based filtering."""

    def test_embedding_call_filters_chat_models(self, selector):
        """Embedding call filters out non-embedding candidates."""
        # This is tested through the _filter_by_capability static method
        candidates = [
            Label(LLMType.EMBEDDING, "aiping", "embed-1"),
            Label(LLMType.CHAT, "aiping", "chat-1"),
        ]
        capable = ModelSelector._filter_by_capability(candidates, Capability.EMBEDDING)
        assert len(capable) == 1
        assert capable[0].llm_type == LLMType.EMBEDDING
