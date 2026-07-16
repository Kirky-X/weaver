# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Migration module for database data transfer.

This module provides unified data migration between:
- PostgreSQL ↔ DuckDB (relational databases)
- Neo4j ↔ LadybugDB (graph databases)

Features:
- Streaming batch processing for large datasets
- Rich progress bar display
- Full and incremental migration modes
- Custom mapping rules via YAML configuration

公开 API:
- MigrationEngine: 迁移引擎
- MigrationConfig: 迁移配置
- MigrationResult: 迁移结果
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
