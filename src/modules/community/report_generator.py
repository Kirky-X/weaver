# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Community report generator for knowledge graph summarization.

Generates comprehensive reports for communities using LLM summarization,
similar to GraphRAG's community report functionality.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from core.db.neo4j import Neo4jPool
from core.llm.client import LLMClient
from core.observability.logging import get_logger

log = get_logger("community.report_generator")


@dataclass
class CommunityReport:
    """Community report with LLM-generated summary."""

    id: str
    community_id: str
    level: int
    title: str
    summary: str
    full_content: str
    rank: float
    entity_count: int
    relationship_count: int
    created_at: datetime
    metadata: dict[str, Any]


class CommunityReportGenerator:
    """Generate community reports using LLM summarization.

    This generator:
    1. Collects community entity and relationship data
    2. Uses LLM to generate structured summaries
    3. Stores reports in Neo4j for later retrieval

    Report structure:
    - Title: Brief descriptive title
    - Summary: Concise overview (1-2 sentences)
    - Full content: Detailed analysis
    - Metadata: Entity/relationship counts, ranks, etc.
    """

    def __init__(
        self,
        neo4j_pool: Neo4jPool,
        llm: LLMClient,
        default_max_content_tokens: int = 2000,
    ) -> None:
        """Initialize community report generator.

        Args:
            neo4j_pool: Neo4j connection pool.
            llm: LLM client for summarization.
            default_max_content_tokens: Max tokens for generated content.
        """
        self._pool = neo4j_pool
        self._llm = llm
        self._max_content_tokens = default_max_content_tokens

    async def generate_report(
        self,
        community_id: str,
        level: int = 0,
    ) -> CommunityReport:
        """Generate a report for a specific community.

        Args:
            community_id: The community ID.
            level: Community hierarchy level.

        Returns:
            CommunityReport with generated content.
        """
        entity_data = await self._get_community_entities(community_id)
        relationship_data = await self._get_community_relationships(community_id)

        if not entity_data:
            return self._create_empty_report(community_id, level)

        content = self._prepare_content(entity_data, relationship_data)

        prompt = self._build_generation_prompt(content)

        try:
            response = await self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )

            generated = response.content if hasattr(response, "content") else str(response)

            title, summary = self._parse_generated_content(generated)

            report = CommunityReport(
                id=str(uuid.uuid4()),
                community_id=community_id,
                level=level,
                title=title,
                summary=summary,
                full_content=generated,
                rank=self._calculate_rank(entity_data, relationship_data),
                entity_count=len(entity_data),
                relationship_count=len(relationship_data),
                created_at=datetime.now(UTC),
                metadata={
                    "entity_types": self._count_entity_types(entity_data),
                    "relationship_types": self._count_relationship_types(relationship_data),
                },
            )

            await self._save_report(report)

            return report

        except Exception as exc:
            log.error("report_generation_failed", community_id=community_id, error=str(exc))
            return self._create_error_report(community_id, level, str(exc))

    async def generate_reports_batch(
        self,
        community_ids: list[str],
        level: int = 0,
    ) -> list[CommunityReport]:
        """Generate reports for multiple communities.

        Args:
            community_ids: List of community IDs.
            level: Community hierarchy level.

        Returns:
            List of CommunityReports.
        """
        reports = []
        for comm_id in community_ids:
            report = await self.generate_report(comm_id, level)
            reports.append(report)
        return reports

    async def _get_community_entities(
        self,
        community_id: str,
    ) -> list[dict[str, Any]]:
        """Get entities belonging to a community."""
        cypher = """
        MATCH (c:Community {id: $community_id})-[:HAS_ENTITY]->(e:Entity)
        RETURN e.canonical_name AS name,
               e.type AS type,
               e.description AS description,
               e.aliases AS aliases
        LIMIT 100
        """

        try:
            results = await self._pool.execute_query(cypher, {"community_id": community_id})
            return [dict(r) for r in results]
        except Exception as exc:
            log.warning("get_community_entities_failed", error=str(exc))
            return []

    async def _get_community_relationships(
        self,
        community_id: str,
    ) -> list[dict[str, Any]]:
        """Get relationships within a community."""
        cypher = """
        MATCH (c:Community {id: $community_id})-[:HAS_ENTITY]->(e1:Entity)
              -[r:RELATED_TO]->(e2:Entity)<-[:HAS_ENTITY]-(c)
        RETURN e1.canonical_name AS source,
               e2.canonical_name AS target,
               r.relation_type AS type,
               r.weight AS weight
        LIMIT 200
        """

        try:
            results = await self._pool.execute_query(cypher, {"community_id": community_id})
            return [dict(r) for r in results]
        except Exception as exc:
            log.warning("get_community_relationships_failed", error=str(exc))
            return []

    def _prepare_content(
        self,
        entities: list[dict[str, Any]],
        relationships: list[dict[str, Any]],
    ) -> str:
        """Prepare content for LLM summarization."""
        lines = ["## Entities\n"]

        type_groups: dict[str, list[dict]] = {}
        for entity in entities:
            etype = entity.get("type", "Unknown")
            if etype not in type_groups:
                type_groups[etype] = []
            type_groups[etype].append(entity)

        for etype, ents in type_groups.items():
            lines.append(f"\n### {etype} ({len(ents)})\n")
            for ent in ents[:20]:
                name = ent.get("name", "Unknown")
                desc = ent.get("description", "")
                lines.append(f"- {name}")
                if desc:
                    lines.append(f"  - {desc[:100]}")

        lines.append("\n## Relationships\n")
        for rel in relationships[:30]:
            source = rel.get("source", "Unknown")
            target = rel.get("target", "Unknown")
            rtype = rel.get("type", "RELATED_TO")
            lines.append(f"- {source} --[{rtype}]--> {target}")

        return "\n".join(lines)

    def _build_generation_prompt(self, content: str) -> str:
        """Build prompt for LLM report generation."""
        return f"""You are generating a structured summary of a community in a knowledge graph.

Analyze the following entity and relationship data to create a comprehensive community report.

{content}

Generate a report with the following structure:

1. **Title**: A brief, descriptive title for this community (in Chinese, 5-15 characters)

2. **Summary**: A concise overview (2-3 sentences in Chinese) that captures the main theme

3. **Full Report**: Detailed analysis including:
   - Main topics and themes
   - Key entities and their roles
   - Important relationships and patterns
   - Any notable insights

Use Chinese for title and summary, mixed Chinese/English for the full report as appropriate.

Report:"""

    def _parse_generated_content(self, content: str) -> tuple[str, str]:
        """Parse generated content to extract title and summary."""
        lines = content.strip().split("\n")

        title = "Community Report"
        summary = ""

        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if "标题" in line_stripped or "Title" in line_stripped:
                if i + 1 < len(lines):
                    title = lines[i + 1].strip().strip("**").strip("#").strip()
            elif "摘要" in line_stripped or "Summary" in line_stripped:
                if i + 1 < len(lines):
                    summary_lines = []
                    for j in range(i + 1, min(i + 4, len(lines))):
                        if lines[j].strip() and not lines[j].startswith("#"):
                            summary_lines.append(lines[j].strip())
                        elif lines[j].startswith("##"):
                            break
                    summary = " ".join(summary_lines[:2])

        if not summary:
            for line in lines:
                if line.strip() and not line.startswith("#") and not line.startswith("-"):
                    summary = line.strip()[:100]
                    break

        return title[:50] or "Community Report", summary[:200] or "Community summary"

    def _calculate_rank(
        self,
        entities: list[dict[str, Any]],
        relationships: list[dict[str, Any]],
    ) -> float:
        """Calculate importance rank for the community."""
        if not entities:
            return 0.0

        entity_score = len(entities) / 100.0
        relationship_score = len(relationships) / 200.0

        unique_types = len(set(e.get("type") for e in entities if e.get("type")))

        rank = (entity_score + relationship_score) * (1 + unique_types * 0.1)

        return min(1.0, rank)

    def _count_entity_types(self, entities: list[dict[str, Any]]) -> dict[str, int]:
        """Count entities by type."""
        counts: dict[str, int] = {}
        for ent in entities:
            etype = ent.get("type", "Unknown")
            counts[etype] = counts.get(etype, 0) + 1
        return counts

    def _count_relationship_types(self, relationships: list[dict[str, Any]]) -> dict[str, int]:
        """Count relationships by type."""
        counts: dict[str, int] = {}
        for rel in relationships:
            rtype = rel.get("type", "RELATED_TO")
            counts[rtype] = counts.get(rtype, 0) + 1
        return counts

    async def _save_report(self, report: CommunityReport) -> None:
        """Save report to Neo4j."""
        cypher = """
        MERGE (r:CommunityReport {id: $id})
        SET r.community_id = $community_id,
            r.level = $level,
            r.title = $title,
            r.summary = $summary,
            r.full_content = $full_content,
            r.rank = $rank,
            r.entity_count = $entity_count,
            r.relationship_count = $relationship_count,
            r.entity_types = $entity_types,
            r.relationship_types = $relationship_types,
            r.created_at = $created_at
        """

        await self._pool.execute_query(
            cypher,
            {
                "id": report.id,
                "community_id": report.community_id,
                "level": report.level,
                "title": report.title,
                "summary": report.summary,
                "full_content": report.full_content,
                "rank": report.rank,
                "entity_count": report.entity_count,
                "relationship_count": report.relationship_count,
                "entity_types": str(report.metadata.get("entity_types", {})),
                "relationship_types": str(report.metadata.get("relationship_types", {})),
                "created_at": report.created_at.isoformat(),
            },
        )

    def _create_empty_report(
        self,
        community_id: str,
        level: int,
    ) -> CommunityReport:
        """Create an empty report for community with no data."""
        return CommunityReport(
            id=str(uuid.uuid4()),
            community_id=community_id,
            level=level,
            title="Empty Community",
            summary="No data available for this community.",
            full_content="",
            rank=0.0,
            entity_count=0,
            relationship_count=0,
            created_at=datetime.now(UTC),
            metadata={},
        )

    def _create_error_report(
        self,
        community_id: str,
        level: int,
        error: str,
    ) -> CommunityReport:
        """Create an error report."""
        return CommunityReport(
            id=str(uuid.uuid4()),
            community_id=community_id,
            level=level,
            title="Report Generation Failed",
            summary=f"Failed to generate report: {error[:50]}",
            full_content=error,
            rank=0.0,
            entity_count=0,
            relationship_count=0,
            created_at=datetime.now(UTC),
            metadata={"error": error},
        )

    async def get_report(self, community_id: str) -> CommunityReport | None:
        """Retrieve an existing report for a community."""
        cypher = """
        MATCH (r:CommunityReport {community_id: $community_id})
        RETURN r.id AS id,
               r.community_id AS community_id,
               r.level AS level,
               r.title AS title,
               r.summary AS summary,
               r.full_content AS full_content,
               r.rank AS rank,
               r.entity_count AS entity_count,
               r.relationship_count AS relationship_count,
               r.created_at AS created_at
        ORDER BY r.created_at DESC
        LIMIT 1
        """

        try:
            results = await self._pool.execute_query(cypher, {"community_id": community_id})
            if results:
                r = results[0]
                return CommunityReport(
                    id=r.get("id", ""),
                    community_id=r.get("community_id", ""),
                    level=r.get("level", 0),
                    title=r.get("title", ""),
                    summary=r.get("summary", ""),
                    full_content=r.get("full_content", ""),
                    rank=r.get("rank", 0.0),
                    entity_count=r.get("entity_count", 0),
                    relationship_count=r.get("relationship_count", 0),
                    created_at=r.get("created_at", datetime.now(UTC)),
                    metadata={},
                )
        except Exception as exc:
            log.warning("get_report_failed", error=str(exc))

        return None
