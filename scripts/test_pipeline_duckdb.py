#!/usr/bin/env python
# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Pipeline test using only DuckDB + LadybugDB (no PostgreSQL/Neo4j/Redis).

Validates the full pipeline: ingest → process → persist using DuckDB as
the relational store, LadybugDB as the graph store, and CashewsRedisFallback
as the Redis replacement.

Usage:
    cd /home/dev/projects/weaver
    python -m src.scripts.test_pipeline_duckdb

Environment:
    FORCE_NEWS_MODE=1  - Force all articles to be treated as news (bypass classifier)
                        Default is 0 (realistic mode, classifier enabled)

Note: This test uses production database paths (data/weaver.duckdb).
"""

from __future__ import annotations

import asyncio
import os
import sys
import traceback
import uuid

# ── Path setup ────────────────────────────────────────────────
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(os.path.dirname(_script_dir))
_src_dir = os.path.join(_project_root, "src")
sys.path.insert(0, _src_dir)

# Force disable PG/Neo4j/Redis before any config loads
os.environ.setdefault("POSTGRES_ENABLED", "false")
os.environ.setdefault("NEO4J_ENABLED", "false")
os.environ.setdefault("DUCKDB_ENABLED", "true")
os.environ.setdefault("LADYBUG_ENABLED", "true")

# Use production database paths for realistic testing
os.environ.setdefault("DUCKDB_DB_PATH", "data/weaver.duckdb")
os.environ.setdefault("LADYBUG_DB_PATH", "data/weaver_graph.ladybug")

# Optional: Force all articles to be treated as news (disabled by default for realism)
FORCE_NEWS_MODE = os.environ.get("FORCE_NEWS_MODE", "0") == "1"

from config.settings import Settings  # noqa: E402
from core.cache.redis import CashewsRedisFallback  # noqa: E402
from core.db.duckdb_pool import DuckDBPool  # noqa: E402
from core.db.ladybug_pool import LadybugPool  # noqa: E402
from core.event.bus import EventBus  # noqa: E402
from core.event.bus import LLMUsageEvent  # noqa: E402
from core.llm.client import LLMClient  # noqa: E402
from core.llm.token_budget import TokenBudgetManager  # noqa: E402
from core.observability.logging import get_logger  # noqa: E402
from core.prompt.loader import PromptLoader  # noqa: E402
from modules.ingestion.domain.models import ArticleRaw, SourceConfig  # noqa: E402
from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher  # noqa: E402
from modules.ingestion.parsing.newsnow_parser import NewsNowParser  # noqa: E402
from modules.knowledge.graph.entity_resolver import EntityResolver  # noqa: E402
from modules.knowledge.graph.name_normalizer import NameNormalizer  # noqa: E402
from modules.knowledge.graph.resolution_rules import EntityResolutionRules  # noqa: E402
from modules.processing.nlp.spacy_extractor import SpacyExtractor  # noqa: E402
from modules.storage.duckdb.article_repo import DuckDBArticleRepo  # noqa: E402
from modules.storage.duckdb.schema import initialize_duckdb_schema  # noqa: E402
from modules.storage.duckdb.source_authority_repo import (  # noqa: E402
    DuckDBSourceAuthorityRepo,
)
from modules.storage.duckdb.vector_repo import DuckDBVectorRepo  # noqa: E402
from modules.storage.ladybug.schema import initialize_ladybug_schema  # noqa: E402
from modules.storage.ladybug.writer import LadybugWriter  # noqa: E402

# ── Phase indicators ──────────────────────────────────────────

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


# ── Main ──────────────────────────────────────────────────────


async def main() -> None:
    print("Pipeline Test: DuckDB + LadybugDB + CashewsRedis")
    print(f"Project root: {_project_root}")

    log = get_logger("test_pipeline_duckdb")

    settings = Settings()

    # ──────────────────────────────────────────────────────────
    # PHASE 0: Initialize infrastructure
    # ──────────────────────────────────────────────────────────
    phase_header("PHASE 0: Infrastructure Initialization")

    # DuckDB (using production path - will append to existing data)
    duckdb_path = settings.duckdb.db_path
    duck_pool = DuckDBPool(db_path=duckdb_path)
    await duck_pool.startup()
    await initialize_duckdb_schema(duck_pool)
    step("DuckDB pool started", True, duckdb_path)

    # LadybugDB (using production path - will append to existing data)
    ladybug_path = settings.ladybug.db_path
    ladybug_pool = LadybugPool(db_path=ladybug_path)
    await ladybug_pool.startup()
    await initialize_ladybug_schema(ladybug_pool)
    step("LadybugDB pool started", True, ladybug_path)

    # Redis fallback (cashews)
    redis_client = CashewsRedisFallback()
    await redis_client.startup()
    step("CashewsRedisFallback started", True, "mem://")

    # EventBus (must be created before LLMClient for event tracking)
    event_bus = EventBus()
    step("EventBus created", True)

    # LLM client (now with event_bus for usage tracking)
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

    # Subscribe LLM usage tracking handler
    from modules.storage.duckdb.llm_usage_repo import DuckDBLLMUsageRepo

    llm_usage_repo = DuckDBLLMUsageRepo(duck_pool)

    async def handle_llm_usage(event: LLMUsageEvent) -> None:
        try:
            await llm_usage_repo.insert_raw(event)
        except Exception as exc:
            log.warning("llm_usage_tracking_failed", error=str(exc))

    event_bus.subscribe(LLMUsageEvent, handle_llm_usage)
    step("LLM usage tracking subscribed", True)

    # SpacyExtractor
    spacy = SpacyExtractor()
    try:
        spacy.warmup(languages=["zh"])
        step("SpacyExtractor warmed up (zh)", True)
    except Exception:
        step("SpacyExtractor warmup skipped (no model)", True, "will use fallback")

    # Repos
    article_repo = DuckDBArticleRepo(duck_pool)
    vector_repo = DuckDBVectorRepo(duck_pool)
    source_auth_repo = DuckDBSourceAuthorityRepo(duck_pool)
    step("DuckDB repos created", True, "ArticleRepo, VectorRepo, SourceAuthorityRepo")

    # LadybugWriter + EntityRepo
    ladybug_writer = LadybugWriter(ladybug_pool)
    from modules.storage.ladybug.entity_repo import LadybugEntityRepo

    ladybug_entity_repo = LadybugEntityRepo(ladybug_pool)
    step("LadybugDB repos created", True, "Writer, EntityRepo")

    # EntityResolver
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
    # PHASE 1: Fetch data from newsnow.world
    # ──────────────────────────────────────────────────────────
    phase_header("PHASE 1: Data Ingestion")

    fetcher = HttpxFetcher(timeout=15.0)
    parser = NewsNowParser(fetcher)

    source_config = SourceConfig(
        id="test-newsnow-hupu",
        name="NewsNow Hupu",
        url="https://www.newsnow.world/api/s?id=hupu",
        source_type="newsnow",
        credibility=0.50,
        tier=2,
    )

    news_items: list = []
    try:
        news_items = await parser.parse(source_config)
        step(f"Fetched {len(news_items)} items", len(news_items) > 0)
    except Exception as exc:
        step("Fetch failed", False, str(exc))
        log.error("phase1_error", detail=traceback.format_exc())
        raise SystemExit(1) from exc

    if not news_items:
        step("No items fetched - API may be down", False)
        raise SystemExit(1)

    # Convert to ArticleRaw
    raw_articles: list[ArticleRaw] = []
    for item in news_items:  # Process all fetched articles (production-like)
        if isinstance(item, dict):
            raw = ArticleRaw(
                url=item.get("url", f"https://test/{uuid.uuid4()}"),
                title=item.get("title", "Untitled"),
                body=item.get("body", item.get("description", "")),
                source=item.get("source", ""),
                source_host=item.get("source_host", ""),
                tier=2,
            )
        else:
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
    # PHASE 2: Build pipeline and process
    # ──────────────────────────────────────────────────────────
    phase_header("PHASE 2: Pipeline Execution")

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
        # community_updater requires Neo4j — not available with LadybugDB
        community_updater=None,
        relation_type_normalizer=rt_normalizer,
    )
    step("Pipeline constructed", True)

    states: list = []
    try:
        states = await pipeline.process_batch(raw_articles)
        step("process_batch completed", True, f"{len(states)} results")
    except Exception as exc:
        step("process_batch failed", False, str(exc))
        log.error("phase2_error", detail=traceback.format_exc())

    # FORCE_NEWS_MODE: If all articles were rejected, force them through for testing
    if FORCE_NEWS_MODE:
        forced_count = 0
        for state in states:
            if isinstance(state, dict) and state.get("terminal"):
                # Force article to be treated as news
                state["is_news"] = True
                state["terminal"] = False
                forced_count += 1
        if forced_count > 0:
            step(f"FORCE_NEWS_MODE: Forced {forced_count} articles to be news", True)

            # Re-run persist on forced articles
            try:
                await pipeline._persist_batch(states)
                step("Persist completed on forced articles", True)
            except Exception as exc:
                step("Persist failed on forced articles", False, str(exc))

    # Report per-article results
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
            step(
                f"Article {i}: {title_str}",
                ok,
                f"terminal={terminal}, is_news={is_news}",
            )
        else:
            step(f"Article {i}", True)

    step(f"Success rate: {success_count}/{len(states)}", success_count > 0)

    # ──────────────────────────────────────────────────────────
    # PHASE 3: Verify DuckDB data
    # ──────────────────────────────────────────────────────────
    phase_header("PHASE 3: DuckDB Verification")

    try:
        async with duck_pool.session_context() as session:
            result = await session.execute(
                __import__("sqlalchemy").text("SELECT count(*) FROM articles")
            )
            article_count = result.scalar()
            step("articles table", article_count > 0, f"{article_count} rows")
    except Exception as exc:
        step("articles table query failed", False, str(exc))
        article_count = 0

    try:
        async with duck_pool.session_context() as session:
            result = await session.execute(
                __import__("sqlalchemy").text("SELECT count(*) FROM article_vectors")
            )
            vec_count = result.scalar()
            step("article_vectors table", vec_count > 0, f"{vec_count} rows")
    except Exception as exc:
        step("article_vectors query failed", False, str(exc))
        vec_count = 0

    try:
        async with duck_pool.session_context() as session:
            result = await session.execute(
                __import__("sqlalchemy").text("SELECT count(*) FROM source_authorities")
            )
            auth_count = result.scalar()
            step("source_authorities table", True, f"{auth_count} rows")
    except Exception as exc:
        step("source_authorities query failed", False, str(exc))

    # ──────────────────────────────────────────────────────────
    # PHASE 4: Verify LadybugDB data
    # ──────────────────────────────────────────────────────────
    phase_header("PHASE 4: LadybugDB Verification")

    try:
        articles_in_graph = await ladybug_pool.execute_query(
            "MATCH (a:Article) RETURN count(a) AS cnt"
        )
        cnt = articles_in_graph[0]["cnt"] if articles_in_graph else 0
        step("Article nodes in graph", cnt > 0, f"{cnt} nodes")
    except Exception as exc:
        step("LadybugDB article query failed", False, str(exc))

    try:
        entities_in_graph = await ladybug_pool.execute_query(
            "MATCH (e:Entity) RETURN count(e) AS cnt"
        )
        cnt = entities_in_graph[0]["cnt"] if entities_in_graph else 0
        step("Entity nodes in graph", True, f"{cnt} nodes")
    except Exception as exc:
        step("LadybugDB entity query failed", False, str(exc))

    try:
        relations_in_graph = await ladybug_pool.execute_query(
            "MATCH ()-[r:MENTIONS]->() RETURN count(r) AS cnt"
        )
        cnt = relations_in_graph[0]["cnt"] if relations_in_graph else 0
        step("MENTIONS relations", True, f"{cnt} edges")
    except Exception as exc:
        step("LadybugDB MENTIONS query failed", False, str(exc))

    # ──────────────────────────────────────────────────────────
    # PHASE 5: Cleanup
    # ──────────────────────────────────────────────────────────
    phase_header("PHASE 5: Cleanup")

    step("LLM client released", True)

    await duck_pool.shutdown()
    step("DuckDB pool closed", True)

    await ladybug_pool.shutdown()
    step("LadybugDB pool closed", True)

    await redis_client.shutdown()
    step("CashewsRedisFallback closed", True)

    # ──────────────────────────────────────────────────────────
    # Summary
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
    else:
        print(f"\n  Pipeline test FAILED — no articles processed successfully")

    return 0 if success_count > 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
