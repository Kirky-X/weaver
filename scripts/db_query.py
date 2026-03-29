#!/usr/bin/env python3
"""Database query and inspection tool for Weaver.

Subcommands:
  stats    Show table record counts (PostgreSQL + Neo4j)
  article  Query complete info for an article by ID
  random   Query random articles with entities and relationships

Usage:
  uv run scripts/db_query.py stats
  uv run scripts/db_query.py article --id <article-uuid>
  uv run scripts/db_query.py random --limit 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


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


# ---------------------------------------------------------------------------
# Sub-command: stats
# ---------------------------------------------------------------------------


async def cmd_stats(_args: argparse.Namespace) -> None:
    """Check all tables in PostgreSQL and Neo4j databases."""
    settings = _get_settings()
    dsn = _pg_dsn(settings)
    neo4j_uri, neo4j_auth = _neo4j_auth(settings)

    print("=" * 80)
    print("PostgreSQL 数据库表检查")
    print("=" * 80)

    # --- PostgreSQL ---
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

    # --- Neo4j ---
    print("\n" + "=" * 80)
    print("Neo4j 图数据库检查")
    print("=" * 80)

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


# ---------------------------------------------------------------------------
# Sub-command: article
# ---------------------------------------------------------------------------


async def cmd_article(args: argparse.Namespace) -> None:
    """Query complete info for a specific article by ID."""
    article_id = args.id
    settings = _get_settings()
    dsn = _pg_dsn(settings)
    neo4j_uri, neo4j_auth = _neo4j_auth(settings)
    results: dict = {}

    # --- PostgreSQL ---
    print(f"正在查询 PostgreSQL (article_id={article_id})...")
    try:
        import asyncpg

        conn = await asyncpg.connect(dsn)

        article_row = await conn.fetchrow("SELECT * FROM articles WHERE id = $1", article_id)
        if article_row:
            results["postgresql"] = {"articles": dict(article_row)}
            print("  找到文章记录")
        else:
            results["postgresql"] = {"articles": None}
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
        results["postgresql_error"] = str(exc)

    # --- Neo4j ---
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
                "MATCH (a:Article {pg_id: $pg_id})-[m:MENTIONS]->(e:Entity) RETURN a, m, e", params
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

            followed = []
            for r in session.run(
                "MATCH (a:Article {pg_id: $pg_id})-[r:FOLLOWED_BY]->(other:Article) RETURN other, r "
                "UNION "
                "MATCH (other:Article)-[r:FOLLOWED_BY]->(a:Article {pg_id: $pg_id}) RETURN other, r",
                params,
            ):
                followed.append(
                    {
                        "related_article": dict(r["other"]),
                        "relationship": dict(r["r"]) if r["r"] else None,
                        "direction": "outgoing" if r["r"].start_node == r["other"] else "incoming",
                    }
                )
            results["neo4j"]["followed_by"] = followed
            print(f"  FOLLOWED_BY 关系：{len(followed)} 条")

            entity_rels = []
            for r in session.run(
                "MATCH (a:Article {pg_id: $pg_id})-[:MENTIONS]->(e1:Entity), (e1)-[r:RELATED_TO]->(e2:Entity) RETURN e1, r, e2",
                params,
            ):
                entity_rels.append(
                    {
                        "source_entity": dict(r["e1"]),
                        "relationship": dict(r["r"]) if r["r"] else None,
                        "target_entity": dict(r["e2"]),
                    }
                )
            results["neo4j"]["entity_relationships"] = entity_rels
            print(f"  实体间 RELATED_TO 关系：{len(entity_rels)} 条")

        driver.close()
    except Exception as exc:
        print(f"Neo4j 查询失败：{exc}")
        results["neo4j_error"] = str(exc)

    # --- Save output ---
    output_file = Path(__file__).parent / "temp" / f"article_{article_id}_complete.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"\n数据已保存到：{output_file}")

    # --- Summary ---
    print("\n" + "=" * 80)
    print("数据摘要:")
    if results.get("postgresql", {}).get("articles"):
        a = results["postgresql"]["articles"]
        print(f"\nPostgreSQL articles 表:")
        print(f"   ID: {a.get('id')}")
        print(f"   标题：{str(a.get('title', 'N/A'))[:60]}...")
        print(f"   分类：{a.get('category')}")
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

    if followed := results.get("neo4j", {}).get("followed_by", []):
        print(f"\nFOLLOWED_BY 关系 ({len(followed)} 条):")
        for rel in followed:
            d = "→" if rel["direction"] == "outgoing" else "←"
            print(f"   {d} {str(rel['related_article'].get('title', 'N/A'))[:50]}")


# ---------------------------------------------------------------------------
# Sub-command: random
# ---------------------------------------------------------------------------


async def cmd_random(args: argparse.Namespace) -> None:
    """Query random articles with entities and relationships from Neo4j."""
    limit = args.limit
    settings = _get_settings()
    neo4j_uri, neo4j_auth = _neo4j_auth(settings)

    print(f"正在查询 {limit} 篇随机文章...")

    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(neo4j_uri, auth=neo4j_auth)
        results = []

        with driver.session() as session:
            # Query 1: random articles with MENTIONS
            query = f"""  # noqa: S608
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
                return

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

        # Save output
        output_file = Path(__file__).parent / "temp" / "query_articles_output.json"
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
                f"  分类：{a['category']}  评分：{a['score']}  实体：{len(ad['entities'])}  关系：{len(ad['relationships'])}"
            )

    except Exception as exc:
        print(f"查询失败：{exc}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Weaver database query and inspection tool")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("stats", help="Show table record counts for PostgreSQL + Neo4j")

    p_article = sub.add_parser("article", help="Query complete info for an article by ID")
    p_article.add_argument("--id", required=True, help="Article UUID")

    p_random = sub.add_parser("random", help="Query random articles with entities")
    p_random.add_argument("--limit", type=int, default=2, help="Number of articles (default: 2)")

    args = parser.parse_args()
    dispatch = {"stats": cmd_stats, "article": cmd_article, "random": cmd_random}
    asyncio.run(dispatch[args.command](args))


if __name__ == "__main__":
    main()
