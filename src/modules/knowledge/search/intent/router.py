# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Intent-aware router - MAGMA-inspired dynamic routing."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from core.llm.client import LLMClient
from core.observability.logging import get_logger
from modules.knowledge.search.engines.global_search import GlobalSearchEngine
from modules.knowledge.search.engines.local_search import LocalSearchEngine
from modules.knowledge.search.temporal.parser import TemporalParser

from .classifier import IntentClassifier
from .schemas import IntentClassification, QueryIntent

if TYPE_CHECKING:
    from modules.storage.postgres.vector_repo import VectorRepo

log = get_logger("search.intent.router")


@dataclass
class RoutingConfig:
    """Configuration for routing behavior."""

    enable_intent_routing: bool = True
    """Whether intent-aware routing is enabled."""

    fallback_mode: str = "local"
    """Fallback search mode if classification fails."""


class IntentRouter:
    """Intent-aware router - MAGMA-inspired dynamic routing."""

    def __init__(
        self,
        local_engine: LocalSearchEngine,
        global_engine: GlobalSearchEngine,
        vector_repo: Optional["VectorRepo"] = None,
        hybrid_engine: object | None = None,
        llm: LLMClient | None = None,
        temporal_parser: TemporalParser | None = None,
        config: RoutingConfig | None = None,
    ) -> None:
        """Initialize intent router with search engines.

        Args:
            local_engine: Local search engine for WHY/WHEN/ENTITY queries.
            global_engine: Global search engine for MULTI_HOP/OPEN queries.
            vector_repo: Optional vector repository for direct article search.
            hybrid_engine: Optional hybrid search engine.
            llm: LLM client for intent classification.
            temporal_parser: Optional temporal parser for time window resolution.
            config: Optional routing configuration.
        """
        self._local = local_engine
        self._global = global_engine
        self._vector = vector_repo
        self._hybrid = hybrid_engine
        self._llm = llm
        self._temporal = temporal_parser or TemporalParser()
        self._config = config or RoutingConfig()

        # MAGMA-inspired intent-to-engine mapping
        self._intent_map: dict[QueryIntent, object] = {
            QueryIntent.WHY: self._search_why,
            QueryIntent.WHEN: self._search_when,
            QueryIntent.ENTITY: self._search_entity,
            QueryIntent.MULTI_HOP: self._search_multi_hop,
            QueryIntent.OPEN: self._search_open,
        }

        # Initialize classifier
        self._classifier = IntentClassifier(llm=llm) if llm else None

    async def route(
        self,
        query: str,
        classification: IntentClassification,
    ) -> dict:
        """Route query to appropriate search engine based on intent.

        Args:
            query: The user's search query.
            classification: Intent classification result.

        Returns:
            Dictionary containing search result and metadata.
        """
        intent = classification.intent

        # Get the search function for this intent
        search_func = self._intent_map.get(intent)

        if search_func is None:
            log.warning("no_search_handler", intent=intent.value)
            search_func = self._search_open

        # Build intent-specific parameters
        params = self._build_intent_params(classification)

        try:
            # Execute the search
            result = await search_func(query, **params)

            # Inject intent metadata into result
            if isinstance(result, dict):
                result["metadata"] = {
                    **result.get("metadata", {}),
                    "intent": intent.value,
                    "intent_confidence": classification.confidence,
                }
            elif hasattr(result, "metadata"):
                result.metadata = {
                    **result.metadata,
                    "intent": intent.value,
                    "intent_confidence": classification.confidence,
                }

            return result
        except Exception as exc:
            log.error("route_failed", query=query, intent=intent.value, error=str(exc))
            # Return fallback result
            return {
                "answer": f"Search failed: {exc!s}",
                "confidence": 0.0,
                "metadata": {
                    "intent": intent.value,
                    "error": str(exc),
                    "fallback_mode": self._config.fallback_mode,
                },
            }

    async def _search_why(self, query: str, **kwargs) -> object:
        """WHY query: prioritize causal reasoning."""
        log.debug("routing_to_why", query=query)
        return await self._local.search(
            query=query,
            use_llm=True,
        )

    async def _search_when(self, query: str, **kwargs) -> object:
        """WHEN query: apply temporal window and sorting."""
        log.debug("routing_to_when", query=query)
        return await self._local.search(
            query=query,
            use_llm=True,
        )

    async def _search_entity(
        self, query: str, entity_names: list[str] | None = None, **kwargs
    ) -> object:
        """ENTITY query: focus on specific entities."""
        log.debug("routing_to_entity", query=query)
        return await self._local.search(
            query=query,
            entity_names=entity_names,
            use_llm=True,
        )

    async def _search_multi_hop(self, query: str, **kwargs) -> object:
        """MULTI_HOP query: use global search with deeper community traversal."""
        log.debug("routing_to_multi_hop", query=query)
        return await self._global.search(
            query=query,
            community_level=1,
            use_llm=True,
        )

    async def _search_open(self, query: str, **kwargs) -> object:
        """OPEN query: comprehensive search across communities."""
        log.debug("routing_to_open", query=query)
        return await self._global.search(
            query=query,
            community_level=0,
            use_llm=True,
        )

    def _build_intent_params(self, classification: IntentClassification) -> dict:
        """Build intent-specific search parameters."""
        params: dict = {}

        if classification.entity_signals:
            params["entity_names"] = classification.entity_signals

        return params
