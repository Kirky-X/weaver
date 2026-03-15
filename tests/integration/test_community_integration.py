"""Integration tests for community detection - NO MOCKS.

Tests Leiden clustering and modularity with real graph data.
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


@pytest.fixture
async def setup_communities(neo4j_pool):
    """Set up test communities."""
    await neo4j_pool.execute_query("""
        MERGE (a:Entity {canonical_name: 'Comm_A', type: '人物'})
        MERGE (b:Entity {canonical_name: 'Comm_B', type: '人物'})
        MERGE (c:Entity {canonical_name: 'Comm_C', type: '人物'})
        MERGE (d:Entity {canonical_name: 'Comm_D', type: '人物'})
        MERGE (a)-[:RELATED_TO {relation_type: '朋友'}]->(b)
        MERGE (b)-[:RELATED_TO {relation_type: '同事'}]->(c)
        MERGE (c)-[:RELATED_TO {relation_type: '朋友'}]->(a)
    """)
    yield
    await neo4j_pool.execute_query("""
        MATCH (e:Entity)
        WHERE e.canonical_name STARTS WITH 'Comm_'
        DETACH DELETE e
    """)


@pytest.mark.asyncio
async def test_leiden_clustering_real_graph(neo4j_pool, setup_communities):
    """Test Leiden clustering with real Neo4j data."""
    from modules.community.leiden import LeidenClustering
    
    edges_data = await neo4j_pool.execute_query("""
        MATCH (e1:Entity)-[r:RELATED_TO]->(e2:Entity)
        RETURN e1.canonical_name AS source, e2.canonical_name AS target, r.weight AS weight
    """)
    
    edges = [
        (r["source"], r["target"], r.get("weight", 1.0))
        for r in edges_data
    ]
    
    clustering = LeidenClustering(resolution=1.0, random_seed=42)
    result = clustering.cluster(edges)
    
    assert result.total_entities >= 3
    assert result.total_edges >= 0


@pytest.mark.asyncio
async def test_modularity_real_graph(neo4j_pool, setup_communities):
    """Test modularity calculation with real data."""
    from modules.community.modularity import ModularityCalculator
    
    edges_data = await neo4j_pool.execute_query("""
        MATCH (e1:Entity)-[r:RELATED_TO]->(e2:Entity)
        RETURN e1.canonical_name AS source, e2.canonical_name AS target
    """)
    
    edges = [(r["source"], r["target"], 1.0) for r in edges_data]
    
    if edges_data:
        partitions = {}
        for r in edges_data:
            partitions[r["source"]] = 0
            partitions[r["target"]] = 1
        
        calc = ModularityCalculator(resolution=1.0)
        result = calc.calculate(edges, partitions)

        assert -1.0 <= result.score <= 1.0


@pytest.mark.asyncio
async def test_hierarchical_leiden(neo4j_pool, setup_communities):
    """Test hierarchical Leiden clustering."""
    from modules.community.leiden import LeidenClustering
    
    edges_data = await neo4j_pool.execute_query("""
        MATCH (e1:Entity)-[r:RELATED_TO]->(e2:Entity)
        RETURN e1.canonical_name AS source, e2.canonical_name AS target
    """)
    
    edges = [(r["source"], r["target"], 1.0) for r in edges_data]
    
    if len(edges) >= 2:
        clustering = LeidenClustering(random_seed=42)
        result = clustering.cluster_with_hierarchy(edges)
        
        assert result.hierarchy is not None
