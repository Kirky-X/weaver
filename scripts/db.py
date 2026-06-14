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
from typing import Any

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

        # nosemgrep: python.sqlalchemy.security.audit sqlalchemy-execute-raw-query
        # Table names from information_schema - internal metadata, not user input
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
                # nosemgrep: python.sqlalchemy.security.audit sqlalchemy-execute-raw-query
                # Table name validated by _validate_table_name() - identifier pattern only
                count = await conn.fetchval(f"SELECT COUNT(*) FROM public.{table_name}")
                results.append({"table": table_name, "count": count, "has_data": count > 0})
            except Exception as exc:
                results.append({"table": table_name, "count": None, "error": str(exc)})

        _print_relational_stats_summary(results, "PostgreSQL")

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
            "source_configs",
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

        _print_relational_stats_summary(results, "DuckDB")

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

            label_items = []
            for label in sorted(labels):
                try:
                    cnt = session.run(f"MATCH (n:{label}) RETURN count(n) AS cnt").single()["cnt"]
                    label_items.append((label, cnt, None))
                except Exception as exc:
                    label_items.append((label, None, str(exc)))

            empty_labels, non_empty_labels = _print_graph_items_summary(label_items, "标签")

            rel_types = [
                r["relationshipType"]
                for r in session.run(
                    "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType"
                )
            ]
            print(f"\n\n找到 {len(rel_types)} 种关系类型:\n")

            rel_items = []
            for rel_type in sorted(rel_types):
                try:
                    cnt = session.run(
                        f"MATCH ()-[r:{rel_type}]->() RETURN count(r) AS cnt"
                    ).single()["cnt"]
                    rel_items.append((rel_type, cnt, None))
                except Exception as exc:
                    rel_items.append((rel_type, None, str(exc)))

            empty_rels, non_empty_rels = _print_graph_items_summary(rel_items, "关系类型")

            _print_graph_stats_summary(
                "Neo4j", empty_labels, non_empty_labels, empty_rels, non_empty_rels
            )

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
                # LadybugDB: Node tables have 'id' column, rel tables have 'edge_type' or '_SRC/_DST'
                # Check for relationship indicators
                col_names = [col.get("name", "").lower() for col in row_result]
                is_rel = any(
                    c in col_names for c in ("edge_type", "properties")
                ) or name.upper() in (
                    "RELATED_TO",
                    "MENTIONS",
                    "FOLLOWED_BY",
                    "EVENT_FOLLOWED_BY",
                    "HAS_ENTITY",
                    "CAUSES",
                    "ENABLES",
                    "PREVENTS",
                    "REPORTS_ON",
                )
                if is_rel:
                    rel_types.append(name)
                else:
                    node_labels.append(name)

        print(f"\n找到 {len(node_labels)} 种节点标签:\n")

        label_items = []
        for label in sorted(node_labels):
            try:
                result = await pool.execute_query(f"MATCH (n:{label}) RETURN COUNT(n) AS cnt")
                cnt = result[0]["cnt"] if result else 0
                label_items.append((label, cnt, None))
            except Exception as exc:
                label_items.append((label, None, str(exc)))

        empty_labels, non_empty_labels = _print_graph_items_summary(label_items, "标签")

        print(f"\n\n找到 {len(rel_types)} 种关系类型:\n")

        rel_items = []
        for rel_type in sorted(rel_types):
            try:
                result = await pool.execute_query(
                    f"MATCH ()-[r:{rel_type}]->() RETURN COUNT(r) AS cnt"
                )
                cnt = result[0]["cnt"] if result else 0
                rel_items.append((rel_type, cnt, None))
            except Exception as exc:
                rel_items.append((rel_type, None, str(exc)))

        empty_rels, non_empty_rels = _print_graph_items_summary(rel_items, "关系类型")

        _print_graph_stats_summary(
            "LadybugDB", empty_labels, non_empty_labels, empty_rels, non_empty_rels
        )

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


def _print_relational_stats_summary(results: list[dict], db_name: str) -> None:
    """打印关系型数据库统计摘要。

    Args:
        results: 查询结果列表，每项包含 table, count, has_data, 可选 error
        db_name: 数据库名称
    """
    results.sort(key=lambda x: (x.get("has_data", False), x["table"]))

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


def _print_graph_items_summary(
    items: list[tuple[Any, int | None, str | None]],
    item_type: str,
) -> tuple[list[str], list[str]]:
    """打印图数据库节点/关系统计表。

    Args:
        items: 已排序的 (名称, 计数, 错误信息) 列表，计数为 None 表示查询出错
        item_type: "标签" 或 "关系类型"

    Returns:
        (empty_list, non_empty_list) 元组
    """
    col_name = "标签" if item_type == "标签" else "关系类型"
    count_name = "节点数" if item_type == "标签" else "数量"

    print(f"{col_name:<30} {count_name:>15} {'状态':<10}")
    print("-" * 80)

    empty_items, non_empty_items = [], []
    for name, cnt, err in items:
        if cnt is not None:
            status = "  空" if cnt == 0 else "✓ 有数据"
            (empty_items if cnt == 0 else non_empty_items).append(name)
            print(f"{name:<30} {cnt:>15,} {status:<10}")
        else:
            print(f"{name:<30} {'ERROR':>15} ✗ {err}")
            empty_items.append(name)

    return empty_items, non_empty_items


def _print_graph_stats_summary(
    db_name: str,
    labels_empty: list[str],
    labels_non_empty: list[str],
    rels_empty: list[str],
    rels_non_empty: list[str],
) -> None:
    """打印图数据库统计摘要。

    Args:
        db_name: 数据库名称
        labels_empty: 空标签列表
        labels_non_empty: 有数据的标签列表
        rels_empty: 空关系类型列表
        rels_non_empty: 有数据的关系类型列表
    """
    print("\n" + "=" * 80)
    print(f"{db_name} 统计摘要:")
    print(f"  节点标签总数：{len(labels_empty) + len(labels_non_empty)}")
    print(f"  有数据的标签：{len(labels_non_empty)}")
    print(f"  空标签数量：{len(labels_empty)}")
    print(f"  关系类型总数：{len(rels_empty) + len(rels_non_empty)}")
    print(f"  有数据的关系：{len(rels_non_empty)}")
    print(f"  空关系数量：{len(rels_empty)}")


def _print_null_fields_report(null_info: list[dict], table_name: str, count: int) -> None:
    """打印单表空字段报告。

    Args:
        null_info: 空字段信息列表，每项包含 column, null_count, total, null_pct, data_type
        table_name: 表名
        count: 表行数
    """
    print(f"\n表 {table_name} ({count} 行)：")
    print(f"  {'列名':<30} {'空值数':>10} {'总数':>10} {'空值率':>10} {'类型':<20}")
    print(f"  {'-' * 80}")
    for info in sorted(null_info, key=lambda x: x["null_pct"], reverse=True):
        print(
            f"  {info['column']:<30} {info['null_count']:>10,} {info['total']:>10,}"
            f" {info['null_pct']:>9.1f}% {info['data_type']:<20}"
        )


def _print_null_fields_summary(total_issues: int) -> None:
    """打印空字段检查摘要。

    Args:
        total_issues: 存在空字段问题的表数量
    """
    if total_issues == 0:
        print("\n所有表均无空字段问题")
    else:
        print(f"\n{'=' * 80}")
        print(f"共 {total_issues} 个表存在空字段")


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
        # nosemgrep: python.sqlalchemy.security.audit sqlalchemy-execute-raw-query
        # CLI tool: col_str from explicit columns, order_clause from validated order_by
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
# null-fields: Check empty/null fields in tables
# ---------------------------------------------------------------------------


async def _null_fields_postgres(settings, table: str | None, threshold: float) -> None:
    """Check NULL/empty fields in PostgreSQL tables."""
    dsn = _pg_dsn(settings)

    print("=" * 80)
    print("PostgreSQL 空字段检查")
    print("=" * 80)

    import asyncpg

    conn = await asyncpg.connect(dsn)
    try:
        if table:
            tables_to_check = [_validate_table_name(table)]
        else:
            rows = await conn.fetch("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """)
            tables_to_check = [
                r["table_name"] for r in rows if not r["table_name"].startswith("alembic_")
            ]

        total_issues = 0
        for tbl in tables_to_check:
            col_rows = await conn.fetch(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = $1
                ORDER BY ordinal_position
                """,
                tbl,
            )
            if not col_rows:
                continue

            count = await conn.fetchval(f"SELECT COUNT(*) FROM public.{tbl}")
            if count == 0:
                print(f"\n表 {tbl}：空表，跳过")
                continue

            null_info = []
            for col in col_rows:
                col_name = col["column_name"]
                # nosemgrep: python.sqlalchemy.security.audit sqlalchemy-execute-raw-query
                # Column/table names validated by _validate_table_name
                null_count = await conn.fetchval(
                    f'SELECT COUNT(*) FROM public.{tbl} WHERE "{col_name}" IS NULL'
                )
                if null_count == 0:
                    continue
                null_pct = null_count / count * 100
                if null_pct >= threshold:
                    null_info.append(
                        {
                            "column": col_name,
                            "null_count": null_count,
                            "total": count,
                            "null_pct": null_pct,
                            "data_type": col["data_type"],
                        }
                    )

            if null_info:
                total_issues += 1
                _print_null_fields_report(null_info, tbl, count)

        _print_null_fields_summary(total_issues)
    finally:
        await conn.close()


async def _null_fields_duckdb(settings, table: str | None, threshold: float) -> None:
    """Check NULL/empty fields in DuckDB tables."""
    db_path = Path(settings.database.duckdb_path)
    if not db_path.exists():
        print(f"DuckDB 文件不存在：{db_path}")
        return

    print("=" * 80)
    print("DuckDB 空字段检查")
    print("=" * 80)

    import duckdb

    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        if table:
            tables_to_check = [_validate_table_name(table)]
        else:
            rows = conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' ORDER BY table_name"
            ).fetchall()
            tables_to_check = [r[0] for r in rows]

        total_issues = 0
        for tbl in tables_to_check:
            col_rows = conn.execute(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'main' AND table_name = ?
                ORDER BY ordinal_position
                """,
                [tbl],
            ).fetchall()
            if not col_rows:
                continue

            count = conn.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()[0]
            if count == 0:
                print(f"\n表 {tbl}：空表，跳过")
                continue

            null_info = []
            for col_name, data_type in col_rows:
                # nosemgrep: python.sqlalchemy.security.audit sqlalchemy-execute-raw-query
                # Column/table names validated by _validate_table_name
                null_count = conn.execute(
                    f'SELECT COUNT(*) FROM "{tbl}" WHERE "{col_name}" IS NULL'
                ).fetchone()[0]
                if null_count == 0:
                    continue
                null_pct = null_count / count * 100
                if null_pct >= threshold:
                    null_info.append(
                        {
                            "column": col_name,
                            "null_count": null_count,
                            "total": count,
                            "null_pct": null_pct,
                            "data_type": data_type,
                        }
                    )

            if null_info:
                total_issues += 1
                _print_null_fields_report(null_info, tbl, count)

        _print_null_fields_summary(total_issues)
    finally:
        conn.close()


async def cmd_null_fields(args: argparse.Namespace) -> None:
    """Check NULL/empty fields in database tables."""
    settings = _get_settings()
    db = args.db or "postgres"
    table = args.table
    threshold = args.threshold

    if db == "postgres":
        await _null_fields_postgres(settings, table, threshold)
    elif db == "duckdb":
        await _null_fields_duckdb(settings, table, threshold)
    else:
        print(f"null-fields 子命令不支持数据库：{db}（仅支持 postgres/duckdb）")


# ---------------------------------------------------------------------------
# Data Quality Check (from _dq_check.py)
# ---------------------------------------------------------------------------

ALLOWED_ENTITY_TYPES = {"人物", "组织机构", "地点", "事件", "数据指标", "法规与政策", "未知"}

KNOWN_NODE_TABLES = [
    "Entity",
    "Article",
    "Community",
    "CommunityReport",
    "EventNode",
    "NarrativeNode",
    "SchemaNode",
]
KNOWN_REL_TABLES = [
    "MENTIONS",
    "FOLLOWED_BY",
    "EVENT_FOLLOWED_BY",
    "CAUSES",
    "ENABLES",
    "PREVENTS",
    "RELATED_TO",
    "HAS_ENTITY",
    "REPORTS_ON",
    "HAS_PARTICIPANT",
    "HAS_SUB_EVENT",
    "HAS_NARRATIVE",
    "HAS_EVENT",
]


async def cmd_dq_check(args: argparse.Namespace) -> None:
    """Run LadybugDB data quality checks."""
    from core.db.ladybug_pool import LadybugPool

    db_path = args.db_path
    pool = LadybugPool(db_path=db_path)
    try:
        await pool.startup()
    except RuntimeError as exc:
        if "lock" in str(exc).lower():
            print(f"⚠ 主数据库被锁定: {exc}")
            return
        raise

    issues: list[str] = []

    try:
        # ── 1. 节点统计 ──
        print("\n── 1. 节点统计 ──")
        node_counts: dict[str, int] = {}
        existing_tables: list[str] = []
        for table in KNOWN_NODE_TABLES:
            try:
                rows = await pool.execute_query(f"MATCH (n:{table}) RETURN count(n) AS cnt")
                cnt = rows[0]["cnt"] if rows else 0
                node_counts[table] = cnt
                existing_tables.append(table)
                print(f"  {table}: {cnt}")
            except Exception as exc:
                node_counts[table] = -1
                print(f"  {table}: 不存在或查询失败 ({str(exc).split('.')[0]})")

        total_nodes = sum(v for v in node_counts.values() if v >= 0)
        print(f"  ── 总计: {total_nodes}")

        # ── 2. EventNode 验证 ──
        print("\n── 2. EventNode 验证 ──")
        event_count = node_counts.get("EventNode", 0)
        print(f"  EventNode 总数: {event_count}")

        if event_count > 0:
            required_attrs = ["content", "event_type", "name", "event_time"]
            for attr in required_attrs:
                try:
                    if attr == "event_time":
                        rows = await pool.execute_query(
                            "MATCH (e:EventNode) WHERE e.event_time IS NULL RETURN count(e) AS cnt"
                        )
                        null_cnt = rows[0]["cnt"] if rows else 0
                        rows_zero = await pool.execute_query(
                            "MATCH (e:EventNode) WHERE e.event_time = 0 RETURN count(e) AS cnt"
                        )
                        zero_cnt = rows_zero[0]["cnt"] if rows_zero else 0
                        pct = ((null_cnt + zero_cnt) / event_count * 100) if event_count else 0
                        status = "✓" if null_cnt == 0 and zero_cnt == 0 else "✗"
                        print(
                            f"  {status} {attr}: {null_cnt} NULL + {zero_cnt} 为0/{event_count} ({pct:.1f}%)"
                        )
                        if null_cnt > 0 or zero_cnt > 0:
                            issues.append(f"EventNode.{attr} 有 {null_cnt} NULL + {zero_cnt} 为0")
                    else:
                        rows = await pool.execute_query(
                            f"MATCH (e:EventNode) WHERE e.{attr} IS NULL OR e.{attr} = '' RETURN count(e) AS cnt"
                        )
                        null_cnt = rows[0]["cnt"] if rows else 0
                        pct = (null_cnt / event_count * 100) if event_count else 0
                        status = "✓" if null_cnt == 0 else "✗"
                        print(f"  {status} {attr}: {null_cnt}/{event_count} 缺失 ({pct:.1f}%)")
                        if null_cnt > 0:
                            issues.append(f"EventNode.{attr} 有 {null_cnt}/{event_count} 条缺失")
                except Exception as exc:
                    print(f"  ? {attr}: 查询失败 ({str(exc).split('.')[0]})")

            # Article → EventNode relationships
            print("\n  ── Article → EventNode 关系检查 ──")
            try:
                has_event_rows = await pool.execute_query(
                    "MATCH (a:Article)-[r:HAS_EVENT]->(e:EventNode) RETURN count(r) AS cnt"
                )
                has_event_cnt = has_event_rows[0]["cnt"] if has_event_rows else 0
                print(f"  HAS_EVENT 关系数 (Article→EventNode): {has_event_cnt}")
            except Exception as exc:
                print(f"  HAS_EVENT: 表不存在 ({str(exc).split('.')[0]})")

            try:
                has_participant_rows = await pool.execute_query(
                    "MATCH (e:EventNode)-[r:HAS_PARTICIPANT]->(en:Entity) RETURN count(r) AS cnt"
                )
                has_participant_cnt = has_participant_rows[0]["cnt"] if has_participant_rows else 0
                print(f"  HAS_PARTICIPANT 关系数 (EventNode→Entity): {has_participant_cnt}")
            except Exception as exc:
                print(f"  HAS_PARTICIPANT: 表不存在 ({str(exc).split('.')[0]})")
        else:
            print("  ⚠ EventNode 不存在或数量为 0！")
            issues.append("EventNode 不存在或数量为 0")

        # ── 3. 关系统计 ──
        print("\n── 3. 关系统计 ──")
        existing_rels: dict[str, int] = {}
        for rel_table in KNOWN_REL_TABLES:
            try:
                rows = await pool.execute_query(
                    f"MATCH ()-[r:{rel_table}]->() RETURN count(r) AS cnt"
                )
                cnt = rows[0]["cnt"] if rows else 0
                existing_rels[rel_table] = cnt
                print(f"  {rel_table}: {cnt}")
            except Exception as exc:
                print(f"  {rel_table}: 表不存在 ({str(exc).split('.')[0]})")

        # ── 4. Article pg_id 检查 ──
        print("\n── 4. Article 节点 pg_id 检查 ──")
        article_cnt = node_counts.get("Article", 0)
        if article_cnt > 0:
            try:
                no_pg_id_rows = await pool.execute_query(
                    "MATCH (a:Article) WHERE a.pg_id IS NULL OR a.pg_id = '' RETURN count(a) AS cnt"
                )
                no_pg_id_cnt = no_pg_id_rows[0]["cnt"] if no_pg_id_rows else 0
                status = "✓" if no_pg_id_cnt == 0 else "✗"
                print(f"  {status} 缺少 pg_id 的 Article: {no_pg_id_cnt}/{article_cnt}")
            except Exception as exc:
                print(f"  pg_id 查询失败: {exc}")
        else:
            print("  Article 数量为 0，跳过检查")

        # ── 5. Entity 类型检查 ──
        print("\n── 5. Entity 节点类型检查 ──")
        entity_cnt = node_counts.get("Entity", 0)
        if entity_cnt > 0:
            try:
                type_rows = await pool.execute_query(
                    "MATCH (e:Entity) RETURN e.type AS type, count(e) AS cnt ORDER BY cnt DESC"
                )
                if type_rows:
                    print("  Entity 类型分布:")
                    unknown_types = []
                    for row in type_rows:
                        etype = row.get("type", "NULL")
                        cnt = row.get("cnt", 0)
                        marker = "" if etype in ALLOWED_ENTITY_TYPES else " ⚠ 不在允许列表"
                        print(f"    {etype}: {cnt}{marker}")
                        if etype not in ALLOWED_ENTITY_TYPES and etype != "NULL":
                            unknown_types.append(etype)
                    if unknown_types:
                        issues.append(f"Entity 存在未知类型: {unknown_types}")
                    else:
                        print("  ✓ 所有类型均在允许列表中")
            except Exception as exc:
                print(f"  Entity 类型查询失败: {exc}")
        else:
            print("  Entity 数量为 0，跳过检查")

        # ── 6. 关系方向验证 ──
        print("\n── 6. 关系方向验证（孤立关系检查）──")
        for rel_table in sorted(existing_rels.keys()):
            cnt = existing_rels[rel_table]
            if cnt == 0:
                continue
            try:
                bad_rows = await pool.execute_query(
                    f"MATCH (src)-[r:{rel_table}]->(tgt) "
                    f"WHERE src.id IS NULL OR tgt.id IS NULL "
                    f"RETURN count(r) AS cnt"
                )
                bad_cnt = bad_rows[0]["cnt"] if bad_rows else 0
                if bad_cnt > 0:
                    print(f"  ✗ {rel_table}: {bad_cnt}/{cnt} 关系的端点节点 id 为空")
                else:
                    print(f"  ✓ {rel_table}: {cnt} 条关系端点节点正常")
            except Exception:
                print(f"  ✓ {rel_table}: {cnt} 条关系（端点检查跳过）")

        # ── 附加：节点主键完整性 ──
        print("\n── 附加检查：节点主键完整性 ──")
        for table in existing_tables:
            cnt = node_counts.get(table, 0)
            if cnt <= 0:
                continue
            try:
                null_id_rows = await pool.execute_query(
                    f"MATCH (n:{table}) WHERE n.id IS NULL OR n.id = '' RETURN count(n) AS cnt"
                )
                null_id_cnt = null_id_rows[0]["cnt"] if null_id_rows else 0
                if null_id_cnt > 0:
                    print(f"  ✗ {table}: {null_id_cnt}/{cnt} 节点 id 为空")
                else:
                    print(f"  ✓ {table}: 所有节点 id 完整")
            except Exception as exc:
                print(f"  ? {table}: 检查失败 ({exc})")

        # ── 附加：MENTIONS 方向 ──
        print("\n── 附加检查：MENTIONS 关系方向 ──")
        if "MENTIONS" in existing_rels and existing_rels["MENTIONS"] > 0:
            try:
                correct_dir = await pool.execute_query(
                    "MATCH (a:Article)-[r:MENTIONS]->(e:Entity) RETURN count(r) AS cnt"
                )
                correct_cnt = correct_dir[0]["cnt"] if correct_dir else 0
                print(f"  Article → Entity: {correct_cnt}")

                reverse_dir = await pool.execute_query(
                    "MATCH (e:Entity)-[r:MENTIONS]->(a:Article) RETURN count(r) AS cnt"
                )
                reverse_cnt = reverse_dir[0]["cnt"] if reverse_dir else 0
                if reverse_cnt > 0:
                    print(f"  ✗ Entity → Article (方向错误): {reverse_cnt}")
                else:
                    print(f"  ✓ 无反向 MENTIONS 关系")
            except Exception as exc:
                print(f"  MENTIONS 方向检查失败: {exc}")

        # Summary
        print(f"\n{'=' * 70}")
        print("  检查摘要")
        print(f"{'=' * 70}")
        missing_tables = [t for t in KNOWN_NODE_TABLES if node_counts.get(t, -1) == -1]
        if missing_tables:
            issues.append(f"缺少节点表: {missing_tables}")
        missing_rels = [r for r in KNOWN_REL_TABLES if r not in existing_rels]
        if missing_rels:
            issues.append(f"缺少关系表: {missing_rels}")

        if issues:
            print("  发现以下问题:")
            for i, issue in enumerate(issues, 1):
                print(f"    {i}. {issue}")
        else:
            print("  ✓ 未发现数据质量问题")

    finally:
        await pool.shutdown()


# ---------------------------------------------------------------------------
# Fix Model ID (from fix_model_id.py)
# ---------------------------------------------------------------------------


async def cmd_fix_model_id(args: argparse.Namespace) -> None:
    """Fix corrupted model_id values in article_vectors table."""
    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"Error: Database file not found: {db_path}")
        return

    import duckdb

    conn = duckdb.connect(str(db_path))

    try:
        if args.dry_run:
            print("=" * 60)
            print("DRY RUN - Previewing fixes")
            print("=" * 60)

            query = """
                SELECT model_id, COUNT(*) as count,
                       MIN(created_at) as first_seen, MAX(created_at) as last_seen
                FROM article_vectors GROUP BY model_id ORDER BY count DESC
            """
            result = conn.execute(query).fetchall()
            print("\nCurrent model_id distribution:")
            for model_id, count, first_seen, last_seen in result:
                print(f"  {model_id!r:40s} {count:6d} rows  ({first_seen} to {last_seen})")

            count_6b = conn.execute(
                "SELECT COUNT(*) FROM article_vectors WHERE model_id = '6B'"
            ).fetchone()[0]

            if count_6b > 0:
                print(f"\n⚠ Found {count_6b} rows with corrupted model_id='6B'")
                print("  These will be updated to 'Qwen3-Embedding-0.6B'")
            else:
                print("\n✓ No corrupted model_id='6B' found")

        elif args.execute:
            print("=" * 60)
            print("EXECUTING fixes")
            print("=" * 60)

            count_6b = conn.execute(
                "SELECT COUNT(*) FROM article_vectors WHERE model_id = '6B'"
            ).fetchone()[0]

            if count_6b == 0:
                print("✓ No corrupted model_id='6B' found. Nothing to fix.")
                return

            print(f"\nFound {count_6b} rows with model_id='6B'")
            print("Updating to 'Qwen3-Embedding-0.6B'...")

            conn.execute("BEGIN TRANSACTION")
            try:
                result = conn.execute("""
                    UPDATE article_vectors SET model_id = 'Qwen3-Embedding-0.6B'
                    WHERE model_id = '6B'
                """)
                updated_count = result.fetchone()[0] if result else 0
                print(f"✓ Updated {updated_count} rows")

                remaining = conn.execute(
                    "SELECT COUNT(*) FROM article_vectors WHERE model_id = '6B'"
                ).fetchone()[0]

                if remaining == 0:
                    print("✓ Verification passed: no more corrupted model_id='6B'")
                    conn.execute("COMMIT")
                    print("✓ Changes committed to database")
                else:
                    print(f"✗ Verification failed: {remaining} rows still have model_id='6B'")
                    conn.execute("ROLLBACK")
            except Exception as e:
                print(f"✗ Error during update: {e}")
                conn.execute("ROLLBACK")
                raise
    finally:
        conn.close()


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

    # null-fields subcommand
    p_null = sub.add_parser("null-fields", help="Check NULL/empty fields in database tables")
    p_null.add_argument("--table", help="Specific table to check (default: all tables)")
    p_null.add_argument(
        "--db",
        choices=["postgres", "duckdb"],
        default="postgres",
        help="Database to query (default: postgres)",
    )
    p_null.add_argument(
        "--threshold",
        type=float,
        default=0,
        help="Minimum null rate percentage to report (default: 0, show all)",
    )

    # dq-check subcommand
    p_dq = sub.add_parser("dq-check", help="Run LadybugDB data quality checks")
    p_dq.add_argument(
        "--db-path",
        type=str,
        default="data/weaver.lbug",
        help="Path to LadybugDB database (default: data/weaver.lbug)",
    )

    # fix-model-id subcommand
    p_fix = sub.add_parser("fix-model-id", help="Fix corrupted model_id values in article_vectors")
    p_fix.add_argument(
        "--db-path",
        type=str,
        default="data/weaver.duckdb",
        help="Path to DuckDB database (default: data/weaver.duckdb)",
    )
    p_fix.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without applying them",
    )
    p_fix.add_argument(
        "--execute",
        action="store_true",
        help="Apply the fixes to the database",
    )

    args = parser.parse_args()

    # Validate db arguments for stats
    if args.command == "stats" and args.db:
        try:
            args.db = _validate_dbs(args.db)
        except ValueError as e:
            parser.error(str(e))

    dispatch = {
        "stats": cmd_stats,
        "article": cmd_article,
        "random": cmd_random,
        "rows": cmd_rows,
        "null-fields": cmd_null_fields,
        "dq-check": cmd_dq_check,
        "fix-model-id": cmd_fix_model_id,
    }
    asyncio.run(dispatch[args.command](args))


if __name__ == "__main__":
    main()
