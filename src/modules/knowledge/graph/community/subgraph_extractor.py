# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Subgraph extraction for incremental community updates.

Provides database-specific subgraph extraction strategies:
- Neo4j: Uses APOC path expansion for efficient subgraph traversal
- LadybugDB: Manual multi-hop expansion (no APOC support)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.db.graph_query_builders import GraphDatabaseType
from core.observability.logging import get_logger

if TYPE_CHECKING:
    from core.protocols import GraphPool

log = get_logger(__name__)


class SubgraphExtractor:
    """Extract subgraphs centered around specified entities.

    Used by incremental community updater to get local neighborhood
    for partial community detection.

    Args:
        pool: Graph database connection pool.
        database_type: Database type (Neo4j or LadybugDB).
    """

    def __init__(
        self,
        pool: GraphPool,
        database_type: GraphDatabaseType = GraphDatabaseType.NEO4J,
    ) -> None:
        self._pool = pool
        self._database_type = database_type

    async def extract_subgraph(
        self,
        entity_names: list[str],
        max_hops: int = 2,
    ) -> list[tuple[str, str, float]]:
        """Extract subgraph edges around specified entities.

        Args:
            entity_names: Center entity canonical names.
            max_hops: Maximum hops from center entities.

        Returns:
            List of (source, target, weight) edge tuples.
        """
        if not entity_names:
            return []

        if self._database_type == GraphDatabaseType.LADYBUG:
            return await self._extract_ladybug(entity_names, max_hops)
        return await self._extract_neo4j(entity_names, max_hops)

    async def _extract_neo4j(
        self,
        entity_names: list[str],
        max_hops: int,
    ) -> list[tuple[str, str, float]]:
        """Extract subgraph from Neo4j using APOC.

        Args:
            entity_names: Center entity canonical names.
            max_hops: Maximum hops from center entities.

        Returns:
            List of edge tuples.
        """
        # Use APOC path expansion for efficient subgraph traversal
        # Note: APOC must be installed on Neo4j server
        query = """
        MATCH (e:Entity)
        WHERE e.canonical_name IN $entity_names
        CALL apoc.path.subgraphAll(e, {
            relationshipFilter: "RELATED_TO",
            maxDepth: $max_hops,
            terminatorNodes: []
        }) YIELD nodes, relationships
        UNWIND relationships AS r
        WITH startNode(r) AS src, endNode(r) AS tgt, r
        WHERE src.pruned IS NULL OR src.pruned = false
          AND tgt.pruned IS NULL OR tgt.pruned = false
        RETURN src.canonical_name AS source,
               tgt.canonical_name AS target,
               coalesce(r.weight, 1.0) AS weight
        """
        results = await self._pool.execute_query(
            query,
            {"entity_names": entity_names, "max_hops": max_hops},
        )

        if not results:
            return []

        # Normalize and deduplicate edges
        import pandas as pd

        df = pd.DataFrame(results)
        if "source" not in df.columns or "target" not in df.columns:
            return []

        df["weight"] = df.get("weight", pd.Series(1.0, index=df.index)).fillna(1.0)
        df["lo"] = df[["source", "target"]].min(axis=1)
        df["hi"] = df[["source", "target"]].max(axis=1)
        df = df.sort_values("weight", ascending=False)
        df = df.drop_duplicates(subset=["lo", "hi"], keep="first")

        return list(zip(df["lo"].tolist(), df["hi"].tolist(), df["weight"].tolist()))

    async def _extract_ladybug(
        self,
        entity_names: list[str],
        max_hops: int,
    ) -> list[tuple[str, str, float]]:
        """Extract subgraph from LadybugDB with manual expansion.

        LadybugDB doesn't support APOC, so we manually expand 1-2 hops.

        Args:
            entity_names: Center entity canonical names.
            max_hops: Maximum hops (1 or 2).

        Returns:
            List of edge tuples.
        """
        # For max_hops=1: direct neighbors only
        if max_hops == 1:
            query = """
            MATCH (e:Entity)-[r:RELATED_TO]-(n:Entity)
            WHERE e.canonical_name IN $entity_names
            RETURN e.canonical_name AS source,
                   n.canonical_name AS target,
                   coalesce(r.weight, 1.0) AS weight
            """
            results = await self._pool.execute_query(query, {"entity_names": entity_names})
        else:
            # For max_hops>=2: expand two hops
            # Collect all reachable entities within 2 hops
            query = """
            MATCH (e:Entity)
            WHERE e.canonical_name IN $entity_names

            // 1-hop neighbors
            OPTIONAL MATCH (e)-[r1:RELATED_TO]-(n1:Entity)
            WITH e, collect(DISTINCT n1.canonical_name) AS hop1_nodes

            // Unwind hop1 to get edges (LadybugDB uses 1-based indexing)
            UNWIND range(1, size(hop1_nodes)) AS idx
            WITH e.canonical_name AS center, hop1_nodes[idx] AS hop1

            // Get 1-hop edges
            MATCH (a:Entity {canonical_name: center})-[r1:RELATED_TO]-(b:Entity {canonical_name: hop1})
            RETURN a.canonical_name AS source,
                   b.canonical_name AS target,
                   coalesce(r1.weight, 1.0) AS weight
            """
            results_1hop = await self._pool.execute_query(query, {"entity_names": entity_names})

            # 2-hop edges (between hop1 nodes and their neighbors)
            query_2hop = """
            MATCH (e:Entity)
            WHERE e.canonical_name IN $entity_names
            MATCH (e)-[r1:RELATED_TO]-(n1:Entity)
            MATCH (n1)-[r2:RELATED_TO]-(n2:Entity)
            WHERE NOT n2.canonical_name IN $entity_names
            RETURN n1.canonical_name AS source,
                   n2.canonical_name AS target,
                   coalesce(r2.weight, 1.0) AS weight
            """
            results_2hop = await self._pool.execute_query(
                query_2hop, {"entity_names": entity_names}
            )

            results = results_1hop + results_2hop

        if not results:
            return []

        # Normalize and deduplicate
        import pandas as pd

        df = pd.DataFrame(results)
        if "source" not in df.columns or "target" not in df.columns:
            return []

        df["weight"] = df.get("weight", pd.Series(1.0, index=df.index)).fillna(1.0)
        df["lo"] = df[["source", "target"]].min(axis=1)
        df["hi"] = df[["source", "target"]].max(axis=1)
        df = df.sort_values("weight", ascending=False)
        df = df.drop_duplicates(subset=["lo", "hi"], keep="first")

        return list(zip(df["lo"].tolist(), df["hi"].tolist(), df["weight"].tolist()))

    async def get_subgraph_entities(
        self,
        entity_names: list[str],
        max_hops: int = 2,
    ) -> list[str]:
        """Get all entity names in the subgraph.

        Args:
            entity_names: Center entity canonical names.
            max_hops: Maximum hops from center entities.

        Returns:
            List of all entity names in subgraph.
        """
        edges = await self.extract_subgraph(entity_names, max_hops)
        if not edges:
            return entity_names

        # Extract unique entity names from edges
        entities = set(entity_names)
        for source, target, _ in edges:
            entities.add(source)
            entities.add(target)

        return sorted(entities)
