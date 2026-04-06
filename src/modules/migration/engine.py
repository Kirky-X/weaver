# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Migration engine for database data transfer.

Core engine that orchestrates migration between:
- PostgreSQL ↔ DuckDB (relational databases)
- Neo4j ↔ LadybugDB (graph databases)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from core.observability.logging import get_logger
from modules.migration.adapters import (
    DuckDBSource,
    DuckDBTarget,
    LadybugSource,
    LadybugTarget,
    Neo4jSource,
    Neo4jTarget,
    PostgresSource,
    PostgresTarget,
)
from modules.migration.exceptions import MigrationError, UnsupportedDatabaseError
from modules.migration.mapping_registry import MappingRegistry
from modules.migration.models import MigrationConfig, MigrationProgress, MigrationResult
from modules.migration.progress import MigrationProgressDisplay

log = get_logger("migration_engine")

SUPPORTED_RELATIONAL_DBS = ["postgres", "duckdb"]
SUPPORTED_GRAPH_DBS = ["neo4j", "ladybug"]


class MigrationEngine:
    """Orchestrates database migration operations.

    Supports:
    - Relational migrations: PostgreSQL ↔ DuckDB
    - Graph migrations: Neo4j ↔ LadybugDB
    - Full and incremental migration modes
    - Custom mapping rules
    - Progress tracking and cancellation
    """

    def __init__(
        self,
        config: MigrationConfig,
        container: Any,
        mapping_registry: MappingRegistry | None = None,
    ) -> None:
        """Initialize the migration engine.

        Args:
            config: Migration configuration.
            container: Dependency injection container with database pools.
            mapping_registry: Optional mapping rules registry.
        """
        self._config = config
        self._container = container
        self._mapping_registry = mapping_registry or MappingRegistry()

        self._progress: dict[str, MigrationProgress] = {}
        self._cancelled = False
        self._display: MigrationProgressDisplay | None = None
        self._started_at: datetime | None = None

        # Load mapping file if specified
        if config.mapping_file:
            self._mapping_registry.load(config.mapping_file)

    def _is_graph_migration(self) -> bool:
        """Check if this is a graph database migration."""
        return (
            self._config.source_db in SUPPORTED_GRAPH_DBS
            or self._config.target_db in SUPPORTED_GRAPH_DBS
        )

    def _create_relational_source(self) -> Any:
        """Create the appropriate source adapter."""
        source_db = self._config.source_db.lower()

        if source_db == "postgres":
            pool = self._container.relational_pool
            return PostgresSource(pool)
        elif source_db == "duckdb":
            pool = self._container.duckdb_pool
            return DuckDBSource(pool)

        raise UnsupportedDatabaseError(source_db, SUPPORTED_RELATIONAL_DBS)

    def _create_relational_target(self) -> Any:
        """Create the appropriate target adapter."""
        target_db = self._config.target_db.lower()

        if target_db == "postgres":
            pool = self._container.relational_pool
            return PostgresTarget(pool)
        elif target_db == "duckdb":
            pool = self._container.duckdb_pool
            return DuckDBTarget(pool)

        raise UnsupportedDatabaseError(target_db, SUPPORTED_RELATIONAL_DBS)

    def _create_graph_source(self) -> Any:
        """Create the appropriate graph source adapter."""
        source_db = self._config.source_db.lower()

        if source_db == "neo4j":
            pool = self._container.graph_pool
            return Neo4jSource(pool)
        elif source_db == "ladybug":
            pool = self._container.ladybug_pool
            return LadybugSource(pool)

        raise UnsupportedDatabaseError(source_db, SUPPORTED_GRAPH_DBS)

    def _create_graph_target(self) -> Any:
        """Create the appropriate graph target adapter."""
        target_db = self._config.target_db.lower()

        if target_db == "neo4j":
            pool = self._container.graph_pool
            return Neo4jTarget(pool)
        elif target_db == "ladybug":
            pool = self._container.ladybug_pool
            return LadybugTarget(pool)

        raise UnsupportedDatabaseError(target_db, SUPPORTED_GRAPH_DBS)

    async def run(self) -> MigrationResult:
        """Execute the migration.

        Returns:
            MigrationResult with details of the operation.
        """
        self._started_at = datetime.utcnow()
        is_graph = self._is_graph_migration()

        # Initialize progress display
        self._display = MigrationProgressDisplay(
            source_db=self._config.source_db,
            target_db=self._config.target_db,
            is_graph=is_graph,
        )

        try:
            if is_graph:
                result = await self._run_graph()
            else:
                result = await self._run_relational()

            result.completed_at = datetime.utcnow()
            self._display.print_summary()

            return result

        except Exception as exc:
            log.error("migration_failed", error=str(exc))
            if self._display:
                self._display.stop()
            raise MigrationError(f"Migration failed: {exc}") from exc

    async def _run_relational(self) -> MigrationResult:
        """Execute relational database migration."""
        source = self._create_relational_source()
        target = self._create_relational_target()

        # Get tables to migrate
        if self._config.tables:
            tables = self._config.tables
        else:
            tables = await source.get_table_names()

        # Initialize result
        result = MigrationResult(
            config=self._config,
            items=[],
            started_at=self._started_at or datetime.utcnow(),
        )

        self._display.start()

        for table in tables:
            if self._cancelled:
                break

            try:
                await self._migrate_table(source, target, table, result)
            except Exception as exc:
                log.error("table_migration_failed", table=table, error=str(exc))
                if self._display:
                    self._display.fail(table, str(exc))
                result.errors.append(f"{table}: {exc}")

        # Finalize result
        result.status = "success" if not result.errors else "partial"
        result.total_migrated = sum(p.migrated for p in result.items)
        result.total_expected = sum(p.total for p in result.items)

        return result

    async def _migrate_table(
        self,
        source: Any,
        target: Any,
        table: str,
        result: MigrationResult,
    ) -> None:
        """Migrate a single table."""
        # Get total count
        total = await source.count(table)

        # Initialize progress
        progress = MigrationProgress(table=table, total=total, status="running")
        self._progress[table] = progress
        result.items.append(progress)

        self._display.add_table(table, total)

        # Ensure schema exists
        schemas = await source.read_schema()
        table_schema = next((s for s in schemas if s.table == table), None)

        if table_schema:
            await target.ensure_schema(table_schema)

        # Migrate data
        offset = 0
        batch_size = self._config.batch_size

        if self._config.incremental_key and self._config.incremental_since:
            # Incremental migration
            async for batch in source.read_incremental(
                table,
                self._config.incremental_key,
                self._config.incremental_since,
                batch_size,
            ):
                if self._cancelled:
                    break

                written = await target.write_batch(table, batch)
                progress.migrated += written
                self._display.update(table, written)

                offset += len(batch)
        else:
            # Full migration
            while offset < total and not self._cancelled:
                batch = await source.read_batch(table, offset, batch_size)
                if not batch:
                    break

                written = await target.write_batch(table, batch)
                progress.migrated += written
                self._display.update(table, written)

                offset += len(batch)

        # Complete or cancel
        if self._cancelled:
            progress.status = "failed"
            self._display.cancel(table)
        else:
            progress.status = "completed"
            self._display.complete(table)

    async def _run_graph(self) -> MigrationResult:
        """Execute graph database migration."""
        source = self._create_graph_source()
        target = self._create_graph_target()

        # Get labels/types to migrate
        if self._config.tables:
            labels = self._config.tables
        else:
            labels = await source.get_label_names()

        # Initialize result
        result = MigrationResult(
            config=self._config,
            items=[],
            started_at=self._started_at or datetime.utcnow(),
        )

        self._display.start()

        # 1. Migrate nodes first (to ensure referential integrity)
        node_schemas = await source.read_node_schema()
        await target.ensure_node_schema(node_schemas)

        for label in labels:
            if self._cancelled:
                break

            try:
                await self._migrate_nodes(source, target, label, result)
            except Exception as exc:
                log.error("node_migration_failed", label=label, error=str(exc))
                if self._display:
                    self._display.fail(label, str(exc))
                result.errors.append(f"{label}: {exc}")

        # 2. Migrate relationships
        rel_types = await source.get_rel_type_names()
        rel_schemas = await source.read_rel_schema()
        await target.ensure_rel_schema(rel_schemas)

        for rel_type in rel_types:
            if self._cancelled:
                break

            try:
                await self._migrate_rels(source, target, rel_type, result)
            except Exception as exc:
                log.error("rel_migration_failed", rel_type=rel_type, error=str(exc))
                result.errors.append(f"{rel_type}: {exc}")

        # Finalize result
        result.status = "success" if not result.errors else "partial"
        result.total_migrated = sum(p.migrated for p in result.items)
        result.total_expected = sum(p.total for p in result.items)

        return result

    async def _migrate_nodes(
        self,
        source: Any,
        target: Any,
        label: str,
        result: MigrationResult,
    ) -> None:
        """Migrate nodes with a specific label."""
        total = await source.count_nodes(label)

        progress = MigrationProgress(table=label, total=total, status="running")
        self._progress[label] = progress
        result.items.append(progress)

        self._display.add_table(label, total)

        offset = 0
        batch_size = self._config.batch_size

        while offset < total and not self._cancelled:
            nodes = await source.read_nodes(label, offset, batch_size)
            if not nodes:
                break

            # Apply mappings if configured
            migrated_nodes = []
            for node in nodes:
                if self._mapping_registry.has_node_mapping(label):
                    _, props = self._mapping_registry.transform_node(label, node)
                    migrated_nodes.append(props)
                else:
                    migrated_nodes.append(node)

            written = await target.write_nodes(label, migrated_nodes)
            progress.migrated += written
            self._display.update(label, written)

            offset += len(nodes)

        if self._cancelled:
            progress.status = "failed"
            self._display.cancel(label)
        else:
            progress.status = "completed"
            self._display.complete(label)

    async def _migrate_rels(
        self,
        source: Any,
        target: Any,
        rel_type: str,
        result: MigrationResult,
    ) -> None:
        """Migrate relationships of a specific type."""
        total = await source.count_rels(rel_type)

        progress = MigrationProgress(table=rel_type, total=total, status="running")
        self._progress[rel_type] = progress
        result.items.append(progress)

        self._display.add_table(rel_type, total)

        offset = 0
        batch_size = self._config.batch_size

        while offset < total and not self._cancelled:
            rels = await source.read_rels(rel_type, offset, batch_size)
            if not rels:
                break

            # Apply mappings if configured
            migrated_rels = []
            for rel in rels:
                if self._mapping_registry.has_rel_mapping(rel_type):
                    _, props = self._mapping_registry.transform_rel(rel_type, rel)
                    # Preserve metadata
                    props["_source_id"] = rel.get("_source_id")
                    props["_target_id"] = rel.get("_target_id")
                    props["_source_label"] = rel.get("_source_label")
                    props["_target_label"] = rel.get("_target_label")
                    migrated_rels.append(props)
                else:
                    migrated_rels.append(rel)

            written = await target.write_rels(rel_type, migrated_rels)
            progress.migrated += written
            self._display.update(rel_type, written)

            offset += len(rels)

        if self._cancelled:
            progress.status = "failed"
            self._display.cancel(rel_type)
        else:
            progress.status = "completed"
            self._display.complete(rel_type)

    def cancel(self) -> None:
        """Cancel the migration."""
        self._cancelled = True
        log.info("migration_cancelled")

    def get_progress(self) -> dict[str, MigrationProgress]:
        """Get current progress for all tables/nodes."""
        return dict(self._progress)

    def get_progress_dict(self) -> dict[str, dict[str, Any]]:
        """Get progress as dictionary for API responses."""
        if self._display:
            return self._display.get_progress_dict()
        return {}
