#!/usr/bin/env python3
# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Test full pipeline with DuckDB + LadybugDB (no PostgreSQL/Neo4j).

Usage:
    uv run python scripts/test_pipeline_duckdb_ladybug.py

Prerequisites:
    - Redis running (required for dedup/rate-limiting)
    - LLM API keys configured in config/llm.toml
    - DuckDB and LadybugDB packages installed
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


async def main() -> None:
    """Run the full pipeline test with DuckDB + LadybugDB."""
    from core.observability.logging import get_logger

    log = get_logger("pipeline_test")

    print("=" * 60)
    print("Weaver Pipeline Test: DuckDB + LadybugDB Mode")
    print("=" * 60)
    print()

    # ── Step 1: Initialize settings ──────────────────────────────
    print("[1/7] Initializing settings...")
    from config.settings import Settings

    settings = Settings()

    # Force disable PostgreSQL and Neo4j
    print(
        f"  PostgreSQL: {settings.postgres.host}:{settings.postgres.port} (will be tried, expect failover)"
    )
    print(f"  Neo4j: {settings.neo4j.uri} (will be tried, expect failover)")
    print(f"  Redis: {settings.redis.host}:{settings.redis.port}")
    print(f"  DuckDB path: {settings.duckdb.db_path}")
    print(f"  LadybugDB path: {settings.ladybug.db_path}")
    print()

    # ── Step 2: Create database strategy ─────────────────────────
    print("[2/7] Creating database strategy (expect failover to DuckDB/LadybugDB)...")
    from core.db.strategy import create_strategy

    strategy = await create_strategy(
        pg_settings=settings.postgres,
        neo4j_settings=settings.neo4j,
        duckdb_settings=settings.duckdb,
        ladybug_settings=settings.ladybug,
    )
    print(f"  Relational: {strategy.relational_type}")
    print(f"  Graph: {strategy.graph_type}")

    if strategy.relational_type != "duckdb":
        print("  ERROR: Expected DuckDB fallback!")
        return
    if strategy.graph_type != "ladybug":
        print("  ERROR: Expected LadybugDB fallback!")
        return
    print("  OK: DuckDB + LadybugDB active")
    print()

    # ── Step 3: Initialize Redis ─────────────────────────────────
    print("[3/7] Initializing Redis...")
    from core.cache.redis import RedisClient

    redis_client = RedisClient(settings.redis.url)
    await redis_client.startup()
    print("  OK: Redis connected")
    print()

    # ── Step 4: Initialize LLM client ────────────────────────────
    print("[4/7] Initializing LLM client...")
    from core.llm.client import LLMClient
    from core.prompt import PromptLoader

    prompt_loader = PromptLoader(settings.prompt.dir)
    llm_client = await LLMClient.create_from_config(
        config_path=str(Path(__file__).parent.parent / "config" / "llm.toml"),
        prompt_loader=prompt_loader,
        redis_client=redis_client,
    )
    print("  OK: LLM client initialized")
    print()

    # ── Step 5: Initialize repositories ──────────────────────────
    print("[5/7] Initializing repositories...")
    from modules.storage.duckdb import (
        DuckDBArticleRepo,
        DuckDBPendingSyncRepo,
        DuckDBSourceAuthorityRepo,
        DuckDBVectorRepo,
    )
    from modules.storage.ladybug import (
        LadybugArticleRepo,
        LadybugEntityRepo,
    )
    from modules.storage.ladybug.writer import LadybugWriter

    article_repo = DuckDBArticleRepo(strategy.relational_pool)
    vector_repo = DuckDBVectorRepo(strategy.relational_pool)
    source_auth_repo = DuckDBSourceAuthorityRepo(strategy.relational_pool)
    pending_sync_repo = DuckDBPendingSyncRepo(strategy.relational_pool)
    print("  OK: DuckDB repos initialized")

    if strategy.graph_pool is not None:
        ladybug_entity_repo = LadybugEntityRepo(strategy.graph_pool)
        ladybug_article_repo = LadybugArticleRepo(strategy.graph_pool)
        ladybug_writer = LadybugWriter(strategy.graph_pool)
        print("  OK: LadybugDB repos initialized")
    else:
        print("  WARN: No graph pool available")
        ladybug_writer = None
    print()

    # ── Step 6: Fetch data from newsnow ──────────────────────────
    print("[6/7] Fetching data from newsnow...")
    from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

    fetcher = HttpxFetcher(timeout=15.0)
    test_url = "https://www.newsnow.world/api/s?id=36kr"

    status, body, _headers = await fetcher.fetch(test_url)
    print(f"  HTTP {status}, body length: {len(body)} bytes")

    if status != 200 or not body:
        print("  ERROR: Failed to fetch data!")
        await cleanup(strategy, redis_client)
        return

    # Parse newsnow response
    import json

    data = json.loads(body)
    items = data.get("items", data.get("newsList", []))
    if not items:
        print("  WARN: No items found in response")
        print(f"  Response keys: {list(data.keys())}")
        print(f"  Sample: {json.dumps(data, ensure_ascii=False)[:500]}")
        await cleanup(strategy, redis_client)
        return

    print(f"  OK: Found {len(items)} items")
    # Show first 3 items
    for i, item in enumerate(items[:3]):
        title = item.get("title", item.get("name", "unknown"))
        url = item.get("url", item.get("sourceUrl", ""))
        print(f"    [{i + 1}] {title[:60]}... | {url[:60]}")
    print()

    # ── Step 7: Run pipeline ─────────────────────────────────────
    print("[7/7] Running pipeline...")
    from core.event import EventBus
    from core.llm.token_budget import TokenBudgetManager

    # Build raw articles from newsnow items
    from modules.ingestion.domain.models import ArticleRaw
    from modules.processing.nlp.spacy_extractor import SpacyExtractor
    from modules.processing.pipeline.graph import Pipeline

    raw_articles: list[ArticleRaw] = []
    for item in items[:5]:  # Limit to 5 items for testing
        title = item.get("title", item.get("name", ""))
        url = item.get("url", item.get("sourceUrl", ""))
        body_text = item.get("description", item.get("summary", ""))
        if not title or not url:
            continue
        raw_articles.append(
            ArticleRaw(
                title=title,
                url=url,
                body=body_text or "",
                source="newsnow:hupu",
                source_host=urlparse(url).hostname or "",
            )
        )

    if not raw_articles:
        print("  WARN: No valid articles to process")
        await cleanup(strategy, redis_client)
        return

    print(f"  Processing {len(raw_articles)} articles through pipeline...")
    print()

    # Create pipeline
    event_bus = EventBus()
    budget = TokenBudgetManager()
    spacy = SpacyExtractor()

    pipeline = Pipeline(
        llm=llm_client,
        budget=budget,
        prompt_loader=prompt_loader,
        event_bus=event_bus,
        spacy=spacy,
        vector_repo=vector_repo,
        article_repo=article_repo,
        neo4j_writer=ladybug_writer,
        source_auth_repo=source_auth_repo,
        entity_resolver=None,  # Entity resolver needs graph pool
        redis_client=redis_client,
        community_updater=None,  # Community updater needs Neo4j
        phase1_concurrency=2,
        phase3_concurrency=2,
    )

    start_time = time.time()

    try:
        results = await pipeline.process_batch(raw_articles)
        elapsed = time.time() - start_time

        print()
        print("=" * 60)
        print("Pipeline Results")
        print("=" * 60)
        print(f"  Total time: {elapsed:.1f}s")
        print(f"  Input articles: {len(raw_articles)}")
        print(f"  Processed: {len(results)}")
        print()

        # Show results per article
        for i, result in enumerate(results):
            title = result.get("title", "unknown")[:50]
            stage = result.get("processing_stage", "unknown")
            is_news = result.get("is_news", False)
            category = result.get("category", "N/A")
            print(f"  [{i + 1}] '{title}...'")
            print(f"      is_news={is_news}, category={category}, stage={stage}")

        # Verify data in DuckDB
        print()
        print("  Verifying DuckDB storage...")
        from sqlalchemy import text

        async with strategy.relational_pool.session_context() as session:
            result = await session.execute(text("SELECT COUNT(*) FROM articles"))
            count = result.scalar()
            print(f"    Total articles in DuckDB: {count}")

            result = await session.execute(
                text(
                    "SELECT id, title, category, is_news FROM articles ORDER BY created_at DESC LIMIT 5"
                )
            )
            rows = result.fetchall()
            for row in rows:
                print(f"    - {row[1][:40]}... | cat={row[2]} | news={row[3]}")

        # Verify LadybugDB storage
        if strategy.graph_pool is not None:
            print()
            print("  Verifying LadybugDB storage...")
            try:
                entities = await strategy.graph_pool.execute_query(
                    "MATCH (e:Entity) RETURN e.canonical_name AS name, e.type AS type LIMIT 10"
                )
                print(f"    Total entities: {len(entities)}")
                for e in entities:
                    print(f"    - {e.get('name', 'N/A')} ({e.get('type', 'N/A')})")
            except Exception as exc:
                print(f"    Query error: {exc}")

        print()
        print("=" * 60)
        print("Pipeline test COMPLETE")
        print("=" * 60)

    except Exception as exc:
        elapsed = time.time() - start_time
        print(f"\n  ERROR after {elapsed:.1f}s: {exc}")
        import traceback

        traceback.print_exc()

    # Cleanup
    await cleanup(strategy, redis_client)


async def cleanup(strategy, redis_client) -> None:
    """Clean up resources."""
    print()
    print("Cleaning up...")
    await redis_client.shutdown()
    await strategy.relational_pool.shutdown()
    if strategy.graph_pool is not None:
        await strategy.graph_pool.shutdown()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
