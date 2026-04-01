# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Entity resolver for entity deduplication and canonical name resolution.

Enhanced version with rule-based resolution and name normalization.
"""

from __future__ import annotations

from typing import Any

from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from core.llm.client import LLMClient
from core.observability.logging import get_logger
from core.protocols import EntityRepository, VectorRepository
from modules.knowledge.graph.name_normalizer import (
    NameNormalizer,
)
from modules.knowledge.graph.resolution_rules import (
    EntityResolutionRules,
    MatchType,
)

log = get_logger("entity_resolver")


class ConstraintError(Exception):
    """Exception raised when Neo4j constraint is violated."""

    pass


def _is_constraint_error(exc: Exception) -> bool:
    """Check if exception is a Constraint error."""
    return "ConstraintError" in str(type(exc).__name__)


class EntityResolver:
    """Resolves entities using rule-based matching, vector similarity, and LLM.

    Resolution pipeline:
    1. Normalize the input name
    2. Check for exact match in Neo4j
    3. Apply rule-based resolution (aliases, abbreviations, translations)
    4. Use vector similarity to find candidates
    5. Use LLM for ambiguous cases
    6. Resolve canonical name with preference rules

    Args:
        entity_repo: Neo4j entity repository.
        vector_repo: Vector repository for pgvector operations.
        llm: LLM client for deduplication decisions.
        resolution_rules: Custom resolution rules (optional).
        name_normalizer: Custom name normalizer (optional).
    """

    SIMILARITY_THRESHOLD = 0.85
    MAX_MERGE_RETRIES = 3
    HIGH_CONFIDENCE_THRESHOLD = 0.9

    def __init__(
        self,
        entity_repo: EntityRepository | None,
        vector_repo: VectorRepository,
        llm: LLMClient | None = None,
        resolution_rules: EntityResolutionRules | None = None,
        name_normalizer: NameNormalizer | None = None,
    ) -> None:
        self._entity_repo = entity_repo
        self._vector_repo = vector_repo
        self._llm = llm
        self._rules = resolution_rules or EntityResolutionRules()
        self._normalizer = name_normalizer or NameNormalizer()

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
            - match_type: Type of match (exact, alias, fuzzy, etc.)
            - confidence: Resolution confidence score
        """
        # Filter out metric strings classified as entities.
        # "本土市场游戏收入1642亿元" has no stable identity — it's a data point,
        # not an entity that should live as a node in the knowledge graph.
        if entity_type == "数据指标" and self._looks_like_metric_string(name):
            return {
                "neo4j_id": "",
                "canonical_name": name,
                "is_new": False,
                "merged": False,
                "match_type": "filtered_metric",
                "confidence": 0.0,
            }

        norm_result = self._normalizer.normalize(name, entity_type)
        normalized_name = norm_result.normalized

        existing = await self._entity_repo.find_entity(normalized_name, entity_type)
        if existing:
            return {
                "neo4j_id": existing["neo4j_id"],
                "canonical_name": existing["canonical_name"],
                "is_new": False,
                "merged": False,
                "match_type": "exact",
                "confidence": 1.0,
            }

        if normalized_name != name:
            existing = await self._entity_repo.find_entity(name, entity_type)
            if existing:
                return {
                    "neo4j_id": existing["neo4j_id"],
                    "canonical_name": existing["canonical_name"],
                    "is_new": False,
                    "merged": False,
                    "match_type": "normalized_exact",
                    "confidence": 0.95,
                }

        if not embedding:
            canonical = self._rules.get_canonical_suggestion(name, entity_type)
            return await self._create_entity(
                name=canonical,
                entity_type=entity_type,
                embedding=embedding,
                description=description,
                is_new=True,
                match_type="new",
                confidence=1.0,
            )

        similar = await self._vector_repo.find_similar_entities(
            embedding=embedding,
            threshold=self.SIMILARITY_THRESHOLD,
            limit=10,
        )

        if not similar:
            canonical = self._rules.get_canonical_suggestion(name, entity_type)
            return await self._create_entity(
                name=canonical,
                entity_type=entity_type,
                embedding=embedding,
                description=description,
                is_new=True,
                match_type="new",
                confidence=1.0,
            )

        # Batch lookup entities by ID to avoid N+1 queries
        neo4j_ids = [sim.neo4j_id for sim in similar]
        entities_by_id = await self._entity_repo.find_entities_by_ids(neo4j_ids)
        entities_map = {e["neo4j_id"]: e for e in entities_by_id}

        candidates = []
        for sim in similar:
            entity = entities_map.get(sim.neo4j_id)
            if entity:
                entity["similarity"] = sim.similarity
                candidates.append(entity)

        if not candidates:
            canonical = self._rules.get_canonical_suggestion(name, entity_type)
            return await self._create_entity(
                name=canonical,
                entity_type=entity_type,
                embedding=embedding,
                description=description,
                is_new=True,
                match_type="new",
                confidence=1.0,
            )

        rule_result = self._rules.resolve(name, entity_type, candidates)
        if rule_result.match_type != MatchType.NONE:
            if rule_result.confidence >= self.HIGH_CONFIDENCE_THRESHOLD:
                target = next(
                    (
                        c
                        for c in candidates
                        if c.get("canonical_name") == rule_result.canonical_name
                    ),
                    None,
                )
                if target:
                    return await self._merge_with_existing(
                        new_name=name,
                        entity_type=entity_type,
                        target=target,
                        embedding=embedding,
                        match_type=rule_result.match_type.value,
                        confidence=rule_result.confidence,
                    )

        if self._llm:
            decision = await self._llm_deduplicate(
                query_name=name,
                entity_type=entity_type,
                candidates=candidates,
            )

            if decision.get("should_merge"):
                target = decision.get("target_entity")
                if target:
                    return await self._merge_with_existing(
                        new_name=name,
                        entity_type=entity_type,
                        target=target,
                        embedding=embedding,
                        match_type="llm_dedup",
                        confidence=decision.get("confidence", 0.8),
                    )

        canonical_name = self._resolve_canonical_name(
            query_name=name,
            entity_type=entity_type,
            candidates=candidates,
        )

        resolved = await self._entity_repo.find_entity(canonical_name, entity_type)
        if resolved:
            await self._entity_repo.add_alias(canonical_name, entity_type, name)
            return {
                "neo4j_id": resolved["neo4j_id"],
                "canonical_name": resolved["canonical_name"],
                "is_new": False,
                "merged": True,
                "match_type": "alias_added",
                "confidence": 0.9,
            }

        return await self._create_entity(
            name=canonical_name,
            entity_type=entity_type,
            embedding=embedding,
            description=description,
            is_new=True,
            match_type="new_canonical",
            confidence=0.9,
        )

    async def _create_entity(
        self,
        name: str,
        entity_type: str,
        embedding: list[float],
        description: str | None,
        is_new: bool,
        match_type: str,
        confidence: float,
    ) -> dict[str, Any]:
        """Create a new entity with retry on constraint violation.

        Uses tenacity for exponential backoff.
        Handles Constraint violation errors from Neo4j.
        """
        retryer = AsyncRetrying(
            reraise=True,
            stop=stop_after_attempt(3),
            wait=wait_exponential_jitter(initial=0.05, max=0.5, jitter=0.02),
            retry=retry_if_exception_type(ConstraintError),
        )

        async for attempt in retryer:
            with attempt:
                try:
                    neo4j_id = await self._entity_repo.merge_entity(
                        canonical_name=name,
                        entity_type=entity_type,
                        description=description,
                    )
                    if embedding:
                        await self._vector_repo.upsert_entity_vector(neo4j_id, embedding)
                    return {
                        "neo4j_id": neo4j_id,
                        "canonical_name": name,
                        "is_new": is_new,
                        "merged": False,
                        "match_type": match_type,
                        "confidence": confidence,
                    }
                except Exception as exc:
                    if _is_constraint_error(exc):
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
                                "match_type": "concurrent_create",
                                "confidence": 0.95,
                            }
                        raise ConstraintError(str(exc)) from exc
                    raise

        raise RuntimeError("Failed to create entity after retries")

    async def _merge_with_existing(
        self,
        new_name: str,
        entity_type: str,
        target: dict[str, Any],
        embedding: list[float],
        match_type: str,
        confidence: float,
    ) -> dict[str, Any]:
        """Merge new entity with existing entity."""
        canonical_name = target["canonical_name"]
        neo4j_id = target["neo4j_id"]

        if new_name != canonical_name:
            await self._entity_repo.add_alias(canonical_name, entity_type, new_name)

        if embedding:
            await self._vector_repo.upsert_entity_vector(neo4j_id, embedding)

        return {
            "neo4j_id": neo4j_id,
            "canonical_name": canonical_name,
            "is_new": False,
            "merged": True,
            "match_type": match_type,
            "confidence": confidence,
        }

    async def _llm_deduplicate(
        self,
        query_name: str,
        entity_type: str,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Use LLM to determine if entities should be merged."""
        if not self._llm:
            return {"should_merge": False}

        candidate_text = "\n".join(
            [
                f"- {c.get('canonical_name', 'unknown')} "
                f"(type: {c.get('type', 'unknown')}, "
                f"similarity: {c.get('similarity', 0):.2f})"
                for c in candidates[:5]
            ]
        )

        prompt = f"""Given a new entity name and existing candidate entities, determine if they refer to the same real-world entity.

New entity:
- Name: {query_name}
- Type: {entity_type}

Candidate entities:
{candidate_text}

Respond with JSON:
{{
  "should_merge": true/false,
  "confidence": 0.0-1.0,
  "reason": "brief explanation",
  "target_entity": {{"canonical_name": "...", "neo4j_id": "..."}} (only if should_merge is true)
}}

Consider:
- Same person, organization, or location should be merged
- Different entities with similar names should NOT be merged
- Consider if they could be aliases, abbreviations, or translations of each other
- Entity type should match for merge"""

        try:
            result = await self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            )
            import re

            import json_repair

            content = result.content if hasattr(result, "content") else str(result)
            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if json_match:
                return json_repair.loads(json_match.group())
        except Exception as e:
            log.warning("llm_dedupe_failed", error=str(e))

        return {"should_merge": False}

    def _looks_like_metric_string(self, name: str) -> bool:
        """Check if a name is a metric string rather than a stable entity name.

        Metric strings describe data points (e.g., "本土市场游戏收入1642亿元")
        and have no stable identity — they should not become entity nodes.

        Filters:
        - Percentages: "12.73%", "9.90%"
        - Monetary values: "97.65亿元", "6亿元", "756.97亿元"
        - Share counts: "2.42亿股"
        - Composite metrics: "本土市场游戏收入1642亿元"
        - Pure numeric expressions with units
        """
        import re

        if not name:
            return False

        name = name.strip()

        # Pattern 1: Pure percentage (e.g., "12.73%", "9.90%")
        if re.match(r"^[\d,．.]+\s*%$", name):
            return True

        # Pattern 2: Monetary values with Chinese units (e.g., "97.65亿元", "6亿元")
        if re.match(r"^[\d,．.]+\s*[万亿]元$", name):
            return True

        # Pattern 3: Share/stock counts (e.g., "2.42亿股")
        if re.match(r"^[\d,．.]+\s*[万亿]?股$", name):
            return True

        # Pattern 4: Other numeric expressions with units (e.g., "1.4亿", "1642亿元")
        if re.match(r"^[\d,．.]+\s*[万亿亿千万百十]+[元股人]?$", name):
            return True

        # Pattern 5: Composite metric descriptions (Chinese + number + unit)
        # e.g., "本土市场游戏收入1642亿元", "月活1.4亿"
        composite_pattern = re.compile(
            r"[\u4e00-\u9fff]"  # has Chinese
            + r".*"  # middle content
            + r"[\u4e00-\u9fff]"  # more Chinese (descriptor word)
            + r".*?"  # optional middle
            + r"\d[\d,．.]*[万亿亿千万百十零点]?[元股人]?元?"
        )
        if composite_pattern.search(name):
            return True

        # Pattern 6: Dividend/bonus expressions (e.g., "每10股派发现金红利0.86元(含税)")
        return bool(re.search(r"每\d+股.*红利.*元", name))

    def _resolve_canonical_name(
        self,
        query_name: str,
        entity_type: str,
        candidates: list[dict[str, Any]],
    ) -> str:
        """Resolve canonical name according to preference rules.

        Priority:
        1. Existing canonical name from high-similarity candidate
        2. Chinese name preferred for Chinese context
        3. Shorter, cleaner name
        """
        if not candidates:
            return query_name

        rule_suggestion = self._rules.get_canonical_suggestion(query_name, entity_type)
        if rule_suggestion != query_name:
            return rule_suggestion

        names = [query_name] + [c.get("canonical_name", "") for c in candidates]
        names = [n for n in names if n]

        return self._normalizer.select_canonical(names, entity_type)

    async def resolve_entities_batch(
        self,
        entities: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Resolve a batch of entities in parallel.

        Args:
            entities: List of entity dicts with 'name', 'type', 'embedding'.

        Returns:
            List of resolved entity dicts.
        """
        import asyncio

        tasks = [
            self.resolve_entity(
                name=entity.get("name", ""),
                entity_type=entity.get("type", "未知"),
                embedding=entity.get("embedding", []),
                description=entity.get("description"),
            )
            for entity in entities
        ]
        return await asyncio.gather(*tasks)

    async def pre_resolve_check(
        self,
        name: str,
        entity_type: str,
    ) -> dict[str, Any] | None:
        """Quick pre-check for entity existence without embedding.

        Useful for fast lookups before expensive embedding computation.

        Args:
            name: Entity name to check.
            entity_type: Entity type.

        Returns:
            Existing entity info or None.
        """
        norm_result = self._normalizer.normalize(name, entity_type)
        normalized_name = norm_result.normalized

        existing = await self._entity_repo.find_entity(normalized_name, entity_type)
        if existing:
            return {
                "neo4j_id": existing["neo4j_id"],
                "canonical_name": existing["canonical_name"],
                "exists": True,
            }

        if normalized_name != name:
            existing = await self._entity_repo.find_entity(name, entity_type)
            if existing:
                return {
                    "neo4j_id": existing["neo4j_id"],
                    "canonical_name": existing["canonical_name"],
                    "exists": True,
                }

        for alias in self._rules.get_all_aliases(name):
            existing = await self._entity_repo.find_entity(alias, entity_type)
            if existing:
                return {
                    "neo4j_id": existing["neo4j_id"],
                    "canonical_name": existing["canonical_name"],
                    "exists": True,
                    "matched_alias": alias,
                }

        return None

    def get_resolution_stats(self) -> dict[str, Any]:
        """Get statistics about resolution rules and mappings."""
        return {
            "known_aliases": len(self._rules._alias_map),
            "abbreviations": len(self._rules._abbreviation_map) // 3,
            "translations": len(self._rules._translation_map) // 2,
            "rules_count": len(self._rules._rules),
        }
