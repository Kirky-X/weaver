# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Migrate existing RELATED_TO edges to semantic types.

Reads all RELATED_TO relationships from Neo4j, normalises the
``relation_type`` property via ``RelationTypeNormalizer``, and creates
new typed edges (e.g. PARTNERS_WITH, INVESTED_IN).  Optionally deletes
the old RELATED_TO edges after migration.

Usage:
    uv run python scripts/migrate_related_to_edges.py [--dry-run] [--delete-old] [--verify]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys

# ---------------------------------------------------------------------------
# Bootstrap import path so that ``config.*`` / ``core.*`` resolve correctly
# when the script is executed directly from the project root.
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config.settings import Settings
from core.db.neo4j import Neo4jPool
from core.db.postgres import PostgresPool
from core.observability.logging import get_logger
from modules.graph_store.relation_type_normalizer import (
    RelationTypeNormalizer,
)

log = get_logger("migrate_related_to")

# Valid Neo4j relationship type pattern (must match entity_repo validation).
_EDGE_TYPE_RE = re.compile(r"^[A-Z_\u4e00-\u9fff][A-Z_\u4e00-\u9fff0-9]*$")

# Fallback edge type when raw_type is empty or unrecognised.
_FALLBACK_EDGE_TYPE = "ASSOCIATED_WITH"

# Relationship types that are *not* entity-to-entity semantic edges and should
# be excluded from counting / verification.
_SYSTEM_REL_TYPES = frozenset({"MENTIONS", "FOLLOWED_BY", "RELATED_TO"})


async def migrate(
    pool: Neo4jPool,
    normalizer: RelationTypeNormalizer,
    *,
    dry_run: bool = False,
    delete_old: bool = False,
) -> int:
    """Migrate RELATED_TO edges to normalised semantic types.

    Args:
        pool: Neo4j connection pool.
        normalizer: Relation-type normaliser.
        dry_run: If *True*, only print what *would* happen.
        delete_old: If *True*, delete old RELATED_TO edges after creating
            new ones.

    Returns:
        Number of edges processed.
    """
    # 1. Query all RELATED_TO edges.
    query = """
    MATCH (from:Entity)-[r:RELATED_TO]->(to:Entity)
    RETURN elementId(from) AS from_id,
           elementId(to)   AS to_id,
           r.relation_type AS raw_type,
           r.description   AS description,
           r.weight        AS weight
    """
    results = await pool.execute_query(query)
    log.info("migrate_query_done", total_edges=len(results))

    migrated = 0
    skipped = 0

    for record in results:
        raw_type = record.get("raw_type") or ""
        from_id = record["from_id"]
        to_id = record["to_id"]

        # 2. Normalise via RelationTypeNormalizer.
        if raw_type:
            normalized = await normalizer.normalize(raw_type)
            edge_type = normalized.name_en if normalized.name_en else raw_type
            direction = "bidirectional" if normalized.is_symmetric else "unidirectional"
        else:
            edge_type = _FALLBACK_EDGE_TYPE
            direction = "unidirectional"

        # Validate edge type so we don't break Neo4j with an invalid name.
        if not _EDGE_TYPE_RE.match(edge_type):
            log.warning("migrate_skip_invalid_type", raw_type=raw_type, edge_type=edge_type)
            skipped += 1
            continue

        if dry_run:
            print(f"  {raw_type or '(none)'} -> {edge_type} [{direction}]")
            migrated += 1
            continue

        # 3. Create the new semantic edge.
        create_query = f"""
        MATCH (from) WHERE elementId(from) = $from_id
        MATCH (to)   WHERE elementId(to)   = $to_id
        MERGE (from)-[r:{edge_type}]->(to)
        ON CREATE SET r.migrated    = true,
                      r.raw_type    = $raw_type,
                      r.direction   = $direction,
                      r.weight      = $weight,
                      r.description = $desc,
                      r.created_at  = datetime(),
                      r.updated_at  = datetime()
        ON MATCH SET  r.updated_at  = datetime(),
                      r.weight      = r.weight + 0.1
        """
        params = {
            "from_id": from_id,
            "to_id": to_id,
            "raw_type": raw_type,
            "direction": direction,
            "weight": record.get("weight") or 1.0,
            "desc": record.get("description"),
        }
        await pool.execute_query(create_query, params)
        migrated += 1

    if skipped:
        log.warning("migrate_skipped", count=skipped)

    # 4. Delete old RELATED_TO edges if requested.
    if delete_old and not dry_run:
        del_query = """
        MATCH ()-[r:RELATED_TO]->()
        DELETE r
        RETURN count(r) AS deleted
        """
        del_result = await pool.execute_query(del_query)
        deleted_count = del_result[0]["deleted"] if del_result else 0
        print(f"Deleted {deleted_count} old RELATED_TO edges")
        log.info("migrate_old_deleted", count=deleted_count)

    return migrated


async def verify(pool: Neo4jPool) -> None:
    """Verify migration data consistency.

    Prints counts of old vs. new edges and highlights any new edges
    missing ``raw_type`` or ``direction`` properties.
    """
    old_result = await pool.execute_query("MATCH ()-[r:RELATED_TO]->() RETURN count(r) AS c")
    old_count = old_result[0]["c"] if old_result else 0

    # Count all semantic (non-system) edges.
    new_result = await pool.execute_query(
        """
        MATCH ()-[r]->()
        WHERE NOT type(r) IN $system_types
        RETURN count(r) AS c
    """,
        {"system_types": list(_SYSTEM_REL_TYPES)},
    )
    new_count = new_result[0]["c"] if new_result else 0

    # Count edges missing required migration properties.
    missing_result = await pool.execute_query(
        """
        MATCH ()-[r]->()
        WHERE NOT type(r) IN $system_types
          AND (r.raw_type IS NULL OR r.direction IS NULL)
        RETURN count(r) AS c
    """,
        {"system_types": list(_SYSTEM_REL_TYPES)},
    )
    missing_count = missing_result[0]["c"] if missing_result else 0

    print(f"Old RELATED_TO edges:    {old_count}")
    print(f"New semantic edges:      {new_count}")
    print(f"Missing raw_type/direction: {missing_count}")

    if old_count > 0 and new_count == 0:
        print("WARNING: Old RELATED_TO edges exist but no new semantic edges found.")
    elif missing_count > 0:
        print("WARNING: Some migrated edges are missing raw_type or direction properties.")


async def main() -> None:
    """Entry point: parse args, initialise connections, run migration."""
    parser = argparse.ArgumentParser(
        description="Migrate RELATED_TO edges to semantic types",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned changes without executing them",
    )
    parser.add_argument(
        "--delete-old",
        action="store_true",
        help="Delete old RELATED_TO edges after successful migration",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify migration data consistency",
    )
    args = parser.parse_args()

    settings = Settings()

    neo4j = Neo4jPool(
        uri=settings.neo4j.uri,
        auth=(settings.neo4j.user, settings.neo4j.password),
    )
    await neo4j.startup()

    pg = PostgresPool(dsn=settings.postgres.dsn)
    await pg.startup()

    normalizer = RelationTypeNormalizer(pg)

    try:
        if args.verify:
            await verify(neo4j)
        else:
            count = await migrate(
                neo4j,
                normalizer,
                dry_run=args.dry_run,
                delete_old=args.delete_old,
            )
            action = "previewed" if args.dry_run else "migrated"
            print(f"Migration complete: {count} edges {action}")
    finally:
        await neo4j.shutdown()
        await pg.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
