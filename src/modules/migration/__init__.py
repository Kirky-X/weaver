# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Migration module for database data transfer.

This module provides unified data migration between:
- PostgreSQL ↔ DuckDB (relational databases)
- Neo4j ↔ LadybugDB (graph databases)

Features:
- Streaming batch processing for large datasets
- Rich progress bar display
- Full and incremental migration modes
- Custom mapping rules via YAML configuration
- FastAPI routes + Typer CLI dual entry points
"""

from __future__ import annotations

from .engine import MigrationEngine
from .models import (
    ColumnDef,
    MigrationConfig,
    MigrationProgress,
    MigrationResult,
    MigrationSchema,
    NodeSchema,
    RelSchema,
)

__all__ = [
    "ColumnDef",
    "MigrationConfig",
    "MigrationEngine",
    "MigrationProgress",
    "MigrationResult",
    "MigrationSchema",
    "NodeSchema",
    "RelSchema",
]
