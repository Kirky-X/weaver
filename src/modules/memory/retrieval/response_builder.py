# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Search Response Builder for MAGMA multi-graph memory.

Coordinates the synthesis pipeline to build comprehensive search responses.
Integrates AdaptiveSearch, EntityAggregator, and NarrativeSynthesizer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.observability.logging import get_logger
from modules.memory.core.graph_types import (
    AggregationType,
    OutputMode,
)

if TYPE_CHECKING:
    from core.llm.client import LLMClient
    from modules.memory.retrieval.adaptive_search import AdaptiveSearchEngine
    from modules.memory.retrieval.entity_aggregator import EntityAggregator
    from modules.memory.retrieval.narrative_synthesizer import NarrativeSynthesizer

log = get_logger("search_response_builder")


class SearchResponseBuilder:
    """Builds comprehensive search responses from retrieved context.

    Orchestrates:
    1. AdaptiveSearch for multi-graph retrieval
    2. EntityAggregator for entity enrichment (optional)
    3. NarrativeSynthesizer for output formatting
    """

    def __init__(
        self,
        search_engine: AdaptiveSearchEngine,
        entity_aggregator: EntityAggregator | None,
        synthesizer: NarrativeSynthesizer,
        llm: LLMClient,
    ) -> None:
        """Initialize the response builder.

        Args:
            search_engine: Adaptive search engine for retrieval.
            entity_aggregator: Optional entity aggregator for enrichment.
            synthesizer: Narrative synthesizer for output formatting.
            llm: LLM client for additional processing.
        """
        self._search_engine = search_engine
        self._entity_aggregator = entity_aggregator
        self._synthesizer = synthesizer
        self._llm = llm

    async def build(
        self,
        query: str,
        output_mode: OutputMode = OutputMode.CONTEXT,
        enrich_entities: bool = False,
        entity_names: list[str] | None = None,
    ) -> dict[str, Any]:
        """Build a comprehensive search response.

        Args:
            query: The search query.
            output_mode: Output format mode.
            enrich_entities: Whether to enrich with entity aggregations.
            entity_names: Optional specific entities to aggregate.

        Returns:
            Complete search response dictionary.
        """
        log.info(
            "response_build_started",
            query=query[:50],
            output_mode=output_mode.value,
            enrich_entities=enrich_entities,
        )

        # 1. Execute adaptive search
        search_results = await self._search_engine.search(query=query)

        # 2. Optionally enrich with entity aggregations
        entity_results: list[dict[str, Any]] = []
        if enrich_entities and self._entity_aggregator:
            entity_results = await self._enrich_entities(
                query=query,
                search_results=search_results,
                entity_names=entity_names,
            )

        # 3. Synthesize output
        synthesis_result = await self._synthesizer.synthesize(
            query=query,
            context_nodes=search_results,
            mode=output_mode,
            include_provenance=True,
        )

        # 4. Build response
        response = {
            "query": query,
            "answer": synthesis_result.output,
            "output_mode": synthesis_result.mode.value,
            "context_tokens": synthesis_result.total_tokens,
            "node_count": synthesis_result.node_count,
            "included_nodes": synthesis_result.included_nodes,
            "summarized_nodes": synthesis_result.summarized_nodes,
            "entities": entity_results,
            "sources": self._extract_sources(search_results),
            "metadata": {
                "search_nodes": len(search_results),
                "enriched_entities": len(entity_results),
                "output_mode": output_mode.value,
            },
        }

        log.info(
            "response_build_complete",
            query=query[:50],
            nodes=synthesis_result.node_count,
            entities=len(entity_results),
        )

        return response

    async def _enrich_entities(
        self,
        query: str,
        search_results: list[dict[str, Any]],
        entity_names: list[str] | None,
    ) -> list[dict[str, Any]]:
        """Enrich response with entity aggregations.

        Args:
            query: The search query.
            search_results: Retrieved search results.
            entity_names: Optional specific entities to aggregate.

        Returns:
            List of entity aggregation results.
        """
        if not self._entity_aggregator:
            return []

        # Determine which entities to aggregate
        entities_to_aggregate: list[str] = []

        if entity_names:
            # Use specified entities
            entities_to_aggregate = entity_names[:5]  # Limit to 5
        else:
            # Extract entities from search results
            seen_entities: set[str] = set()
            for result in search_results:
                entities = result.get("entities", [])
                for entity in entities:
                    if isinstance(entity, dict):
                        name = entity.get("name", "")
                    elif isinstance(entity, str):
                        name = entity
                    else:
                        continue

                    if name and name not in seen_entities and len(entities_to_aggregate) < 5:
                        entities_to_aggregate.append(name)
                        seen_entities.add(name)

        # Aggregate each entity
        results: list[dict[str, Any]] = []
        for entity_name in entities_to_aggregate:
            try:
                agg_result = await self._entity_aggregator.aggregate(
                    entity_name=entity_name,
                    aggregation_type=AggregationType.FACTS,
                    hops=2,
                )
                results.append(
                    {
                        "entity": agg_result.entity_name,
                        "type": agg_result.entity_type,
                        "facts": agg_result.facts,
                        "count": agg_result.count,
                        "confidence": agg_result.confidence,
                    }
                )
            except Exception as exc:
                log.warning(
                    "entity_aggregation_failed",
                    entity=entity_name,
                    error=str(exc),
                )

        return results

    def _extract_sources(
        self,
        search_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Extract source references from search results.

        Args:
            search_results: Retrieved search results.

        Returns:
            List of source dictionaries.
        """
        sources: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        for result in search_results:
            node_id = result.get("id", "")
            if node_id and node_id not in seen_ids:
                sources.append(
                    {
                        "id": node_id,
                        "score": result.get("score", 0.0),
                        "timestamp": result.get("timestamp"),
                    }
                )
                seen_ids.add(node_id)

        return sources[:20]  # Limit to 20 sources
