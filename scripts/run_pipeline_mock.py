#!/usr/bin/env python
"""Run full pipeline with mock LLM for testing."""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import datetime, timezone
from config.settings import Settings
from core.db.postgres import PostgresPool
from core.cache.redis import RedisClient
from core.llm.token_budget import TokenBudgetManager
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

log = get_logger("run_pipeline_mock")


class MockLLMClient:
    def __init__(self):
        self._budget = TokenBudgetManager()
        self._prompts = PromptLoader(Settings().prompt.dir)
    
    async def call(self, call_point, input_text, **kwargs):
        if call_point.value == "classifier":
            return type("ClassifierOutput", (), {"is_news": True, "confidence": 0.9})()
        elif call_point.value == "cleaner":
            return type("CleanerOutput", (), {"cleaned_text": input_text[:500] if len(input_text) > 500 else input_text, "removed_ratio": 0.1})()
        elif call_point.value == "categorizer":
            return type("CategorizerOutput", (), {"category": "科技", "confidence": 0.85})()
        elif call_point.value == "merger":
            return type("MergerOutput", (), {"should_merge": False, "target_id": None, "similarity": 0.0})()
        elif call_point.value == "analyze":
            return type("AnalyzeOutput", (), {"summary": "Test summary", "keywords": ["tech"], "sentiment": "neutral"})()
        elif call_point.value == "credibility_checker":
            return type("CredibilityOutput", (), {"credibility_score": 0.75, "factors": {}})()
        elif call_point.value == "entity_extractor":
            return type("EntityOutput", (), {"entities": [], "relations": []})()
        elif call_point.value == "entity_resolver":
            return type("ResolverOutput", (), {"resolved_entities": [], "new_aliases": []})()
        return None
    
    async def embed(self, texts, **kwargs):
        import numpy as np
        return [np.random.rand(1024).tolist() for _ in texts]
    
    async def batch_embed(self, texts, **kwargs):
        import numpy as np
        return [np.random.rand(1024).tolist() for _ in texts]


def get_test_articles() -> list[ArticleRaw]:
    return [
        ArticleRaw(
            url="https://example.com/test/1",
            title="OpenAI发布GPT-5，性能大幅提升",
            body="OpenAI今日发布了最新的大型语言模型GPT-5，该模型在多项基准测试中表现出色。",
            source="Test News",
            source_host="example.com",
            tier=2,
        ),
        ArticleRaw(
            url="https://example.com/test/2",
            title="苹果公司市值突破3万亿美元",
            body="苹果公司股价今日大涨，市值首次突破3万亿美元大关。",
            source="Test News",
            source_host="example.com",
            tier=2,
        ),
        ArticleRaw(
            url="https://example.com/test/3",
            title="中国成功发射新一代载人飞船",
            body="中国航天局今日宣布，成功发射了新一代载人飞船。",
            source="Test News",
            source_host="example.com",
            tier=2,
        ),
    ]


async def main():
    print("=" * 60)
    print("Weaver Pipeline - Full Flow Test (Mock LLM)")
    print("=" * 60)
    
    settings = Settings()
    
    print("\n[1/6] Initializing PostgreSQL...")
    pg_pool = PostgresPool(settings.postgres.dsn)
    await pg_pool.startup()
    print("  OK PostgreSQL connected")
    
    print("\n[2/6] Initializing Redis...")
    redis = RedisClient(settings.redis.url)
    await redis.startup()
    print("  OK Redis connected")
    
    print("\n[3/6] Initializing Mock LLM...")
    llm_client = MockLLMClient()
    event_bus = EventBus()
    prompt_loader = PromptLoader(settings.prompt.dir)
    token_budget = TokenBudgetManager()
    print("  OK Mock LLM ready")
    
    print("\n[4/6] Initializing Neo4j...")
    neo4j_writer = None
    try:
        neo4j_pool = Neo4jPool(settings.neo4j.uri, settings.neo4j.auth_tuple)
        await neo4j_pool.startup()
        neo4j_writer = Neo4jWriter(neo4j_pool)
        print("  OK Neo4j connected")
    except Exception as e:
        print(f"  WARN Neo4j not available: {e}")
    
    print("\n[5/6] Initializing repositories...")
    article_repo = ArticleRepo(pg_pool)
    vector_repo = VectorRepo(pg_pool)
    source_auth_repo = SourceAuthorityRepo(pg_pool)
    spacy_extractor = SpacyExtractor()
    print("  OK Repositories ready")
    
    print("\n[6/6] Initializing Pipeline...")
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
    print("  OK Pipeline ready")
    
    all_articles = get_test_articles()
    print(f"\n  Test articles loaded: {len(all_articles)}")
    
    print("\n" + "=" * 60)
    print("Processing articles through Pipeline...")
    print("=" * 60)
    
    try:
        results = await pipeline.process_batch(all_articles)
        
        success = sum(1 for r in results if not r.get("terminal", False))
        terminal = len(results) - success
        
        print(f"\n{'=' * 60}")
        print("Pipeline Results:")
        print(f"  Total processed: {len(results)}")
        print(f"  Success: {success}")
        print(f"  Terminal: {terminal}")
        print("=" * 60)
        
        for i, result in enumerate(results):
            status = "OK" if not result.get("terminal") else "SKIP"
            title = result.get("title", "N/A")[:40]
            category = result.get("category", "N/A")
            print(f"  {status} [{i+1}] {title}... | {category}")
        
    except Exception as e:
        print(f"\nERROR Pipeline error: {e}")
        import traceback
        traceback.print_exc()
    
    print("\nVerifying data in database...")
    
    import asyncpg
    conn = await asyncpg.connect(settings.postgres.dsn)
    count = await conn.fetchval("SELECT COUNT(*) FROM articles")
    print(f"  Articles in DB: {count}")
    await conn.close()
    
    print("\nShutting down...")
    await pg_pool.shutdown()
    await redis.shutdown()
    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
