# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for graph metrics - NO MOCKS.

Tests with fallback graph databases (Neo4j or LadybugDB).
"""

import uuid

import pytest


@pytest.fixture
async def entity_repo(graph_pool):
    """Create EntityRepository based on graph pool type."""
    pool, db_type = graph_pool
    if db_type == "ladybug":
        from modules.storage.ladybug import LadybugEntityRepo

        return LadybugEntityRepo(pool), pool, db_type
    else:
        from modules.storage.neo4j.entity_repo import Neo4jEntityRepo

        return Neo4jEntityRepo(pool), pool, db_type


@pytest.fixture
async def setup_test_graph(entity_repo):
    """Set up test graph data using EntityRepository."""
    repo, pool, db_type = entity_repo

    # Create entities using EntityRepository (handles LadybugDB UUID requirements)
    e1_id = await repo.merge_entity(
        canonical_name="MetricsTest_Person1",
        entity_type="人物",
    )
    e2_id = await repo.merge_entity(
        canonical_name="MetricsTest_Person2",
        entity_type="人物",
    )
    e3_id = await repo.merge_entity(
        canonical_name="MetricsTest_Org",
        entity_type="组织机构",
    )

    # Create relationships using EntityRepository
    await repo.merge_relation(
        from_entity_id=e1_id,
        to_entity_id=e2_id,
        edge_type="RELATED_TO",
        properties={"relation_type": "认识"},
    )
    await repo.merge_relation(
        from_entity_id=e2_id,
        to_entity_id=e3_id,
        edge_type="RELATED_TO",
        properties={"relation_type": "工作于"},
    )

    yield
    # Cleanup - handle both Neo4j (DETACH DELETE) and LadybugDB (manual delete)
    if db_type == "ladybug":
        # LadybugDB doesn't support DETACH DELETE
        await pool.execute_query("""
            MATCH (e:Entity)-[r:RELATED_TO]->()
            WHERE e.canonical_name STARTS WITH 'MetricsTest'
            DELETE r
        """)
        await pool.execute_query("""
            MATCH (e:Entity)
            WHERE e.canonical_name STARTS WITH 'MetricsTest'
            DELETE e
        """)
    else:
        await pool.execute_query("""
            MATCH (e:Entity)
            WHERE e.canonical_name STARTS WITH 'MetricsTest'
            DETACH DELETE e
        """)


@pytest.mark.asyncio
async def test_graph_metrics_calculation(entity_repo, setup_test_graph):
    """Test graph metrics with real data."""
    from modules.knowledge.graph.metrics import GraphQualityMetrics

    _, pool, db_type = entity_repo
    metrics = GraphQualityMetrics(pool, db_type=db_type)
    result = await metrics.calculate_all_metrics()

    assert result.total_entities >= 3
    assert result.total_relationships >= 2


@pytest.mark.asyncio
async def test_connected_components(entity_repo, setup_test_graph):
    """Test connected components detection."""
    from modules.knowledge.graph.metrics import GraphQualityMetrics

    _, pool, db_type = entity_repo
    metrics = GraphQualityMetrics(pool, db_type=db_type)
    components = await metrics.get_connected_components()

    assert isinstance(components, list)


@pytest.mark.asyncio
async def test_orphan_entities(entity_repo):
    """Test orphan entity detection."""
    from modules.knowledge.graph.metrics import GraphQualityMetrics

    repo, pool, db_type = entity_repo

    # Create orphan entity using EntityRepository
    await repo.merge_entity(
        canonical_name="MetricsTest_Orphan",
        entity_type="人物",
    )

    metrics = GraphQualityMetrics(pool, db_type=db_type)
    orphans = await metrics.find_orphan_entities(limit=10)

    assert isinstance(orphans, list)

    # Cleanup - handle both Neo4j and LadybugDB
    if db_type == "ladybug":
        await pool.execute_query("""
            MATCH (e:Entity {canonical_name: 'MetricsTest_Orphan'})
            DELETE e
        """)
    else:
        await pool.execute_query("""
            MATCH (e:Entity {canonical_name: 'MetricsTest_Orphan'})
            DETACH DELETE e
        """)


@pytest.mark.asyncio
async def test_modularity_calculation(entity_repo, setup_test_graph):
    """Test modularity with real graph."""
    from modules.knowledge.graph.metrics import GraphQualityMetrics

    _, pool, db_type = entity_repo
    metrics = GraphQualityMetrics(pool, db_type=db_type)
    score = await metrics.calculate_modularity()

    assert -1.0 <= score <= 1.0
