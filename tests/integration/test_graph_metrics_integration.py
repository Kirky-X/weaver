# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for graph metrics - NO MOCKS.

Tests with real Neo4j database.
"""

import os

import pytest


@pytest.fixture
async def neo4j_pool():
    """Get real Neo4j pool."""
    from core.db.neo4j import Neo4jPool

    # Use port 7687 (Docker weaver stack) and password from .env
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "password")
    pool = Neo4jPool(uri, (user, password))
    await pool.startup()
    yield pool


@pytest.fixture
async def setup_test_graph(neo4j_pool):
    """Set up test graph data."""
    await neo4j_pool.execute_query("""
        MERGE (e1:Entity {canonical_name: 'MetricsTest_Person1', type: '人物'})
        MERGE (e2:Entity {canonical_name: 'MetricsTest_Person2', type: '人物'})
        MERGE (e3:Entity {canonical_name: 'MetricsTest_Org', type: '组织机构'})
        MERGE (e1)-[:RELATED_TO {relation_type: '认识'}]->(e2)
        MERGE (e2)-[:RELATED_TO {relation_type: '工作于'}]->(e3)
    """)
    yield
    await neo4j_pool.execute_query("""
        MATCH (e:Entity)
        WHERE e.canonical_name STARTS WITH 'MetricsTest'
        DETACH DELETE e
    """)


@pytest.mark.asyncio
async def test_graph_metrics_calculation(neo4j_pool, setup_test_graph):
    """Test graph metrics with real data."""
    from modules.graph_store.metrics import GraphQualityMetrics

    metrics = GraphQualityMetrics(neo4j_pool)
    result = await metrics.calculate_all_metrics()

    assert result.total_entities >= 3
    assert result.total_relationships >= 2


@pytest.mark.asyncio
async def test_connected_components(neo4j_pool, setup_test_graph):
    """Test connected components detection."""
    from modules.graph_store.metrics import GraphQualityMetrics

    metrics = GraphQualityMetrics(neo4j_pool)
    components = await metrics.get_connected_components()

    assert isinstance(components, list)


@pytest.mark.asyncio
async def test_orphan_entities(neo4j_pool):
    """Test orphan entity detection."""
    from modules.graph_store.metrics import GraphQualityMetrics

    await neo4j_pool.execute_query("""
        MERGE (e:Entity {canonical_name: 'MetricsTest_Orphan', type: '人物'})
    """)

    metrics = GraphQualityMetrics(neo4j_pool)
    orphans = await metrics.find_orphan_entities(limit=10)

    assert isinstance(orphans, list)

    await neo4j_pool.execute_query("""
        MATCH (e:Entity {canonical_name: 'MetricsTest_Orphan'})
        DETACH DELETE e
    """)


@pytest.mark.asyncio
async def test_modularity_calculation(neo4j_pool, setup_test_graph):
    """Test modularity with real graph."""
    from modules.graph_store.metrics import GraphQualityMetrics

    metrics = GraphQualityMetrics(neo4j_pool)
    score = await metrics.calculate_modularity()

    assert -1.0 <= score <= 1.0
