# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Core type definitions for multi-graph memory system."""

from enum import Enum


class CausalRelationType(Enum):
    """Types of causal relationships between events.

    Based on MAGMA paper's causal graph edge semantics.
    """

    CAUSES = "CAUSES"
    """Direct causation: event A directly causes event B."""

    ENABLES = "ENABLES"
    """Conditional enabling: event A creates conditions for event B to occur."""

    PREVENTS = "PREVENTS"
    """Prevention: event A reduces or prevents the likelihood of event B."""


class EdgeType(Enum):
    """Types of edges in the multi-graph memory system.

    Corresponds to MAGMA's four orthogonal graph views.
    """

    TEMPORAL = "TEMPORAL"
    """Chronological ordering edges (τ_i < τ_j)."""

    CAUSAL = "CAUSAL"
    """Logical entailment edges (CAUSES, ENABLES, PREVENTS)."""

    SEMANTIC = "SEMANTIC"
    """Conceptual similarity edges (cos(v_i, v_j) > θ)."""

    ENTITY = "ENTITY"
    """Entity-event association edges (MENTIONS, PARTICIPATES_IN)."""


class IntentType(Enum):
    """Query intent types for adaptive retrieval.

    Used to route graph traversal based on query semantics.
    """

    WHY = "WHY"
    """Causal reasoning queries: "Why did X happen?" """

    WHEN = "WHEN"
    """Temporal reasoning queries: "When did Y occur?" """

    ENTITY = "ENTITY"
    """Entity-centric queries: "What is Z?" """

    OPEN = "OPEN"
    """Open-domain queries: "Tell me about W" """


# Intent-to-edge weight mapping for MAGMA Equation 5
# S(n_j | n_i, q) = exp(λ₁·φ(type(e_ij), T_q) + λ₂·sim(v_j, q))
INTENT_EDGE_WEIGHTS: dict[IntentType, dict[EdgeType, float]] = {
    IntentType.WHY: {
        EdgeType.CAUSAL: 5.0,
        EdgeType.TEMPORAL: 2.0,
        EdgeType.ENTITY: 1.5,
        EdgeType.SEMANTIC: 0.5,
    },
    IntentType.WHEN: {
        EdgeType.TEMPORAL: 5.0,
        EdgeType.CAUSAL: 1.0,
        EdgeType.ENTITY: 2.0,
        EdgeType.SEMANTIC: 1.0,
    },
    IntentType.ENTITY: {
        EdgeType.ENTITY: 5.0,
        EdgeType.SEMANTIC: 3.0,
        EdgeType.CAUSAL: 1.0,
        EdgeType.TEMPORAL: 1.0,
    },
    IntentType.OPEN: {
        EdgeType.SEMANTIC: 4.0,
        EdgeType.ENTITY: 2.0,
        EdgeType.CAUSAL: 1.5,
        EdgeType.TEMPORAL: 1.0,
    },
}
