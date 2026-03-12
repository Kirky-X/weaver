"""Entity resolver for entity deduplication and canonical name resolution."""

from __future__ import annotations

import asyncio
from typing import Any

from core.llm.client import LLMClient
from core.llm.types import CallPoint
from core.observability.logging import get_logger
from modules.storage.neo4j.entity_repo import Neo4jEntityRepo
from modules.storage.vector_repo import VectorRepo

log = get_logger("entity_resolver")


class EntityResolver:
    """Resolves entities using vector similarity and LLM deduplication.

    This resolver:
    1. Uses pgvector to find similar existing entities
    2. Uses LLM to determine if entities should be merged/aliased
    3. Resolves canonical names for new and existing entities
    4. Handles concurrent write conflicts with retry logic

    Args:
        entity_repo: Neo4j entity repository.
        vector_repo: Vector repository for pgvector operations.
        llm: LLM client for deduplication decisions.
    """

    # Similarity threshold for considering entities as candidates
    SIMILARITY_THRESHOLD = 0.85

    # Maximum retry attempts for concurrent constraint violations
    MAX_MERGE_RETRIES = 3

    def __init__(
        self,
        entity_repo: Neo4jEntityRepo,
        vector_repo: VectorRepo,
        llm: LLMClient | None = None,
    ) -> None:
        self._entity_repo = entity_repo
        self._vector_repo = vector_repo
        self._llm = llm

    async def resolve_entity(
        self,
        name: str,
        entity_type: str,
        embedding: list[float],
        description: str | None = None,
    ) -> dict[str, Any]:
        """Resolve an entity, finding matches or creating new.

        Args:
            name: The entity name to resolve.
            entity_type: The entity type.
            embedding: The embedding vector for the entity.
            description: Optional description.

        Returns:
            Dict containing:
            - neo4j_id: The resolved entity's Neo4j ID
            - canonical_name: The canonical name used
            - is_new: Whether this is a newly created entity
            - merged: Whether it was merged with existing entity
        """
        # 1. Check if exact match exists
        existing = await self._entity_repo.find_entity(name, entity_type)
        if existing:
            return {
                "neo4j_id": existing["neo4j_id"],
                "canonical_name": existing["canonical_name"],
                "is_new": False,
                "merged": False,
            }

        # 2. Use vector similarity to find candidates
        similar = await self._vector_repo.find_similar_entities(
            embedding=embedding,
            threshold=self.SIMILARITY_THRESHOLD,
            limit=5,
        )

        if not similar:
            # No similar entities found, create new
            return await self._create_entity(
                name=name,
                entity_type=entity_type,
                embedding=embedding,
                description=description,
                is_new=True,
            )

        # 3. Get full entity info for candidates
        candidates = []
        for sim in similar:
            entity = await self._entity_repo.find_entity_by_id(sim.neo4j_id)
            if entity:
                entity["similarity"] = sim.similarity
                candidates.append(entity)

        if not candidates:
            return await self._create_entity(
                name=name,
                entity_type=entity_type,
                embedding=embedding,
                description=description,
                is_new=True,
            )

        # 4. Use LLM to determine if should merge, or resolve canonical name
        if self._llm:
            decision = await self._llm_deduplicate(
                query_name=name,
                candidates=candidates,
            )

            if decision.get("should_merge"):
                # Merge with existing entity
                target = decision["target_entity"]
                return await self._merge_with_existing(
                    new_name=name,
                    entity_type=entity_type,
                    target=target,
                    embedding=embedding,
                )
            else:
                # Resolve canonical name
                canonical_name = await self._resolve_canonical_name(
                    query_name=name,
                    candidates=candidates,
                )
                # Check if resolved canonical exists
                resolved = await self._entity_repo.find_entity(
                    canonical_name, entity_type
                )
                if resolved:
                    # Add as alias
                    await self._entity_repo.add_alias(
                        canonical_name, entity_type, name
                    )
                    return {
                        "neo4j_id": resolved["neo4j_id"],
                        "canonical_name": resolved["canonical_name"],
                        "is_new": False,
                        "merged": True,
                    }
                else:
                    return await self._create_entity(
                        name=canonical_name,
                        entity_type=entity_type,
                        embedding=embedding,
                        description=description,
                        is_new=True,
                    )
        else:
            # No LLM, use first candidate with highest similarity
            top_candidate = max(candidates, key=lambda x: x["similarity"])
            return await self._merge_with_existing(
                new_name=name,
                entity_type=entity_type,
                target=top_candidate,
                embedding=embedding,
            )

    async def _create_entity(
        self,
        name: str,
        entity_type: str,
        embedding: list[float],
        description: str | None,
        is_new: bool,
    ) -> dict[str, Any]:
        """Create a new entity with retry on constraint violation."""
        for attempt in range(self.MAX_MERGE_RETRIES):
            try:
                neo4j_id = await self._entity_repo.merge_entity(
                    canonical_name=name,
                    entity_type=entity_type,
                    description=description,
                )
                await self._vector_repo.upsert_entity_vector(neo4j_id, embedding)
                return {
                    "neo4j_id": neo4j_id,
                    "canonical_name": name,
                    "is_new": is_new,
                    "merged": False,
                }
            except Exception as exc:
                if "ConstraintError" in str(type(exc).__name__):
                    if attempt == self.MAX_MERGE_RETRIES - 1:
                        raise
                    # Entity was created by concurrent transaction, fetch it
                    existing = await self._entity_repo.find_entity(name, entity_type)
                    if existing:
                        await self._vector_repo.upsert_entity_vector(
                            existing["neo4j_id"], embedding
                        )
                        return {
                            "neo4j_id": existing["neo4j_id"],
                            "canonical_name": existing["canonical_name"],
                            "is_new": False,
                            "merged": False,
                        }
                    await asyncio.sleep(0.05 * (attempt + 1))
                else:
                    raise

        raise RuntimeError("Failed to create entity after retries")

    async def _merge_with_existing(
        self,
        new_name: str,
        entity_type: str,
        target: dict[str, Any],
        embedding: list[float],
    ) -> dict[str, Any]:
        """Merge new entity with existing entity."""
        canonical_name = target["canonical_name"]
        neo4j_id = target["neo4j_id"]

        # Add new name as alias if different
        if new_name != canonical_name:
            await self._entity_repo.add_alias(canonical_name, entity_type, new_name)

        # Update vector if needed
        await self._vector_repo.upsert_entity_vector(neo4j_id, embedding)

        return {
            "neo4j_id": neo4j_id,
            "canonical_name": canonical_name,
            "is_new": False,
            "merged": True,
        }

    async def _llm_deduplicate(
        self,
        query_name: str,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Use LLM to determine if entities should be merged.

        Args:
            query_name: The new entity name to evaluate.
            candidates: List of existing similar entities.

        Returns:
            Dict with 'should_merge' and optionally 'target_entity'.
        """
        if not self._llm:
            return {"should_merge": False}

        # Build prompt for LLM
        candidate_text = "\n".join([
            f"- {c.get('canonical_name', 'unknown')} (similarity: {c.get('similarity', 0):.2f})"
            for c in candidates[:3]
        ])

        prompt = f"""Given a new entity name and existing candidate entities, determine if they refer to the same real-world entity.

New entity name: {query_name}

Candidate entities:
{candidate_text}

Respond with JSON:
{{
  "should_merge": true/false,
  "reason": "brief explanation",
  "target_entity": {{"canonical_name": "...", "neo4j_id": "..."}} (only if should_merge is true)
}}

Consider:
- Same person, organization, or location should be merged
- Different entities with similar names should NOT be merged
- Consider if they could be aliases or translations of each other"""

        try:
            result = await self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            )
            # Parse JSON from response
            import json
            content = result.content if hasattr(result, "content") else str(result)
            # Try to extract JSON
            import re
            json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except Exception as e:
            log.warning("llm_dedupe_failed", error=str(e))

        # Fallback: don't merge
        return {"should_merge": False}

    async def _resolve_canonical_name(
        self,
        query_name: str,
        candidates: list[dict[str, Any]],
    ) -> str:
        """Resolve canonical name according to rules from neo4j-detail.md.

        Rules (by priority):
        1. If candidates exist with canonical_name, use that (don't change)
        2. If candidates come from authoritative sources (tier=1), use that name
        3. Otherwise prefer Chinese name (system面向中文场景)

        Args:
            query_name: The new entity name to resolve.
            candidates: List of existing similar entities.

        Returns:
            The canonical name to use.
        """
        if not candidates:
            return query_name

        # Rule 1: If any candidate has existing canonical, use that
        # (already handled by exact match at start)

        # For candidates from vector search, pick best based on rules
        # Simplified: use the candidate with highest similarity
        # In production, could incorporate source authority data
        best = max(candidates, key=lambda x: x.get("similarity", 0))
        return best.get("canonical_name", query_name)

    async def resolve_entities_batch(
        self,
        entities: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Resolve a batch of entities efficiently.

        Args:
            entities: List of entity dicts with 'name', 'type', 'embedding'.

        Returns:
            List of resolved entity dicts.
        """
        results = []
        for entity in entities:
            result = await self.resolve_entity(
                name=entity.get("name", ""),
                entity_type=entity.get("type", "未知"),
                embedding=entity.get("embedding", []),
                description=entity.get("description"),
            )
            results.append(result)
        return results
