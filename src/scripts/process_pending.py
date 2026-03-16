#!/usr/bin/env python
"""Script to process pending articles from the database."""

import asyncio
from config.settings import Settings
from core.db.postgres import PostgresPool
from core.cache.redis import RedisClient
from core.llm.config_manager import LLMConfigManager
from core.llm.token_budget import TokenBudgetManager
from core.llm.queue_manager import LLMQueueManager
from core.event.bus import EventBus
from core.llm.client import LLMClient
from core.prompt.loader import PromptLoader
from modules.storage.article_repo import ArticleRepo
from modules.storage.vector_repo import VectorRepo
from modules.collector.models import ArticleRaw
from modules.graph_store.neo4j_writer import Neo4jWriter
from modules.storage.source_authority_repo import SourceAuthorityRepo
from modules.nlp.spacy_extractor import SpacyExtractor


async def main():
    print("Starting article processing...")

    # Initialize settings
    settings = Settings()

    # Initialize PostgreSQL
    pool = PostgresPool(settings.postgres.dsn)
    await pool.startup()

    # Initialize Redis
    redis = RedisClient(settings.redis.url)
    await redis.startup()

    # Initialize LLM
    from core.llm.rate_limiter_pro import RateLimiter as ProRateLimiter
    
    config_manager = LLMConfigManager(settings.llm)
    rate_limiter = ProRateLimiter(storage_type="memory", redis_url=None)
    await rate_limiter.initialize()
    
    for name, cfg in config_manager.list_providers():
        if cfg.rpm_limit > 0:
            rate_limiter.set_rate_limit(name, f"{cfg.rpm_limit}/minute")
    
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

    # Initialize repos
    article_repo = ArticleRepo(pool)
    vector_repo = VectorRepo(pool)
    source_authority_repo = SourceAuthorityRepo(pool)

    # Get Neo4j writer (optional - may fail if Neo4j not available)
    neo4j_writer = None
    try:
        from core.db.neo4j import Neo4jPool
        neo4j_pool = Neo4jPool(settings.neo4j.uri, ("neo4j", settings.neo4j.password))
        await neo4j_pool.startup()
        neo4j_writer = Neo4jWriter(neo4j_pool)
    except Exception as e:
        print(f"  ⚠ Neo4j not available: {e}")

    # Process pending articles
    print(f"\n[5/7] Processing pending articles...")
    from modules.pipeline.graph import Pipeline
    pipeline = Pipeline(
        llm=llm_client,
        article_repo=article_repo,
        vector_repo=vector_repo,
        source_authority_repo=source_authority_repo,
        neo4j_writer=neo4j_writer,
        extractor=SpacyExtractor(),
    )
    
    pending = await article_repo.list_pending(limit=10)
    print(f"  Found {len(pending)} pending articles")
    
    for article in pending:
        print(f"  Processing: {article.title[:50]}...")
        try:
            from modules.pipeline.types import PipelineState
            state = PipelineState(
                raw=article,
                cleaned={"title": article.title, "body": article.body or ""},
            )
            await pipeline.process_single(state)
            print(f"    ✓ Done")
        except Exception as e:
            print(f"    ✗ Error: {e}")

    # Cleanup
    print("\n[6/7] Shutting down...")
    await pool.shutdown()
    await redis.shutdown()
    print("✓ Done!")


if __name__ == "__main__":
    asyncio.run(main())
