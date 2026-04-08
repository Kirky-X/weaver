# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Community management API endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.dependencies import get_graph_pool, get_llm_client
from api.middleware.auth import verify_api_key
from api.schemas.response import APIResponse, success_response
from core.constants import ProcessingStatus
from core.observability.logging import get_logger
from core.protocols import GraphPool
from modules.knowledge.graph.community_detector import CommunityDetector
from modules.knowledge.graph.community_health_checker import CommunityHealthChecker
from modules.knowledge.graph.community_health_models import (
    IssueType,
)
from modules.knowledge.graph.community_repair_service import CommunityRepairService
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


# ── Health Check Models ───────────────────────────────────────


class HealthOverviewResponse(BaseModel):
    """Response model for community health overview."""

    status: str
    score: float
    total_communities: int
    communities_with_reports: int
    stale_reports: int
    empty_communities: int
    hierarchy_issues: int
    last_check_at: str | None


class IssueDetail(BaseModel):
    """Detail model for a health issue."""

    issue_type: str
    severity: str
    community_id: str | None = None
    description: str
    suggestion: str
    auto_repairable: bool


class DiagnoseResponse(BaseModel):
    """Response model for full health diagnosis."""

    status: str
    score: float
    issues: list[IssueDetail]
    metrics: dict[str, Any]
    repair_suggestions: list[str]


class RepairRequest(BaseModel):
    """Request model for repair operation."""

    repair_types: list[str] | None = Field(
        default=None,
        description="Specific repair types to run, or None for all auto-repairable",
    )
    dry_run: bool = Field(
        default=False,
        description="If True, only count without making changes",
    )


class RepairResponse(BaseModel):
    """Response model for repair operation."""

    repaired: dict[str, int]
    failed: dict[str, list[str]]
    duration_ms: float


# ── Endpoints ───────────────────────────────────────────


@router.post("/rebuild", response_model=APIResponse[RebuildResponse])
async def rebuild_communities(
    request: RebuildRequest = RebuildRequest(),
    _: str = Depends(verify_api_key),
    pool: GraphPool = Depends(get_graph_pool),
) -> APIResponse[RebuildResponse]:
    """Rebuild all communities from scratch.

    This endpoint:
    1. Deletes all existing communities
    2. Runs Hierarchical Leiden detection
    3. Creates new Community nodes with HAS_ENTITY relationships

    Args:
        request: Rebuild parameters.
        _: Verified API key.
        pool: GraphPool connection pool.

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
    pool: GraphPool = Depends(get_graph_pool),
    llm: Any = Depends(get_llm_client),
) -> APIResponse[ReportGenerateResponse]:
    """Generate reports for all communities.

    Args:
        level: Optional community level filter.
        regenerate_stale: Whether to regenerate stale reports.
        _: Verified API key.
        pool: GraphPool connection pool.
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
    pool: GraphPool = Depends(get_graph_pool),
    llm: Any = Depends(get_llm_client),
) -> APIResponse[dict[str, Any]]:
    """Regenerate report for a specific community.

    Args:
        community_id: Community UUID.
        _: Verified API key.
        pool: GraphPool connection pool.
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
    pool: GraphPool = Depends(get_graph_pool),
) -> APIResponse[CommunityListResponse]:
    """List communities, optionally filtered by level.

    Args:
        level: Optional level filter.
        limit: Maximum number of results.
        offset: Result offset for pagination.
        _: Verified API key.
        pool: GraphPool connection pool.

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
    pool: GraphPool = Depends(get_graph_pool),
) -> APIResponse[CommunityDetailResponse]:
    """Get detailed information about a specific community.

    Args:
        community_id: Community UUID.
        _: Verified API key.
        pool: GraphPool connection pool.

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


# ── Health Check Endpoints ───────────────────────────────────────


@router.get("/health", response_model=APIResponse[HealthOverviewResponse])
async def get_health_overview(
    _: str = Depends(verify_api_key),
    pool: GraphPool = Depends(get_graph_pool),
) -> APIResponse[HealthOverviewResponse]:
    """Get community health overview.

    Returns a quick summary of community health status without full diagnosis.

    Args:
        _: Verified API key.
        pool: GraphPool connection pool.

    Returns:
        Health overview with status and key metrics.

    """
    checker = CommunityHealthChecker(pool)

    try:
        # Quick metrics check
        metrics = await checker._repo.get_overall_metrics()

        # Determine basic status from metrics
        total = metrics.get("total_communities", 0)
        empty = metrics.get("empty_community_count", 0)
        with_reports = metrics.get("communities_with_reports", 0)
        stale = metrics.get("stale_report_count", 0)

        if total == 0:
            status = "critical"
            score = 0.0
        else:
            empty_ratio = empty / total if total > 0 else 0
            report_ratio = with_reports / total if total > 0 else 0

            # Quick score calculation
            score = 100.0
            if empty_ratio > 0.10:
                score -= 30
            elif empty_ratio > 0.05:
                score -= 15
            if report_ratio < 0.7:
                score -= 10
            if stale > 0:
                score -= 5

            score = max(0.0, min(100.0, score))

            if score >= 80:
                status = "healthy"
            elif score >= 60:
                status = "moderate"
            elif score >= 40:
                status = "degraded"
            else:
                status = "critical"

        # Get hierarchy breaks count
        hierarchy_breaks = await checker._repo.find_hierarchy_breaks()

        return success_response(
            HealthOverviewResponse(
                status=status,
                score=score,
                total_communities=total,
                communities_with_reports=with_reports,
                stale_reports=stale,
                empty_communities=empty,
                hierarchy_issues=len(hierarchy_breaks),
                last_check_at=None,  # No persistent last check time yet
            )
        )

    except Exception as exc:
        log.error("get_health_overview_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Health check failed: {exc!s}")


@router.post("/health/diagnose", response_model=APIResponse[DiagnoseResponse])
async def diagnose_health(
    _: str = Depends(verify_api_key),
    pool: GraphPool = Depends(get_graph_pool),
) -> APIResponse[DiagnoseResponse]:
    """Perform full community health diagnosis.

    Runs comprehensive checks including:
    - Empty communities
    - Entity count mismatches
    - Missing reports
    - Stale reports
    - Hierarchy integrity
    - Modularity score

    Args:
        _: Verified API key.
        pool: GraphPool connection pool.

    Returns:
        Detailed diagnosis with all issues and suggestions.

    """
    checker = CommunityHealthChecker(pool)

    try:
        report = await checker.diagnose_all()

        # Convert issues to response format
        issue_details = [
            IssueDetail(
                issue_type=issue.issue_type.value,
                severity=issue.severity,
                community_id=issue.community_id,
                description=issue.description,
                suggestion=issue.suggestion,
                auto_repairable=issue.auto_repairable,
            )
            for issue in report.issues
        ]

        # Extract repair suggestions
        suggestions = list({issue.suggestion for issue in report.issues if issue.auto_repairable})

        return success_response(
            DiagnoseResponse(
                status=report.status.value,
                score=report.score,
                issues=issue_details,
                metrics=report.metrics,
                repair_suggestions=suggestions,
            )
        )

    except Exception as exc:
        log.error("diagnose_health_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Diagnosis failed: {exc!s}")


@router.post("/health/repair", response_model=APIResponse[RepairResponse])
async def repair_health(
    request: RepairRequest = RepairRequest(),
    _: str = Depends(verify_api_key),
    pool: GraphPool = Depends(get_graph_pool),
    llm: Any = Depends(get_llm_client),
) -> APIResponse[RepairResponse]:
    """Repair community health issues.

    Automatically repairs auto-repairable issues:
    - Empty communities (delete)
    - Entity count mismatches (update)
    - Stale reports (regenerate)
    - Broken hierarchy references (clean up)

    Args:
        request: Repair parameters.
        _: Verified API key.
        pool: GraphPool connection pool.
        llm: LLM client for report regeneration.

    Returns:
        Repair results with counts and any failures.

    """
    log.info(
        "repair_health_requested",
        repair_types=request.repair_types,
        dry_run=request.dry_run,
    )

    # First diagnose to get issues
    checker = CommunityHealthChecker(pool)
    report = await checker.diagnose_all()

    # Filter to auto-repairable issues
    repairable_issues = [i for i in report.issues if i.auto_repairable]

    # Filter by requested repair types if specified
    if request.repair_types:
        type_set = {IssueType(t) for t in request.repair_types}
        repairable_issues = [i for i in repairable_issues if i.issue_type in type_set]

    if not repairable_issues:
        return success_response(
            RepairResponse(
                repaired={},
                failed={},
                duration_ms=0.0,
            )
        )

    # Create repair service
    report_generator = CommunityReportGenerator(pool=pool, llm_client=llm)
    repair_service = CommunityRepairService(pool=pool, report_generator=report_generator)

    try:
        summary = await repair_service.auto_repair(
            issues=repairable_issues,
            dry_run=request.dry_run,
        )

        # Build response
        repaired = {}
        failed = {}

        for result in summary.results:
            if result.success:
                repaired[result.repair_type] = result.affected_count
            else:
                failed[result.repair_type] = [result.error or "Unknown error"]

        log.info(
            "repair_health_complete",
            repaired=repaired,
            failed_count=len(failed),
            duration_ms=summary.duration_ms,
        )

        return success_response(
            RepairResponse(
                repaired=repaired,
                failed=failed,
                duration_ms=summary.duration_ms,
            )
        )

    except Exception as exc:
        log.error("repair_health_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Repair failed: {exc!s}")
