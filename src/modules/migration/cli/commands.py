# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Typer CLI commands for migration."""

from __future__ import annotations

from typing import Any

import typer
from rich.console import Console

app = typer.Typer(
    name="migration",
    help="Database migration tools for Weaver",
)
console = Console()


@app.command("relational")
def migrate_relational(
    source: str = typer.Option(..., "--from", "-s", help="Source database (postgres | duckdb)"),
    target: str = typer.Option(..., "--to", "-t", help="Target database (postgres | duckdb)"),
    tables: list[str] = typer.Option(None, "--table", "-T", help="Tables to migrate (repeatable)"),
    batch_size: int = typer.Option(5000, "--batch", "-b", help="Batch size"),
    incremental_key: str | None = typer.Option(
        None, "--incremental", "-i", help="Incremental key column"
    ),
    incremental_since: str | None = typer.Option(None, "--since", help="Incremental start value"),
    mapping: str | None = typer.Option(None, "--mapping", "-m", help="Mapping file path"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without executing"),
) -> None:
    """Migrate relational databases (PostgreSQL ↔ DuckDB).

    Examples:
        # Full migration
        python -m weaver migration relational --from postgres --to duckdb

        # Specific tables
        python -m weaver migration relational -s postgres -t duckdb -T articles -T entities

        # Incremental migration
        python -m weaver migration relational -s postgres -t duckdb \\
            --incremental updated_at --since "2024-01-01"

        # With custom mapping
        python -m weaver migration relational -s duckdb -t postgres \\
            --mapping config/mappings/custom.yaml
    """
    import asyncio

    from modules.migration.engine import MigrationEngine
    from modules.migration.mapping_registry import MappingRegistry
    from modules.migration.models import MigrationConfig

    # Validate database types
    source = source.lower()
    target = target.lower()

    if source not in ("postgres", "duckdb"):
        console.print(f"[red]Invalid source: {source}. Must be 'postgres' or 'duckdb'[/red]")
        raise typer.Exit(1)

    if target not in ("postgres", "duckdb"):
        console.print(f"[red]Invalid target: {target}. Must be 'postgres' or 'duckdb'[/red]")
        raise typer.Exit(1)

    if source == target:
        console.print("[red]Source and target must be different databases[/red]")
        raise typer.Exit(1)

    # Create config
    config = MigrationConfig(
        source_db=source,
        target_db=target,
        tables=tables or None,
        batch_size=batch_size,
        incremental_key=incremental_key,
        incremental_since=incremental_since,
        mapping_file=mapping,
    )

    if dry_run:
        console.print("\n[yellow]DRY RUN[/yellow] - Migration preview:")
        console.print(f"  Source:      {source}")
        console.print(f"  Target:      {target}")
        console.print(f"  Tables:      {tables or '(all)'}")
        console.print(f"  Batch size:  {batch_size}")
        if incremental_key:
            console.print(f"  Incremental: {incremental_key} >= {incremental_since}")
        if mapping:
            console.print(f"  Mapping:     {mapping}")
        console.print()
        return

    # Run migration
    async def run() -> Any:
        from container import Container

        container = Container()
        await container.startup()

        try:
            mapping_registry = None
            if mapping:
                mapping_registry = MappingRegistry()
                mapping_registry.load(mapping)

            engine = MigrationEngine(
                config=config,
                container=container,
                mapping_registry=mapping_registry,
            )

            return await engine.run()
        finally:
            await container.shutdown()

    result = asyncio.run(run())

    # Print summary
    console.print("\n[green]Migration completed![/green]")
    console.print(f"  Status:  {result.status}")
    console.print(f"  Migrated: {result.total_migrated:,} / {result.total_expected:,}")

    if result.errors:
        console.print(f"\n[red]Errors ({len(result.errors)}):[/red]")
        for error in result.errors[:5]:
            console.print(f"  - {error}")


@app.command("graph")
def migrate_graph(
    source: str = typer.Option(..., "--from", "-s", help="Source database (neo4j | ladybug)"),
    target: str = typer.Option(..., "--to", "-t", help="Target database (neo4j | ladybug)"),
    nodes: list[str] = typer.Option(
        None, "--node", "-n", help="Node labels to migrate (repeatable)"
    ),
    relations: list[str] = typer.Option(
        None, "--rel", "-r", help="Relationship types to migrate (repeatable)"
    ),
    batch_size: int = typer.Option(5000, "--batch", "-b", help="Batch size"),
    mapping: str | None = typer.Option(None, "--mapping", "-m", help="Mapping file path"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without executing"),
) -> None:
    """Migrate graph databases (Neo4j ↔ LadybugDB).

    Examples:
        # Full graph migration
        python -m weaver migration graph --from neo4j --to ladybug

        # Specific node labels
        python -m weaver migration graph -s neo4j -t ladybug \\
            --node Entity --node Article

        # With custom mapping
        python -m weaver migration graph -s ladybug -t neo4j \\
            --mapping config/mappings/entity_map.yaml
    """
    import asyncio

    from modules.migration.engine import MigrationEngine
    from modules.migration.mapping_registry import MappingRegistry
    from modules.migration.models import MigrationConfig

    # Validate database types
    source = source.lower()
    target = target.lower()

    if source not in ("neo4j", "ladybug"):
        console.print(f"[red]Invalid source: {source}. Must be 'neo4j' or 'ladybug'[/red]")
        raise typer.Exit(1)

    if target not in ("neo4j", "ladybug"):
        console.print(f"[red]Invalid target: {target}. Must be 'neo4j' or 'ladybug'[/red]")
        raise typer.Exit(1)

    if source == target:
        console.print("[red]Source and target must be different databases[/red]")
        raise typer.Exit(1)

    # Combine nodes and relations as "tables" for config
    tables = nodes + relations if nodes or relations else None

    config = MigrationConfig(
        source_db=source,
        target_db=target,
        tables=tables,
        batch_size=batch_size,
        mapping_file=mapping,
    )

    if dry_run:
        console.print("\n[yellow]DRY RUN[/yellow] - Graph migration preview:")
        console.print(f"  Source:      {source}")
        console.print(f"  Target:      {target}")
        console.print(f"  Nodes:       {nodes or '(all)'}")
        console.print(f"  Relations:   {relations or '(all)'}")
        console.print(f"  Batch size:  {batch_size}")
        if mapping:
            console.print(f"  Mapping:     {mapping}")
        console.print()
        return

    # Run migration
    async def run() -> Any:
        from container import Container

        container = Container()
        await container.startup()

        try:
            mapping_registry = None
            if mapping:
                mapping_registry = MappingRegistry()
                mapping_registry.load(mapping)

            engine = MigrationEngine(
                config=config,
                container=container,
                mapping_registry=mapping_registry,
            )

            return await engine.run()
        finally:
            await container.shutdown()

    result = asyncio.run(run())

    # Print summary
    console.print("\n[green]Graph migration completed![/green]")
    console.print(f"  Status:    {result.status}")
    console.print(f"  Migrated:  {result.total_migrated:,} / {result.total_expected:,}")

    if result.errors:
        console.print(f"\n[red]Errors ({len(result.errors)}):[/red]")
        for error in result.errors[:5]:
            console.print(f"  - {error}")


@app.command("list-mappings")
def list_mappings(
    mapping_dir: str = typer.Option("config/mappings", "--dir", "-d", help="Mapping directory"),
) -> None:
    """List available mapping files."""
    from pathlib import Path

    mapping_path = Path(mapping_dir)

    if not mapping_path.exists():
        console.print(f"[yellow]Mapping directory not found: {mapping_dir}[/yellow]")
        return

    yaml_files = list(mapping_path.glob("*.yaml")) + list(mapping_path.glob("*.yml"))

    if not yaml_files:
        console.print(f"[yellow]No mapping files found in {mapping_dir}[/yellow]")
        return

    console.print(f"\n[bold]Mapping files in {mapping_dir}:[/bold]\n")

    for f in sorted(yaml_files):
        console.print(f"  • {f.name}")

    console.print()


if __name__ == "__main__":
    app()
