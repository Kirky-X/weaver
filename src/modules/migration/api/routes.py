# Copyright (c) 2026 KirkyX. All Rights Reserved
"""FastAPI routes for migration API."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from modules.migration.api.dependencies import MigrationService, get_migration_service
from modules.migration.api.schemas import (
    ErrorResponse,
    MappingInfo,
    MappingListResponse,
    MappingUploadRequest,
    MigrationCancelResponse,
    MigrationProgressResponse,
    MigrationRequest,
    MigrationStatusResponse,
)
from modules.migration.mapping_registry import MappingRegistry
from modules.migration.models import MigrationConfig

router = APIRouter(prefix="/migration", tags=["migration"])

# Global mapping registry for uploaded mappings
_uploaded_mappings: dict[str, MappingRegistry] = {}


@router.post(
    "/relational",
    response_model=MigrationStatusResponse,
    responses={400: {"model": ErrorResponse}},
)
async def start_relational_migration(
    request: MigrationRequest,
    background_tasks: BackgroundTasks,
    service: MigrationService = Depends(get_migration_service),
) -> MigrationStatusResponse:
    """Start a relational database migration (PostgreSQL ↔ DuckDB)."""
    # Validate database types
    valid_dbs = ["postgres", "duckdb"]
    if request.source_db.lower() not in valid_dbs:
        raise HTTPException(
            400,
            f"Invalid source_db: {request.source_db}. Must be one of {valid_dbs}",
        )
    if request.target_db.lower() not in valid_dbs:
        raise HTTPException(
            400,
            f"Invalid target_db: {request.target_db}. Must be one of {valid_dbs}",
        )
    if request.source_db.lower() == request.target_db.lower():
        raise HTTPException(400, "Source and target databases must be different")

    # Create config
    config = MigrationConfig(
        source_db=request.source_db.lower(),
        target_db=request.target_db.lower(),
        tables=request.tables,
        batch_size=request.batch_size,
        incremental_key=request.incremental_key,
        incremental_since=request.incremental_since,
        mapping_file=request.mapping_file,
        strict_mode=request.strict_mode,
    )

    # Create task
    task_id = service.create_task(config)

    # Schedule background execution
    background_tasks.add_task(service.run_migration, task_id)

    return MigrationStatusResponse(
        task_id=task_id,
        status="pending",
        message=f"Migration from {request.source_db} to {request.target_db} started",
    )


@router.post(
    "/graph",
    response_model=MigrationStatusResponse,
    responses={400: {"model": ErrorResponse}},
)
async def start_graph_migration(
    request: MigrationRequest,
    background_tasks: BackgroundTasks,
    service: MigrationService = Depends(get_migration_service),
) -> MigrationStatusResponse:
    """Start a graph database migration (Neo4j ↔ LadybugDB)."""
    # Validate database types
    valid_dbs = ["neo4j", "ladybug"]
    if request.source_db.lower() not in valid_dbs:
        raise HTTPException(
            400,
            f"Invalid source_db: {request.source_db}. Must be one of {valid_dbs}",
        )
    if request.target_db.lower() not in valid_dbs:
        raise HTTPException(
            400,
            f"Invalid target_db: {request.target_db}. Must be one of {valid_dbs}",
        )
    if request.source_db.lower() == request.target_db.lower():
        raise HTTPException(400, "Source and target databases must be different")

    # Create config
    config = MigrationConfig(
        source_db=request.source_db.lower(),
        target_db=request.target_db.lower(),
        tables=request.tables,
        batch_size=request.batch_size,
        mapping_file=request.mapping_file,
        strict_mode=request.strict_mode,
    )

    # Create task
    task_id = service.create_task(config)

    # Schedule background execution
    background_tasks.add_task(service.run_migration, task_id)

    return MigrationStatusResponse(
        task_id=task_id,
        status="pending",
        message=f"Graph migration from {request.source_db} to {request.target_db} started",
    )


@router.get(
    "/{task_id}/progress",
    response_model=MigrationProgressResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_migration_progress(
    task_id: str,
    service: MigrationService = Depends(get_migration_service),
) -> MigrationProgressResponse:
    """Get migration progress for a task."""
    status = service.get_status(task_id)

    if status["status"] == "not_found":
        raise HTTPException(404, f"Task {task_id} not found")

    config: MigrationConfig = status["config"]
    progress_data = status.get("progress", {})
    result = status.get("result", {})

    # Build items list
    items = []
    total_migrated = 0
    total_expected = 0

    for table, data in progress_data.items():
        items.append(
            {
                "table": table,
                "total": data.get("total", 0),
                "migrated": data.get("migrated", 0),
                "percent": data.get("percent", 0.0),
                "status": "completed" if data.get("completed") else "running",
                "error": data.get("error"),
            }
        )
        total_migrated += data.get("migrated", 0)
        total_expected += data.get("total", 0)

    # Override with result if completed
    if result:
        total_migrated = result.get("total_migrated", total_migrated)
        total_expected = result.get("total_expected", total_expected)

    # Calculate elapsed time
    started_at = status.get("started_at") or datetime.utcnow()
    elapsed_seconds = 0.0
    if started_at and status["status"] in ("running", "completed", "failed", "cancelled"):
        elapsed_seconds = (datetime.utcnow() - started_at).total_seconds()

    return MigrationProgressResponse(
        task_id=task_id,
        source_db=config.source_db,
        target_db=config.target_db,
        items=items,
        total_migrated=total_migrated,
        total_expected=total_expected,
        started_at=started_at,
        elapsed_seconds=elapsed_seconds,
        status=status["status"],
        error=status.get("error"),
    )


@router.post(
    "/{task_id}/cancel",
    response_model=MigrationCancelResponse,
    responses={404: {"model": ErrorResponse}},
)
async def cancel_migration(
    task_id: str,
    service: MigrationService = Depends(get_migration_service),
) -> MigrationCancelResponse:
    """Cancel a running migration."""
    success = service.cancel_task(task_id)

    if not success:
        raise HTTPException(404, f"Task {task_id} not found or not running")

    return MigrationCancelResponse(
        task_id=task_id,
        status="cancelled",
        message="Migration cancelled successfully",
    )


@router.post(
    "/mappings",
    response_model=MappingInfo,
    responses={400: {"model": ErrorResponse}},
)
async def upload_mapping(
    request: MappingUploadRequest,
) -> MappingInfo:
    """Upload a custom mapping configuration."""
    try:
        import yaml

        # Parse YAML content
        data = yaml.safe_load(request.content)

        # Create and load registry
        registry = MappingRegistry()

        # Parse nodes
        node_mappings = []
        for node_data in data.get("nodes", []):
            label = node_data.get("source_label", "")
            node_mappings.append(label)

        # Parse relations
        rel_mappings = []
        for rel_data in data.get("relations", []):
            rel_type = rel_data.get("source_type", "")
            rel_mappings.append(rel_type)

        # Store the mapping
        _uploaded_mappings[request.name] = registry

        return MappingInfo(
            name=request.name,
            node_mappings=node_mappings,
            rel_mappings=rel_mappings,
        )

    except yaml.YAMLError as exc:
        raise HTTPException(400, f"Invalid YAML: {exc}")


@router.get("/mappings", response_model=MappingListResponse)
async def list_mappings() -> MappingListResponse:
    """List all uploaded mappings."""
    mappings = []

    for name, registry in _uploaded_mappings.items():
        mappings.append(
            MappingInfo(
                name=name,
                node_mappings=registry.list_node_mappings(),
                rel_mappings=registry.list_rel_mappings(),
            )
        )

    return MappingListResponse(mappings=mappings)
