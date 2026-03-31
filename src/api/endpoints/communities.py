# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Community management API endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.dependencies import get_llm_client, get_neo4j_pool
from api.middleware.auth import verify_api_key
from api.schemas.response import APIResponse, success_response
from core.constants import ProcessingStatus
from core.db.neo4j import Neo4jPool
from core.observability.logging import get_logger
from modules.knowledge.graph.community_detector import CommunityDetector
from modules.knowledge.graph.community_repo import Neo4jCommunityRepo
from modules.knowledge.graph.community_report_generator import (
    CommunityReportGenerator,
    ReportGenerationResult,
)

log = get_logger("community_api")

router = APIRouter(prefix="/admin/communities", tags=["admin", "communities"])


# ── Request/Response Models ─────────────────────────────────────


class RebuildRequest(BaseModel):
    """Request model for community rebuild."""

    max_cluster_size: int = Field(default=10, ge=1, le=100, description="Maximum cluster size")
    seed: int = Field(default=42, description="Random seed for reproducibility")


class RebuildResponse(BaseModel):
    """Response model for community rebuild."""

    status: str
    communities_created: int
    entities_processed: int
    levels: int
    modularity: float
    orphan_count: int
    execution_time_ms: float


class ReportGenerateResponse(BaseModel):
    """Response model for report generation."""

    total: int
    success: int
    failed: int
    failed_ids: list[str] = Field(default_factory=list)


class CommunityResponse(BaseModel):
    """Response model for a single community."""

    id: str
    title: str | None = None
    level: int
    entity_count: int
    parent_id: str | None
    rank: float | None = None
    period: str | None
    has_report: bool = False


class CommunityDetailResponse(BaseModel):
    """Detailed response model for a community."""

    id: str
    title: str | None = None
    level: int
    entity_count: int
    parent_id: str | None
    children_ids: list[str] = Field(default_factory=list)
    rank: float | None = None
    period: str | None
    modularity: float | None
    entities: list[dict[str, str]] = Field(default_factory=list)
    report: dict[str, Any] | None = None


class CommunityListResponse(BaseModel):
    """Response model for community list."""

    communities: list[CommunityResponse]
    total: int
    level: int | None


# ── Endpoints ───────────────────────────────────────────


@router.post("/rebuild", response_model=APIResponse[RebuildResponse])
async def rebuild_communities(
    request: RebuildRequest = RebuildRequest(),
    _: str = Depends(verify_api_key),
    pool: Neo4jPool = Depends(get_neo4j_pool),
) -> APIResponse[RebuildResponse]:
    """Rebuild all communities from scratch.

    This endpoint:
    1. Deletes all existing communities
    2. Runs Hierarchical Leiden detection
    3. Creates new Community nodes with HAS_ENTITY relationships

    Args:
        request: Rebuild parameters.
        _: Verified API key.
        pool: Neo4j connection pool.

    Returns:
        Rebuild statistics.
    """
    log.info("community_rebuild_requested", max_cluster_size=request.max_cluster_size)

    detector = CommunityDetector(
        pool=pool,
        max_cluster_size=request.max_cluster_size,
        default_seed=request.seed,
    )

    try:
        result = await detector.rebuild_communities(
            max_cluster_size=request.max_cluster_size,
            seed=request.seed,
        )

        log.info(
            "community_rebuild_complete",
            communities=result.total_communities,
            entities=result.total_entities,
            modularity=result.modularity,
        )

        return success_response(
            RebuildResponse(
                status=ProcessingStatus.COMPLETED.value,
                communities_created=result.total_communities,
                entities_processed=result.total_entities,
                levels=result.levels,
                modularity=result.modularity,
                orphan_count=result.orphan_count,
                execution_time_ms=result.execution_time_ms,
            )
        )

    except Exception as exc:
        log.error("community_rebuild_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Rebuild failed: {exc!s}")


@router.post("/reports/generate", response_model=APIResponse[ReportGenerateResponse])
async def generate_all_reports(
    level: int | None = Query(None, description="Community level filter"),
    regenerate_stale: bool = Query(True, description="Regenerate stale reports"),
    _: str = Depends(verify_api_key),
    pool: Neo4jPool = Depends(get_neo4j_pool),
    llm: Any = Depends(get_llm_client),
) -> APIResponse[ReportGenerateResponse]:
    """Generate reports for all communities.

    Args:
        level: Optional community level filter.
        regenerate_stale: Whether to regenerate stale reports.
        _: Verified API key.
        pool: Neo4j connection pool.
        llm: LLM client.

    Returns:
        Generation statistics.
    """
    log.info("report_generation_requested", level=level)

    generator = CommunityReportGenerator(pool=pool, llm_client=llm)

    try:
        result = await generator.generate_all_reports(
            level=level,
            regenerate_stale=regenerate_stale,
        )

        log.info(
            "report_generation_complete",
            total=result["total"],
            success=result["success"],
            failed=result["failed"],
        )

        return success_response(
            ReportGenerateResponse(
                total=result["total"],
                success=result["success"],
                failed=result["failed"],
                failed_ids=result.get("failed_ids", []),
            )
        )

    except Exception as exc:
        log.error("report_generation_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Report generation failed: {exc!s}")


@router.post(
    "/{community_id}/report/regenerate",
    response_model=APIResponse[dict[str, Any]],
)
async def regenerate_report(
    community_id: str,
    _: str = Depends(verify_api_key),
    pool: Neo4jPool = Depends(get_neo4j_pool),
    llm: Any = Depends(get_llm_client),
) -> APIResponse[dict[str, Any]]:
    """Regenerate report for a specific community.

    Args:
        community_id: Community UUID.
        _: Verified API key.
        pool: Neo4j connection pool.
        llm: LLM client.

    Returns:
        Generation result.
    """
    generator = CommunityReportGenerator(pool=pool, llm_client=llm)

    try:
        result: ReportGenerationResult = await generator.regenerate_report(community_id)

        if result.success:
            return success_response(
                {
                    "status": ProcessingStatus.COMPLETED.value,
                    "community_id": community_id,
                    "report_id": result.report_id,
                }
            )
        else:
            # Check if community not found
            error_msg = result.error or "Unknown error"
            if "not found" in error_msg.lower():
                raise HTTPException(
                    status_code=404,
                    detail=f"Community '{community_id}' not found",
                )
            raise HTTPException(
                status_code=500,
                detail=f"Report regeneration failed: {error_msg}",
            )

    except HTTPException:
        raise
    except Exception as exc:
        log.error("report_regeneration_failed", community_id=community_id, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Report regeneration failed: {exc!s}")


# ── Graph Community Endpoints ─────────────────────────────────────

graph_router = APIRouter(prefix="/graph/communities", tags=["graph", "communities"])


@graph_router.get("", response_model=APIResponse[CommunityListResponse])
async def list_communities(
    level: int | None = Query(None, description="Filter by community level"),
    limit: int = Query(20, ge=1, le=100, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Result offset"),
    _: str = Depends(verify_api_key),
    pool: Neo4jPool = Depends(get_neo4j_pool),
) -> APIResponse[CommunityListResponse]:
    """List communities, optionally filtered by level.

    Args:
        level: Optional level filter.
        limit: Maximum number of results.
        offset: Result offset for pagination.
        _: Verified API key.
        pool: Neo4j connection pool.

    Returns:
        List of communities.
    """
    repo = Neo4jCommunityRepo(pool)

    try:
        communities = await repo.list_communities(level=level, limit=limit, offset=offset)
        total = await repo.count_communities(level=level)

        # Check which communities have reports
        community_responses = []
        for c in communities:
            report = await repo.get_report(c.id)
            community_responses.append(
                CommunityResponse(
                    id=c.id,
                    title=c.title,
                    level=c.level,
                    entity_count=c.entity_count,
                    parent_id=c.parent_id,
                    rank=c.rank,
                    period=c.period,
                    has_report=report is not None,
                )
            )

        return success_response(
            CommunityListResponse(
                communities=community_responses,
                total=total,
                level=level,
            )
        )

    except Exception as exc:
        log.error("list_communities_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Failed to list communities: {exc!s}")


@graph_router.get("/{community_id}", response_model=APIResponse[CommunityDetailResponse])
async def get_community(
    community_id: str,
    _: str = Depends(verify_api_key),
    pool: Neo4jPool = Depends(get_neo4j_pool),
) -> APIResponse[CommunityDetailResponse]:
    """Get detailed information about a specific community.

    Args:
        community_id: Community UUID.
        _: Verified API key.
        pool: Neo4j connection pool.

    Returns:
        Community details with entities and report.
    """
    repo = Neo4jCommunityRepo(pool)

    try:
        community = await repo.get_community(community_id)

        if community is None:
            raise HTTPException(status_code=404, detail="Community not found")

        # Get entities
        entities_query = """
        MATCH (c:Community {id: $community_id})-[:HAS_ENTITY]->(e:Entity)
        RETURN e.canonical_name AS name, e.type AS type
        ORDER BY e.canonical_name
        LIMIT 50
        """
        entities_result = await pool.execute_query(
            entities_query,
            {"community_id": community_id},
        )
        entities = [
            {"name": r.get("name", ""), "type": r.get("type", "未知")} for r in entities_result
        ]

        # Get children
        children_query = """
        MATCH (c:Community {parent_id: $community_id})
        RETURN c.id AS id
        """
        children_result = await pool.execute_query(
            children_query,
            {"community_id": community_id},
        )
        children_ids = [r.get("id", "") for r in children_result]

        # Get report
        report = await repo.get_report(community_id)
        report_data = None
        if report:
            report_data = {
                "summary": report.summary,
                "rank": report.rank,
                "key_entities": report.key_entities,
            }

        return success_response(
            CommunityDetailResponse(
                id=community.id,
                title=community.title,
                level=community.level,
                entity_count=community.entity_count,
                parent_id=community.parent_id,
                children_ids=children_ids,
                rank=community.rank,
                period=community.period,
                modularity=community.modularity,
                entities=entities,
                report=report_data,
            )
        )

    except HTTPException:
        raise
    except Exception as exc:
        log.error("get_community_failed", community_id=community_id, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Failed to get community: {exc!s}")
