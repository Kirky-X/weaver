# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Entity Aggregator for MAGMA multi-graph memory.

Aggregates entity neighborhood information to support entity-centric queries.
Implements the EntityAggregator component from MAGMA specification.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from core.observability import get_logger
from modules.memory.core.graph_types import (
    AggregationResult,
    AggregationType,
)

if TYPE_CHECKING:
    from core.llm.client import LLMClient

log = get_logger(__name__)


class EntityGraphRepoProtocol(Protocol):
    """Protocol for entity graph repository."""

    async def get_entity_neighborhood(
        self,
        entity_name: str,
        entity_type: str | None = None,
        hops: int = 2,
        limit: int = 50,
    ) -> dict[str, Any] | None: ...


class EntityAggregator:
    """Aggregates entity neighborhood information.

    Supports three aggregation modes:
    - FACTS: Extract key factual statements about the entity
    - COUNT: Count events and relationships involving the entity
    - TIMELINE: Generate chronological sequence of entity-related events
    """

    def __init__(
        self,
        entity_repo: EntityGraphRepoProtocol,
        llm: LLMClient,
        max_events: int = 20,
    ) -> None:
        """Initialize the entity aggregator.

        Args:
            entity_repo: Repository for entity graph operations.
            llm: LLM client for content aggregation.
            max_events: Maximum events to process per aggregation.
        """
        self._entity_repo = entity_repo
        self._llm = llm
        self._max_events = max_events

    async def aggregate(
        self,
        entity_name: str,
        aggregation_type: AggregationType,
        hops: int = 2,
    ) -> AggregationResult:
        """Aggregate information about an entity.

        Args:
            entity_name: Canonical name of the entity.
            aggregation_type: Type of aggregation to perform.
            hops: Number of hops for neighborhood expansion.

        Returns:
            AggregationResult with aggregated information.
        """
        log.info(
            "entity_aggregation_started",
            entity=entity_name,
            agg_type=aggregation_type.value,
            hops=hops,
        )

        try:
            # Get entity neighborhood
            neighborhood = await self._entity_repo.get_entity_neighborhood(
                entity_name=entity_name,
                hops=hops,
                limit=self._max_events,
            )

            if neighborhood is None:
                log.warning("entity_not_found", entity=entity_name)
                return AggregationResult(
                    entity_name=entity_name,
                    entity_type="unknown",
                    aggregation_type=aggregation_type,
                    confidence=0.0,
                )

            # Route to appropriate aggregation method, forwarding the caller
            # supplied entity_name so a neighborhood missing "center" still
            # yields a valid entity_name instead of "".
            if aggregation_type == AggregationType.FACTS:
                return await self._aggregate_facts(neighborhood, entity_name=entity_name)
            elif aggregation_type == AggregationType.COUNT:
                return await self._aggregate_count(neighborhood, entity_name=entity_name)
            elif aggregation_type == AggregationType.TIMELINE:
                return await self._aggregate_timeline(neighborhood, entity_name=entity_name)
            else:
                log.warning("unknown_aggregation_type", agg_type=aggregation_type)
                return AggregationResult(
                    entity_name=entity_name,
                    entity_type="unknown",
                    aggregation_type=aggregation_type,
                    confidence=0.0,
                )

        except Exception as exc:
            log.error(
                "entity_aggregation_failed",
                entity=entity_name,
                error=str(exc),
            )
            return AggregationResult(
                entity_name=entity_name,
                entity_type="unknown",
                aggregation_type=aggregation_type,
                confidence=0.0,
            )

    async def _aggregate_facts(
        self,
        neighborhood: dict[str, Any],
        entity_name: str = "",
    ) -> AggregationResult:
        """Extract key facts about the entity using LLM.

        Args:
            neighborhood: Entity neighborhood data.

        Returns:
            AggregationResult with extracted facts.
        """
        resolved_name = neighborhood.get("center") or entity_name or ""
        # Build context from neighborhood
        context = self._build_neighborhood_context(neighborhood)

        try:
            # Use LLM to extract facts
            response = await self._llm.call_at(
                call_point="ENTITY_FACTS",
                payload={
                    "entity_name": resolved_name,
                    "context": context,
                    "task": "extract_facts",
                },
            )

            # Parse response with type coercion: LLM may return confidence as
            # a string like "high" and facts as a bare string or mixed list.
            if isinstance(response, dict):
                raw_facts = response.get("facts", [])
                if isinstance(raw_facts, str):
                    facts: list[str] = [raw_facts] if raw_facts.strip() else []
                elif isinstance(raw_facts, list):
                    facts = [str(f) for f in raw_facts if isinstance(f, (str, int, float))]
                else:
                    facts = []
                entity_type = response.get("entity_type", "unknown")
                if not isinstance(entity_type, str):
                    entity_type = str(entity_type)
                reasoning = response.get("reasoning", "")
                if not isinstance(reasoning, str):
                    reasoning = str(reasoning)
                confidence = response.get("confidence", 0.7)
                if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
                    log.warning(
                        "fact_confidence_non_numeric",
                        entity=resolved_name,
                        confidence_type=type(confidence).__name__,
                    )
                    confidence = 0.5
                confidence = float(confidence)
            else:
                # Fallback: treat response as raw text
                facts = [line.strip() for line in str(response).split("\n") if line.strip()]
                entity_type = "unknown"
                reasoning = ""
                confidence = 0.5

            return AggregationResult(
                entity_name=resolved_name,
                entity_type=entity_type,
                aggregation_type=AggregationType.FACTS,
                facts=facts[:10],  # Limit to top 10 facts
                reasoning_trace=reasoning,
                confidence=confidence,
            )

        except Exception as exc:
            log.warning("fact_extraction_failed", error=str(exc))
            return AggregationResult(
                entity_name=resolved_name,
                entity_type="unknown",
                aggregation_type=AggregationType.FACTS,
                confidence=0.0,
            )

    async def _aggregate_count(
        self,
        neighborhood: dict[str, Any],
        entity_name: str = "",
    ) -> AggregationResult:
        """Count events and relationships involving the entity.

        Args:
            neighborhood: Entity neighborhood data.

        Returns:
            AggregationResult with counts.
        """
        events = neighborhood.get("events", [])
        related_entities = neighborhood.get("related_entities", [])
        relations = neighborhood.get("relations", [])

        event_count = len(events)
        related_entity_count = len(related_entities)
        relation_count = len(relations)

        # The center entity's own type when the neighborhood supplies it;
        # neighbor types carry no information about the center, so we must
        # not infer from them (corr#369) — default to "unknown".
        entity_type = neighborhood.get("center_type") or "unknown"

        resolved_name = neighborhood.get("center") or entity_name or ""
        # Build summary reasoning
        reasoning = (
            f"Entity {resolved_name} appears in {event_count} events, "
            f"has {related_entity_count} related entities, "
            f"and {relation_count} relationships."
        )

        return AggregationResult(
            entity_name=resolved_name,
            entity_type=entity_type,
            aggregation_type=AggregationType.COUNT,
            count=event_count,
            reasoning_trace=reasoning,
            confidence=min(1.0, event_count / 10),  # Higher count = higher confidence
        )

    async def _aggregate_timeline(
        self,
        neighborhood: dict[str, Any],
        entity_name: str = "",
    ) -> AggregationResult:
        """Generate chronological sequence of entity-related events.

        Args:
            neighborhood: Entity neighborhood data.

        Returns:
            AggregationResult with timeline facts.
        """
        events = neighborhood.get("events", [])
        related_entities = neighborhood.get("related_entities", [])

        # Sort events by timestamp
        events_with_time = [e for e in events if e.get("timestamp")]
        sorted_events = sorted(
            events_with_time,
            key=lambda e: e.get("timestamp", ""),
        )

        # Build timeline facts
        timeline_facts = []
        for event in sorted_events[:10]:  # Limit to 10 events
            timestamp = event.get("timestamp", "Unknown time")
            content = event.get("content", "")[:100]  # Truncate content
            fact = f"[{timestamp}] {content}"
            timeline_facts.append(fact)

        entity_type = "unknown"
        if related_entities:
            entity_type = related_entities[0].get("type", "unknown")

        return AggregationResult(
            entity_name=neighborhood.get("center") or entity_name or "",
            entity_type=entity_type,
            aggregation_type=AggregationType.TIMELINE,
            facts=timeline_facts,
            count=len(sorted_events),
            reasoning_trace=f"Timeline generated from {len(sorted_events)} events.",
            confidence=min(1.0, len(sorted_events) / 5),
        )

    def _build_neighborhood_context(
        self,
        neighborhood: dict[str, Any],
    ) -> str:
        """Build context string from neighborhood data.

        Args:
            neighborhood: Entity neighborhood data.

        Returns:
            Formatted context string.
        """
        parts: list[str] = []

        # Add entity info
        parts.append(f"Entity: {neighborhood.get('center', '')}")
        parts.append(f"Hops: {neighborhood.get('hops', 2)}")

        # Add events
        events = neighborhood.get("events", [])
        if events:
            parts.append("\nRelated Events:")
            for i, event in enumerate(events[:10]):
                content = event.get("content", "")[:200]
                timestamp = event.get("timestamp", "unknown")
                parts.append(f"  {i + 1}. [{timestamp}] {content}")

        # Add related entities
        related_entities = neighborhood.get("related_entities", [])
        if related_entities:
            parts.append("\nRelated Entities:")
            for entity in related_entities[:10]:
                name = entity.get("canonical_name", entity.get("name", "unknown"))
                etype = entity.get("type", "unknown")
                parts.append(f"  - {name} ({etype})")

        # Add relations
        relations = neighborhood.get("relations", [])
        if relations:
            parts.append("\nRelations:")
            for rel in relations[:10]:
                source = rel.get("source", "unknown")
                target = rel.get("target", "unknown")
                rel_type = rel.get("type", "related_to")
                parts.append(f"  - {source} --[{rel_type}]--> {target}")

        return "\n".join(parts)
