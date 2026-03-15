"""Integration tests for text unit manager - NO MOCKS.

Tests with real Neo4j database.
"""

import pytest
import os


def get_neo4j_pool():
    """Get real Neo4j pool."""
    from core.db.neo4j import Neo4jPool
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7688")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "testpassword123")
    pool = Neo4jPool(uri, (user, password))
    import asyncio
    asyncio.run(pool.startup())
    return pool


@pytest.fixture(scope="module")
def neo4j_pool():
    pool = get_neo4j_pool()
    yield pool


@pytest.mark.asyncio
async def test_text_unit_chunking_real(neo4j_pool):
    """Test text chunking with real data."""
    from modules.community.text_unit_manager import TextUnitManager
    
    manager = TextUnitManager(neo4j_pool)
    
    text = "这是第一段文本。这是第二段文本。这是第三段文本。"
    chunks = manager.chunk_text(text, chunk_size=20)
    
    assert len(chunks) > 0
    assert all(isinstance(c, str) for c in chunks)


@pytest.mark.asyncio
async def test_text_unit_creation_real(neo4j_pool):
    """Test text unit creation with real database."""
    from modules.community.text_unit_manager import TextUnitManager
    
    manager = TextUnitManager(neo4j_pool)
    
    await neo4j_pool.execute_query("""
        MERGE (a:Article {pg_id: 'test-text-unit-article'})
        SET a.title = 'Test Article'
    """)
    
    text = "实体A 与 实体B 合作。实体B 属于 实体C。"
    units = await manager.create_text_units("test-text-unit-article", text)
    
    assert len(units) > 0
    assert units[0].source_article_id == "test-text-unit-article"
    
    await neo4j_pool.execute_query("""
        MATCH (a:Article {pg_id: 'test-text-unit-article'})
        DETACH DELETE a
    """)
    await neo4j_pool.execute_query("""
        MATCH (t:TextUnit)
        WHERE t.source_article_id = 'test-text-unit-article'
        DETACH DELETE t
    """)


@pytest.mark.asyncio
async def test_token_estimation_real(neo4j_pool):
    """Test token estimation accuracy."""
    from modules.community.text_unit_manager import TextUnitManager
    
    manager = TextUnitManager(neo4j_pool)
    
    chinese_text = "你好世界这是一个测试"
    tokens = manager.estimate_tokens(chinese_text)
    
    assert tokens > 0
    
    mixed_text = "Hello 你好 World 世界"
    tokens_mixed = manager.estimate_tokens(mixed_text)
    
    assert tokens_mixed > 0
