# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for graph_types module."""

import pytest

from modules.memory.core.graph_types import (
    INTENT_EDGE_WEIGHTS,
    CausalRelationType,
    EdgeType,
    IntentType,
)


@pytest.mark.unit
def test_causal_relation_type_values():
    """Test CausalRelationType enum has correct values."""
    assert CausalRelationType.CAUSES.value == "CAUSES"
    assert CausalRelationType.ENABLES.value == "ENABLES"
    assert CausalRelationType.PREVENTS.value == "PREVENTS"


@pytest.mark.unit
def test_edge_type_values():
    """Test EdgeType enum has correct values."""
    assert EdgeType.TEMPORAL.value == "TEMPORAL"
    assert EdgeType.CAUSAL.value == "CAUSAL"
    assert EdgeType.SEMANTIC.value == "SEMANTIC"
    assert EdgeType.ENTITY.value == "ENTITY"


@pytest.mark.unit
def test_intent_type_values():
    """Test IntentType enum has correct values."""
    assert IntentType.WHY.value == "WHY"
    assert IntentType.WHEN.value == "WHEN"
    assert IntentType.ENTITY.value == "ENTITY"
    assert IntentType.OPEN.value == "OPEN"


@pytest.mark.unit
def test_intent_edge_weights_structure():
    """Test INTENT_EDGE_WEIGHTS has correct structure."""
    # WHY queries should prioritize CAUSAL edges
    assert INTENT_EDGE_WEIGHTS[IntentType.WHY][EdgeType.CAUSAL] == 5.0
    assert INTENT_EDGE_WEIGHTS[IntentType.WHY][EdgeType.TEMPORAL] == 2.0

    # WHEN queries should prioritize TEMPORAL edges
    assert INTENT_EDGE_WEIGHTS[IntentType.WHEN][EdgeType.TEMPORAL] == 5.0

    # ENTITY queries should prioritize ENTITY edges
    assert INTENT_EDGE_WEIGHTS[IntentType.ENTITY][EdgeType.ENTITY] == 5.0


@pytest.mark.unit
def test_intent_edge_weights_completeness():
    """Test all intent types have weights for all edge types."""
    for intent in IntentType:
        for edge in EdgeType:
            assert edge in INTENT_EDGE_WEIGHTS[intent], f"Missing weight for {intent} -> {edge}"
            assert isinstance(
                INTENT_EDGE_WEIGHTS[intent][edge], float
            ), f"Weight for {intent} -> {edge} should be float"
