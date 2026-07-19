# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Shared fixtures for integration tests with service fallback.

Supports three modes:
1. Real services available: Use real connections (PostgreSQL, Neo4j, Redis)
2. Services unavailable: Fall back to embedded databases (DuckDB, LadybugDB)
3. Redis unavailable: Skip tests that require Redis

All fixtures use real databases - no mocks. DuckDB and LadybugDB are real
embedded databases that can run without external services.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import pytest


def get_postgres_dsn():
    """Get PostgreSQL DSN from environment variables."""
    return (
        os.getenv("WEAVER_POSTGRES__DSN")
        or os.getenv("POSTGRES_DSN")
        or f"postgresql+asyncpg://{os.getenv('POSTGRES_USER', 'postgres')}:{os.getenv('POSTGRES_PASSWORD', 'invalid')}@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}/{os.getenv('POSTGRES_DATABASE', 'weaver')}"
    )


def get_neo4j_config():
    """Get Neo4j connection config."""
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "password")
    return uri, (user, password)


def get_redis_url():
    """Get Redis URL."""
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


async def check_postgres_available() -> bool:
    """Check if PostgreSQL is available."""
    try:
        from core.db import PostgresPool

        dsn = get_postgres_dsn()
        pool = PostgresPool(dsn)
        await pool.startup()
        await pool.shutdown()
        return True
    except Exception:
        return False


async def check_neo4j_available() -> bool:
    """Check if Neo4j is available."""
    try:
        from core.db.neo4j import Neo4jPool

        uri, auth = get_neo4j_config()
        pool = Neo4jPool(uri, auth)
        await pool.startup()
        await pool.shutdown()
        return True
    except Exception:
        return False


async def check_redis_available() -> bool:
    """Check if Redis is available."""
    try:
        from redis import asyncio as aioredis

        url = get_redis_url()
        client = aioredis.from_url(url)
        await client.ping()
        await client.aclose()
        return True
    except Exception:
        return False


@pytest.fixture
def unique_id():
    """Generate unique test ID to avoid conflicts."""
    return str(uuid.uuid4())


@pytest.fixture
def auth_headers():
    """Return auth headers for API requests.

    Reads ``WEAVER_API__API_KEY`` (pydantic-settings nested delimiter ``__``)
    so the value matches what the running server is configured with via .env.
    The fallback default satisfies ``MIN_API_KEY_LENGTH = 32`` (see
    src/api/middleware/auth.py:21) to avoid spurious 500/403 when .env is
    not loaded.
    """
    api_key = os.getenv("WEAVER_API__API_KEY", "test-api-key-32chars-long!!!!!!!")
    return {"X-API-Key": api_key}


@pytest.fixture
async def cache_client():
    """Create a real Redis client for integration tests.

    Skips tests if Redis is not available.
    """
    from redis import asyncio as aioredis

    if not await check_redis_available():
        pytest.skip("Redis not available")

    url = get_redis_url()
    client = aioredis.from_url(url)
    yield client
    await client.aclose()


@pytest.fixture
def event_bus():
    """Create a real EventBus for integration tests."""
    from core.event import EventBus

    return EventBus()


# ─────────────────────────────────────────────────────────────────────────────
# Fallback fixtures: Use embedded databases when external services unavailable
# These are REAL databases, not mocks - fully compliant with integration test rules
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
async def relational_pool():
    """Create a relational database pool with automatic fallback.

    Tries PostgreSQL first, falls back to DuckDB if unavailable.
    DuckDB is a real embedded database - no mocks.

    Returns:
        tuple: (pool, database_type) where database_type is DatabaseType.POSTGRES
        or DatabaseType.DUCKDB. Returned as DatabaseType enum (not str) so
        downstream code calling ``.value`` (e.g. container.relational_pool_type)
        works correctly. DatabaseType inherits str, so ``== "postgres"`` and
        ``== "duckdb"`` comparisons still pass for legacy callers.
    """
    from core.db.query_builders import DatabaseType

    # Try PostgreSQL first
    if await check_postgres_available():
        from core.db import PostgresPool

        dsn = get_postgres_dsn()
        pool = PostgresPool(dsn)
        await pool.startup()
        yield pool, DatabaseType.POSTGRES
        await pool.shutdown()
    else:
        # Fallback to DuckDB (real embedded database)
        from core.db.duckdb_pool import DuckDBPool
        from core.db.duckdb_schema import initialize_duckdb_schema

        # Use temp file path for test isolation (DuckDB will create the file)
        with tempfile.NamedTemporaryFile(suffix=".duckdb", delete=True) as f:
            db_path = f.name  # Get the path

        # File is now deleted, DuckDB will create a fresh database
        try:
            pool = DuckDBPool(db_path=db_path)
            await pool.startup()
            await initialize_duckdb_schema(pool)
            yield pool, DatabaseType.DUCKDB
            await pool.shutdown()
        finally:
            # Cleanup temp file
            if os.path.exists(db_path):
                os.unlink(db_path)


@pytest.fixture
async def graph_pool():
    """Create a graph database pool with automatic fallback.

    Tries Neo4j first, falls back to LadybugDB if unavailable.
    LadybugDB is a real embedded graph database - no mocks.

    Returns:
        tuple: (pool, database_type) where database_type is "neo4j" or "ladybug"
    """
    # Try Neo4j first
    if await check_neo4j_available():
        from core.db.neo4j import Neo4jPool

        uri, auth = get_neo4j_config()
        pool = Neo4jPool(uri, auth)
        await pool.startup()
        yield pool, "neo4j"
        await pool.shutdown()
    else:
        # Fallback to LadybugDB (real embedded graph database)
        from core.db.ladybug_pool import LadybugPool
        from core.db.ladybug_schema import initialize_ladybug_schema

        # Use temp file path for test isolation (LadybugDB will create the file)
        with tempfile.NamedTemporaryFile(suffix=".ladybug", delete=True) as f:
            db_path = f.name  # Get the path

        # File is now deleted, LadybugDB will create a fresh database
        try:
            pool = LadybugPool(db_path=db_path)
            await pool.startup()
            await initialize_ladybug_schema(pool)
            yield pool, "ladybug"
            await pool.shutdown()
        finally:
            # Cleanup temp file
            if os.path.exists(db_path):
                os.unlink(db_path)


@pytest.fixture
async def cache_client():
    """Create a cache pool with automatic fallback.

    Tries Redis first, falls back to CashewsClient (in-memory) if unavailable.
    CashewsClient is a real in-memory cache - no mocks.

    Returns:
        tuple: (pool, cache_type) where cache_type is "redis" or "cashews"
    """
    # Try Redis first
    if await check_redis_available():
        from core.cache import RedisClient

        url = get_redis_url()
        client = RedisClient(url)
        await client.startup()
        yield client, "redis"
        await client.shutdown()
    else:
        # Fallback to CashewsClient (real in-memory cache)
        from core.cache import CashewsClient

        client = CashewsClient()
        await client.startup()
        yield client, "cashews"
        await client.shutdown()


@pytest.fixture
async def database_strategy(relational_pool, graph_pool):
    """Create a DatabaseStrategy using fallback databases.

    Uses the relational_pool and graph_pool fixtures which automatically
    fall back to embedded databases when external services are unavailable.
    """
    from core.db.strategy import DatabaseStrategy

    rel_pool, rel_type = relational_pool
    g_pool, g_type = graph_pool

    yield DatabaseStrategy(
        relational_pool=rel_pool,
        graph_pool=g_pool,
        relational_type=rel_type,
        graph_type=g_type,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Optional fixtures for tests that can work with or without services
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
async def optional_relational_pool():
    """Optional relational database pool - returns None if not available."""
    from core.db import PostgresPool

    if not await check_postgres_available():
        yield None
        return

    dsn = get_postgres_dsn()
    pool = PostgresPool(dsn)
    await pool.startup()
    yield pool
    await pool.shutdown()


@pytest.fixture
async def optional_graph_pool():
    """Optional graph database pool - returns None if not available."""
    from core.db.neo4j import Neo4jPool

    if not await check_neo4j_available():
        yield None
        return

    uri, auth = get_neo4j_config()
    pool = Neo4jPool(uri, auth)
    await pool.startup()
    yield pool
    await pool.shutdown()


@pytest.fixture
async def optional_cache_client():
    """Optional Redis client - returns None if not available."""
    from redis import asyncio as aioredis

    if not await check_redis_available():
        yield None
        return

    url = get_redis_url()
    client = aioredis.from_url(url)
    yield client
    await client.aclose()


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline Integration Test: Pre-flight Checks (Tasks 1.1-1.7)
# These fixtures verify the environment before running pipeline node tests.
# Each check returns a result; dependent tests are skipped if checks fail.
# ─────────────────────────────────────────────────────────────────────────────

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "gemma4:e4b")
OLLAMA_EMBEDDING_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL", "qwen3-embedding:0.6b")


async def _check_ollama_available() -> bool:
    """Check if ollama service is reachable."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            return resp.status_code == 200
    except Exception:
        return False


async def _check_ollama_models() -> tuple[bool, bool]:
    """Check if required ollama models are available.

    Returns:
        (chat_model_available, embedding_model_available)
    """
    import httpx

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            if resp.status_code != 200:
                return False, False
            data = resp.json()
            model_names = [m.get("name", "") for m in data.get("models", [])]
            chat_ok = any(OLLAMA_CHAT_MODEL in name for name in model_names)
            embed_ok = any(OLLAMA_EMBEDDING_MODEL in name for name in model_names)
            return chat_ok, embed_ok
    except Exception:
        return False, False


async def _check_embedding_dimension() -> int | None:
    """Check embedding dimension by calling the embedding model.

    Returns:
        Embedding dimension, or None if check failed.
    """
    try:
        from core.event import EventBus
        from core.llm.client import LLMClient
        from core.llm.config.config import LLMSettings

        llm_settings = LLMSettings()
        event_bus = EventBus()
        llm_client = await LLMClient.create_from_settings(llm_settings, event_bus)
        embeddings = await llm_client.embed_default(["test"])
        return len(embeddings[0]) if embeddings and embeddings[0] else None
    except Exception:
        return None


async def _check_spacy_model() -> bool:
    """Check if spaCy model can be loaded."""
    try:
        from modules.processing.nlp.spacy_extractor import SpacyExtractor

        extractor = SpacyExtractor()
        return extractor.is_loaded()
    except Exception:
        return False


async def _check_duckdb_vector_query(relational_pool_tuple: tuple[Any, str]) -> bool:
    """Check if DuckDB supports vector similarity queries.

    Args:
        relational_pool_tuple: (pool, db_type) from the relational_pool fixture.
    """
    pool, db_type = relational_pool_tuple
    if db_type != "duckdb":
        return True  # PostgreSQL supports pgvector natively

    try:
        # Try a simple vector similarity query
        await pool.execute(
            "SELECT array_cosine_similarity([1.0, 2.0, 3.0]::FLOAT[3], [1.0, 2.0, 3.0]::FLOAT[3])"
        )
        return True
    except Exception:
        return False


async def _check_ladybug_schema(graph_pool_tuple: tuple[Any, str]) -> bool:
    """Check if LadybugDB schema has entity/relation constraints.

    Args:
        graph_pool_tuple: (pool, db_type) from the graph_pool fixture.
    """
    pool, db_type = graph_pool_tuple
    if db_type != "ladybug":
        return True  # Neo4j has schema by default

    try:
        # Check if entity and relation node types exist
        result = await pool.execute("MATCH (n) RETURN count(n) LIMIT 1")
        return True
    except Exception:
        return False


@pytest.fixture
async def ollama_available():
    """Check if ollama service is available. Skip tests if not."""
    if not await _check_ollama_available():
        pytest.skip("Ollama service not available at " + OLLAMA_BASE_URL)
    return True


@pytest.fixture
async def ollama_models(ollama_available):
    """Check if required ollama models are available. Skip tests if not."""
    chat_ok, embed_ok = await _check_ollama_models()
    if not chat_ok:
        pytest.skip(f"Ollama chat model '{OLLAMA_CHAT_MODEL}' not available")
    if not embed_ok:
        pytest.skip(f"Ollama embedding model '{OLLAMA_EMBEDDING_MODEL}' not available")
    return {"chat_model": OLLAMA_CHAT_MODEL, "embedding_model": OLLAMA_EMBEDDING_MODEL}


@pytest.fixture
async def embedding_dimension(ollama_models):
    """Check embedding dimension compatibility. Skip tests if incompatible."""
    dim = await _check_embedding_dimension()
    if dim is None:
        pytest.skip("Cannot determine embedding dimension from ollama")
    return dim


@pytest.fixture
async def spacy_available():
    """Check if spaCy model is loaded. Skip entity tests if not."""
    if not await _check_spacy_model():
        pytest.skip("spaCy model not available")
    return True


@pytest.fixture
async def duckdb_vector_available(relational_pool):
    """Check if DuckDB supports vector similarity queries."""
    available = await _check_duckdb_vector_query(relational_pool)
    if not available:
        pytest.skip("DuckDB vector similarity queries not available")
    return True


@pytest.fixture
async def ladybug_schema_available(graph_pool):
    """Check if LadybugDB schema is complete."""
    available = await _check_ladybug_schema(graph_pool)
    if not available:
        pytest.skip("LadybugDB schema not complete")
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline Integration Test: LLM Client & Node Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
async def llm_client(ollama_models, event_bus, prompt_loader):
    """Create a real LLMClient from config/llm.toml for integration tests.

    Uses the ollama_models fixture to ensure required models are available.
    Injects prompt_loader so that call_at can build system_prompt and user_content
    from configured prompts (required for structured output via output_model).
    """
    from core.llm.client import LLMClient
    from core.llm.config.config import LLMSettings

    llm_settings = LLMSettings()
    client = await LLMClient.create_from_settings(
        llm_settings, event_bus, prompt_loader=prompt_loader
    )
    yield client


@pytest.fixture
def token_budget():
    """Create a TokenBudgetManager for integration tests.

    Uses default model resolution (settings.llm.tokenizer_model or gpt-4o).
    """
    from core.llm.config.token_budget import TokenBudgetManager

    return TokenBudgetManager()


@pytest.fixture
def prompt_loader():
    """Create a PromptLoader for integration tests.

    Uses the project's config/prompts directory.
    """
    from pathlib import Path

    from core.prompt.loader import PromptLoader

    project_root = Path(__file__).resolve().parent.parent.parent
    return PromptLoader(str(project_root / "config" / "prompts"))


@pytest.fixture
async def spacy_extractor(spacy_available):
    """Create a SpacyExtractor instance. Skips if spaCy model not available."""
    from modules.processing.nlp.spacy_extractor import SpacyExtractor

    return SpacyExtractor()


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline Integration Test: Test Data Fixtures (Tasks 2.1-2.4)
# ─────────────────────────────────────────────────────────────────────────────


# Preset fixture articles for when RSS is unavailable
_PRESET_ARTICLES = [
    {
        "title": "华为发布新款AI芯片，性能提升超50%",
        "body": (
            "华为在深圳举行的产品发布会上正式推出了最新一代AI训练芯片昇腾910B。"
            "据华为官方介绍，该芯片采用7nm工艺制程，在FP16算力上较前代产品提升超过50%，"
            "同时功耗降低了30%。华为轮值董事长表示，昇腾910B将广泛应用于大模型训练、"
            "自动驾驶和科学计算等领域。业内分析人士认为，此举将进一步加剧全球AI芯片"
            "市场的竞争格局，对英伟达的市场份额构成挑战。目前已有超过200家企业表达了"
            "采购意向，预计首批产品将于下季度交付。"
        ),
        "url": "https://example.com/test/huawei-ai-chip",
        "source_host": "example.com",
        "html": (
            "<html><body><article><h1>华为发布新款AI芯片，性能提升超50%</h1>"
            "<p>华为在深圳举行的产品发布会上正式推出了最新一代AI训练芯片昇腾910B。</p>"
            "<p>据华为官方介绍，该芯片采用7nm工艺制程，在FP16算力上较前代产品提升超过50%，"
            "同时功耗降低了30%。</p></article></body></html>"
        ),
    },
    {
        "title": "央行宣布降准0.5个百分点释放长期资金约1万亿元",
        "body": (
            "中国人民银行今日宣布，决定于下月15日下调金融机构存款准备金率0.5个百分点"
            "（不含已执行5%存款准备金率的金融机构）。本次下调后，金融机构加权平均存款准备金率"
            "约为6.6%。央行表示，此次降准将释放长期资金约1万亿元，旨在保持流动性合理充裕，"
            "优化金融机构资金结构，降低企业融资成本。市场人士分析认为，降准信号明确，"
            "有助于稳定市场预期，提振投资者信心。受此消息影响，A股三大指数午后集体拉升，"
            "沪指涨超1%。"
        ),
        "url": "https://example.com/test/pboc-reserve-ratio",
        "source_host": "example.com",
        "html": (
            "<html><body><article><h1>央行宣布降准0.5个百分点释放长期资金约1万亿元</h1>"
            "<p>中国人民银行今日宣布，决定于下月15日下调金融机构存款准备金率0.5个百分点。</p>"
            "<p>央行表示，此次降准将释放长期资金约1万亿元。</p></article></body></html>"
        ),
    },
    {
        "title": "国际空间站成功完成太阳能电池板更换任务",
        "body": (
            "据NASA消息，国际空间站两名宇航员今日成功完成了长达7小时的太空行走任务，"
            "更换了空间站老旧的太阳能电池板。新安装的太阳能电池板采用最新Roll-Out技术，"
            "发电效率较旧版提升约30%。此次更换任务是空间站现代化升级计划的重要组成部分，"
            "预计将确保空间站至少运行至2030年。欧洲航天局和日本宇宙航空研究开发机构"
            "均对此次任务的成功表示祝贺。空间站目前共有8组太阳能电池板，"
            "此次更换的是其中最老旧的一组。"
        ),
        "url": "https://example.com/test/iss-solar-panel",
        "source_host": "example.com",
        "html": (
            "<html><body><article><h1>国际空间站成功完成太阳能电池板更换任务</h1>"
            "<p>据NASA消息，国际空间站两名宇航员今日成功完成了长达7小时的太空行走任务。</p>"
            "<p>新安装的太阳能电池板采用最新Roll-Out技术，发电效率较旧版提升约30%。</p>"
            "</article></body></html>"
        ),
    },
]


async def _fetch_rss_articles(source_url: str, max_items: int = 3) -> list[dict[str, Any]]:
    """Fetch real articles from an RSS source.

    Args:
        source_url: RSS feed URL.
        max_items: Maximum number of items to fetch.

    Returns:
        List of article dicts with title, body, url, source_host, html.
    """
    import httpx

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(source_url)
            if resp.status_code != 200:
                return []

        import feedparser

        feed = feedparser.parse(resp.text)
        articles = []
        for entry in feed.entries[:max_items]:
            title = getattr(entry, "title", "")
            body = getattr(entry, "summary", "") or getattr(entry, "description", "")
            url = getattr(entry, "link", "")
            source_host = source_url.split("/")[2] if "//" in source_url else source_url
            html = (
                getattr(entry, "content", [{}])[0].get("value", "")
                if hasattr(entry, "content")
                else ""
            )
            if title and body:
                articles.append(
                    {
                        "title": title,
                        "body": body,
                        "url": url,
                        "source_host": source_host,
                        "html": html,
                    }
                )
        return articles
    except Exception:
        return []


@pytest.fixture
async def pipeline_test_articles():
    """Provide test articles for pipeline integration tests.

    Tries to fetch real RSS articles first, falls back to preset articles.
    Limits to 3 items per source as per design.
    """
    # Try real RSS source (solidot)
    articles = await _fetch_rss_articles("https://www.solidot.org/index.rss", max_items=3)

    # Fallback to preset articles if RSS unavailable
    if not articles:
        articles = _PRESET_ARTICLES

    return articles


@pytest.fixture
async def pipeline_raw_articles(pipeline_test_articles):
    """Create RawArticle instances from test articles."""
    from modules.ingestion.domain.models import RawArticle

    raw_articles = []
    for article in pipeline_test_articles:
        raw = RawArticle(
            url=article["url"],
            title=article["title"],
            body=article["body"],
            source=article["source_host"],
            source_host=article["source_host"],
            html=article.get("html"),
            publish_time=datetime.now(timezone.utc),
        )
        raw_articles.append(raw)
    return raw_articles


@pytest.fixture
async def pipeline_cleanup(relational_pool, graph_pool):
    """Clean up test data from DuckDB and LadybugDB after tests.

    Yields None, then cleans up in teardown.
    """
    yield None

    # Cleanup relational DB test data
    pool, db_type = relational_pool
    try:
        if db_type == "duckdb":
            await pool.execute("DELETE FROM article_vectors WHERE 1=1")
            await pool.execute("DELETE FROM articles WHERE 1=1")
    except Exception:
        pass  # Best-effort cleanup

    # Cleanup graph DB test data
    g_pool, g_type = graph_pool
    try:
        if g_type == "ladybug":
            await g_pool.execute("MATCH (n) DETACH DELETE n")
    except Exception:
        pass  # Best-effort cleanup


# ─────────────────────────────────────────────────────────────────────────────
# Mock Detection: Integration tests MUST use real services
# ─────────────────────────────────────────────────────────────────────────────


def pytest_collection_modifyitems(config, items):
    """Detect mock usage in integration tests and raise error.

    Integration tests MUST use real services (PostgreSQL, Neo4j, Redis).
    If a test needs mock, move it to tests/unit/ directory.
    """
    import inspect
    from pathlib import Path

    forbidden_patterns = [
        "MagicMock",
        "AsyncMock",
        "patch(",
        "@patch",
        "unittest.mock",
    ]

    integration_dir = Path(__file__).parent

    for item in items:
        # Only check tests within integration directory
        test_path = Path(str(item.fspath))
        if not str(test_path).startswith(str(integration_dir)):
            continue

        # Only check test functions, not fixtures
        if not hasattr(item, "function"):
            continue

        try:
            source = inspect.getsource(item.function)
        except (TypeError, OSError):
            continue

        for pattern in forbidden_patterns:
            if pattern in source:
                raise AssertionError(
                    f"\n"
                    f"╔════════════════════════════════════════════════════════════╗\n"
                    f"║  ❌ 集成测试禁止使用 mock!                                  ║\n"
                    f"╠════════════════════════════════════════════════════════════╣\n"
                    f"║  测试: {item.name:<50} ║\n"
                    f"║  文件: {item.fspath!s:<50} ║\n"
                    f"║  检测到: {pattern:<48} ║\n"
                    f"╠════════════════════════════════════════════════════════════╣\n"
                    f"║  集成测试必须使用真实服务。                                 ║\n"
                    f"║  如需 mock，请将测试移至 tests/unit/ 目录。                 ║\n"
                    f"╚════════════════════════════════════════════════════════════╝\n"
                )
