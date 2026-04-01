# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Community report generator using LLM."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from core.db.neo4j import Neo4jPool
from core.llm.client import LLMClient
from core.llm.types import CallPoint
from core.observability.logging import get_logger
from modules.knowledge.community.repo import Neo4jCommunityRepo

log = get_logger("community_report_generator")


class CommunityReportOutput(BaseModel):
    """LLM output model for community report."""

    title: str = Field(description="社区标题")
    summary: str = Field(description="社区摘要")
    full_content: str = Field(description="完整报告内容")
    key_entities: list[str] = Field(default_factory=list, description="关键实体列表")
    key_relationships: list[str] = Field(default_factory=list, description="关键关系列表")
    rank: float = Field(ge=1.0, le=10.0, description="重要性评分")


@dataclass
class ReportGenerationResult:
    """Result of report generation for a single community."""

    community_id: str
    success: bool
    report_id: str | None = None
    error: str | None = None


class CommunityReportGenerator:
    """Generates LLM-powered reports for communities.

    Handles:
    - Fetching community data from Neo4j
    - Formatting prompts for LLM
    - Storing generated reports with embeddings
    - Batch report generation with concurrency control

    Args:
        pool: Neo4j connection pool.
        llm_client: LLM client for report generation.
        max_concurrent: Maximum concurrent LLM calls.
    """

    def __init__(
        self,
        pool: Neo4jPool,
        llm_client: LLMClient,
        max_concurrent: int = 5,
    ) -> None:
        self._pool = pool
        self._repo = Neo4jCommunityRepo(pool)
        self._llm = llm_client
        self._max_concurrent = max_concurrent

    async def generate_report(self, community_id: str) -> ReportGenerationResult:
        """Generate a report for a single community.

        Args:
            community_id: UUID of the community.

        Returns:
            ReportGenerationResult with success status and report ID.
        """
        log.info("report_generation_start", community_id=community_id)

        try:
            # Step 1: Get community data
            community_data = await self._get_community_data(community_id)
            if not community_data:
                log.warning("community_not_found", community_id=community_id)
                return ReportGenerationResult(
                    community_id=community_id,
                    success=False,
                    error="Community not found",
                )

            # Step 2: Get entities and relationships
            entities = await self._get_community_entities(community_id)
            relationships = await self._get_community_relationships(community_id)

            if not entities:
                log.warning("community_no_entities", community_id=community_id)
                return ReportGenerationResult(
                    community_id=community_id,
                    success=False,
                    error="Community has no entities",
                )

            # Step 3: Call LLM to generate report
            report_output = await self._call_llm(
                community_id=community_id,
                level=community_data.get("level", 0),
                entity_count=len(entities),
                entities=entities,
                relationships=relationships,
            )

            if not report_output:
                return ReportGenerationResult(
                    community_id=community_id,
                    success=False,
                    error="LLM generation failed",
                )

            # Step 4: Store report in Neo4j
            report_id = await self._repo.create_report(
                community_id=community_id,
                title=report_output.title,
                summary=report_output.summary,
                full_content=report_output.full_content,
                key_entities=report_output.key_entities,
                key_relationships=report_output.key_relationships,
                rank=report_output.rank,
            )

            # Step 5: Generate and store embedding
            await self._store_report_embedding(report_id, report_output.full_content)

            log.info(
                "report_generation_complete",
                community_id=community_id,
                report_id=report_id,
                title=report_output.title,
            )

            return ReportGenerationResult(
                community_id=community_id,
                success=True,
                report_id=report_id,
            )

        except Exception as exc:
            log.error(
                "report_generation_failed",
                community_id=community_id,
                error=str(exc),
            )
            return ReportGenerationResult(
                community_id=community_id,
                success=False,
                error=str(exc),
            )

    async def generate_all_reports(
        self,
        level: int | None = None,
        regenerate_stale: bool = True,
    ) -> dict[str, Any]:
        """Generate reports for all communities.

        Args:
            level: Optional level filter. If None, generate for all levels.
            regenerate_stale: Whether to regenerate stale reports.

        Returns:
            Dict with total, success, and failed counts.
        """
        log.info("batch_report_generation_start", level=level)

        # Get all communities
        communities = await self._repo.list_communities(level=level, limit=10000)

        # Filter out communities that already have reports (unless stale)
        to_generate: list[str] = []
        for community in communities:
            if community.level == -1:  # Skip orphan communities
                continue

            existing_report = await self._repo.get_report(community.id)
            if existing_report is None:
                to_generate.append(community.id)
            elif regenerate_stale and existing_report.stale:
                await self._repo.delete_report(community.id)
                to_generate.append(community.id)

        log.info(
            "batch_report_generation_queue",
            total_communities=len(communities),
            to_generate=len(to_generate),
        )

        # Generate reports with concurrency control
        semaphore = asyncio.Semaphore(self._max_concurrent)

        async def generate_with_semaphore(cid: str) -> ReportGenerationResult:
            async with semaphore:
                return await self.generate_report(cid)

        results = await asyncio.gather(
            *[generate_with_semaphore(cid) for cid in to_generate],
            return_exceptions=True,
        )

        # Count successes and failures
        success_count = 0
        failed_count = 0
        failed_ids: list[str] = []

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                failed_count += 1
                failed_ids.append(to_generate[i])
            elif isinstance(result, ReportGenerationResult):
                if result.success:
                    success_count += 1
                else:
                    failed_count += 1
                    failed_ids.append(to_generate[i])

        log.info(
            "batch_report_generation_complete",
            total=len(to_generate),
            success=success_count,
            failed=failed_count,
        )

        return {
            "total": len(to_generate),
            "success": success_count,
            "failed": failed_count,
            "failed_ids": failed_ids,
        }

    async def regenerate_report(self, community_id: str) -> ReportGenerationResult:
        """Regenerate a report for a community.

        Deletes existing report and generates a new one.

        Args:
            community_id: UUID of the community.

        Returns:
            ReportGenerationResult with success status.
        """
        log.info("report_regeneration_start", community_id=community_id)

        # Delete existing report if any
        await self._repo.delete_report(community_id)

        # Generate new report
        return await self.generate_report(community_id)

    async def _get_community_data(self, community_id: str) -> dict[str, Any] | None:
        """Get community metadata from Neo4j.

        Args:
            community_id: Community UUID.

        Returns:
            Community data dict or None.
        """
        query = """
        MATCH (c:Community {id: $community_id})
        RETURN c.id AS id, c.level AS level, c.entity_count AS entity_count
        """
        result = await self._pool.execute_query(query, {"community_id": community_id})
        if result:
            return dict(result[0])
        return None

    async def _get_community_entities(self, community_id: str) -> list[dict[str, str]]:
        """Get entities belonging to a community.

        Args:
            community_id: Community UUID.

        Returns:
            List of entity dicts with name, type, description.
        """
        query = """
        MATCH (c:Community {id: $community_id})-[:HAS_ENTITY]->(e:Entity)
        RETURN e.canonical_name AS name, e.type AS type, e.description AS description
        ORDER BY e.canonical_name
        LIMIT 50
        """
        results = await self._pool.execute_query(query, {"community_id": community_id})
        return [
            {
                "name": r.get("name", ""),
                "type": r.get("type", "未知"),
                "description": r.get("description", "")[:200] if r.get("description") else "",
            }
            for r in results
        ]

    async def _get_community_relationships(self, community_id: str) -> list[dict[str, str]]:
        """Get relationships within a community.

        Args:
            community_id: Community UUID.

        Returns:
            List of relationship dicts.
        """
        query = """
        MATCH (c:Community {id: $community_id})-[:HAS_ENTITY]->(e1:Entity)
        MATCH (e1)-[r:RELATED_TO]->(e2:Entity)
        WHERE (c)-[:HAS_ENTITY]->(e2)
        RETURN e1.canonical_name AS source,
               r.relation_type AS relation_type,
               e2.canonical_name AS target,
               r.weight AS weight
        ORDER BY r.weight DESC
        LIMIT 30
        """
        results = await self._pool.execute_query(query, {"community_id": community_id})
        return [
            {
                "source": r.get("source", ""),
                "relation_type": r.get("relation_type", "相关"),
                "target": r.get("target", ""),
                "weight": r.get("weight", 1.0),
            }
            for r in results
        ]

    async def _call_llm(
        self,
        community_id: str,
        level: int,
        entity_count: int,
        entities: list[dict[str, str]],
        relationships: list[dict[str, str]],
    ) -> CommunityReportOutput | None:
        """Call LLM to generate community report.

        Args:
            community_id: Community UUID.
            level: Community hierarchy level.
            entity_count: Number of entities.
            entities: List of entity dicts.
            relationships: List of relationship dicts.

        Returns:
            CommunityReportOutput or None on failure.
        """
        # Format entities for prompt
        entities_text = "\n".join(
            f"- {e['name']} ({e['type']}): {e['description']}"
            for e in entities[:30]  # Limit to avoid token overflow
        )

        # Format relationships for prompt
        relationships_text = "\n".join(
            f"- {r['source']} --[{r['relation_type']}]--> {r['target']}"
            for r in relationships[:20]  # Limit to avoid token overflow
        )
        if not relationships_text:
            relationships_text = "（无关系数据）"

        try:
            # Build user prompt from template
            prompt_loader = self._llm._prompts
            user_template = prompt_loader.get("community_report", "user")
            user_content = user_template.format(
                community_id=community_id,
                level=level,
                entity_count=entity_count,
                entities=entities_text,
                relationships=relationships_text,
            )

            system_prompt = prompt_loader.get("community_report", "system")

            raw_result = await self._llm.call_at(
                call_point=CallPoint.COMMUNITY_REPORT,
                payload={
                    "system_prompt": system_prompt,
                    "user_content": user_content,
                },
                output_model=CommunityReportOutput,
            )

            if not raw_result:
                log.warning("llm_empty_response", community_id=community_id)
                return None

            return raw_result

        except Exception as exc:
            log.error(
                "llm_call_failed",
                community_id=community_id,
                error=str(exc),
            )
            return None

    async def _store_report_embedding(
        self,
        report_id: str,
        content: str,
    ) -> bool:
        """Generate and store embedding for report content.

        Args:
            report_id: Report UUID.
            content: Report full content.

        Returns:
            True if successful.
        """
        try:
            embeddings = await self._llm.embed(
                "embedding.aiping_embedding.Qwen3-Embedding-0.6B", [content]
            )
            if embeddings:
                await self._repo.update_report_embedding(report_id, embeddings[0])
                log.debug("report_embedding_stored", report_id=report_id)
                return True
        except Exception as exc:
            log.warning(
                "report_embedding_failed",
                report_id=report_id,
                error=str(exc),
            )
        return False

    async def mark_stale_reports(self) -> int:
        """Mark reports as stale when community entity count changed significantly.

        Returns:
            Number of reports marked as stale.
        """
        query = """
        MATCH (r:CommunityReport)-[:REPORTS_ON]->(c:Community)
        WHERE r.stale = false
        WITH r, c,
             c.entity_count AS current_count,
             size([(c)-[:HAS_ENTITY]->(e) | e]) AS actual_count
        WHERE abs(current_count - actual_count) > current_count * 0.2
        SET r.stale = true
        RETURN count(r) AS stale_count
        """
        result = await self._pool.execute_query(query)
        if result:
            stale_count = result[0].get("stale_count", 0)
            if stale_count > 0:
                log.info("reports_marked_stale", count=stale_count)
            return stale_count
        return 0
