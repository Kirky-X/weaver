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
from core.llm.rate_limiter import RedisTokenBucket
from core.llm.client import LLMClient
from core.prompt.loader import PromptLoader
from modules.storage.article_repo import ArticleRepo
from modules.storage.vector_repo import VectorRepo
from modules.pipeline.graph import Pipeline
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

    # Initialize repos
    article_repo = ArticleRepo(pool)
    vector_repo = VectorRepo(pool)
    source_authority_repo = SourceAuthorityRepo(pool)

    # Get Neo4j writer (optional - may fail if Neo4j not available)
    neo4j_writer = None
    try:
        from core.db.neo4j import Neo4jPool
        neo4j_pool = Neo4jPool(settings.neo4j.uri, settings.neo4j.auth)
        await neo4j_pool.startup()
        neo4j_writer = Neo4jWriter(neo4j_pool)
    except Exception as e:
        print(f"Warning: Neo4j not available: {e}")

    # Initialize pipeline
    event_bus = EventBus()
    budget = TokenBudgetManager()
    spacy_extractor = SpacyExtractor()

    pipeline = Pipeline(
        llm=llm_client,
        budget=budget,
        prompt_loader=prompt_loader,
        event_bus=event_bus,
        spacy=spacy_extractor,
        vector_repo=vector_repo,
        article_repo=article_repo,
        neo4j_writer=neo4j_writer,
        source_auth_repo=source_authority_repo,
    )

    # Get pending articles from database
    print("Fetching pending articles...")
    pending_articles = await article_repo.get_pending(limit=10)
    print(f"Found {len(pending_articles)} pending articles")

    if not pending_articles:
        print("No pending articles to process")
        await pool.shutdown()
        await redis.shutdown()
        return

    # Convert to ArticleRaw
    articles = []
    for article in pending_articles:
        articles.append(ArticleRaw(
            url=article.source_url,
            title=article.title,
            body=article.body or "",
            source="",
            publish_time=article.publish_time,
            source_host=article.source_host,
        ))

    print(f"Processing {len(articles)} articles through pipeline...")

    # Process through pipeline
    try:
        results = await pipeline.process_batch(articles)
        print(f"Processed {len(results)} articles")

        # Check results
        success_count = sum(1 for r in results if not r.get("terminal"))
        print(f"Success: {success_count}/{len(results)}")
    except Exception as e:
        print(f"Error processing: {e}")
        import traceback
        traceback.print_exc()

    # Cleanup
    await pool.shutdown()
    await redis.shutdown()
    print("Done")


if __name__ == "__main__":
    asyncio.run(main())
