# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Result types for memory consolidation operations."""

from dataclasses import dataclass


@dataclass
class ConsolidationResult:
    """Result of slow path consolidation for a single event.

    Attributes:
        event_id: ID of the processed event.
        causal_edges_added: Number of causal edges created.
        entity_links_added: Number of entity links discovered.
        confidence_avg: Average confidence of inferred edges.
    """

    event_id: str
    causal_edges_added: int = 0
    entity_links_added: int = 0
    confidence_avg: float = 0.0
