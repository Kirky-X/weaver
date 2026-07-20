#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Weaver Article graph node deduplication migration script.

Cleans up residual business fields (title, category, publish_time, score)
from Article nodes in both Neo4j and LadybugDB backends, after the
T025-T030 Article node slim-down (design.md §D2).

Migration flow:
    1. Backup: Query all Article nodes with legacy fields, write to JSON (atomic)
    2. Cleanup: Drop legacy columns (LadybugDB) or REMOVE legacy properties (Neo4j)
    3. Impact: Print backup count and modified node count
    4. Confirm: Prompt user to proceed (unless --yes)
    5. Migrate: Execute cleanup on the active graph backend

Usage:
    uv run python scripts/dedup_article_graph.py migrate --yes
    uv run python scripts/dedup_article_graph.py migrate --dry-run
    uv run python scripts/dedup_article_graph.py migrate --yes --backup-path /tmp/backup.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Legacy fields to clean up (per T025-T030 Article node slim-down)
LEGACY_FIELDS: list[str] = ["title", "category", "publish_time", "score"]

# Default backup file path
DEFAULT_BACKUP_PATH = "data/article_fields_backup.json"


# ── Backup ───────────────────────────────────────────────────────────


async def backup_article_fields(pool: Any, backup_path: str) -> list[dict[str, Any]]:
    """Backup all Article nodes with legacy fields to JSON file (atomic write).

    Args:
        pool: GraphPool Protocol implementation (Neo4j or LadybugDB).
        backup_path: Path to write the JSON backup file.

    Returns:
        List of Article node dicts with legacy fields.
    """
    return_clause = ", ".join(f"a.{field} AS {field}" for field in ["id", "pg_id", *LEGACY_FIELDS])
    query = f"MATCH (a:Article) RETURN {return_clause}"

    articles = await pool.execute_query(query)

    # Atomic write: temp file + os.replace
    backup_dir = Path(backup_path).parent
    backup_dir.mkdir(parents=True, exist_ok=True)

    tmp_path = backup_path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(
            {
                "articles": articles,
                "backup_time": datetime.now(UTC).isoformat(),
            },
            f,
            indent=2,
        )

    os.replace(tmp_path, backup_path)

    return articles


# ── Cleanup functions ────────────────────────────────────────────────


async def cleanup_ladybug(pool: Any) -> int:
    """Clean up legacy fields from LadybugDB Article table (idempotent).

    Each DROP COLUMN is wrapped in try/except to be idempotent — silently
    ignored if the column doesn't exist.

    Returns:
        Count of successfully dropped columns.
    """
    success_count = 0
    for field in LEGACY_FIELDS:
        try:
            await pool.execute_query(f"ALTER TABLE Article DROP COLUMN {field}")
            success_count += 1
        except Exception:
            pass  # Column doesn't exist — idempotent
    return success_count


async def cleanup_neo4j(pool: Any) -> int:
    """Clean up legacy properties from Neo4j Article nodes.

    First executes a count query to determine how many nodes will be
    modified, then executes the REMOVE query to delete legacy properties.

    Returns:
        Count of nodes that had legacy properties removed.
    """
    count_query = (
        "MATCH (a:Article) WHERE "
        + " OR ".join(f"a.{field} IS NOT NULL" for field in LEGACY_FIELDS)
        + " RETURN count(a) AS modified_count"
    )
    count_result = await pool.execute_query(count_query)
    modified_count = count_result[0].get("modified_count", 0) if count_result else 0

    remove_query = "MATCH (a:Article) REMOVE a.title, a.category, a.publish_time, a.score"
    await pool.execute_query(remove_query)

    return modified_count


# ── User confirmation ────────────────────────────────────────────────


def confirm_proceed(impact: dict[str, Any], *, yes: bool = False) -> bool:
    """Display impact and prompt user for confirmation.

    Args:
        impact: Dict with backup_count and pool_type keys.
        yes: If True, skip confirmation and return True immediately.

    Returns:
        True if user confirms (or yes=True), False otherwise.
    """
    if yes:
        return True

    print(f"\n[Impact] Backup count: {impact['backup_count']}")
    print(f"[Impact] Pool type: {impact['pool_type']}")
    response = input("Proceed with cleanup? [y/N]: ")
    return response.lower() in ("y", "yes")


# ── Main migration function ──────────────────────────────────────────


async def migrate(
    *,
    pool: Any,
    pool_type: str,
    backup_path: str,
    yes: bool,
    dry_run: bool,
) -> dict[str, Any]:
    """Execute the Article graph node deduplication migration.

    Args:
        pool: GraphPool Protocol implementation (Neo4j or LadybugDB).
        pool_type: "neo4j" or "ladybug".
        backup_path: Path to write the JSON backup file.
        yes: If True, skip confirmation prompt.
        dry_run: If True, only perform backup (no cleanup queries).

    Returns:
        Dict with migration result info (backup_count, pool_type,
        dry_run, cancelled, modified_count).
    """
    # Step 1: Backup (read-only, always performed)
    articles = await backup_article_fields(pool, backup_path)
    backup_count = len(articles)

    impact: dict[str, Any] = {
        "backup_count": backup_count,
        "pool_type": pool_type,
        "dry_run": dry_run,
        "cancelled": False,
        "modified_count": 0,
    }

    # Step 2: If dry-run, stop here (no modification queries)
    if dry_run:
        print(f"[DRY-RUN] Backed up {backup_count} articles to {backup_path}")
        print("[DRY-RUN] No cleanup queries executed.")
        return impact

    # Step 3: User confirmation
    if not confirm_proceed(impact, yes=yes):
        impact["cancelled"] = True
        print("[CANCELLED] Migration cancelled by user.")
        return impact

    # Step 4: Execute cleanup based on backend type
    if pool_type == "ladybug":
        modified = await cleanup_ladybug(pool)
    elif pool_type == "neo4j":
        modified = await cleanup_neo4j(pool)
    else:
        raise ValueError(f"Unsupported pool_type: {pool_type}")

    impact["modified_count"] = modified
    print(f"[OK] Migration completed: {modified} nodes modified.")
    return impact


# ── CLI entry point ──────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="dedup_article_graph",
        description="Weaver Article graph node deduplication migration script. "
        "Cleans up residual legacy fields (title, category, publish_time, score) "
        "from Article nodes after T025-T030 slim-down.",
    )
    sub = parser.add_subparsers(dest="command")

    # migrate subcommand (default)
    p_migrate = sub.add_parser("migrate", help="Execute the deduplication migration")
    p_migrate.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip confirmation prompt",
    )
    p_migrate.add_argument(
        "--dry-run",
        action="store_true",
        help="Only perform backup; do not execute cleanup queries",
    )
    p_migrate.add_argument(
        "--backup-path",
        default=DEFAULT_BACKUP_PATH,
        help=f"Path to write the JSON backup file (default: {DEFAULT_BACKUP_PATH})",
    )

    return parser


async def _async_main(args: argparse.Namespace) -> int:
    """Async main entry point.

    Initializes the container (simplified — only init_strategy, no LLM/pipeline)
    to get the active graph backend, then executes the migration.
    """
    # Add src/ to path for importing container modules
    src_path = str(Path(__file__).resolve().parent.parent / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

    from config.settings import Settings
    from container import Container, set_container, set_settings

    settings = Settings()
    container = Container().configure(settings)
    set_container(container)
    set_settings(settings)

    # Only init_strategy (graph pool is part of strategy, no LLM/pipeline needed)
    await container.init_strategy()

    graph_pool = container.graph_pool()
    pool_type = container.graph_pool_type

    if graph_pool is None or pool_type is None:
        print("[ERROR] No graph database available (graph_pool is None).", file=sys.stderr)
        return 1

    try:
        result = await migrate(
            pool=graph_pool,
            pool_type=pool_type,
            backup_path=args.backup_path,
            yes=args.yes,
            dry_run=args.dry_run,
        )

        if result["cancelled"]:
            return 1
        return 0
    finally:
        await graph_pool.shutdown()


def main() -> None:
    """CLI entry point.

    If no subcommand is provided, defaults to 'migrate'.
    """
    argv = sys.argv[1:]
    # Default subcommand: if no subcommand or first arg starts with '-', prepend 'migrate'
    if not argv or argv[0].startswith("-"):
        argv = ["migrate", *argv]

    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "migrate":
        exit_code = asyncio.run(_async_main(args))
        sys.exit(exit_code)
    else:
        parser.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
