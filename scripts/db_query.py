#!/usr/bin/env python3
"""Database query and inspection tool for Weaver.

Subcommands:
  stats    Show table record counts (PostgreSQL + Neo4j + DuckDB + LadybugDB)
  article  Query complete info for an article by ID
  random   Query random articles with entities and relationships
  rows     Query rows from a specified table with pagination and sorting

Usage:
  uv run scripts/db_query.py stats
  uv run scripts/db_query.py stats --db duckdb
  uv run scripts/db_query.py article --id <article-uuid>
  uv run scripts/db_query.py article --id <article-uuid> --db duckdb
  uv run scripts/db_query.py random --limit 3
  uv run scripts/db_query.py random --limit 3 --db ladybug
  uv run scripts/db_query.py rows articles --limit 20 --page 1
  uv run scripts/db_query.py rows Article --db neo4j --columns name,type
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Valid database choices
VALID_DBS = ("postgres", "duckdb", "neo4j", "ladybug")


def _get_settings():
    """Load Settings to obtain database connection info."""
    from config.settings import Settings

    return Settings()


def _pg_dsn(settings) -> str:
    """Build asyncpg-compatible DSN (no +asyncpg scheme)."""
    pg = settings.postgres
    return f"postgresql://{pg.user}:{pg.password}@{pg.host}:{pg.port}/{pg.database}"


def _neo4j_auth(settings):
    """Return (uri, (user, password)) for Neo4j."""
    n4 = settings.neo4j
    return n4.uri, (n4.user, n4.password)


def _validate_dbs(dbs: list[str] | None) -> list[str]:
    """Validate database names and return deduplicated list.

    Args:
        dbs: List of database names to validate, or None.

    Returns:
        Deduplicated list of valid database names.

    Raises:
        ValueError: If any database name is invalid.
    """
    if not dbs:
        return []
    invalid = [db for db in dbs if db not in VALID_DBS]
    if invalid:
        raise ValueError(f"Invalid database(s): {invalid}. Valid options: {', '.join(VALID_DBS)}")
    return list(dict.fromkeys(dbs))  # Preserve order, remove duplicates


def _get_default_dbs_for_stats(settings) -> list[str]:
    """Get default databases for stats command based on enabled status.

    Args:
        settings: Application settings.

    Returns:
        List of enabled database names.
    """
    dbs = []
    if settings.postgres:
        dbs.append("postgres")
    if settings.duckdb.enabled:
        dbs.append("duckdb")
    if settings.neo4j.enabled:
        dbs.append("neo4j")
    if settings.ladybug.enabled:
        dbs.append("ladybug")
    return dbs


# ---------------------------------------------------------------------------
# Database-specific stats functions
# ---------------------------------------------------------------------------


async def _stats_postgres(settings) -> None:
    """Check all tables in PostgreSQL database."""
    dsn = _pg_dsn(settings)

    print("=" * 80)
    print("PostgreSQL 数据库表检查")
    print("=" * 80)

    try:
        import asyncpg

        conn = await asyncpg.connect(dsn)

        tables = await conn.fetch("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
            """)

        print(f"\n找到 {len(tables)} 个表:\n")

        results = []
        for table_row in tables:
            table_name = table_row["table_name"]
            if table_name.startswith("alembic_"):
                continue
            try:
                count = await conn.fetchval(f"SELECT COUNT(*) FROM public.{table_name}")
                results.append({"table": table_name, "count": count, "has_data": count > 0})
            except Exception as exc:
                results.append({"table": table_name, "count": None, "error": str(exc)})

        results.sort(key=lambda x: (x["has_data"], x["table"]))

        print(f"{'表名':<40} {'记录数':>15} {'状态':<10}")
        print("-" * 80)

        empty_tables, non_empty_tables = [], []
        for result in results:
            table_name, count = result["table"], result["count"]
            if count is not None:
                status = "  空表" if count == 0 else "✓ 有数据"
                (empty_tables if count == 0 else non_empty_tables).append(table_name)
                print(f"{table_name:<40} {count:>15,} {status:<10}")
            else:
                print(f"{table_name:<40} {'ERROR':>15} ✗ {result.get('error', '')}")

        print("\n" + "=" * 80)
        print(f"统计摘要:")
        print(f"  总表数：{len(results)}")
        print(f"  有数据的表：{len(non_empty_tables)}")
        print(f"  空表数量：{len(empty_tables)}")
        if empty_tables:
            print(f"\n空表列表 ({len(empty_tables)} 个):")
            for t in empty_tables:
                print(f"  - {t}")

        await conn.close()
    except Exception as exc:
        print(f"PostgreSQL 检查失败：{exc}")


async def _stats_duckdb(settings) -> None:
    """Check all tables in DuckDB database."""
    print("=" * 80)
    print("DuckDB 数据库表检查")
    print("=" * 80)

    if not settings.duckdb.enabled:
        print("\nDuckDB 已禁用 (settings.duckdb.enabled=False)")
        return

    try:
        from core.db.duckdb_pool import DuckDBPool

        pool = DuckDBPool(db_path=settings.duckdb.db_path)
        await pool.startup()

        # DuckDB tables to check
        tables_to_check = [
            "articles",
            "sources",
            "article_vectors",
            "entity_vectors",
            "llm_usage_raw",
            "llm_usage_hourly",
            "llm_failures",
            "pending_sync",
            "source_authorities",
            "relation_types",
            "relation_type_aliases",
            "unknown_relation_types",
        ]

        print(f"\n检查 {len(tables_to_check)} 个表:\n")
        print(f"{'表名':<40} {'记录数':>15} {'状态':<10}")
        print("-" * 80)

        results = []
        async with pool.session_context() as session:
            from sqlalchemy import text

            for table_name in tables_to_check:
                try:
                    result = await session.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                    count = result.scalar() or 0
                    results.append({"table": table_name, "count": count, "has_data": count > 0})
                except Exception as exc:
                    results.append(
                        {"table": table_name, "count": None, "has_data": False, "error": str(exc)}
                    )

        results.sort(key=lambda x: (x.get("has_data", False), x["table"]))

        empty_tables, non_empty_tables = [], []
        for result in results:
            table_name, count = result["table"], result["count"]
            if count is not None:
                status = "  空表" if count == 0 else "✓ 有数据"
                (empty_tables if count == 0 else non_empty_tables).append(table_name)
                print(f"{table_name:<40} {count:>15,} {status:<10}")
            else:
                print(f"{table_name:<40} {'ERROR':>15} ✗ {result.get('error', '')}")

        print("\n" + "=" * 80)
        print(f"统计摘要:")
        print(f"  总表数：{len(results)}")
        print(f"  有数据的表：{len(non_empty_tables)}")
        print(f"  空表数量：{len(empty_tables)}")
        if empty_tables:
            print(f"\n空表列表 ({len(empty_tables)} 个):")
            for t in empty_tables:
                print(f"  - {t}")

        await pool.shutdown()
    except Exception as exc:
        print(f"DuckDB 检查失败：{exc}")


async def _stats_neo4j(settings) -> None:
    """Check all nodes and relationships in Neo4j graph database."""
    neo4j_uri, neo4j_auth = _neo4j_auth(settings)

    print("=" * 80)
    print("Neo4j 图数据库检查")
    print("=" * 80)

    if not settings.neo4j.enabled:
        print("\nNeo4j 已禁用 (settings.neo4j.enabled=False)")
        return

    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(neo4j_uri, auth=neo4j_auth)
        with driver.session() as session:
            labels = [r["label"] for r in session.run("CALL db.labels() YIELD label RETURN label")]
            print(f"\n找到 {len(labels)} 种节点标签:\n")
            print(f"{'标签':<30} {'节点数':>15} {'状态':<10}")
            print("-" * 80)

            empty_labels, non_empty_labels = [], []
            for label in sorted(labels):
                try:
                    cnt = session.run(f"MATCH (n:{label}) RETURN count(n) AS cnt").single()["cnt"]
                    status = "  空" if cnt == 0 else "✓ 有数据"
                    (empty_labels if cnt == 0 else non_empty_labels).append(label)
                    print(f"{label:<30} {cnt:>15,} {status:<10}")
                except Exception as exc:
                    print(f"{label:<30} {'ERROR':>15} ✗ {exc}")
                    empty_labels.append(label)

            rel_types = [
                r["relationshipType"]
                for r in session.run(
                    "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType"
                )
            ]
            print(f"\n\n找到 {len(rel_types)} 种关系类型:\n")
            print(f"{'关系类型':<30} {'数量':>15} {'状态':<10}")
            print("-" * 80)

            empty_rels, non_empty_rels = [], []
            for rel_type in sorted(rel_types):
                try:
                    cnt = session.run(
                        f"MATCH ()-[r:{rel_type}]->() RETURN count(r) AS cnt"
                    ).single()["cnt"]
                    status = "  空" if cnt == 0 else "✓ 有数据"
                    (empty_rels if cnt == 0 else non_empty_rels).append(rel_type)
                    print(f"{rel_type:<30} {cnt:>15,} {status:<10}")
                except Exception as exc:
                    print(f"{rel_type:<30} {'ERROR':>15} ✗ {exc}")
                    empty_rels.append(rel_type)

            print("\n" + "=" * 80)
            print(f"Neo4j 统计摘要:")
            print(f"  节点标签总数：{len(labels)}")
            print(f"  有数据的标签：{len(non_empty_labels)}")
            print(f"  空标签数量：{len(empty_labels)}")
            print(f"  关系类型总数：{len(rel_types)}")
            print(f"  有数据的关系：{len(non_empty_rels)}")
            print(f"  空关系数量：{len(empty_rels)}")

        driver.close()
    except Exception as exc:
        print(f"Neo4j 检查失败：{exc}")


async def _stats_ladybug(settings) -> None:
    """Check all nodes and relationships in LadybugDB graph database."""
    print("=" * 80)
    print("LadybugDB 图数据库检查")
    print("=" * 80)

    if not settings.ladybug.enabled:
        print("\nLadybugDB 已禁用 (settings.ladybug.enabled=False)")
        return

    try:
        from core.db.ladybug_pool import LadybugPool

        pool = LadybugPool(db_path=settings.ladybug.db_path)
        await pool.startup()

        # Query node tables (LadybugDB uses SHOW_TABLES)
        tables_result = await pool.execute_query("CALL show_tables() RETURN *")

        # Filter for node tables (those without source/destination in name)
        node_labels = []
        rel_types = []
        for row in tables_result:
            name = row.get("name", "")
            if name and not name.startswith("_"):
                # Check if it's a relationship table
                row_result = await pool.execute_query(f"CALL table_info('{name}') RETURN *")
                # Node tables have PRIMARY KEY, rel tables have FROM/TO
                is_rel = any(
                    col.get("name", "").lower() in ("from", "to", "_from", "_to")
                    for col in row_result
                )
                if is_rel:
                    rel_types.append(name)
                else:
                    node_labels.append(name)

        print(f"\n找到 {len(node_labels)} 种节点标签:\n")
        print(f"{'标签':<30} {'节点数':>15} {'状态':<10}")
        print("-" * 80)

        empty_labels, non_empty_labels = [], []
        for label in sorted(node_labels):
            try:
                result = await pool.execute_query(f"MATCH (n:{label}) RETURN COUNT(n) AS cnt")
                cnt = result[0]["cnt"] if result else 0
                status = "  空" if cnt == 0 else "✓ 有数据"
                (empty_labels if cnt == 0 else non_empty_labels).append(label)
                print(f"{label:<30} {cnt:>15,} {status:<10}")
            except Exception as exc:
                print(f"{label:<30} {'ERROR':>15} ✗ {exc}")
                empty_labels.append(label)

        print(f"\n\n找到 {len(rel_types)} 种关系类型:\n")
        print(f"{'关系类型':<30} {'数量':>15} {'状态':<10}")
        print("-" * 80)

        empty_rels, non_empty_rels = [], []
        for rel_type in sorted(rel_types):
            try:
                result = await pool.execute_query(
                    f"MATCH ()-[r:{rel_type}]->() RETURN COUNT(r) AS cnt"
                )
                cnt = result[0]["cnt"] if result else 0
                status = "  空" if cnt == 0 else "✓ 有数据"
                (empty_rels if cnt == 0 else non_empty_rels).append(rel_type)
                print(f"{rel_type:<30} {cnt:>15,} {status:<10}")
            except Exception as exc:
                print(f"{rel_type:<30} {'ERROR':>15} ✗ {exc}")
                empty_rels.append(rel_type)

        print("\n" + "=" * 80)
        print(f"LadybugDB 统计摘要:")
        print(f"  节点标签总数：{len(node_labels)}")
        print(f"  有数据的标签：{len(non_empty_labels)}")
        print(f"  空标签数量：{len(empty_labels)}")
        print(f"  关系类型总数：{len(rel_types)}")
        print(f"  有数据的关系：{len(non_empty_rels)}")
        print(f"  空关系数量：{len(empty_rels)}")

        await pool.shutdown()
    except Exception as exc:
        print(f"LadybugDB 检查失败：{exc}")


# ---------------------------------------------------------------------------
# Sub-command: stats
# ---------------------------------------------------------------------------


async def cmd_stats(args: argparse.Namespace) -> None:
    """Check tables in specified databases."""
    settings = _get_settings()

    # Determine which databases to query
    if args.db:
        dbs = args.db
    else:
        dbs = _get_default_dbs_for_stats(settings)

    # Run stats for each database
    for db in dbs:
        if db == "postgres":
            await _stats_postgres(settings)
        elif db == "duckdb":
            await _stats_duckdb(settings)
        elif db == "neo4j":
            await _stats_neo4j(settings)
        elif db == "ladybug":
            await _stats_ladybug(settings)


# ---------------------------------------------------------------------------
# Database-specific article functions
# ---------------------------------------------------------------------------


async def _article_postgres(article_id: str, settings) -> dict:
    """Query article from PostgreSQL database."""
    dsn = _pg_dsn(settings)
    results: dict = {}

    print(f"正在查询 PostgreSQL (article_id={article_id})...")
    try:
        import asyncpg

        conn = await asyncpg.connect(dsn)

        article_row = await conn.fetchrow("SELECT * FROM articles WHERE id = $1", article_id)
        if article_row:
            results["articles"] = dict(article_row)
            print("  找到文章记录")
        else:
            results["articles"] = None
            print("  未找到文章记录")

        related_tables = [
            "article_cleaned",
            "article_features",
            "article_ranking",
            "entity_mentions",
            "article_relationships",
        ]
        results["related_tables"] = {}
        for table in related_tables:
            try:
                exists = await conn.fetchval(
                    "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name = $1)",
                    table,
                )
                if not exists:
                    results["related_tables"][table] = {"exists": False}
                    continue
                rows = await conn.fetch(
                    f"SELECT * FROM public.{table} WHERE article_id = $1 LIMIT 10",
                    article_id,
                )
                results["related_tables"][table] = {
                    "exists": True,
                    "count": len(rows),
                    "data": [dict(r) for r in rows],
                }
                print(f"  {table}: {len(rows)} 条记录" if rows else f"  {table}: 无记录")
            except Exception as exc:
                results["related_tables"][table] = {"exists": True, "error": str(exc)}

        await conn.close()
    except Exception as exc:
        print(f"PostgreSQL 查询失败：{exc}")
        results["error"] = str(exc)

    return results


async def _article_duckdb(article_id: str, settings) -> dict:
    """Query article from DuckDB database."""
    results: dict = {}

    print(f"正在查询 DuckDB (article_id={article_id})...")

    if not settings.duckdb.enabled:
        print("  DuckDB 已禁用")
        return {"error": "DuckDB disabled"}

    try:
        from sqlalchemy import text

        from core.db.duckdb_pool import DuckDBPool

        pool = DuckDBPool(db_path=settings.duckdb.db_path)
        await pool.startup()

        async with pool.session_context() as session:
            # Query article
            result = await session.execute(
                text("SELECT * FROM articles WHERE id = :id"),
                {"id": article_id},
            )
            row = result.fetchone()
            if row:
                # Get column names
                columns = result.keys()
                results["articles"] = dict(zip(columns, row, strict=True))
                print("  找到文章记录")
            else:
                results["articles"] = None
                print("  未找到文章记录")

            # Query article_vectors
            results["related_tables"] = {}
            try:
                vec_result = await session.execute(
                    text("SELECT * FROM article_vectors WHERE article_id = :id"),
                    {"id": article_id},
                )
                vec_rows = vec_result.fetchall()
                if vec_rows:
                    vec_columns = vec_result.keys()
                    results["related_tables"]["article_vectors"] = {
                        "exists": True,
                        "count": len(vec_rows),
                        "data": [dict(zip(vec_columns, r, strict=True)) for r in vec_rows],
                    }
                    print(f"  article_vectors: {len(vec_rows)} 条记录")
                else:
                    results["related_tables"]["article_vectors"] = {"exists": True, "count": 0}
            except Exception as exc:
                results["related_tables"]["article_vectors"] = {"error": str(exc)}

        await pool.shutdown()
    except Exception as exc:
        print(f"DuckDB 查询失败：{exc}")
        results["error"] = str(exc)

    return results


# ---------------------------------------------------------------------------
# Database-specific random functions
# ---------------------------------------------------------------------------


async def _random_neo4j(limit: int, settings) -> list[dict]:
    """Query random articles from Neo4j graph database."""
    neo4j_uri, neo4j_auth = _neo4j_auth(settings)
    results = []

    print(f"正在查询 Neo4j ({limit} 篇文章)...")

    if not settings.neo4j.enabled:
        print("  Neo4j 已禁用")
        return results

    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(neo4j_uri, auth=neo4j_auth)

        with driver.session() as session:
            # Query 1: random articles with MENTIONS
            query = f"""
            MATCH (a:Article)-[m:MENTIONS]->(e:Entity)
            RETURN
                a.pg_id AS article_pg_id, a.title AS article_title,
                a.category AS article_category, a.publish_time AS article_publish_time,
                a.score AS article_score, a.created_at AS article_created_at,
                e.id AS entity_id, e.canonical_name AS entity_canonical_name,
                e.type AS entity_type, e.description AS entity_description,
                e.aliases AS entity_aliases,
                m.role AS mention_role, m.created_at AS mention_created_at
            LIMIT {limit * 10}
            """
            records = list(session.run(query))
            if not records:
                print("未找到任何文章和实体数据")
                driver.close()
                return results

            # Group by article
            article_map: dict[str, dict] = {}
            for rec in records:
                pg_id = rec["article_pg_id"]
                if pg_id not in article_map:
                    article_map[pg_id] = {
                        "article": {
                            "pg_id": pg_id,
                            "title": rec["article_title"],
                            "category": rec["article_category"],
                            "publish_time": (
                                rec["article_publish_time"].iso_format()
                                if rec["article_publish_time"]
                                else None
                            ),
                            "score": rec["article_score"],
                            "created_at": (
                                rec["article_created_at"].iso_format()
                                if rec["article_created_at"]
                                else None
                            ),
                        },
                        "entities": [],
                        "relationships": [],
                    }
                entity_data = {
                    "id": rec["entity_id"],
                    "canonical_name": rec["entity_canonical_name"],
                    "type": rec["entity_type"],
                    "description": rec["entity_description"],
                    "aliases": rec["entity_aliases"] or [],
                }
                if not any(
                    e["canonical_name"] == entity_data["canonical_name"]
                    for e in article_map[pg_id]["entities"]
                ):
                    article_map[pg_id]["entities"].append(entity_data)
                article_map[pg_id]["relationships"].append(
                    {
                        "type": "MENTIONS",
                        "source": {
                            "type": "Article",
                            "pg_id": pg_id,
                            "title": rec["article_title"],
                        },
                        "target": {
                            "type": "Entity",
                            "canonical_name": rec["entity_canonical_name"],
                        },
                        "properties": {"role": rec["mention_role"]},
                    }
                )

            selected = list(article_map.values())[:limit]

            # Query 2 & 3: additional relationships per article
            for article_data in selected:
                pg_id = article_data["article"]["pg_id"]

                followed = []
                for r in session.run(
                    "MATCH (a:Article {pg_id: $pg_id})-[r:FOLLOWED_BY]->(related:Article) "
                    "RETURN related.pg_id AS pg_id, related.title AS title, related.category AS category",
                    {"pg_id": pg_id},
                ):
                    followed.append(
                        {"pg_id": r["pg_id"], "title": r["title"], "category": r["category"]}
                    )
                    article_data["relationships"].append(
                        {
                            "type": "FOLLOWED_BY",
                            "source": {"type": "Article", "pg_id": pg_id},
                            "target": {"type": "Article", "pg_id": r["pg_id"]},
                        }
                    )
                article_data["followed_articles"] = followed

                entity_rels = []
                for r in session.run(
                    "MATCH (e1:Entity)<-[:MENTIONS]-(a:Article {pg_id: $pg_id}), (e1)-[r:RELATED_TO]->(e2:Entity) "
                    "RETURN e1.canonical_name AS src, e2.canonical_name AS tgt, r.relation_type AS rtype LIMIT 20",
                    {"pg_id": pg_id},
                ):
                    entity_rels.append(
                        {
                            "source_entity": r["src"],
                            "target_entity": r["tgt"],
                            "relation_type": r["rtype"],
                        }
                    )
                    article_data["relationships"].append(
                        {
                            "type": "RELATED_TO",
                            "source": {"type": "Entity", "canonical_name": r["src"]},
                            "target": {"type": "Entity", "canonical_name": r["tgt"]},
                            "properties": {"relation_type": r["rtype"]},
                        }
                    )
                article_data["entity_relationships"] = entity_rels

                results.append(article_data)

        driver.close()
    except Exception as exc:
        print(f"Neo4j 查询失败：{exc}")

    return results


async def _random_ladybug(limit: int, settings) -> list[dict]:
    """Query random articles from LadybugDB graph database."""
    results = []

    print(f"正在查询 LadybugDB ({limit} 篇文章)...")

    if not settings.ladybug.enabled:
        print("  LadybugDB 已禁用")
        return results

    try:
        from core.db.ladybug_pool import LadybugPool

        pool = LadybugPool(db_path=settings.ladybug.db_path)
        await pool.startup()

        # Query articles with MENTIONS
        query = f"""
        MATCH (a:Article)-[m:MENTIONS]->(e:Entity)
        RETURN
            a.pg_id AS article_pg_id, a.title AS article_title,
            a.category AS article_category, a.publish_time AS article_publish_time,
            a.score AS article_score,
            e.id AS entity_id, e.canonical_name AS entity_canonical_name,
            e.type AS entity_type, e.description AS entity_description,
            m.role AS mention_role
        LIMIT {limit * 10}
        """
        records = await pool.execute_query(query)

        if not records:
            print("未找到任何文章和实体数据")
            await pool.shutdown()
            return results

        # Group by article
        article_map: dict[str, dict] = {}
        for rec in records:
            pg_id = rec.get("article_pg_id")
            if not pg_id:
                continue
            if pg_id not in article_map:
                article_map[pg_id] = {
                    "article": {
                        "pg_id": pg_id,
                        "title": rec.get("article_title"),
                        "category": rec.get("article_category"),
                        "publish_time": rec.get("article_publish_time"),
                        "score": rec.get("article_score"),
                    },
                    "entities": [],
                    "relationships": [],
                }
            entity_data = {
                "id": rec.get("entity_id"),
                "canonical_name": rec.get("entity_canonical_name"),
                "type": rec.get("entity_type"),
                "description": rec.get("entity_description"),
            }
            if not any(
                e["canonical_name"] == entity_data["canonical_name"]
                for e in article_map[pg_id]["entities"]
            ):
                article_map[pg_id]["entities"].append(entity_data)
            article_map[pg_id]["relationships"].append(
                {
                    "type": "MENTIONS",
                    "source": {
                        "type": "Article",
                        "pg_id": pg_id,
                        "title": rec.get("article_title"),
                    },
                    "target": {
                        "type": "Entity",
                        "canonical_name": rec.get("entity_canonical_name"),
                    },
                    "properties": {"role": rec.get("mention_role")},
                }
            )

        selected = list(article_map.values())[:limit]

        # Query additional relationships per article
        for article_data in selected:
            pg_id = article_data["article"]["pg_id"]

            # FOLLOWED_BY relationships
            followed_query = """
            MATCH (a:Article {pg_id: $pg_id})-[r:FOLLOWED_BY]->(related:Article)
            RETURN related.pg_id AS pg_id, related.title AS title, related.category AS category
            """
            followed_records = await pool.execute_query(followed_query, {"pg_id": pg_id})
            followed = []
            for r in followed_records:
                followed.append(
                    {
                        "pg_id": r.get("pg_id"),
                        "title": r.get("title"),
                        "category": r.get("category"),
                    }
                )
                article_data["relationships"].append(
                    {
                        "type": "FOLLOWED_BY",
                        "source": {"type": "Article", "pg_id": pg_id},
                        "target": {"type": "Article", "pg_id": r.get("pg_id")},
                    }
                )
            article_data["followed_articles"] = followed

            # RELATED_TO relationships between entities
            entity_rels_query = """
            MATCH (e1:Entity)<-[:MENTIONS]-(a:Article {pg_id: $pg_id}), (e1)-[r:RELATED_TO]->(e2:Entity)
            RETURN e1.canonical_name AS src, e2.canonical_name AS tgt, r.edge_type AS rtype
            LIMIT 20
            """
            entity_rels_records = await pool.execute_query(entity_rels_query, {"pg_id": pg_id})
            entity_rels = []
            for r in entity_rels_records:
                entity_rels.append(
                    {
                        "source_entity": r.get("src"),
                        "target_entity": r.get("tgt"),
                        "relation_type": r.get("rtype"),
                    }
                )
                article_data["relationships"].append(
                    {
                        "type": "RELATED_TO",
                        "source": {"type": "Entity", "canonical_name": r.get("src")},
                        "target": {"type": "Entity", "canonical_name": r.get("tgt")},
                        "properties": {"relation_type": r.get("rtype")},
                    }
                )
            article_data["entity_relationships"] = entity_rels

            results.append(article_data)

        await pool.shutdown()
    except Exception as exc:
        print(f"LadybugDB 查询失败：{exc}")

    return results


# ---------------------------------------------------------------------------
# Table name validation
# ---------------------------------------------------------------------------


def _validate_table_name(table: str) -> str:
    """Validate table name to prevent SQL injection.

    Args:
        table: Table name to validate.

    Returns:
        Validated table name.

    Raises:
        ValueError: If table name is invalid.
    """
    if not table:
        raise ValueError("Table name cannot be empty")
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", table):
        raise ValueError(
            f"Invalid table name '{table}'. "
            "Must start with letter or underscore, contain only letters, digits, underscore."
        )
    return table


# ---------------------------------------------------------------------------
# Output formatting utilities
# ---------------------------------------------------------------------------


def _truncate_value(value: str, max_len: int = 50) -> str:
    """Truncate long string for display.

    Args:
        value: String value to truncate.
        max_len: Maximum length before truncation.

    Returns:
        Truncated string with ellipsis if needed.
    """
    if value is None:
        return "NULL"
    s = str(value)
    if len(s) > max_len:
        return s[: max_len - 3] + "..."
    return s


def _format_output_table(
    rows: list[dict],
    columns: list[str] | None = None,
    title: str = "",
) -> None:
    """Format rows as a rich table.

    Args:
        rows: List of row dictionaries.
        columns: Column names to display (default: all from first row).
        title: Table title.
    """
    console = Console()

    if not rows:
        console.print("[yellow]No rows found[/yellow]")
        return

    # Determine columns from first row if not specified
    if columns is None:
        columns = list(rows[0].keys())

    table = Table(title=title, show_header=True, header_style="bold cyan")

    for col in columns:
        table.add_column(col, overflow="fold", max_width=50)

    for row in rows:
        table.add_row(*[_truncate_value(row.get(col)) for col in columns])

    console.print(table)


def _format_output_json(rows: list[dict]) -> None:
    """Format rows as JSON output.

    Args:
        rows: List of row dictionaries.
    """
    print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))


# ---------------------------------------------------------------------------
# Database-specific rows query functions
# ---------------------------------------------------------------------------


async def _rows_postgres(
    table: str,
    columns: list[str] | None,
    limit: int,
    offset: int,
    order_by: list[tuple[str, str]] | None,
    settings,
) -> list[dict]:
    """Query rows from PostgreSQL table."""
    dsn = _pg_dsn(settings)
    rows = []

    try:
        import asyncpg

        conn = await asyncpg.connect(dsn)

        # Build column list
        col_str = ", ".join(columns) if columns else "*"

        # Build ORDER BY clause
        order_clause = ""
        if order_by:
            order_parts = [f"{col} {direction.upper()}" for col, direction in order_by]
            order_clause = f" ORDER BY {', '.join(order_parts)}"

        # Build and execute query
        query = f"SELECT {col_str} FROM public.{table}{order_clause} LIMIT $1 OFFSET $2"
        result = await conn.fetch(query, limit, offset)

        rows = [dict(r) for r in result]
        await conn.close()
    except Exception as exc:
        print(f"PostgreSQL 查询失败：{exc}")

    return rows


async def _rows_duckdb(
    table: str,
    columns: list[str] | None,
    limit: int,
    offset: int,
    order_by: list[tuple[str, str]] | None,
    settings,
) -> list[dict]:
    """Query rows from DuckDB table."""
    rows = []

    if not settings.duckdb.enabled:
        print("DuckDB 已禁用")
        return rows

    try:
        from sqlalchemy import text

        from core.db.duckdb_pool import DuckDBPool

        pool = DuckDBPool(db_path=settings.duckdb.db_path)
        await pool.startup()

        async with pool.session_context() as session:
            # Build column list
            col_str = ", ".join(columns) if columns else "*"

            # Build ORDER BY clause
            order_clause = ""
            if order_by:
                order_parts = [f"{col} {direction.upper()}" for col, direction in order_by]
                order_clause = f" ORDER BY {', '.join(order_parts)}"

            # Build and execute query
            query = text(f"SELECT {col_str} FROM {table}{order_clause} LIMIT :limit OFFSET :offset")
            result = await session.execute(query, {"limit": limit, "offset": offset})

            # Get column names
            col_names = result.keys()
            rows = [dict(zip(col_names, row, strict=True)) for row in result.fetchall()]

        await pool.shutdown()
    except Exception as exc:
        print(f"DuckDB 查询失败：{exc}")

    return rows


async def _rows_neo4j(
    label: str,
    properties: list[str] | None,
    limit: int,
    offset: int,
    order_by: list[tuple[str, str]] | None,
    settings,
) -> list[dict]:
    """Query nodes from Neo4j graph database."""
    neo4j_uri, neo4j_auth = _neo4j_auth(settings)
    rows = []

    if not settings.neo4j.enabled:
        print("Neo4j 已禁用")
        return rows

    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(neo4j_uri, auth=neo4j_auth)

        with driver.session() as session:
            # Build RETURN clause
            if properties:
                return_clause = ", ".join(f"n.{p} AS {p}" for p in properties)
            else:
                return_clause = "n"

            # Build ORDER BY clause
            order_clause = ""
            if order_by:
                order_parts = [f"n.{col} {direction.upper()}" for col, direction in order_by]
                order_clause = f" ORDER BY {', '.join(order_parts)}"

            # Build and execute query
            query = (
                f"MATCH (n:{label}) RETURN {return_clause}{order_clause} SKIP $skip LIMIT $limit"
            )
            result = session.run(query, {"skip": offset, "limit": limit})

            for record in result:
                if properties:
                    rows.append({p: record.get(p) for p in properties})
                else:
                    # Return all properties from node
                    node = record.get("n")
                    if node:
                        rows.append(dict(node))

        driver.close()
    except Exception as exc:
        print(f"Neo4j 查询失败：{exc}")

    return rows


async def _rows_ladybug(
    label: str,
    properties: list[str] | None,
    limit: int,
    offset: int,
    order_by: list[tuple[str, str]] | None,
    settings,
) -> list[dict]:
    """Query nodes from LadybugDB graph database."""
    rows = []

    if not settings.ladybug.enabled:
        print("LadybugDB 已禁用")
        return rows

    try:
        from core.db.ladybug_pool import LadybugPool

        pool = LadybugPool(db_path=settings.ladybug.db_path)
        await pool.startup()

        # Build RETURN clause
        if properties:
            return_clause = ", ".join(f"n.{p} AS {p}" for p in properties)
        else:
            return_clause = "n"

        # Build ORDER BY clause
        order_clause = ""
        if order_by:
            order_parts = [f"n.{col} {direction.upper()}" for col, direction in order_by]
            order_clause = f" ORDER BY {', '.join(order_parts)}"

        # Build and execute query
        query = f"MATCH (n:{label}) RETURN {return_clause}{order_clause} SKIP $skip LIMIT $limit"
        result = await pool.execute_query(query, {"skip": offset, "limit": limit})

        for record in result:
            if properties:
                rows.append({p: record.get(p) for p in properties})
            else:
                # Return all properties from node
                node_data = record.get("n")
                if node_data:
                    rows.append(node_data if isinstance(node_data, dict) else {"value": node_data})

        await pool.shutdown()
    except Exception as exc:
        print(f"LadybugDB 查询失败：{exc}")

    return rows


# ---------------------------------------------------------------------------
# Sub-command: rows
# ---------------------------------------------------------------------------


async def cmd_rows(args: argparse.Namespace) -> None:
    """Query rows from a specified table with pagination and sorting."""
    table = args.table
    db = args.db
    columns_str = args.columns
    limit = args.limit
    page = args.page
    order_by_args = args.order_by
    output_format = args.format

    # Validate table name
    try:
        _validate_table_name(table)
    except ValueError as e:
        print(f"错误：{e}")
        return

    # Parse columns
    columns = columns_str.split(",") if columns_str else None

    # Parse order_by
    order_by = None
    if order_by_args:
        order_by = []
        for item in order_by_args:
            if ":" in item:
                col, direction = item.split(":", 1)
                direction = direction.lower()
                if direction not in ("asc", "desc"):
                    print(f"警告：无效的排序方向 '{direction}'，使用 'asc'")
                    direction = "asc"
            else:
                col = item
                direction = "asc"
            order_by.append((col.strip(), direction))

    # Calculate offset
    offset = (page - 1) * limit

    # Get settings
    settings = _get_settings()

    # Query based on database type
    if db == "postgres":
        rows = await _rows_postgres(table, columns, limit, offset, order_by, settings)
    elif db == "duckdb":
        rows = await _rows_duckdb(table, columns, limit, offset, order_by, settings)
    elif db == "neo4j":
        rows = await _rows_neo4j(table, columns, limit, offset, order_by, settings)
    elif db == "ladybug":
        rows = await _rows_ladybug(table, columns, limit, offset, order_by, settings)
    else:
        print(f"不支持的数据库：{db}")
        return

    # Output results
    if output_format == "json":
        _format_output_json(rows)
    else:
        title = f"{db.upper()}: {table} (page {page}, {len(rows)} rows)"
        _format_output_table(rows, columns, title)


async def cmd_article(args: argparse.Namespace) -> None:
    """Query complete info for a specific article by ID."""
    article_id = args.id
    db = args.db or "postgres"
    settings = _get_settings()
    results: dict = {}

    if db == "postgres":
        results["postgresql"] = await _article_postgres(article_id, settings)
    elif db == "duckdb":
        results["duckdb"] = await _article_duckdb(article_id, settings)

    # --- Neo4j (always query for graph context) ---
    if db == "postgres":
        neo4j_uri, neo4j_auth = _neo4j_auth(settings)
        print("\n正在查询 Neo4j...")
        try:
            from neo4j import GraphDatabase

            driver = GraphDatabase.driver(neo4j_uri, auth=neo4j_auth)
            with driver.session() as session:
                params = {"pg_id": article_id}

                record = session.run("MATCH (a:Article {pg_id: $pg_id}) RETURN a", params).single()
                results["neo4j"] = {"article": dict(record["a"]) if record else None}
                print("  找到 Article 节点" if record else "  未找到 Article 节点")

                mentions = []
                for r in session.run(
                    "MATCH (a:Article {pg_id: $pg_id})-[m:MENTIONS]->(e:Entity) RETURN a, m, e",
                    params,
                ):
                    mentions.append(
                        {
                            "article": dict(r["a"]),
                            "relationship": dict(r["m"]) if r["m"] else None,
                            "entity": dict(r["e"]),
                        }
                    )
                results["neo4j"]["mentions"] = mentions
                print(f"  MENTIONS 关系：{len(mentions)} 条")

            driver.close()
        except Exception as exc:
            print(f"Neo4j 查询失败：{exc}")
            results["neo4j_error"] = str(exc)

    # --- Save output ---
    output_file = Path(__file__).parent / "temp" / f"article_{article_id}_{db}.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"\n数据已保存到：{output_file}")

    # --- Summary ---
    print("\n" + "=" * 80)
    print("数据摘要:")
    db_key = "duckdb" if db == "duckdb" else "postgresql"
    if results.get(db_key, {}).get("articles"):
        a = results[db_key]["articles"]
        print(f"\n{db.upper()} articles 表:")
        print(f"   ID: {a.get('id')}")
        print(f"   标题：{str(a.get('title', 'N/A'))[:60]}...")
        print(f"   分类：{a.get('category')}")
        if db == "postgres":
            print(f"   persist_status: {a.get('persist_status')}")

    if results.get("neo4j", {}).get("article"):
        a = results["neo4j"]["article"]
        print(f"\nNeo4j Article 节点:")
        print(f"   pg_id: {a.get('pg_id')}")
        print(f"   title: {str(a.get('title', 'N/A'))[:60]}...")

    if mentions := results.get("neo4j", {}).get("mentions", []):
        print(f"\nMENTIONS 关系 ({len(mentions)} 条):")
        for i, m in enumerate(mentions[:10], 1):
            print(f"   {i}. {m['entity'].get('canonical_name')}")
        if len(mentions) > 10:
            print(f"   ... 还有 {len(mentions) - 10} 个")


# ---------------------------------------------------------------------------
# Sub-command: random
# ---------------------------------------------------------------------------


async def cmd_random(args: argparse.Namespace) -> None:
    """Query random articles with entities and relationships."""
    limit = args.limit
    db = args.db or "neo4j"
    settings = _get_settings()

    if db == "neo4j":
        results = await _random_neo4j(limit, settings)
    elif db == "ladybug":
        results = await _random_ladybug(limit, settings)
    else:
        print(f"random 子命令不支持数据库：{db}")
        return

    if not results:
        return

    # Save output
    output_file = Path(__file__).parent / "temp" / f"query_articles_{db}.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    print(f"\n成功查询到 {len(results)} 篇文章")
    print(f"数据已保存到：{output_file}\n")
    for i, ad in enumerate(results, 1):
        a = ad["article"]
        print(f"文章 {i}: {a['title']}")
        print(
            f"  分类：{a.get('category')}  评分：{a.get('score')}  实体：{len(ad['entities'])}  关系：{len(ad['relationships'])}"
        )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Weaver database query and inspection tool")
    sub = parser.add_subparsers(dest="command", required=True)

    # stats subcommand
    p_stats = sub.add_parser("stats", help="Show table record counts for databases")
    p_stats.add_argument(
        "--db",
        action="append",
        choices=VALID_DBS,
        help="Database(s) to query (default: all enabled). Can be specified multiple times.",
    )

    # article subcommand
    p_article = sub.add_parser("article", help="Query complete info for an article by ID")
    p_article.add_argument("--id", required=True, help="Article UUID")
    p_article.add_argument(
        "--db",
        choices=["postgres", "duckdb"],
        default="postgres",
        help="Database to query (default: postgres)",
    )

    # random subcommand
    p_random = sub.add_parser("random", help="Query random articles with entities")
    p_random.add_argument("--limit", type=int, default=2, help="Number of articles (default: 2)")
    p_random.add_argument(
        "--db",
        choices=["neo4j", "ladybug"],
        default="neo4j",
        help="Database to query (default: neo4j)",
    )

    # rows subcommand
    p_rows = sub.add_parser("rows", help="Query rows from a table with pagination")
    p_rows.add_argument("table", help="Table name (or node label for graph DBs)")
    p_rows.add_argument(
        "--db",
        choices=VALID_DBS,
        default="postgres",
        help="Database to query (default: postgres)",
    )
    p_rows.add_argument(
        "--columns",
        help="Columns to return (comma-separated, default: all)",
    )
    p_rows.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Rows per page (default: 20)",
    )
    p_rows.add_argument(
        "--page",
        type=int,
        default=1,
        help="Page number (default: 1)",
    )
    p_rows.add_argument(
        "--order-by",
        action="append",
        help="Order by column[:asc|desc] (can specify multiple times)",
    )
    p_rows.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format (default: table)",
    )

    args = parser.parse_args()

    # Validate db arguments for stats
    if args.command == "stats" and args.db:
        try:
            args.db = _validate_dbs(args.db)
        except ValueError as e:
            parser.error(str(e))

    dispatch = {"stats": cmd_stats, "article": cmd_article, "random": cmd_random, "rows": cmd_rows}
    asyncio.run(dispatch[args.command](args))


if __name__ == "__main__":
    main()
