#!/usr/bin/env python
"""Run full pipeline: RSS fetch -> Process -> Store."""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import datetime, timezone
from config.settings import Settings
from core.db.postgres import PostgresPool
from core.cache.redis import RedisClient
from core.llm.config_manager import LLMConfigManager
from core.llm.token_budget import TokenBudgetManager
from core.llm.queue_manager import LLMQueueManager
from core.llm.rate_limiter import RedisTokenBucket
from core.llm.client import LLMClient
from core.prompt.loader import PromptLoader
from core.event.bus import EventBus
from modules.storage.article_repo import ArticleRepo
from modules.storage.vector_repo import VectorRepo
from modules.storage.source_authority_repo import SourceAuthorityRepo
from modules.pipeline.graph import Pipeline
from modules.collector.models import ArticleRaw
from modules.graph_store.neo4j_writer import Neo4jWriter
from modules.nlp.spacy_extractor import SpacyExtractor
from core.db.neo4j import Neo4jPool
from core.observability.logging import get_logger

log = get_logger("run_pipeline")

RSS_FEEDS = [
    {"url": "https://hnrss.org/frontpage", "name": "Hacker News", "tier": 2},
]


def get_test_articles() -> list[ArticleRaw]:
    return [
        ArticleRaw(
            url="https://example.com/test/1",
            title="OpenAI发布GPT-5，性能大幅提升",
            body="OpenAI今日发布了最新的大型语言模型GPT-5，该模型在多项基准测试中表现出色，推理能力显著提升。专家认为这将是人工智能领域的重大突破。",
            source="Test News",
            source_host="example.com",
            tier=2,
        ),
        ArticleRaw(
            url="https://example.com/test/2",
            title="苹果公司市值突破3万亿美元",
            body="苹果公司股价今日大涨，市值首次突破3万亿美元大关，成为全球首家达到这一里程碑的公司。分析师预计苹果将继续保持增长势头。",
            source="Test News",
            source_host="example.com",
            tier=2,
        ),
        ArticleRaw(
            url="https://example.com/test/3",
            title="中国成功发射新一代载人飞船",
            body="中国航天局今日宣布，成功发射了新一代载人飞船，这是中国航天事业的又一重要里程碑。飞船将进行为期一个月的在轨测试。",
            source="Test News",
            source_host="example.com",
            tier=2,
        ),
    ]


async def fetch_rss_feed(url: str) -> list[dict]:
    import feedparser
    import httpx
    
    log.info("fetching_rss_feed", url=url)
    
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        try:
            response = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; Weaver/1.0)"})
            feed = feedparser.parse(response.text)
            
            items = []
            for entry in feed.entries[:10]:
                link = entry.get("link", "")
                if not link:
                    continue
                items.append({
                    "url": link,
                    "title": entry.get("title", "Untitled"),
                    "body": entry.get("summary", entry.get("description", "")),
                    "source_host": link.split("/")[2] if "/" in link else url,
                })
            
            log.info("rss_feed_parsed", url=url, items=len(items))
            return items
        except Exception as e:
            log.error("rss_fetch_failed", url=url, error=str(e))
            return []


async def main():
    print("=" * 60)
    print("Weaver Pipeline - Full Flow Test")
    print("=" * 60)
    
    settings = Settings()
    
    print("\n[1/7] Initializing PostgreSQL...")
    pg_pool = PostgresPool(settings.postgres.dsn)
    await pg_pool.startup()
    print("  ✓ PostgreSQL connected")
    
    print("\n[2/7] Initializing Redis...")
    redis = RedisClient(settings.redis.url)
    await redis.startup()
    print("  ✓ Redis connected")
    
    print("\n[3/7] Initializing LLM...")
    config_manager = LLMConfigManager(settings.llm)
    rate_limiter = RedisTokenBucket(redis=redis._redis)
    event_bus = EventBus()
    queue_manager = LLMQueueManager(
        config_manager=config_manager,
        rate_limiter=rate_limiter,
        event_bus=event_bus,
    )
    await queue_manager.startup()
    
    prompt_loader = PromptLoader(settings.prompt.dir)
    token_budget = TokenBudgetManager()
    
    llm_client = LLMClient(
        queue_manager=queue_manager,
        prompt_loader=prompt_loader,
        token_budget=token_budget,
    )
    print("  ✓ LLM client ready")
    
    print("\n[4/7] Initializing Neo4j...")
    neo4j_writer = None
    try:
        neo4j_pool = Neo4jPool(settings.neo4j.uri, ("neo4j", settings.neo4j.password))
        await neo4j_pool.startup()
        neo4j_writer = Neo4jWriter(neo4j_pool)
        print("  ✓ Neo4j connected")
    except Exception as e:
        print(f"  ⚠ Neo4j not available: {e}")
    
    print("\n[5/7] Initializing repositories...")
    article_repo = ArticleRepo(pg_pool)
    vector_repo = VectorRepo(pg_pool)
    source_auth_repo = SourceAuthorityRepo(pg_pool)
    spacy_extractor = SpacyExtractor()
    print("  ✓ Repositories ready")
    
    print("\n[6/7] Initializing Pipeline...")
    pipeline = Pipeline(
        llm=llm_client,
        budget=token_budget,
        prompt_loader=prompt_loader,
        event_bus=event_bus,
        spacy=spacy_extractor,
        vector_repo=vector_repo,
        article_repo=article_repo,
        neo4j_writer=neo4j_writer,
        source_auth_repo=source_auth_repo,
    )
    print("  ✓ Pipeline ready")
    
    print("\n[7/7] Fetching RSS feeds...")
    all_articles = []
    
    for feed in RSS_FEEDS:
        items = await fetch_rss_feed(feed["url"])
        for item in items:
            all_articles.append(ArticleRaw(
                url=item["url"],
                title=item["title"],
                body=item["body"],
                source=feed["name"],
                source_host=item["source_host"],
                tier=feed["tier"],
            ))
    
    print(f"\n  RSS articles fetched: {len(all_articles)}")
    
    if not all_articles:
        print("\n  Using test articles as fallback...")
        all_articles = get_test_articles()
        print(f"  Test articles loaded: {len(all_articles)}")
    
    if not all_articles:
        print("\n⚠ No articles to process!")
        await pg_pool.shutdown()
        await redis.shutdown()
        return
    
    print("\n" + "=" * 60)
    print("Processing articles through Pipeline...")
    print("=" * 60)
    
    try:
        results = await pipeline.process_batch(all_articles[:10])
        
        success = sum(1 for r in results if not r.get("terminal", False))
        terminal = len(results) - success
        
        print(f"\n{'=' * 60}")
        print("Pipeline Results:")
        print(f"  Total processed: {len(results)}")
        print(f"  Success: {success}")
        print(f"  Terminal (filtered out): {terminal}")
        print("=" * 60)
        
        for i, result in enumerate(results[:5]):
            status = "✓" if not result.get("terminal") else "✗"
            raw = result.get("raw")
            title = raw.title if raw else (result.get("cleaned", {}).get("title", "N/A") or "N/A")[:50]
            category = result.get("category", "N/A")
            print(f"  {status} [{i+1}] {title}... | {category}")
        
    except Exception as e:
        print(f"\n✗ Pipeline error: {e}")
        import traceback
        traceback.print_exc()
    
    print("\nShutting down...")
    await pg_pool.shutdown()
    await redis.shutdown()
    print("\n✓ Done!")


if __name__ == "__main__":
    asyncio.run(main())
