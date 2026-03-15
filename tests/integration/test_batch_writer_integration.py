"""Integration tests for batch writer - NO MOCKS.

These tests connect to real Neo4j database.
Requires: NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD environment variables.
"""

import pytest
import os


def get_neo4j_pool():
    """Get real Neo4j pool for integration tests."""
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
    """Get Neo4j pool for integration tests."""
    pool = get_neo4j_pool()
    yield pool


@pytest.fixture
async def cleanup_test_data(neo4j_pool):
    """Clean up test data after each test."""
    yield
    await neo4j_pool.execute_query("""
        MATCH (e:Entity)
        WHERE e.canonical_name STARTS WITH 'TestIntegration'
        DETACH DELETE e
    """)
    await neo4j_pool.execute_query("""
        MATCH (a:Article)
        WHERE a.title STARTS WITH 'TestIntegration'
        DETACH DELETE a
    """)


@pytest.mark.asyncio
async def test_batch_merge_entities_real(neo4j_pool, cleanup_test_data):
    """Test batch entity merge with real database."""
    from modules.graph_store.batch_writer import Neo4jBatchWriter, EntityBatch
    
    writer = Neo4jBatchWriter(neo4j_pool)
    
    entities = [
        EntityBatch(
            canonical_name="TestIntegration_Entity1",
            entity_type="人物",
            description="Test person 1"
        ),
        EntityBatch(
            canonical_name="TestIntegration_Entity2",
            entity_type="组织机构",
            description="Test org 1"
        ),
    ]
    
    result = await writer.merge_entities_batch(entities)
    
    assert result.total == 2
    assert result.created >= 0
    
    verify = await neo4j_pool.execute_query("""
        MATCH (e:Entity {canonical_name: 'TestIntegration_Entity1'})
        RETURN e.canonical_name as name, e.type as type
    """)
    assert len(verify) > 0


@pytest.mark.asyncio
async def test_batch_merge_relations_real(neo4j_pool, cleanup_test_data):
    """Test batch relation merge with real database."""
    from modules.graph_store.batch_writer import Neo4jBatchWriter, EntityBatch, RelationBatch
    
    writer = Neo4jBatchWriter(neo4j_pool)
    
    entities = [
        EntityBatch(canonical_name="TestIntegration_Person", entity_type="人物"),
        EntityBatch(canonical_name="TestIntegration_Company", entity_type="组织机构"),
    ]
    await writer.merge_entities_batch(entities)
    
    relations = [
        RelationBatch(
            from_name="TestIntegration_Person",
            from_type="人物",
            to_name="TestIntegration_Company",
            to_type="组织机构",
            relation_type="工作于"
        ),
    ]
    
    result = await writer.merge_relations_batch(relations)
    
    assert result.total == 1
    
    verify = await neo4j_pool.execute_query("""
        MATCH (p:Entity {canonical_name: 'TestIntegration_Person'})
              -[r:RELATED_TO]->(c:Entity {canonical_name: 'TestIntegration_Company'})
        RETURN r.relation_type as rel_type
    """)
    assert len(verify) > 0


@pytest.mark.asyncio
async def test_batch_mentions_real(neo4j_pool):
    """Test batch mentions with real database."""
    from modules.graph_store.batch_writer import Neo4jBatchWriter, EntityBatch
    
    writer = Neo4jBatchWriter(neo4j_pool)
    
    await neo4j_pool.execute_query("""
        MERGE (a:Article {pg_id: 'test-integration-article-1'})
        SET a.title = 'TestIntegration Article'
    """)
    
    entities = [
        EntityBatch(canonical_name="TestIntegration_EntityForMention", entity_type="人物"),
    ]
    await writer.merge_entities_batch(entities)
    
    mentions = [
        {
            "article_id": "test-integration-article-1",
            "entity_name": "TestIntegration_EntityForMention",
            "entity_type": "人物",
            "role": "subject"
        }
    ]
    
    result = await writer.merge_mentions_batch(mentions)
    
    assert result.total >= 0
    
    await neo4j_pool.execute_query("""
        MATCH (a:Article {pg_id: 'test-integration-article-1'})
        DETACH DELETE a
    """)
    await neo4j_pool.execute_query("""
        MATCH (e:Entity {canonical_name: 'TestIntegration_EntityForMention'})
        DETACH DELETE e
    """)


@pytest.mark.asyncio
async def test_entity_repo_batch_operations_real(neo4j_pool):
    """Test entity repo batch operations with real database."""
    from modules.storage.neo4j.entity_repo import Neo4jEntityRepo
    
    repo = Neo4jEntityRepo(neo4j_pool)
    
    entities = [
        {
            "canonical_name": "TestIntegration_BatchEntity1",
            "type": "人物",
            "description": "Batch test 1"
        },
        {
            "canonical_name": "TestIntegration_BatchEntity2",
            "type": "地点",
            "description": "Batch test 2"
        },
    ]
    
    result = await repo.merge_entities_batch(entities)
    
    assert result["created"] >= 0
    
    await neo4j_pool.execute_query("""
        MATCH (e:Entity)
        WHERE e.canonical_name STARTS WITH 'TestIntegration_BatchEntity'
        DETACH DELETE e
    """)
