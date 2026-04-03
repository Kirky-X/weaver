# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Core type definitions for multi-graph memory system."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


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


class AggregationType(Enum):
    """Types of entity neighborhood aggregation.

    Determines how entity-related events are summarized.
    """

    FACTS = "FACTS"
    """Extract key factual statements from events."""

    COUNT = "COUNT"
    """Aggregate statistical counts of events."""

    TIMELINE = "TIMELINE"
    """Generate chronological sequence of events."""


class OutputMode(Enum):
    """Output format modes for search response.

    Determines how retrieved context is presented to user.
    """

    CONTEXT = "CONTEXT"
    """Raw context snippets for downstream processing."""

    NARRATIVE = "NARRATIVE"
    """LLM-synthesized narrative answer."""


@dataclass
class EntityNeighborhood:
    """Neighborhood of an entity in the multi-graph memory.

    Contains the entity, its associated events, related entities,
    and the relations connecting them.
    """

    center: str
    """Canonical name of the center entity."""

    events: list[dict[str, Any]] = field(default_factory=list)
    """Events mentioning or involving the center entity."""

    related_entities: list[dict[str, Any]] = field(default_factory=list)
    """Entities connected to the center entity."""

    relations: list[dict[str, Any]] = field(default_factory=list)
    """Relations between center entity and related entities."""

    hops: int = 2
    """Number of hops used to expand the neighborhood."""


@dataclass
class AggregationResult:
    """Result of aggregating entity neighborhood information.

    Produced by EntityAggregator component.
    """

    entity_name: str
    """Name of the aggregated entity."""

    entity_type: str
    """Type classification of the entity."""

    aggregation_type: AggregationType
    """Type of aggregation performed."""

    facts: list[str] = field(default_factory=list)
    """Extracted factual statements (for FACTS mode)."""

    count: int = 0
    """Count of events (for COUNT mode)."""

    reasoning_trace: str = ""
    """LLM reasoning trace for the aggregation."""

    confidence: float = 0.0
    """Confidence score for the aggregation result."""


@dataclass
class SynthesisResult:
    """Result of LLM synthesis of retrieved context.

    Produced by NarrativeSynthesizer component.
    """

    output: str
    """Synthesized narrative or context output."""

    mode: OutputMode
    """Output mode used for synthesis."""

    total_tokens: int = 0
    """Total tokens consumed in synthesis."""

    node_count: int = 0
    """Number of memory nodes included."""

    included_nodes: list[str] = field(default_factory=list)
    """IDs of nodes included in synthesis."""

    summarized_nodes: list[str] = field(default_factory=list)
    """IDs of nodes that were summarized away."""
