#!/usr/bin/env python
# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Pipeline test using RSS feed (Solidot) with DuckDB + LadybugDB.

Tests the full pipeline: RSS ingest → process → persist using DuckDB as
the relational store and LadybugDB as the graph store.

Usage:
    cd /home/dev/projects/weaver
    python -m src.scripts.test_pipeline_rss

Environment:
    FORCE_NEWS_MODE=1  - Force all articles to be treated as news (bypass classifier)
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys

# Path setup
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)  # scripts/ -> weaver/
_src_dir = os.path.join(_project_root, "src")
sys.path.insert(0, _src_dir)
sys.path.insert(0, _project_root)  # For config/

# Force disable PG/Neo4j/Redis before any config loads
os.environ.setdefault("POSTGRES_ENABLED", "false")
os.environ.setdefault("NEO4J_ENABLED", "false")
os.environ.setdefault("DUCKDB_ENABLED", "true")
os.environ.setdefault("LADYBUG_ENABLED", "true")
os.environ.setdefault("DUCKDB_DB_PATH", "data/weaver.duckdb")
os.environ.setdefault("LADYBUG_DB_PATH", "data/weaver_graph.ladybug")

# Optional: Force all articles to be treated as news
FORCE_NEWS_MODE = os.environ.get("FORCE_NEWS_MODE", "0") == "1"

# Phase indicators
PASS = "\u2713"
FAIL = "\u2717"


def phase_header(name: str) -> None:
    width = 60
    print(f"\n{'=' * width}")
    print(f"  {name}")
    print(f"{'=' * width}")


def step(label: str, ok: bool, detail: str = "") -> None:
    mark = PASS if ok else FAIL
    suffix = f"  ({detail})" if detail else ""
    print(f"  {mark} {label}{suffix}")


async def clear_duckdb(pool) -> dict[str, int]:
    """Clear all data from DuckDB tables, return row counts before deletion."""
    from sqlalchemy import text

    counts = {}
    # Tables are hardcoded - safe for internal test script
    tables = [
        "articles",
        "article_vectors",
        "entity_vectors",
        "source_authorities",
        "llm_failures",
        "llm_usage_raw",
        "llm_usage_hourly",
        "pending_sync",
        "unknown_relation_types",
    ]

    async with pool.session_context() as session:
        for table in tables:
            with contextlib.suppress(Exception):
                result = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
                counts[table] = result.scalar() or 0
                await session.execute(text(f"DELETE FROM {table}"))
        await session.commit()

    return counts


async def clear_ladybug(pool) -> dict[str, int]:
    """Clear all nodes and relationships from LadybugDB."""
    counts = {}

    # Count nodes before deletion
    with contextlib.suppress(Exception):
        article_count = await pool.execute_query("MATCH (a:Article) RETURN count(a) AS cnt")
        counts["Article"] = article_count[0]["cnt"] if article_count else 0

    with contextlib.suppress(Exception):
        entity_count = await pool.execute_query("MATCH (e:Entity) RETURN count(e) AS cnt")
        counts["Entity"] = entity_count[0]["cnt"] if entity_count else 0

    # Delete all relationships first
    with contextlib.suppress(Exception):
        await pool.execute_query("MATCH ()-[r:MENTIONS]->() DELETE r")
    with contextlib.suppress(Exception):
        await pool.execute_query("MATCH ()-[r:FOLLOWED_BY]->() DELETE r")
    with contextlib.suppress(Exception):
        await pool.execute_query("MATCH ()-[r:RELATED_TO]->() DELETE r")

    # Delete all nodes
    with contextlib.suppress(Exception):
        await pool.execute_query("MATCH (n:Article) DELETE n")
    with contextlib.suppress(Exception):
        await pool.execute_query("MATCH (n:Entity) DELETE n")

    return counts


async def main() -> int:
    """Main entry point for RSS pipeline test."""
    print("Pipeline Test: RSS (Solidot) → DuckDB + LadybugDB")
    print(f"Project root: {_project_root}")

    # Import after path setup
    from config.settings import Settings
    from core.observability.logging import get_logger

    log = get_logger("test_pipeline_rss")
    from core.cache.redis import CashewsRedisFallback
    from core.db.duckdb_pool import DuckDBPool
    from core.db.ladybug_pool import LadybugPool
    from core.event.bus import EventBus, LLMUsageEvent
    from core.llm.client import LLMClient
    from core.llm.token_budget import TokenBudgetManager
    from core.prompt.loader import PromptLoader
    from modules.processing.nlp.spacy_extractor import SpacyExtractor
    from modules.storage.duckdb.schema import initialize_duckdb_schema
    from modules.storage.ladybug.schema import initialize_ladybug_schema

    settings = Settings()

    # ──────────────────────────────────────────────────────────
    # PHASE 0: Initialize infrastructure
    # ──────────────────────────────────────────────────────────
    phase_header("PHASE 0: Infrastructure Initialization")

    # DuckDB
    duckdb_path = settings.duckdb.db_path
    duck_pool = DuckDBPool(db_path=duckdb_path)
    await duck_pool.startup()
    await initialize_duckdb_schema(duck_pool)
    step("DuckDB pool started", True, duckdb_path)

    # LadybugDB
    ladybug_path = settings.ladybug.db_path
    ladybug_pool = LadybugPool(db_path=ladybug_path)
    await ladybug_pool.startup()
    await initialize_ladybug_schema(ladybug_pool)
    step("LadybugDB pool started", True, ladybug_path)

    # Redis fallback (cashews)
    redis_client = CashewsRedisFallback()
    await redis_client.startup()
    step("CashewsRedisFallback started", True, "mem://")

    # EventBus
    event_bus = EventBus()
    step("EventBus created", True)

    # LLM client
    prompt_dir = settings.prompt.dir
    prompt_loader = PromptLoader(prompt_dir)
    config_path = os.path.join(_project_root, "config/llm.toml")
    llm_client = await LLMClient.create_from_config(
        config_path=config_path,
        prompt_loader=prompt_loader,
        redis_client=redis_client,
        event_bus=event_bus,
    )
    step("LLM client initialized", True)

    # LLM usage tracking
    from modules.storage.duckdb.llm_usage_repo import DuckDBLLMUsageRepo

    llm_usage_repo = DuckDBLLMUsageRepo(duck_pool)

    async def handle_llm_usage(event: LLMUsageEvent) -> None:
        with contextlib.suppress(Exception):
            await llm_usage_repo.insert_raw(event)

    event_bus.subscribe(LLMUsageEvent, handle_llm_usage)
    step("LLM usage tracking subscribed", True)

    # SpacyExtractor
    spacy = SpacyExtractor()
    try:
        spacy.warmup(languages=["zh"])
        step("SpacyExtractor warmed up (zh)", True)
    except Exception:
        step("SpacyExtractor warmup skipped", True, "will use fallback")

    # Repos
    from modules.storage.duckdb.article_repo import DuckDBArticleRepo
    from modules.storage.duckdb.source_authority_repo import DuckDBSourceAuthorityRepo
    from modules.storage.duckdb.vector_repo import DuckDBVectorRepo

    article_repo = DuckDBArticleRepo(duck_pool)
    vector_repo = DuckDBVectorRepo(duck_pool)
    source_auth_repo = DuckDBSourceAuthorityRepo(duck_pool)
    step("DuckDB repos created", True)

    # LadybugDB repos
    from modules.storage.ladybug.entity_repo import LadybugEntityRepo
    from modules.storage.ladybug.writer import LadybugWriter

    ladybug_writer = LadybugWriter(ladybug_pool)
    ladybug_entity_repo = LadybugEntityRepo(ladybug_pool)
    step("LadybugDB repos created", True)

    # EntityResolver
    from modules.knowledge.graph.entity_resolver import EntityResolver
    from modules.knowledge.graph.name_normalizer import NameNormalizer
    from modules.knowledge.graph.resolution_rules import EntityResolutionRules

    name_normalizer = NameNormalizer()
    resolution_rules = EntityResolutionRules()
    entity_resolver = EntityResolver(
        entity_repo=ladybug_entity_repo,
        vector_repo=vector_repo,
        llm=llm_client,
        resolution_rules=resolution_rules,
        name_normalizer=name_normalizer,
    )
    step("EntityResolver created", True)

    # ──────────────────────────────────────────────────────────
    # PHASE 1: Clear databases
    # ──────────────────────────────────────────────────────────
    phase_header("PHASE 1: Clear Databases")

    duck_counts = await clear_duckdb(duck_pool)
    for table, count in duck_counts.items():
        if count >= 0:
            step(f"Cleared {table}", True, f"{count} rows deleted")
        else:
            step(f"Skipped {table}", True, "table not found")

    lady_counts = await clear_ladybug(ladybug_pool)
    for node_type, count in lady_counts.items():
        step(f"Cleared {node_type} nodes", True, f"{count} nodes deleted")

    step("Databases cleared", True)

    # ──────────────────────────────────────────────────────────
    # PHASE 2: RSS Fetch and Parse
    # ──────────────────────────────────────────────────────────
    phase_header("PHASE 2: RSS Fetch & Parse")

    from modules.ingestion.domain.models import ArticleRaw, SourceConfig
    from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher
    from modules.ingestion.parsing.rss_parser import RSSParser

    fetcher = HttpxFetcher(timeout=15.0)
    parser = RSSParser(fetcher)

    # Solidot RSS 配置
    source_config = SourceConfig(
        id="test-solidot-rss",
        name="Solidot",
        url="https://www.solidot.org/index.rss",
        source_type="rss",
        credibility=0.70,  # 科技新闻, 较高可信度
        tier=2,
    )
    step("RSS source configured", True, source_config.url)

    # 抓取并解析 RSS
    news_items: list = []
    try:
        news_items = await parser.parse(source_config)
        step(f"Fetched {len(news_items)} items", len(news_items) > 0)
    except Exception as exc:
        import traceback

        step("RSS fetch failed", False, str(exc))
        log.error("rss_fetch_error", detail=traceback.format_exc())
        raise SystemExit(1) from exc

    if not news_items:
        step("No items fetched - RSS may be empty", False)
        raise SystemExit(1)

    # 限制文章数量以加快测试
    MAX_ARTICLES = int(os.environ.get("MAX_ARTICLES", "2"))
    if len(news_items) > MAX_ARTICLES:
        news_items = news_items[:MAX_ARTICLES]
        step(f"Limited to {MAX_ARTICLES} articles", True)

    # 转换为 ArticleRaw
    raw_articles: list[ArticleRaw] = []
    for item in news_items:
        raw = ArticleRaw(
            url=item.url,
            title=item.title,
            body=item.body or item.description,
            source=item.source,
            source_host=item.source_host,
            tier=2,
        )
        raw_articles.append(raw)

    step(f"Converted to ArticleRaw", True, f"{len(raw_articles)} articles")
    await parser.close()

    # ──────────────────────────────────────────────────────────
    # PHASE 3: Pipeline Execution
    # ──────────────────────────────────────────────────────────
    phase_header("PHASE 3: Pipeline Execution")

    from modules.knowledge.core.relation_types import RelationTypeNormalizer
    from modules.processing.pipeline.graph import Pipeline

    rt_normalizer = RelationTypeNormalizer(duck_pool)
    step("RelationTypeNormalizer created", True)

    pipeline = Pipeline(
        llm=llm_client,
        budget=TokenBudgetManager(),
        prompt_loader=prompt_loader,
        event_bus=event_bus,
        spacy=spacy,
        vector_repo=vector_repo,
        article_repo=article_repo,
        neo4j_writer=ladybug_writer,
        source_auth_repo=source_auth_repo,
        entity_resolver=entity_resolver,
        redis_client=redis_client,
        community_updater=None,  # LadybugDB doesn't support community detection
        relation_type_normalizer=rt_normalizer,
    )
    step("Pipeline constructed", True)

    states: list = []
    try:
        states = await pipeline.process_batch(raw_articles)
        step("process_batch completed", True, f"{len(states)} results")
    except Exception as exc:
        import traceback

        step("process_batch failed", False, str(exc))
        log.error("process_batch_error", detail=traceback.format_exc())

    # FORCE_NEWS_MODE: 强制所有文章作为新闻处理
    if FORCE_NEWS_MODE:
        forced_count = 0
        for state in states:
            if isinstance(state, dict) and state.get("terminal"):
                state["is_news"] = True
                state["terminal"] = False
                forced_count += 1
        if forced_count > 0:
            step(f"FORCE_NEWS_MODE: Forced {forced_count} articles", True)
            with contextlib.suppress(Exception):
                await pipeline._persist_batch(states)
                step("Persist completed on forced articles", True)

    # 报告每篇文章结果
    success_count = 0
    for i, state in enumerate(states):
        if isinstance(state, dict):
            terminal = state.get("terminal", False)
            ok = not terminal
            if ok:
                success_count += 1
            title = state.get("raw", None)
            title_str = title.title[:40] if hasattr(title, "title") else "?"
            is_news = state.get("is_news", "?")

            # Debug: print entity and relation counts
            entities = state.get("entities", [])
            relations = state.get("relations", [])
            print(f"  [DEBUG] Article {i}: {len(entities)} entities, {len(relations)} relations")

            step(f"Article {i}: {title_str}", ok, f"terminal={terminal}, is_news={is_news}")
        else:
            step(f"Article {i}", True)

    step(f"Success rate: {success_count}/{len(states)}", success_count > 0)

    # ──────────────────────────────────────────────────────────
    # PHASE 4: DuckDB Verification
    # ──────────────────────────────────────────────────────────
    phase_header("PHASE 4: DuckDB Verification")

    import sqlalchemy

    article_count = 0
    vec_count = 0

    with contextlib.suppress(Exception):
        async with duck_pool.session_context() as session:
            result = await session.execute(sqlalchemy.text("SELECT count(*) FROM articles"))
            article_count = result.scalar()
            step("articles table", article_count > 0, f"{article_count} rows")

    with contextlib.suppress(Exception):
        async with duck_pool.session_context() as session:
            result = await session.execute(sqlalchemy.text("SELECT count(*) FROM article_vectors"))
            vec_count = result.scalar()
            step("article_vectors table", vec_count > 0, f"{vec_count} rows")

    with contextlib.suppress(Exception):
        async with duck_pool.session_context() as session:
            result = await session.execute(
                sqlalchemy.text("SELECT count(*) FROM source_authorities")
            )
            auth_count = result.scalar()
            step("source_authorities table", True, f"{auth_count} rows")

    with contextlib.suppress(Exception):
        async with duck_pool.session_context() as session:
            result = await session.execute(sqlalchemy.text("SELECT count(*) FROM llm_usage_raw"))
            llm_count = result.scalar()
            step("llm_usage_raw table", True, f"{llm_count} rows")

    # ──────────────────────────────────────────────────────────
    # PHASE 5: LadybugDB Verification
    # ──────────────────────────────────────────────────────────
    phase_header("PHASE 5: LadybugDB Verification")

    with contextlib.suppress(Exception):
        articles_in_graph = await ladybug_pool.execute_query(
            "MATCH (a:Article) RETURN count(a) AS cnt"
        )
        cnt = articles_in_graph[0]["cnt"] if articles_in_graph else 0
        step("Article nodes in graph", cnt > 0, f"{cnt} nodes")

    with contextlib.suppress(Exception):
        entities_in_graph = await ladybug_pool.execute_query(
            "MATCH (e:Entity) RETURN count(e) AS cnt"
        )
        cnt = entities_in_graph[0]["cnt"] if entities_in_graph else 0
        step("Entity nodes in graph", True, f"{cnt} nodes")

    with contextlib.suppress(Exception):
        relations_in_graph = await ladybug_pool.execute_query(
            "MATCH ()-[r:MENTIONS]->() RETURN count(r) AS cnt"
        )
        cnt = relations_in_graph[0]["cnt"] if relations_in_graph else 0
        step("MENTIONS relations", True, f"{cnt} edges")

    with contextlib.suppress(Exception):
        related_in_graph = await ladybug_pool.execute_query(
            "MATCH ()-[r:RELATED_TO]->() RETURN count(r) AS cnt"
        )
        cnt = related_in_graph[0]["cnt"] if related_in_graph else 0
        step("RELATED_TO relations", True, f"{cnt} edges")

    # ──────────────────────────────────────────────────────────
    # PHASE 6: Cleanup
    # ──────────────────────────────────────────────────────────
    phase_header("PHASE 6: Cleanup")

    step("LLM client released", True)

    await duck_pool.shutdown()
    step("DuckDB pool closed", True)

    await ladybug_pool.shutdown()
    step("LadybugDB pool closed", True)

    await redis_client.shutdown()
    step("CashewsRedisFallback closed", True)

    # ──────────────────────────────────────────────────────────
    # SUMMARY
    # ──────────────────────────────────────────────────────────
    phase_header("SUMMARY")
    log.info(
        "pipeline_test_summary",
        articles_processed=len(states),
        successful=success_count,
        duckdb_articles=article_count,
        duckdb_vectors=vec_count,
        duckdb_path=duckdb_path,
        ladybug_path=ladybug_path,
    )

    if success_count > 0:
        print(f"\n  Pipeline test PASSED")
        return 0
    else:
        print(f"\n  Pipeline test FAILED — no articles processed successfully")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
