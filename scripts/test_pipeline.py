#!/usr/bin/env python
# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unified pipeline test script for Weaver.

Supports multiple test modes:
  - newsnow: Test NewsNow data ingestion (default)
  - rss: Test RSS feed ingestion
  - strategy: Test database failover strategy

Usage:
    # NewsNow mode (default)
    uv run scripts/test_pipeline.py --mode newsnow --max-items 5

    # RSS mode
    uv run scripts/test_pipeline.py --mode rss --source solidot --max-items 2

    # Strategy mode (test database failover)
    uv run scripts/test_pipeline.py --mode strategy

    # Additional options
    uv run scripts/test_pipeline.py --force-news --clear-db
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import sys
import time
from pathlib import Path
from typing import Any

# Path setup
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# ─────────────────────────────────────────────────────────────────────────────
# Phase indicators
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# Infrastructure Setup
# ─────────────────────────────────────────────────────────────────────────────


async def setup_infrastructure(
    use_strategy: bool = False,
    clear_db: bool = False,
) -> dict[str, Any]:
    """Initialize all infrastructure components.

    Args:
        use_strategy: If True, use strategy pattern for DB failover.
        clear_db: If True, clear databases before testing.

    Returns:
        Dictionary with initialized components.
    """
    from config.settings import Settings
    from core.cache.redis import CashewsRedisFallback
    from core.db.duckdb_pool import DuckDBPool
    from core.db.ladybug_pool import LadybugPool
    from core.event.bus import EventBus, LLMUsageEvent
    from core.llm.client import LLMClient
    from core.observability.logging import get_logger
    from core.prompt.loader import PromptLoader
    from modules.processing.nlp.spacy_extractor import SpacyExtractor
    from modules.storage.duckdb.schema import initialize_duckdb_schema
    from modules.storage.ladybug.schema import initialize_ladybug_schema

    log = get_logger("test_pipeline")
    settings = Settings()

    phase_header("PHASE 0: Infrastructure Initialization")
    components: dict[str, Any] = {"settings": settings, "log": log}

    if use_strategy:
        # Use strategy pattern for database failover
        from core.db.strategy import create_strategy

        strategy = await create_strategy(
            pg_settings=settings.postgres,
            neo4j_settings=settings.neo4j,
            duckdb_settings=settings.duckdb,
            ladybug_settings=settings.ladybug,
        )

        components["strategy"] = strategy
        components["relational_pool"] = strategy.relational_pool
        components["graph_pool"] = strategy.graph_pool
        components["relational_type"] = strategy.relational_type
        components["graph_type"] = strategy.graph_type

        step(f"Relational: {strategy.relational_type}", True)
        step(f"Graph: {strategy.graph_type}", True)

        duck_pool = strategy.relational_pool
        ladybug_pool = strategy.graph_pool
    else:
        # Direct DuckDB + LadybugDB setup
        os.environ.setdefault("POSTGRES_ENABLED", "false")
        os.environ.setdefault("NEO4J_ENABLED", "false")
        os.environ.setdefault("DUCKDB_ENABLED", "true")
        os.environ.setdefault("LADYBUG_ENABLED", "true")

        duckdb_path = settings.duckdb.db_path
        duck_pool = DuckDBPool(db_path=duckdb_path)
        await duck_pool.startup()
        await initialize_duckdb_schema(duck_pool)
        step("DuckDB pool started", True, str(duckdb_path))

        ladybug_path = settings.ladybug.db_path
        ladybug_pool = LadybugPool(db_path=ladybug_path)
        await ladybug_pool.startup()
        await initialize_ladybug_schema(ladybug_pool)
        step("LadybugDB pool started", True, str(ladybug_path))

        components["relational_pool"] = duck_pool
        components["graph_pool"] = ladybug_pool
        components["relational_type"] = "duckdb"
        components["graph_type"] = "ladybug"

    # Redis fallback
    redis_client = CashewsRedisFallback()
    await redis_client.startup()
    step("CashewsRedisFallback started", True, "mem://")
    components["redis_client"] = redis_client

    # EventBus
    event_bus = EventBus()
    step("EventBus created", True)
    components["event_bus"] = event_bus

    # LLM client
    prompt_dir = settings.prompt.dir
    prompt_loader = PromptLoader(prompt_dir)
    config_path = Path(__file__).parent.parent / "config" / "llm.toml"
    llm_client = await LLMClient.create_from_config(
        config_path=str(config_path),
        prompt_loader=prompt_loader,
        redis_client=redis_client,
        event_bus=event_bus,
    )
    step("LLM client initialized", True)
    components["llm_client"] = llm_client
    components["prompt_loader"] = prompt_loader

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
    components["spacy"] = spacy

    # Repositories
    from modules.storage.duckdb.article_repo import DuckDBArticleRepo
    from modules.storage.duckdb.source_authority_repo import DuckDBSourceAuthorityRepo
    from modules.storage.duckdb.vector_repo import DuckDBVectorRepo
    from modules.storage.ladybug.entity_repo import LadybugEntityRepo
    from modules.storage.ladybug.writer import LadybugWriter

    article_repo = DuckDBArticleRepo(duck_pool)
    vector_repo = DuckDBVectorRepo(duck_pool)
    source_auth_repo = DuckDBSourceAuthorityRepo(duck_pool)
    step("DuckDB repos created", True)

    ladybug_writer = LadybugWriter(ladybug_pool) if ladybug_pool else None
    ladybug_entity_repo = LadybugEntityRepo(ladybug_pool) if ladybug_pool else None
    step("LadybugDB repos created", bool(ladybug_pool))

    components["article_repo"] = article_repo
    components["vector_repo"] = vector_repo
    components["source_auth_repo"] = source_auth_repo
    components["ladybug_writer"] = ladybug_writer
    components["ladybug_entity_repo"] = ladybug_entity_repo

    # EntityResolver
    from modules.knowledge.graph.entity_resolver import EntityResolver
    from modules.knowledge.graph.name_normalizer import NameNormalizer
    from modules.knowledge.graph.resolution_rules import EntityResolutionRules

    name_normalizer = NameNormalizer()
    resolution_rules = EntityResolutionRules()
    entity_resolver = (
        EntityResolver(
            entity_repo=ladybug_entity_repo,
            vector_repo=vector_repo,
            llm=llm_client,
            resolution_rules=resolution_rules,
            name_normalizer=name_normalizer,
        )
        if ladybug_entity_repo
        else None
    )
    step("EntityResolver created", bool(entity_resolver))
    components["entity_resolver"] = entity_resolver

    # Clear databases if requested
    if clear_db:
        await clear_databases(duck_pool, ladybug_pool)

    return components


async def clear_databases(duck_pool, ladybug_pool) -> None:
    """Clear all data from test databases."""
    import sqlalchemy

    phase_header("PHASE: Clear Databases")

    # Clear DuckDB tables
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

    async with duck_pool.session_context() as session:
        for table in tables:
            with contextlib.suppress(Exception):
                await session.execute(sqlalchemy.text(f"DELETE FROM {table}"))
        await session.commit()
    step("DuckDB tables cleared", True)

    # Clear LadybugDB nodes
    if ladybug_pool:
        with contextlib.suppress(Exception):
            await ladybug_pool.execute_query("MATCH ()-[r]->() DELETE r")
            await ladybug_pool.execute_query("MATCH (n) DELETE n")
        step("LadybugDB nodes cleared", True)


# ─────────────────────────────────────────────────────────────────────────────
# Data Fetching
# ─────────────────────────────────────────────────────────────────────────────


async def fetch_newsnow_data(max_items: int, source_id: str = "36kr") -> list:
    """Fetch articles from NewsNow API and crawl article bodies.

    Args:
        max_items: Maximum number of articles to fetch.
        source_id: NewsNow source ID (e.g., 36kr, hupu, baidu).
    """
    from modules.ingestion.crawling.crawler import Crawler
    from modules.ingestion.domain.models import SourceConfig
    from modules.ingestion.fetching.crawl4ai_fetcher import Crawl4AIFetcher
    from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher
    from modules.ingestion.fetching.smart_fetcher import SmartFetcher
    from modules.ingestion.parsing.newsnow_parser import NewsNowParser

    phase_header("PHASE: NewsNow Fetch & Parse")

    # Create fetchers for body crawling
    httpx_fetcher = HttpxFetcher(timeout=15.0)
    crawl4ai_fetcher = Crawl4AIFetcher(headless=True, stealth_enabled=True)
    smart_fetcher = SmartFetcher(
        httpx_fetcher=httpx_fetcher,
        crawl4ai_fetcher=crawl4ai_fetcher,
    )
    crawler = Crawler(smart_fetcher=smart_fetcher)

    # Use separate fetcher for API calls
    api_fetcher = HttpxFetcher(timeout=15.0)
    parser = NewsNowParser(api_fetcher)

    source_config = SourceConfig(
        id=f"test-newsnow-{source_id}",
        name=f"NewsNow {source_id}",
        url=f"https://www.newsnow.world/api/s?id={source_id}",
        source_type="newsnow",
        credibility=0.50,
        tier=2,
    )

    news_items = await parser.parse(source_config)
    step(f"Fetched {len(news_items)} items", len(news_items) > 0)

    await api_fetcher.close()

    if not news_items:
        await parser.close()
        await smart_fetcher.close()
        return []

    # Limit items
    news_items = news_items[:max_items]
    step(f"Limited to {max_items} articles", True)

    # Crawl article bodies using Crawler with SmartFetcher
    step(f"Crawling article bodies...", True)
    results = await crawler.crawl_batch(news_items)

    # Filter successful crawls
    from modules.ingestion.domain.models import ArticleRaw
    from modules.ingestion.fetching.exceptions import FetchError

    raw_articles = []
    for result in results:
        if isinstance(result, ArticleRaw):
            raw_articles.append(result)
        elif isinstance(result, FetchError):
            print(f"  ⚠ Failed to crawl: {result.url} - {result.message}")

    step(f"Crawled {len(raw_articles)} articles with bodies", len(raw_articles) > 0)

    await smart_fetcher.close()
    return raw_articles


async def fetch_rss_data(source: str, max_items: int) -> list:
    """Fetch articles from RSS feed."""
    from modules.ingestion.domain.models import ArticleRaw, SourceConfig
    from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher
    from modules.ingestion.parsing.rss_parser import RSSParser

    phase_header("PHASE: RSS Fetch & Parse")

    # RSS source configurations
    rss_sources = {
        "solidot": {
            "url": "https://www.solidot.org/index.rss",
            "name": "Solidot",
            "credibility": 0.70,
        },
        "cnbeta": {
            "url": "https://plink.anyfeeder.com/cnbeta",
            "name": "CNBeta",
            "credibility": 0.70,
        },
        "huxiu": {
            "url": "https://plink.anyfeeder.com/huxiu",
            "name": "Huxiu",
            "credibility": 0.70,
        },
    }

    if source not in rss_sources:
        print(f"Unknown RSS source: {source}. Available: {list(rss_sources.keys())}")
        return []

    src_config = rss_sources[source]

    fetcher = HttpxFetcher(timeout=15.0)
    parser = RSSParser(fetcher)

    source_config = SourceConfig(
        id=f"test-rss-{source}",
        name=src_config["name"],
        url=src_config["url"],
        source_type="rss",
        credibility=src_config["credibility"],
        tier=2,
    )

    news_items = await parser.parse(source_config)
    step(f"Fetched {len(news_items)} items", len(news_items) > 0, src_config["url"])

    if not news_items:
        await parser.close()
        return []

    # Limit items
    news_items = news_items[:max_items]
    step(f"Limited to {max_items} articles", True)

    # Convert to ArticleRaw
    raw_articles = []
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

    await parser.close()
    step(f"Converted to ArticleRaw", True, f"{len(raw_articles)} articles")
    return raw_articles


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline Execution
# ─────────────────────────────────────────────────────────────────────────────


async def run_pipeline(
    components: dict[str, Any],
    raw_articles: list,
    force_news: bool = False,
) -> list:
    """Run the processing pipeline on raw articles."""
    from modules.knowledge.core.relation_types import RelationTypeNormalizer
    from modules.processing.pipeline.graph import Pipeline

    phase_header("PHASE: Pipeline Execution")

    rt_normalizer = RelationTypeNormalizer(components["relational_pool"])
    step("RelationTypeNormalizer created", True)

    pipeline = Pipeline(
        llm=components["llm_client"],
        budget=__import__(
            "core.llm.token_budget", fromlist=["TokenBudgetManager"]
        ).TokenBudgetManager(),
        prompt_loader=components["prompt_loader"],
        event_bus=components["event_bus"],
        spacy=components["spacy"],
        vector_repo=components["vector_repo"],
        article_repo=components["article_repo"],
        neo4j_writer=components["ladybug_writer"],
        source_auth_repo=components["source_auth_repo"],
        entity_resolver=components["entity_resolver"],
        redis_client=components["redis_client"],
        community_updater=None,  # LadybugDB doesn't support community detection
        relation_type_normalizer=rt_normalizer,
    )
    step("Pipeline constructed", True)

    states = await pipeline.process_batch(raw_articles)
    step("process_batch completed", True, f"{len(states)} results")

    # Force news mode if requested
    if force_news:
        forced_count = 0
        for state in states:
            if isinstance(state, dict) and state.get("terminal"):
                state["is_news"] = True
                state["terminal"] = False
                forced_count += 1
        if forced_count > 0:
            step(f"FORCE_NEWS: Forced {forced_count} articles", True)
            with contextlib.suppress(Exception):
                await pipeline._persist_batch(states)
                step("Persist completed on forced articles", True)

    # Report results
    success_count = 0
    for i, state in enumerate(states):
        if isinstance(state, dict):
            terminal = state.get("terminal", False)
            if not terminal:
                success_count += 1
            title = state.get("raw", None)
            title_str = title.title[:40] if hasattr(title, "title") else "?"
            is_news = state.get("is_news", "?")
            step(
                f"Article {i}: {title_str}", not terminal, f"terminal={terminal}, is_news={is_news}"
            )

    step(f"Success rate: {success_count}/{len(states)}", success_count > 0)
    return states


# ─────────────────────────────────────────────────────────────────────────────
# Verification
# ─────────────────────────────────────────────────────────────────────────────


async def verify_results(components: dict[str, Any], states: list) -> dict[str, Any]:
    """Verify data was stored correctly."""
    import sqlalchemy

    phase_header("PHASE: Verification")

    results = {}
    duck_pool = components["relational_pool"]
    ladybug_pool = components["graph_pool"]

    # DuckDB verification
    try:
        async with duck_pool.session_context() as session:
            result = await session.execute(sqlalchemy.text("SELECT count(*) FROM articles"))
            article_count = result.scalar()
            step("articles table", article_count > 0, f"{article_count} rows")
            results["duckdb_articles"] = article_count
    except Exception as e:
        step("articles table query failed", False, str(e))
        results["duckdb_articles"] = 0

    try:
        async with duck_pool.session_context() as session:
            result = await session.execute(sqlalchemy.text("SELECT count(*) FROM article_vectors"))
            vec_count = result.scalar()
            step("article_vectors table", vec_count > 0, f"{vec_count} rows")
            results["duckdb_vectors"] = vec_count
    except Exception:
        results["duckdb_vectors"] = 0

    # LadybugDB verification
    if ladybug_pool:
        try:
            articles_in_graph = await ladybug_pool.execute_query(
                "MATCH (a:Article) RETURN count(a) AS cnt"
            )
            cnt = articles_in_graph[0]["cnt"] if articles_in_graph else 0
            step("Article nodes in graph", cnt > 0, f"{cnt} nodes")
            results["ladybug_articles"] = cnt
        except Exception as e:
            step("LadybugDB query failed", False, str(e))
            results["ladybug_articles"] = 0

        try:
            entities_in_graph = await ladybug_pool.execute_query(
                "MATCH (e:Entity) RETURN count(e) AS cnt"
            )
            cnt = entities_in_graph[0]["cnt"] if entities_in_graph else 0
            step("Entity nodes in graph", True, f"{cnt} nodes")
            results["ladybug_entities"] = cnt
        except Exception:
            results["ladybug_entities"] = 0

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Cleanup
# ─────────────────────────────────────────────────────────────────────────────


async def cleanup(components: dict[str, Any]) -> None:
    """Clean up resources."""
    phase_header("PHASE: Cleanup")

    if "relational_pool" in components:
        await components["relational_pool"].shutdown()
        step("Relational pool closed", True)

    if components.get("graph_pool"):
        await components["graph_pool"].shutdown()
        step("Graph pool closed", True)

    if "redis_client" in components:
        await components["redis_client"].shutdown()
        step("Redis client closed", True)


# ─────────────────────────────────────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────────────────────────────────────


async def main(args: argparse.Namespace) -> int:
    """Main entry point."""
    print("=" * 60)
    print(f"Pipeline Test: {args.mode.upper()} mode")
    print("=" * 60)

    start_time = time.time()

    try:
        # Setup infrastructure
        components = await setup_infrastructure(
            use_strategy=(args.mode == "strategy"),
            clear_db=args.clear_db,
        )

        # Fetch data based on mode
        if args.mode == "newsnow":
            raw_articles = await fetch_newsnow_data(args.max_items, args.source_id)
        elif args.mode == "rss":
            raw_articles = await fetch_rss_data(args.source, args.max_items)
        elif args.mode == "strategy":
            # Use NewsNow for strategy mode
            raw_articles = await fetch_newsnow_data(args.max_items, args.source_id)
        else:
            print(f"Unknown mode: {args.mode}")
            return 1

        if not raw_articles:
            print("No articles fetched. Test cannot proceed.")
            await cleanup(components)
            return 1

        # Run pipeline
        states = await run_pipeline(components, raw_articles, args.force_news)

        # Verify results
        results = await verify_results(components, states)

        # Cleanup
        await cleanup(components)

        # Summary
        elapsed = time.time() - start_time
        phase_header("SUMMARY")
        print(f"  Elapsed: {elapsed:.1f}s")
        print(f"  Articles processed: {len(states)}")
        print(f"  DuckDB articles: {results.get('duckdb_articles', 0)}")
        print(f"  LadybugDB articles: {results.get('ladybug_articles', 0)}")

        success_count = sum(1 for s in states if isinstance(s, dict) and not s.get("terminal"))
        if success_count > 0:
            print(f"\n  Pipeline test PASSED")
            return 0
        else:
            print(f"\n  Pipeline test FAILED — no articles processed successfully")
            return 1

    except Exception as e:
        print(f"\n  ERROR: {e}")
        __import__("traceback").print_exc()
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Unified pipeline test script for Weaver",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # NewsNow mode (default)
    uv run scripts/test_pipeline.py --mode newsnow --max-items 5

    # NewsNow with custom source
    uv run scripts/test_pipeline.py --mode newsnow --source-id hupu --max-items 5

    # RSS mode
    uv run scripts/test_pipeline.py --mode rss --source solidot --max-items 2

    # Strategy mode (test database failover)
    uv run scripts/test_pipeline.py --mode strategy

    # Force all articles as news
    uv run scripts/test_pipeline.py --force-news --clear-db
        """,
    )
    parser.add_argument(
        "--mode",
        choices=["newsnow", "rss", "strategy"],
        default="newsnow",
        help="Test mode: newsnow (default), rss, or strategy",
    )
    parser.add_argument(
        "--source",
        default="solidot",
        help="RSS source name (default: solidot). Available: solidot, cnbeta, huxiu",
    )
    parser.add_argument(
        "--source-id",
        default="36kr",
        help="NewsNow source ID (default: 36kr). Examples: 36kr, hupu, baidu",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=5,
        help="Maximum articles to process (default: 5)",
    )
    parser.add_argument(
        "--force-news",
        action="store_true",
        help="Force all articles to be treated as news",
    )
    parser.add_argument(
        "--clear-db",
        action="store_true",
        help="Clear databases before testing",
    )

    args = parser.parse_args()
    exit_code = asyncio.run(main(args))
    sys.exit(exit_code)
