# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Causal Edge Inference Service.

Infers CAUSES, ENABLES, PREVENTS edges from existing entity relationships
using LLM-based semantic analysis.

This service:
1. Analyzes entity relationships (INVESTS_IN, 合资, ACQUIRES, etc.)
2. Identifies potential causal chains
3. Uses LLM to determine causal type and confidence
4. Creates causal edges between EventNodes or Entity-derived events

Reference: GraphRAG's causal reasoning methodology
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from core.constants import DatabaseType
from core.llm.types import CallPoint
from core.observability import get_logger
from modules.memory.core.graph_types import CausalRelationType

log = get_logger(__name__)


class RelationCategory(Enum):
    """Categories of relationships for causal inference."""

    INVESTMENT = "investment"  # INVESTS_IN, 投资
    PARTNERSHIP = "partnership"  # PARTNERS_WITH, 合资, 合作
    ACQUISITION = "acquisition"  # ACQUIRES, 收购
    CONTROL = "control"  # CONTROLS, 管理
    PARTICIPATION = "participation"  # PARTICIPATES_IN, 参与
    INFLUENCE = "influence"  # INFLUENCES, 影响
    REGULATION = "regulation"  # REGULATES, 监管
    SUPPLY = "supply"  # 供应, 生产
    COMPETITION = "competition"  # 竞争
    OTHER = "other"


@dataclass
class CausalInference:
    """Result of causal inference for a relationship."""

    source_entity: str
    target_entity: str
    original_relation: str
    causal_type: CausalRelationType
    confidence: float
    evidence: str
    source_event_id: str | None = None
    target_event_id: str | None = None


@dataclass
class InferenceConfig:
    """Configuration for causal inference service."""

    batch_size: int = 20
    confidence_threshold: float = 0.6
    max_relations_per_entity: int = 50
    llm_timeout_seconds: int = 30
    enable_parallel_inference: bool = True


# Mapping of relation types to categories for causal inference
RELATION_CATEGORY_MAP: dict[str, RelationCategory] = {
    "INVESTS_IN": RelationCategory.INVESTMENT,
    "投资": RelationCategory.INVESTMENT,
    "PARTNERS_WITH": RelationCategory.PARTNERSHIP,
    "合资": RelationCategory.PARTNERSHIP,
    "合作": RelationCategory.PARTNERSHIP,
    "ACQUIRES": RelationCategory.ACQUISITION,
    "收购": RelationCategory.ACQUISITION,
    "CONTROLS": RelationCategory.CONTROL,
    "管理": RelationCategory.CONTROL,
    "PARTICIPATES_IN": RelationCategory.PARTICIPATION,
    "参与": RelationCategory.PARTICIPATION,
    "INFLUENCES": RelationCategory.INFLUENCE,
    "影响": RelationCategory.INFLUENCE,
    "REGULATES": RelationCategory.REGULATION,
    "监管": RelationCategory.REGULATION,
}


class CausalInferenceService:
    """Service for inferring causal relationships from entity data."""

    def __init__(
        self,
        pool: Any,
        llm_client: Any,
        causal_repo: Any,
        config: InferenceConfig | None = None,
    ) -> None:
        """Initialize causal inference service.

        Args:
            pool: Graph database pool (Neo4j or LadybugDB).
            llm_client: LLM client for semantic analysis.
            causal_repo: CausalGraphRepo for storing inferred edges.
            config: Service configuration.
        """
        self._pool = pool
        self._llm = llm_client
        self._causal_repo = causal_repo
        self._config = config or InferenceConfig()
        self._is_ladybug = pool.database_type == DatabaseType.LADYBUG.value

    async def infer_and_create_causal_edges(
        self,
        entity_names: list[str] | None = None,
        relation_types: list[str] | None = None,
    ) -> dict[str, int]:
        """Infer and create causal edges from entity relationships.

        Args:
            entity_names: Optional filter for specific entities.
            relation_types: Optional filter for specific relation types.

        Returns:
            Dict with stats: edges_created, edges_filtered, errors
        """
        stats = {
            "edges_created": 0,
            "edges_filtered": 0,
            "errors": 0,
            "relations_analyzed": 0,
        }

        log.info("causal_inference_start", entities=len(entity_names) if entity_names else "all")

        # Step 1: Get entity relationships
        relations = await self._get_entity_relations(entity_names, relation_types)
        stats["relations_analyzed"] = len(relations)

        if not relations:
            log.warning("causal_inference_no_relations")
            return stats

        log.info("causal_inference_relations_found", count=len(relations))

        # Step 2: Batch inference using LLM
        inferences = await self._batch_infer_causality(relations)

        # Step 3: Create causal edges
        for inference in inferences:
            if inference.confidence < self._config.confidence_threshold:
                stats["edges_filtered"] += 1
                continue

            # Get or create EventNodes for entities
            source_event_id = await self._get_or_create_event_node(
                inference.source_entity,
                inference.source_event_id,
            )
            target_event_id = await self._get_or_create_event_node(
                inference.target_entity,
                inference.target_event_id,
            )

            if not source_event_id or not target_event_id:
                stats["errors"] += 1
                continue

            # Add causal edge
            success = await self._causal_repo.add_causal_edge(
                source_id=source_event_id,
                target_id=target_event_id,
                relation_type=inference.causal_type,
                confidence=inference.confidence,
                evidence=inference.evidence,
            )

            if success:
                stats["edges_created"] += 1
            else:
                stats["errors"] += 1

        log.info("causal_inference_complete", **stats)
        return stats

    async def _get_entity_relations(
        self,
        entity_names: list[str] | None,
        relation_types: list[str] | None,
    ) -> list[dict[str, Any]]:
        """Get entity relationships from graph database.

        Args:
            entity_names: Filter by entity names.
            relation_types: Filter by relation types.

        Returns:
            List of relation dicts with source, target, type, description.
        """
        from core.db.safe_query import validate_edge_type

        # Only get relations that are potentially causal
        causal_relation_types = list(RELATION_CATEGORY_MAP.keys())
        limit = self._config.max_relations_per_entity * 10

        # Build query based on filters
        if self._is_ladybug:
            # LadybugDB: fully parameterized query
            type_filter = ""
            if relation_types:
                type_filter = "AND r.edge_type IN $relation_types"

            entity_filter = ""
            if entity_names:
                entity_filter = (
                    "AND (e1.canonical_name IN $entity_names OR e2.canonical_name IN $entity_names)"
                )

            query = f"""
            MATCH (e1:Entity)-[r]->(e2:Entity)
            WHERE r.edge_type IN $causal_types
            {type_filter}
            {entity_filter}
            RETURN e1.canonical_name AS source,
                   e2.canonical_name AS target,
                   r.edge_type AS relation_type,
                   r.properties AS properties
            LIMIT $limit
            """

            params: dict[str, Any] = {
                "causal_types": causal_relation_types,
                "limit": limit,
            }
            if relation_types:
                params["relation_types"] = relation_types
            if entity_names:
                params["entity_names"] = entity_names
        else:
            # Neo4j: relationship types in MATCH pattern cannot be parameterized,
            # validate each type to prevent injection
            validated_causal = [validate_edge_type(t) for t in causal_relation_types]
            causal_types_str = "|".join(validated_causal)

            type_filter = ""
            if relation_types:
                validated_rel = [validate_edge_type(t) for t in relation_types]
                type_filter = "AND type(r) IN $relation_types"

            entity_filter = ""
            if entity_names:
                entity_filter = (
                    "AND (e1.canonical_name IN $entity_names OR e2.canonical_name IN $entity_names)"
                )

            query = f"""
            MATCH (e1:Entity)-[r:{causal_types_str}]->(e2:Entity)
            {type_filter}
            {entity_filter}
            RETURN e1.canonical_name AS source,
                   e2.canonical_name AS target,
                   type(r) AS relation_type,
                   r.description AS description
            LIMIT $limit
            """

            params = {"limit": limit}
            if relation_types:
                params["relation_types"] = relation_types
            if entity_names:
                params["entity_names"] = entity_names

        try:
            results = await self._pool.execute_query(query, params)
            return [dict(r) for r in results]
        except Exception as exc:
            log.error("get_entity_relations_failed", error=str(exc))
            return []

    async def _batch_infer_causality(
        self,
        relations: list[dict[str, Any]],
    ) -> list[CausalInference]:
        """Batch infer causal relationships using LLM.

        Args:
            relations: List of entity relations.

        Returns:
            List of CausalInference objects.
        """
        if not relations:
            return []

        inferences: list[CausalInference] = []

        # Process in batches
        batch_size = self._config.batch_size
        batches = [relations[i : i + batch_size] for i in range(0, len(relations), batch_size)]

        for batch in batches:
            try:
                batch_results = await self._infer_batch(batch)
                inferences.extend(batch_results)
            except Exception as exc:
                log.warning("batch_inference_failed", error=str(exc))

        return inferences

    async def _infer_batch(
        self,
        relations: list[dict[str, Any]],
    ) -> list[CausalInference]:
        """Infer causality for a batch of relations using LLM.

        Args:
            relations: Batch of relations.

        Returns:
            List of inferences.
        """
        # Build prompt for LLM
        relations_text = "\n".join(
            f"- {r['source']} -> {r['target']} (关系: {r['relation_type']})" for r in relations
        )

        system_prompt = """你是一个因果推理专家。分析实体之间的关系，推断可能的因果链。

对于每个关系，判断：
1. 这是否是因果关系（CAUSES）、促成关系（ENABLES）或阻碍关系（PREVENTS）
2. 置信度（0.0-1.0），基于关系的语义强度
3. 简短证据说明（20字以内）

关系类型含义：
- CAUSES: A直接导致B发生
- ENABLES: A为B的发生创造条件
- PREVENTS: A阻止或减少B发生的可能性

输出格式（JSON数组）：
[
  {"source": "实体A", "target": "实体B", "type": "CAUSES|ENABLES|PREVENTS", "confidence": 0.8, "evidence": "简短说明"},
  ...
]

如果关系不能推断为因果关系，置信度设为0。"""

        user_content = f"""分析以下实体关系，推断因果链：

{relations_text}

请输出JSON数组格式的分析结果。"""

        try:
            result = await self._llm.call_at(
                call_point=CallPoint.CAUSAL_INFERENCE,
                payload={
                    "system_prompt": system_prompt,
                    "user_content": user_content,
                },
            )

            # Parse LLM response
            import json

            response_text = str(result) if result else ""

            # Extract JSON array from response
            json_start = response_text.find("[")
            json_end = response_text.rfind("]") + 1

            if json_start >= 0 and json_end > json_start:
                json_str = response_text[json_start:json_end]
                parsed = json.loads(json_str)

                inferences = []
                for item in parsed:
                    try:
                        causal_type = CausalRelationType(item.get("type", "CAUSES"))
                        confidence = float(item.get("confidence", 0.0))

                        # Find matching relation for source/target
                        source = item.get("source", "")
                        target = item.get("target", "")

                        matching_relation = next(
                            (
                                r
                                for r in relations
                                if r["source"] == source and r["target"] == target
                            ),
                            None,
                        )

                        if matching_relation:
                            inference = CausalInference(
                                source_entity=source,
                                target_entity=target,
                                original_relation=matching_relation["relation_type"],
                                causal_type=causal_type,
                                confidence=confidence,
                                evidence=item.get("evidence", ""),
                            )
                            inferences.append(inference)
                    except (ValueError, KeyError) as e:
                        log.debug("parse_inference_item_failed", error=str(e))

                return inferences

        except Exception as exc:
            log.warning("llm_inference_failed", error=str(exc))

        return []

    async def _get_or_create_event_node(
        self,
        entity_name: str,
        existing_event_id: str | None = None,
    ) -> str | None:
        """Get existing EventNode for entity or create one.

        Args:
            entity_name: Entity canonical name.
            existing_event_id: Optional existing event ID.

        Returns:
            EventNode ID or None if failed.
        """
        if existing_event_id:
            return existing_event_id

        # Check if entity has type='事件' (already an event)
        query = """
        MATCH (e:Entity {canonical_name: $entity_name})
        WHERE e.type = '事件'
        RETURN e.id AS event_id
        """

        try:
            result = await self._pool.execute_query(
                query,
                {"entity_name": entity_name},
            )

            if result and result[0].get("event_id"):
                return result[0]["event_id"]

            # Create new EventNode from entity
            return await self._create_event_from_entity(entity_name)

        except Exception as exc:
            log.warning("get_event_node_failed", entity=entity_name, error=str(exc))
            return None

    async def _create_event_from_entity(
        self,
        entity_name: str,
    ) -> str | None:
        """Create EventNode from entity data.

        Args:
            entity_name: Entity canonical name.

        Returns:
            New EventNode ID or None.
        """
        # Get entity details
        if self._is_ladybug:
            query = f"""
            MATCH (e:Entity {{canonical_name: '{entity_name}'}})
            RETURN e.id AS entity_id,
                   e.description AS description,
                   e.created_at AS created_at
            """
        else:
            query = """
            MATCH (e:Entity {canonical_name: $entity_name})
            RETURN e.id AS entity_id,
                   e.description AS description,
                   e.created_at AS created_at
            """

        try:
            result = await self._pool.execute_query(
                query,
                {"entity_name": entity_name} if not self._is_ladybug else {},
            )

            if not result:
                return None

            entity_data = result[0]
            entity_id = entity_data.get("entity_id")
            description = entity_data.get("description", "")
            created_at = entity_data.get("created_at", int(time.time()))

            # Create EventNode
            now = int(time.time())
            event_id = entity_id  # Use entity ID as event ID

            if self._is_ladybug:
                create_query = f"""
                CREATE (e:EventNode {{
                    id: '{event_id}',
                    content: '{entity_name}: {description}',
                    attributes: '{{}}',
                    event_type: 'derived',
                    name: '{entity_name}',
                    description: '{description}',
                    event_time: {created_at},
                    created_at: {now}
                }})
                RETURN e.id AS id
                """
            else:
                create_query = """
                CREATE (e:EventNode {
                    id: $event_id,
                    content: $content,
                    attributes: '{}',
                    event_type: 'derived',
                    name: $name,
                    description: $description,
                    event_time: $event_time,
                    created_at: datetime()
                })
                RETURN e.id AS id
                """

            params = {
                "event_id": event_id,
                "content": f"{entity_name}: {description}",
                "name": entity_name,
                "description": description,
                "event_time": created_at,
            }

            create_result = await self._pool.execute_query(
                create_query,
                params if not self._is_ladybug else {},
            )

            if create_result:
                log.info("event_node_created_from_entity", entity=entity_name)
                return event_id

        except Exception as exc:
            log.warning("create_event_failed", entity=entity_name, error=str(exc))

        return None
