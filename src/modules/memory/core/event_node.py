# Copyright (c) 2026 KirkyX. All Rights Reserved
"""EventNode: MAGMA's unified memory item representation.

n_i = <c_i, τ_i, v_i, A_i>
- c_i: content (text summary of the event)
- τ_i: timestamp (discrete temporal anchor)
- v_i: vector embedding (R^d dense representation)
- A_i: attributes (structured metadata)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class EventNode:
    """Unified memory item representing an event or observation.

    This is MAGMA's core data structure for representing memory items
    across all four graph views (Temporal, Causal, Semantic, Entity).

    Attributes:
        id: Unique identifier (typically article UUID).
        content: Text summary describing the event.
        timestamp: When the event occurred (τ_i).
        embedding: Dense vector representation for semantic search (v_i).
        attributes: Structured metadata (A_i) including title, source, etc.
    """

    id: str
    content: str
    timestamp: datetime
    embedding: list[float] | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_pipeline_state(cls, state: dict[str, Any]) -> EventNode:
        """Create EventNode from pipeline processing state.

        Args:
            state: Pipeline state dictionary containing article data.

        Returns:
            EventNode instance populated from state.
        """
        article_id = state.get("article_id", "")

        # Extract content
        cleaned = state.get("cleaned", {})
        title = cleaned.get("title", "")
        content = cleaned.get("content", title)

        # Combine title and content for full representation
        full_content = f"{title}\n\n{content}" if title and content else content or title

        # Extract timestamp
        raw = state.get("raw")
        timestamp = getattr(raw, "publish_time", None) if raw else None
        if timestamp is None:
            timestamp = datetime.now(UTC)

        # Extract embedding
        vectors = state.get("vectors", {})
        embedding = vectors.get("content") if isinstance(vectors, dict) else None

        # Build attributes
        attributes: dict[str, Any] = {}

        if raw:
            url = getattr(raw, "url", None)
            if url:
                attributes["source_url"] = url

        category = state.get("category")
        if category:
            attributes["category"] = category.value if hasattr(category, "value") else str(category)

        if title:
            attributes["title"] = title

        return cls(
            id=str(article_id),
            content=full_content,
            timestamp=timestamp,
            embedding=embedding,
            attributes=attributes,
        )
