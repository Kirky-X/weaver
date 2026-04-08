# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Graph quality metrics module for monitoring knowledge graph health."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from core.constants import GraphHealthStatus
from core.db.graph_query_builders import GraphQueryBuilder, create_graph_query_builder
from core.observability.logging import get_logger

if TYPE_CHECKING:
    from core.protocols import GraphPool

log = get_logger("graph.metrics")


def _dfs_component(start: str, adjacency: dict[str, set[str]], visited: set[str]) -> set[str]:
    """Perform DFS to find a connected component.

    Args:
        start: Starting node ID.
        adjacency: Adjacency dictionary mapping nodes to their neighbors.
        visited: Set of already visited nodes (modified in-place).

    Returns:
        Set of nodes in the connected component.
    """
    stack = [start]
    component: set[str] = set()
    while stack:
        node = stack.pop()
        if node in visited:
            continue
        visited.add(node)
        component.add(node)
        for neighbor in adjacency.get(node, []):
            if neighbor not in visited:
                stack.append(neighbor)
    return component


@dataclass
class GraphMetrics:
    """Graph quality metrics snapshot."""

    total_entities: int = 0
    total_articles: int = 0
    total_relationships: int = 0
    total_mentions: int = 0
    connected_components: int = 0
    largest_component_size: int = 0
    average_degree: float = 0.0
    modularity_score: float | None = None
    orphan_entities: int = 0
    high_degree_entities: list[dict[str, Any]] = field(default_factory=list)
    entity_type_distribution: dict[str, int] = field(default_factory=dict)
    relationship_type_distribution: dict[str, int] = field(default_factory=dict)
    computed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "total_entities": self.total_entities,
            "total_articles": self.total_articles,
            "total_relationships": self.total_relationships,
            "total_mentions": self.total_mentions,
            "connected_components": self.connected_components,
            "largest_component_size": self.largest_component_size,
            "average_degree": self.average_degree,
            "modularity_score": self.modularity_score,
            "orphan_entities": self.orphan_entities,
            "high_degree_entities": self.high_degree_entities,
            "entity_type_distribution": self.entity_type_distribution,
            "relationship_type_distribution": self.relationship_type_distribution,
            "computed_at": self.computed_at.isoformat(),
        }


@dataclass
class EntityDegree:
    """Entity degree statistics."""

    entity_id: str
    canonical_name: str
    entity_type: str
    in_degree: int = 0
    out_degree: int = 0
    mention_count: int = 0
    total_degree: int = 0

    @property
    def degree(self) -> int:
        """Total degree (in + out)."""
        return self.in_degree + self.out_degree


@dataclass
class ConnectedComponent:
    """Connected component info."""

    component_id: int
    node_ids: list[str]
    size: int
    entity_types: dict[str, int]


class GraphQualityMetrics:
    """Graph quality metrics calculator.

    Provides comprehensive metrics for monitoring knowledge graph health:
    - Entity/relationship counts
    - Connected components analysis
    - Degree distribution
    - Orphan detection
    - Modularity score (optional)

    Implements: MetricsCalculator
    """

    def __init__(
        self,
        pool: GraphPool,
        query_builder: GraphQueryBuilder | None = None,
        db_type: str = "neo4j",
    ) -> None:
        """Initialize metrics calculator.

        Args:
            pool: Graph database connection pool.
            query_builder: Optional query builder for database-specific syntax.
            db_type: Database type ('neo4j' or 'ladybug'), used to create
                query_builder if not provided.
        """
        self._pool = pool
        self._query_builder = query_builder or create_graph_query_builder(db_type)

    async def calculate_all_metrics(
        self,
        include: set[str] | None = None,
    ) -> GraphMetrics:
        """Calculate graph metrics with optional selective computation.

        Args:
            include: Set of items to compute. None means compute all.
                Supported values: components, orphans, high_degree, modularity, distributions.
        """
        log.info("graph_metrics_calculation_start", include=list(include) if include else "all")

        metrics = GraphMetrics()

        # Counts are always cheap — always calculate
        await self._calculate_counts(
            metrics, include_orphans=(include is None or "orphans" in include)
        )

        # Degree metrics (average_degree is cheap, high_degree_entities is selective)
        await self._calculate_degree_metrics(
            metrics, include_high_degree=(include is None or "high_degree" in include)
        )

        # Component analysis — expensive
        if include is None or "components" in include:
            await self._calculate_component_metrics(metrics)

        # Distributions — moderate cost
        if include is None or "distributions" in include:
            await self._calculate_distributions(metrics)

        # Modularity — moderate cost (calculated alongside components)
        if include is None or "modularity" in include:
            await self._calculate_modularity(metrics)

        log.info(
            "graph_metrics_calculation_complete",
            entities=metrics.total_entities,
            relationships=metrics.total_relationships,
            components=metrics.connected_components,
        )

        return metrics

    async def _calculate_counts(
        self,
        metrics: GraphMetrics,
        include_orphans: bool = True,
    ) -> None:
        """Calculate basic entity and relationship counts."""
        queries: dict[str, str] = {
            "entities": "MATCH (e:Entity) RETURN count(e) AS count",
            "articles": "MATCH (a:Article) RETURN count(a) AS count",
            "relationships": (
                """
                MATCH ()-[r:RELATED_TO]->()
                RETURN count(r) AS count
            """
            ),
            "mentions": (
                """
                MATCH ()-[r:MENTIONS]->()
                RETURN count(r) AS count
            """
            ),
        }

        if include_orphans:
            queries["orphans"] = """
                MATCH (e:Entity)
                WHERE NOT ()-[:MENTIONS]->(e)
                  AND NOT (e)-[:RELATED_TO]-()
                  AND NOT ()-[:RELATED_TO]->(e)
                RETURN count(e) AS count
            """

        for key, query in queries.items():
            try:
                result = await self._pool.execute_query(query)
                count = result[0]["count"] if result else 0
                if key == "entities":
                    metrics.total_entities = count
                elif key == "articles":
                    metrics.total_articles = count
                elif key == "relationships":
                    metrics.total_relationships = count
                elif key == "mentions":
                    metrics.total_mentions = count
                elif key == "orphans":
                    metrics.orphan_entities = count
            except Exception as exc:
                log.warning("metrics_count_failed", key=key, error=str(exc))

    async def _calculate_degree_metrics(
        self,
        metrics: GraphMetrics,
        min_degree: int = 10,
        limit: int = 100,
        include_high_degree: bool = True,
    ) -> None:
        """Calculate degree distribution and optionally high-degree entities."""
        # Always compute average degree (cheap query)
        if metrics.total_entities > 0:
            all_degree_query = """
            MATCH (e:Entity)
            OPTIONAL MATCH (e)-[r_out:RELATED_TO]->()
            OPTIONAL MATCH ()-[r_in:RELATED_TO]->(e)
            WITH e, count(DISTINCT r_out) + count(DISTINCT r_in) AS degree
            RETURN avg(degree) AS avg_degree
            """
            try:
                avg_result = await self._pool.execute_query(all_degree_query)
                if avg_result:
                    metrics.average_degree = avg_result[0].get("avg_degree", 0.0) or 0.0
            except Exception as exc:
                log.warning("metrics_avg_degree_failed", error=str(exc))

        # Skip expensive per-entity query when not needed
        if not include_high_degree:
            return

        degree_query = """
        MATCH (e:Entity)
        OPTIONAL MATCH (e)-[r_out:RELATED_TO]->()
        OPTIONAL MATCH ()-[r_in:RELATED_TO]->(e)
        OPTIONAL MATCH ()-[m:MENTIONS]->(e)
        WITH e,
             count(DISTINCT r_out) AS out_degree,
             count(DISTINCT r_in) AS in_degree,
             count(DISTINCT m) AS mention_count
        RETURN e.canonical_name AS name,
               e.type AS type,
               in_degree,
               out_degree,
               mention_count,
               (in_degree + out_degree) AS total_degree
        ORDER BY total_degree DESC
        LIMIT $limit
        """

        try:
            results = await self._pool.execute_query(degree_query, {"limit": limit})

            high_degree_entities = []
            total_degree_sum = 0
            entity_count = 0

            for row in results:
                total_degree = row.get("total_degree", 0)
                total_degree_sum += total_degree
                entity_count += 1

                if total_degree >= min_degree:
                    high_degree_entities.append(
                        {
                            "name": row.get("name"),
                            "type": row.get("type"),
                            "in_degree": row.get("in_degree", 0),
                            "out_degree": row.get("out_degree", 0),
                            "mention_count": row.get("mention_count", 0),
                            "total_degree": total_degree,
                        }
                    )

            metrics.high_degree_entities = high_degree_entities

            if metrics.total_entities > 0:
                all_degree_query = """
                MATCH (e:Entity)
                OPTIONAL MATCH (e)-[r_out:RELATED_TO]->()
                OPTIONAL MATCH ()-[r_in:RELATED_TO]->(e)
                WITH e, count(DISTINCT r_out) + count(DISTINCT r_in) AS degree
                RETURN avg(degree) AS avg_degree
                """
                avg_result = await self._pool.execute_query(all_degree_query)
                if avg_result:
                    metrics.average_degree = avg_result[0].get("avg_degree", 0.0) or 0.0

        except Exception as exc:
            log.warning("metrics_degree_calculation_failed", error=str(exc))

    async def _calculate_component_metrics(self, metrics: GraphMetrics) -> None:
        """Calculate connected component statistics."""
        component_query = self._query_builder.build_component_neighbors_query()

        try:
            results = await self._pool.execute_query(component_query)

            adjacency: dict[str, set[str]] = defaultdict(set)
            all_entities: set[str] = set()

            for row in results:
                entity = row.get("entity")
                neighbors = row.get("neighbors", [])
                if entity:
                    all_entities.add(entity)
                    # LadybugDB returns neighbors as list of Entity objects
                    # Neo4j returns neighbors as list of canonical_name strings
                    if self._query_builder.supports_list_comprehension():
                        # Neo4j: neighbors are already strings
                        for neighbor in neighbors:
                            if neighbor:
                                adjacency[entity].add(neighbor)
                                all_entities.add(neighbor)
                    else:
                        # LadybugDB: neighbors are Entity objects
                        for neighbor in neighbors:
                            if neighbor and isinstance(neighbor, dict):
                                neighbor_name = neighbor.get("canonical_name")
                                if neighbor_name:
                                    adjacency[entity].add(neighbor_name)
                                    all_entities.add(neighbor_name)

            visited: set[str] = set()
            components: list[set[str]] = []

            for entity in all_entities:
                if entity not in visited:
                    component = _dfs_component(entity, adjacency, visited)
                    components.append(component)

            metrics.connected_components = len(components)
            if components:
                metrics.largest_component_size = max(len(c) for c in components)

        except Exception as exc:
            log.warning("metrics_component_calculation_failed", error=str(exc))

    async def _calculate_distributions(self, metrics: GraphMetrics) -> None:
        """Calculate entity and relationship type distributions."""
        entity_type_query = """
        MATCH (e:Entity)
        RETURN e.type AS type, count(e) AS count
        ORDER BY count DESC
        """

        # LadybugDB uses edge_type property; Neo4j uses dynamic relation types
        # For RELATED_TO table, we use edge_type for both
        rel_type_query = """
        MATCH ()-[r:RELATED_TO]->()
        RETURN r.edge_type AS type, count(r) AS count
        ORDER BY count DESC
        LIMIT 20
        """

        try:
            entity_results = await self._pool.execute_query(entity_type_query)
            metrics.entity_type_distribution = {
                r["type"]: r["count"] for r in entity_results if r.get("type")
            }
        except Exception as exc:
            log.warning("metrics_entity_distribution_failed", error=str(exc))

        try:
            rel_results = await self._pool.execute_query(rel_type_query)
            metrics.relationship_type_distribution = {
                r["type"]: r["count"] for r in rel_results if r.get("type")
            }
        except Exception as exc:
            log.warning("metrics_rel_distribution_failed", error=str(exc))

    async def _calculate_modularity(self, metrics: GraphMetrics) -> None:
        """Calculate modularity score using connected component data."""
        if metrics.connected_components <= 1:
            # Single component or no data — modularity is trivially 0
            metrics.modularity_score = 0.0 if metrics.total_entities > 0 else None
            return

        # Reuse component data if already computed, otherwise compute
        component_query = self._query_builder.build_component_neighbors_query()

        try:
            results = await self._pool.execute_query(component_query)

            adjacency: dict[str, set[str]] = defaultdict(set)
            all_entities: set[str] = set()

            for row in results:
                entity = row.get("entity")
                neighbors = row.get("neighbors", [])
                if entity:
                    all_entities.add(entity)
                    # Handle both Neo4j (string list) and LadybugDB (Entity object list)
                    if self._query_builder.supports_list_comprehension():
                        for neighbor in neighbors:
                            if neighbor:
                                adjacency[entity].add(neighbor)
                                all_entities.add(neighbor)
                    else:
                        for neighbor in neighbors:
                            if neighbor and isinstance(neighbor, dict):
                                neighbor_name = neighbor.get("canonical_name")
                                if neighbor_name:
                                    adjacency[entity].add(neighbor_name)
                                    all_entities.add(neighbor_name)

            visited: set[str] = set()
            components: list[set[str]] = []
            for entity in all_entities:
                if entity not in visited:
                    component = _dfs_component(entity, adjacency, visited)
                    components.append(component)

            # Compute modularity Q = sum[(e_ii / m) - (a_i / 2m)^2]
            total_edges = sum(len(adjacency.get(n, set())) for n in all_entities) // 2
            if total_edges == 0:
                metrics.modularity_score = 0.0
                return

            q = 0.0
            for component in components:
                e_ii = 0
                for node in component:
                    for neighbor in adjacency.get(node, set()):
                        if neighbor in component:
                            e_ii += 1
                e_ii //= 2  # each edge counted twice

                a_i = sum(len(adjacency.get(n, set())) for n in component)

                q += (e_ii / total_edges) - (a_i / (2 * total_edges)) ** 2

            metrics.modularity_score = q

        except Exception as exc:
            log.warning("metrics_modularity_calculation_failed", error=str(exc))

    async def get_connected_components(self) -> list[ConnectedComponent]:
        """Get all connected components with details."""
        component_query = self._query_builder.build_component_neighbors_query()

        results = await self._pool.execute_query(component_query)

        adjacency: dict[str, set[str]] = defaultdict(set)
        entity_types: dict[str, str] = {}
        all_entities: set[str] = set()

        for row in results:
            entity = row.get("entity")
            etype = row.get("type")
            neighbors = row.get("neighbors", [])
            if entity:
                all_entities.add(entity)
                if etype:
                    entity_types[entity] = etype
                # Handle both Neo4j (string list) and LadybugDB (Entity object list)
                if self._query_builder.supports_list_comprehension():
                    for neighbor in neighbors:
                        if neighbor:
                            adjacency[entity].add(neighbor)
                            all_entities.add(neighbor)
                else:
                    for neighbor in neighbors:
                        if neighbor and isinstance(neighbor, dict):
                            neighbor_name = neighbor.get("canonical_name")
                            if neighbor_name:
                                adjacency[entity].add(neighbor_name)
                                all_entities.add(neighbor_name)

        visited: set[str] = set()
        components: list[ConnectedComponent] = []

        component_id = 0
        for entity in all_entities:
            if entity not in visited:
                node_set = _dfs_component(entity, adjacency, visited)
                node_list = list(node_set)
                type_dist: dict[str, int] = defaultdict(int)
                for node in node_list:
                    etype = entity_types.get(node, "Unknown")
                    type_dist[etype] += 1

                components.append(
                    ConnectedComponent(
                        component_id=component_id,
                        node_ids=node_list,
                        size=len(node_list),
                        entity_types=dict(type_dist),
                    )
                )
                component_id += 1

        return sorted(components, key=lambda c: c.size, reverse=True)

    async def get_largest_connected_component(self) -> ConnectedComponent | None:
        """Get the largest connected component."""
        components = await self.get_connected_components()
        return components[0] if components else None

    async def calculate_entity_degrees(self) -> list[EntityDegree]:
        """Calculate degree statistics for all entities."""
        query = self._query_builder.build_degree_query()

        results = await self._pool.execute_query(query)

        return [
            EntityDegree(
                entity_id=r.get("entity_id", ""),
                canonical_name=r.get("name", ""),
                entity_type=r.get("type", "Unknown"),
                in_degree=r.get("in_degree", 0),
                out_degree=r.get("out_degree", 0),
                mention_count=r.get("mention_count", 0),
                total_degree=r.get("in_degree", 0) + r.get("out_degree", 0),
            )
            for r in results
        ]

    async def find_orphan_entities(self, limit: int = 1000) -> list[dict[str, Any]]:
        """Find entities with no connections."""
        query = """
        MATCH (e:Entity)
        WHERE NOT ()-[:MENTIONS]->(e)
          AND NOT (e)-[:RELATED_TO]-()
          AND NOT ()-[:RELATED_TO]->(e)
        RETURN e.canonical_name AS name,
               e.type AS type,
               e.created_at AS created_at
        ORDER BY e.created_at DESC
        LIMIT $limit
        """

        results = await self._pool.execute_query(query, {"limit": limit})
        entities = []
        for r in results:
            created_at = r.get("created_at")
            if hasattr(created_at, "isoformat"):
                created_at = created_at.isoformat()
            entities.append(
                {
                    "name": r.get("name"),
                    "type": r.get("type"),
                    "created_at": created_at,
                }
            )
        return entities

    async def get_high_degree_entities(
        self,
        min_degree: int = 10,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get entities with degree above threshold."""
        query = """
        MATCH (e:Entity)
        OPTIONAL MATCH (e)-[r_out:RELATED_TO]->()
        OPTIONAL MATCH ()-[r_in:RELATED_TO]->(e)
        WITH e,
             count(DISTINCT r_out) AS out_degree,
             count(DISTINCT r_in) AS in_degree,
             (count(DISTINCT r_out) + count(DISTINCT r_in)) AS total_degree
        WHERE total_degree >= $min_degree
        RETURN e.canonical_name AS name,
               e.type AS type,
               in_degree,
               out_degree,
               total_degree
        ORDER BY total_degree DESC
        LIMIT $limit
        """

        results = await self._pool.execute_query(
            query,
            {"min_degree": min_degree, "limit": limit},
        )

        return [
            {
                "name": r.get("name"),
                "type": r.get("type"),
                "in_degree": r.get("in_degree", 0),
                "out_degree": r.get("out_degree", 0),
                "total_degree": r.get("total_degree", 0),
            }
            for r in results
        ]

    async def calculate_modularity(
        self,
        partitions: dict[str, int] | None = None,
        resolution: float = 1.0,
    ) -> float:
        """Calculate graph modularity score.

        If partitions not provided, uses simple degree-based clustering.

        Args:
            partitions: Optional mapping of entity name to community ID.
            resolution: Resolution parameter for modularity calculation.

        Returns:
            Modularity score between -1 and 1.
        """
        edges_query = self._query_builder.build_edges_with_weight_query()

        results = await self._pool.execute_query(edges_query)
        edges = [
            (r["source"], r["target"], r["weight"])
            for r in results
            if r.get("source") and r.get("target")
        ]

        if not edges:
            return 0.0

        if partitions is None:
            partitions = await self._generate_simple_partitions(edges)

        return self._compute_modularity(edges, partitions, resolution)

    async def _generate_simple_partitions(
        self,
        edges: list[tuple[str, str, float]],
    ) -> dict[str, int]:
        """Generate simple partitions based on connected components."""
        adjacency: dict[str, set[str]] = defaultdict(set)
        all_nodes: set[str] = set()

        for source, target, _ in edges:
            adjacency[source].add(target)
            adjacency[target].add(source)
            all_nodes.add(source)
            all_nodes.add(target)

        visited: set[str] = set()
        partitions: dict[str, int] = {}
        community_id = 0

        for node in all_nodes:
            if node not in visited:
                component = _dfs_component(node, adjacency, visited)
                for n in component:
                    partitions[n] = community_id
                community_id += 1

        return partitions

    def _compute_modularity(
        self,
        edges: list[tuple[str, str, float]],
        partitions: dict[str, int],
        resolution: float = 1.0,
    ) -> float:
        """Compute modularity score from edges and partitions.

        Based on GraphRAG implementation.
        """
        if not edges or not partitions:
            return 0.0

        total_weight = sum(e[2] for e in edges)
        if total_weight == 0:
            return 0.0

        degree_sums_within: dict[int, float] = defaultdict(float)
        degree_sums_for: dict[int, float] = defaultdict(float)

        for source, target, weight in edges:
            src_comm = partitions.get(source, -1)
            tgt_comm = partitions.get(target, -1)

            if src_comm == tgt_comm and src_comm != -1:
                degree_sums_within[src_comm] += weight * 2

            if src_comm != -1:
                degree_sums_for[src_comm] += weight
            if tgt_comm != -1:
                degree_sums_for[tgt_comm] += weight

        modularity = 0.0
        for comm in set(partitions.values()):
            if comm == -1:
                continue
            intra = degree_sums_within[comm]
            total = degree_sums_for[comm]
            modularity += intra - resolution * (total**2) / (2 * total_weight)

        return modularity / (2 * total_weight)

    async def get_health_summary(self) -> dict[str, Any]:
        """Get a quick health summary of the graph."""
        metrics = await self.calculate_all_metrics()

        health_score = self._compute_health_score(metrics)

        return {
            "health_score": health_score,
            "status": self._get_health_status(health_score),
            "entity_count": metrics.total_entities,
            "relationship_count": metrics.total_relationships,
            "orphan_ratio": (
                metrics.orphan_entities / metrics.total_entities
                if metrics.total_entities > 0
                else 0
            ),
            "connectedness": (
                metrics.largest_component_size / metrics.total_entities
                if metrics.total_entities > 0
                else 0
            ),
            "average_degree": metrics.average_degree,
            "recommendations": self._generate_recommendations(metrics),
        }

    def _compute_health_score(self, metrics: GraphMetrics) -> float:
        """Compute overall health score (0-100)."""
        if metrics.total_entities == 0:
            return 0.0

        score = 100.0

        orphan_ratio = metrics.orphan_entities / metrics.total_entities
        score -= orphan_ratio * 30

        if metrics.total_entities > 0:
            connectedness = metrics.largest_component_size / metrics.total_entities
            score -= (1 - connectedness) * 20

        if metrics.average_degree < 1:
            score -= 20
        elif metrics.average_degree < 2:
            score -= 10

        return max(0.0, min(100.0, score))

    def _get_health_status(self, score: float) -> str:
        """Get health status label."""
        if score >= 80:
            return GraphHealthStatus.HEALTHY.value
        elif score >= 60:
            return GraphHealthStatus.MODERATE.value
        elif score >= 40:
            return GraphHealthStatus.DEGRADED.value
        else:
            return GraphHealthStatus.CRITICAL.value

    def _generate_recommendations(self, metrics: GraphMetrics) -> list[str]:
        """Generate recommendations based on metrics."""
        recommendations = []

        if metrics.orphan_entities > 0:
            orphan_ratio = (
                metrics.orphan_entities / metrics.total_entities
                if metrics.total_entities > 0
                else 0
            )
            if orphan_ratio > 0.1:
                recommendations.append(
                    f"High orphan entity ratio ({orphan_ratio:.1%}). "
                    "Consider running entity cleanup or improving entity extraction."
                )

        if metrics.average_degree < 1.5:
            recommendations.append(
                "Low average degree indicates sparse graph. "
                "Consider improving relationship extraction."
            )

        if metrics.connected_components > 10:
            recommendations.append(
                f"Many disconnected components ({metrics.connected_components}). "
                "Consider adding more relationship types or improving entity linking."
            )

        if not recommendations:
            recommendations.append("Graph health is good. No immediate actions required.")

        return recommendations
