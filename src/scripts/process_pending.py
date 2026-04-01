#!/usr/bin/env python
# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Script to process pending articles from the database."""

import asyncio
import os
import sys

# Add src to path before any local imports
_script_dir = os.path.dirname(os.path.abspath(__file__))  # .../src/scripts
_project_root = os.path.dirname(os.path.dirname(_script_dir))  # .../src -> project root
_src_dir = os.path.join(_project_root, "src")  # .../src
sys.path.insert(0, _src_dir)


from config.settings import Settings  # noqa: E402
from core.cache.redis import RedisClient  # noqa: E402
from core.db.postgres import PostgresPool  # noqa: E402
from core.event.bus import EventBus  # noqa: E402
from core.llm.client import LLMClient  # noqa: E402
from core.llm.token_budget import TokenBudgetManager  # noqa: E402
from core.prompt.loader import PromptLoader  # noqa: E402
from modules.ingestion.domain.models import ArticleRaw  # noqa: E402
from modules.knowledge.graph.writer import Neo4jWriter  # noqa: E402
from modules.processing.nlp.spacy_extractor import SpacyExtractor  # noqa: E402
from modules.storage.postgres.article_repo import ArticleRepo  # noqa: E402
from modules.storage.postgres.source_authority_repo import SourceAuthorityRepo  # noqa: E402
from modules.storage.postgres.vector_repo import VectorRepo  # noqa: E402


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

    # Initialize LLM client from config (use absolute path)
    prompt_loader = PromptLoader(settings.prompt.dir)
    config_path = os.path.join(_project_root, "config/llm.toml")

    llm_client = await LLMClient.create_from_config(
        config_path=config_path,
        prompt_loader=prompt_loader,
        redis_client=redis,
    )

    # Initialize repos
    article_repo = ArticleRepo(pool)
    vector_repo = VectorRepo(pool)
    source_authority_repo = SourceAuthorityRepo(pool)

    # Get Neo4j writer (optional - may fail if Neo4j not available)
    neo4j_writer = None
    try:
        from core.db.neo4j import Neo4jPool

        neo4j_pool = Neo4jPool(settings.neo4j.uri, (settings.neo4j.user, settings.neo4j.password))
        await neo4j_pool.startup()
        neo4j_writer = Neo4jWriter(neo4j_pool)
    except Exception as e:
        print(f"  Warning: Neo4j not available: {e}")

    # Process pending articles
    print("\nProcessing pending articles...")
    from modules.processing.pipeline.graph import Pipeline

    pipeline = Pipeline(
        llm=llm_client,
        budget=TokenBudgetManager(),
        prompt_loader=prompt_loader,
        event_bus=EventBus(),
        spacy=SpacyExtractor(),
        vector_repo=vector_repo,
        article_repo=article_repo,
        neo4j_writer=neo4j_writer,
        source_auth_repo=source_authority_repo,
    )

    pending = await article_repo.get_pending(limit=10)
    print(f"  Found {len(pending)} pending articles")

    # Convert Article ORM objects to ArticleRaw dataclass objects
    raw_articles = []
    for article in pending:
        raw = ArticleRaw(
            url=article.source_url,
            title=article.title,
            body=article.body or "",
            source=article.source_host or "",
            publish_time=article.publish_time,
            source_host=article.source_host or "",
            tier=2,
        )
        raw_articles.append(raw)

    if raw_articles:
        print("  Processing batch...")
        try:
            states = await pipeline.process_batch(raw_articles)
            success = sum(1 for s in states if not s.get("terminal"))
            print(f"    Processed {success}/{len(raw_articles)} articles")
        except Exception as e:
            import traceback

            print(f"    Error: {e}")
            traceback.print_exc()

    # Cleanup
    print("\nShutting down...")
    await llm_client.close()
    await pool.shutdown()
    await redis.shutdown()
    print("Done!")


if __name__ == "__main__":
    asyncio.run(main())
