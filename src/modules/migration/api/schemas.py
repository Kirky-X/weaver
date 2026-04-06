# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Pydantic schemas for migration API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class MigrationRequest(BaseModel):
    """Request to start a migration."""

    source_db: str = Field(
        ...,
        description="Source database type: postgres | duckdb | neo4j | ladybug",
    )
    target_db: str = Field(
        ...,
        description="Target database type: postgres | duckdb | neo4j | ladybug",
    )
    tables: list[str] | None = Field(
        None,
        description="Tables/nodes to migrate (null = all)",
    )
    batch_size: int = Field(
        5000,
        ge=100,
        le=50000,
        description="Rows per batch",
    )
    incremental_key: str | None = Field(
        None,
        description="Column for incremental migration",
    )
    incremental_since: Any | None = Field(
        None,
        description="Starting value for incremental migration",
    )
    mapping_file: str | None = Field(
        None,
        description="Path to YAML mapping rules file",
    )
    strict_mode: bool = Field(
        False,
        description="Fail on type conversion errors",
    )


class ItemProgress(BaseModel):
    """Progress for a single table/node."""

    table: str
    total: int
    migrated: int
    percent: float
    status: str
    error: str | None = None


class MigrationProgressResponse(BaseModel):
    """Response for migration progress query."""

    task_id: str
    source_db: str
    target_db: str
    items: list[ItemProgress]
    total_migrated: int
    total_expected: int
    started_at: datetime
    elapsed_seconds: float
    status: str
    error: str | None = None


class MigrationStatusResponse(BaseModel):
    """Response for migration start request."""

    task_id: str
    status: str
    message: str


class MigrationCancelResponse(BaseModel):
    """Response for migration cancel request."""

    task_id: str
    status: str
    message: str


class MappingUploadRequest(BaseModel):
    """Request to upload a mapping file."""

    name: str = Field(..., description="Mapping name")
    content: str = Field(..., description="YAML content of mapping rules")


class MappingInfo(BaseModel):
    """Information about a mapping."""

    name: str
    node_mappings: list[str]
    rel_mappings: list[str]


class MappingListResponse(BaseModel):
    """Response for listing mappings."""

    mappings: list[MappingInfo]


class ErrorResponse(BaseModel):
    """Error response."""

    error: str
    detail: str | None = None
