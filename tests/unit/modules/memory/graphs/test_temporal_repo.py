# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for TemporalGraphRepo."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.constants import DatabaseType
from modules.memory.core.event_node import EventNode
from modules.memory.graphs.temporal import TemporalGraphRepo


@pytest.fixture
def mock_pool():
    """Create mock Neo4j pool."""
    pool = MagicMock()
    pool.execute_query = AsyncMock()
    return pool


@pytest.fixture
def repo(mock_pool):
    """Create TemporalGraphRepo with mock pool."""
    return TemporalGraphRepo(pool=mock_pool)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_append_to_chain_creates_event_node(repo, mock_pool):
    """Test that append_to_chain creates EventNode in Neo4j."""
    event = EventNode(
        id="event-001",
        content="Test event content",
        timestamp=datetime(2026, 4, 2, 12, 0, 0, tzinfo=UTC),
        attributes={"title": "Test Title"},
    )

    mock_pool.execute_query.return_value = [{"created": "event-001"}]

    result = await repo.append_to_chain(event)

    assert result is True
    mock_pool.execute_query.assert_called_once()

    # Verify query contains EventNode creation
    call_args = mock_pool.execute_query.call_args
    query = call_args[0][0] if call_args[0] else call_args.kwargs.get("query", "")
    assert "EventNode" in query


@pytest.mark.unit
@pytest.mark.asyncio
async def test_append_to_chain_links_to_previous(repo, mock_pool):
    """Test that append_to_chain creates FOLLOWED_BY relationship."""
    event = EventNode(
        id="event-002",
        content="Second event",
        timestamp=datetime(2026, 4, 2, 13, 0, 0, tzinfo=UTC),
    )

    mock_pool.execute_query.return_value = [{"linked": 1}]

    await repo.append_to_chain(event)

    call_args = mock_pool.execute_query.call_args
    query = call_args[0][0] if call_args[0] else call_args.kwargs.get("query", "")
    assert "FOLLOWED_BY" in query


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_temporal_chain(repo, mock_pool):
    """Test retrieving temporal chain of events."""
    mock_pool.execute_query.return_value = [
        {"id": "event-001", "content": "First", "timestamp": "2026-04-02T12:00:00Z"},
        {"id": "event-002", "content": "Second", "timestamp": "2026-04-02T13:00:00Z"},
    ]

    events = await repo.get_temporal_chain(limit=10)

    assert len(events) == 2
    assert events[0]["id"] == "event-001"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_neighbors(repo, mock_pool):
    """Test getting temporal neighbors of an event."""
    mock_pool.execute_query.return_value = [
        {"id": "prev-event", "direction": "previous"},
        {"id": "next-event", "direction": "next"},
    ]

    neighbors = await repo.get_neighbors("event-001")

    assert len(neighbors) == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ensure_constraints(repo, mock_pool):
    """Test that constraints are created."""
    mock_pool.execute_query.return_value = []

    await repo.ensure_constraints()

    # Should be called for constraint creation
    assert mock_pool.execute_query.call_count >= 1


# --- Time-window filtering tests (spec: temporal-search-time-filter-fix) ---


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_events_by_timerange_ladybug():
    """LadybugDB 路径：Cypher 使用 event_time (INT64) 字段过滤，params 为 int。"""
    pool = MagicMock()
    pool.execute_query = AsyncMock(
        return_value=[
            {
                "id": "e1",
                "content": "Event 1",
                "timestamp": 1782400000,
                "attributes": "{}",
            }
        ]
    )
    pool.database_type = DatabaseType.LADYBUG.value
    repo = TemporalGraphRepo(pool=pool)

    await repo.get_events_by_timerange(start_time=1782400000, end_time=1782500000, limit=50)

    call_args = pool.execute_query.call_args
    query = call_args[0][0]
    params = call_args[0][1]
    assert "e.event_time >= $start_time AND e.event_time <= $end_time" in query
    assert "e.timestamp" not in query  # 确保没误用 Neo4j 字段
    assert params["start_time"] == 1782400000
    assert params["end_time"] == 1782500000
    assert params["limit"] == 50
    assert isinstance(params["start_time"], int)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_events_by_timerange_neo4j(repo, mock_pool):
    """Neo4j 路径：Cypher 使用 timestamp 字段过滤，params 为 datetime 对象。

    Neo4j 的 timestamp 属性是 datetime 类型，不能直接和 int 比较否则类型错误。
    实现必须把 int 转成 datetime 传参。
    """
    mock_pool.execute_query.return_value = [
        {
            "id": "e1",
            "content": "Event 1",
            "timestamp": "2026-06-26T00:00:00Z",
            "attributes": "{}",
        }
    ]

    await repo.get_events_by_timerange(start_time=1782400000, end_time=1782500000, limit=100)

    call_args = mock_pool.execute_query.call_args
    query = call_args[0][0]
    params = call_args[0][1]
    assert "e.timestamp >= $start_time AND e.timestamp <= $end_time" in query
    assert "e.event_time" not in query  # 确保没误用 LadybugDB 字段
    assert params["limit"] == 100
    # Neo4j 路径必须把 int 转成 datetime，否则 Cypher 类型不匹配
    assert isinstance(params["start_time"], datetime)
    assert isinstance(params["end_time"], datetime)
    assert int(params["start_time"].timestamp()) == 1782400000
    assert int(params["end_time"].timestamp()) == 1782500000


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_events_by_timerange_empty(repo, mock_pool):
    """空窗口返回空列表。"""
    mock_pool.execute_query.return_value = []

    result = await repo.get_events_by_timerange(
        start_time=1782400000, end_time=1782400001, limit=10
    )

    assert result == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_temporal_events_with_time_window(repo, mock_pool):
    """带时间窗口的 search：WHERE 包含时间谓词，params 含 datetime 类型时间参数。"""
    mock_pool.execute_query.return_value = [
        {
            "id": "e1",
            "content": "AI breakthrough",
            "timestamp": "2026-06-26T00:00:00Z",
            "attributes": "{}",
        }
    ]

    await repo.search_temporal_events(
        query="AI",
        limit=10,
        start_time=1782400000,
        end_time=1782500000,
    )

    call_args = mock_pool.execute_query.call_args
    query = call_args[0][0]
    params = call_args[0][1]
    assert "e.timestamp >= $start_time AND e.timestamp <= $end_time" in query
    assert params["query"] == "AI"
    assert params["limit"] == 10
    # Neo4j 路径 params 为 datetime
    assert isinstance(params["start_time"], datetime)
    assert isinstance(params["end_time"], datetime)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_temporal_events_without_time_window_backward_compat(repo, mock_pool):
    """不传时间参数时 WHERE 不含时间条件（向后兼容）。

    验证 task 2.2 的向后兼容承诺：start_time/end_time 为 None 时
    查询行为与修改前一致，不引入时间过滤。
    """
    mock_pool.execute_query.return_value = []

    await repo.search_temporal_events(query="AI", limit=10)

    call_args = mock_pool.execute_query.call_args
    query = call_args[0][0]
    params = call_args[0][1]
    # WHERE 子句不含时间谓词
    assert "start_time" not in query
    assert "end_time" not in query
    assert "$start_time" not in query
    assert "$end_time" not in query
    # params 也不含时间参数
    assert "start_time" not in params
    assert "end_time" not in params
    assert params["query"] == "AI"
    assert params["limit"] == 10


# --- D1 semantic re-ranking tests (spec: search-engine) ---


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_temporal_events_uses_query_embedding(repo, mock_pool):
    """query_embedding 提供时按余弦相似度降序重排（D1 / Task 2.3-2.5）。

    构造 3 个候选事件，故意按时间戳升序排列（alpha<beta<gamma），
    但语义相似度顺序为 alpha > gamma > beta。重排后应得到
    [alpha, gamma, beta]，且每个结果携带 ``similarity_score``。
    """
    # query 沿 x 轴对齐：sim(alpha) > sim(gamma) > sim(beta)
    query_embedding = [1.0, 0.0, 0.0, 0.0]
    mock_pool.execute_query.return_value = [
        {
            "id": "alpha",
            "content": "alpha event",
            "timestamp": "2026-06-01T00:00:00Z",
            "attributes": "{}",
            "embedding": [0.9, 0.1, 0.0, 0.0],
        },
        {
            "id": "beta",
            "content": "beta event",
            "timestamp": "2026-06-02T00:00:00Z",
            "attributes": "{}",
            "embedding": [0.0, 0.9, 0.1, 0.0],
        },
        {
            "id": "gamma",
            "content": "gamma event",
            "timestamp": "2026-06-03T00:00:00Z",
            "attributes": "{}",
            "embedding": [0.5, 0.5, 0.5, 0.5],
        },
    ]

    results = await repo.search_temporal_events(
        query="event",
        limit=10,
        query_embedding=query_embedding,
    )

    # 重排后顺序应为 alpha > gamma > beta（按相似度）
    assert [r["id"] for r in results] == ["alpha", "gamma", "beta"]
    # 所有结果都携带 similarity_score
    assert all("similarity_score" in r for r in results)
    # alpha 相似度最高，beta 最低（query 与 beta 正交）
    assert results[0]["similarity_score"] > results[1]["similarity_score"]
    assert results[1]["similarity_score"] > results[2]["similarity_score"]
    # beta 与 query 正交，相似度应为 0
    assert results[2]["similarity_score"] == 0.0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_temporal_events_query_embedding_with_missing_persistence(repo, mock_pool):
    """query_embedding 提供但 EventNode 未持久化 embedding 时，使用 embed_batch 兜底（Q2）。

    场景：图 DB 中部分事件的 embedding 字段为 None（老数据）。
    当 embedding_service 提供时，应调用 embed_batch 计算缺失 embedding，
    并按计算结果重排，而不是直接返回 0 相似度。
    """
    query_embedding = [1.0, 0.0]

    # Mock embedding_service: 返回与 query 对齐的 embedding（高相似度）
    embedding_service = MagicMock()
    embedding_service.embed_batch = AsyncMock(return_value=[[0.95, 0.05], [0.05, 0.95]])

    mock_pool.execute_query.return_value = [
        {
            "id": "no-emb-1",
            "content": "missing embedding event 1",
            "timestamp": "2026-06-01T00:00:00Z",
            "attributes": "{}",
            "embedding": None,  # 老数据，未持久化
        },
        {
            "id": "no-emb-2",
            "content": "missing embedding event 2",
            "timestamp": "2026-06-02T00:00:00Z",
            "attributes": "{}",
            "embedding": None,
        },
    ]

    results = await repo.search_temporal_events(
        query="event",
        limit=10,
        query_embedding=query_embedding,
        embedding_service=embedding_service,
    )

    # embed_batch 被调用一次，参数为缺失 embedding 的 content 列表
    embedding_service.embed_batch.assert_awaited_once_with(
        ["missing embedding event 1", "missing embedding event 2"]
    )
    # 第一个事件计算出的 embedding 与 query 对齐，相似度最高
    assert results[0]["id"] == "no-emb-1"
    assert results[0]["similarity_score"] > results[1]["similarity_score"]
    # 计算出的 embedding 写回到结果中（供下游 EventNode 构造使用）
    assert results[0]["embedding"] == [0.95, 0.05]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_temporal_events_no_embedding_falls_back_to_contains(repo, mock_pool):
    """query_embedding=None 时保留旧行为：CONTAINS + timestamp 排序（Task 2.4）。

    关键断言：
    1. 结果中不应添加 ``similarity_score`` 字段（避免误导下游）
    2. 结果顺序应保持图 DB 返回的顺序（按 timestamp ASC）
    3. 不应调用 embedding_service.embed_batch（语义重排逻辑未触发）
    """
    embedding_service = MagicMock()
    embedding_service.embed_batch = AsyncMock(return_value=[])

    mock_pool.execute_query.return_value = [
        {
            "id": "first",
            "content": "event one",
            "timestamp": "2026-06-01T00:00:00Z",
            "attributes": "{}",
            "embedding": [0.1, 0.2, 0.3],
        },
        {
            "id": "second",
            "content": "event two",
            "timestamp": "2026-06-02T00:00:00Z",
            "attributes": "{}",
            "embedding": [0.4, 0.5, 0.6],
        },
    ]

    results = await repo.search_temporal_events(
        query="event",
        limit=10,
        embedding_service=embedding_service,
    )

    # 顺序保持图 DB 返回顺序（timestamp ASC）
    assert [r["id"] for r in results] == ["first", "second"]
    # 不应添加 similarity_score 字段
    assert all("similarity_score" not in r for r in results)
    # 不应调用 embed_batch
    embedding_service.embed_batch.assert_not_called()


# --- D2 EventNode embedding persistence tests (spec: event-node-integration) ---


@pytest.mark.unit
@pytest.mark.asyncio
async def test_append_to_chain_persists_embedding_neo4j(repo, mock_pool):
    """Neo4j 写入路径持久化 EventNode embedding（D2 / Task 6.2-6.4）。

    旧行为：``ON CREATE SET`` 不包含 embedding，EventNode 永远无 embedding
    属性（Q2 finding），导致 search_temporal_events 的 query_embedding 重排
    必须依赖 embedding_service.embed_batch 兜底。
    新行为：Cypher SET 子句包含 ``e.embedding = $embedding``，params 透传
    ``event.embedding``，让 anchor 搜索能直接复用持久化向量。
    """
    embedding = [0.1, 0.2, 0.3, 0.4]
    event = EventNode(
        id="event-with-emb",
        content="event with embedding",
        timestamp=datetime(2026, 6, 26, 12, 0, 0, tzinfo=UTC),
        embedding=embedding,
    )
    mock_pool.execute_query.return_value = [{"created": "event-with-emb"}]

    await repo.append_to_chain(event)

    call_args = mock_pool.execute_query.call_args
    query = call_args[0][0]
    params = call_args[0][1]
    # Cypher SET 子句必须包含 embedding（ON CREATE + ON MATCH 两个分支）
    assert "e.embedding = $embedding" in query
    assert "CASE WHEN $embedding IS NOT NULL THEN $embedding ELSE e.embedding END" in query
    # params 透传 embedding（不是 None）
    assert params["embedding"] == embedding


@pytest.mark.unit
@pytest.mark.asyncio
async def test_append_to_chain_persists_embedding_ladybug():
    """LadybugDB 写入路径持久化 EventNode embedding（D2 / Task 6.2-6.4）。

    LadybugDB 使用 ``CREATE (e:EventNode {..., embedding: $embedding})``
    语法，schema 中 EventNode 表已添加 ``embedding DOUBLE[]`` 列
    （见 ladybug_schema.py）。

    Mock 策略：LadybugDB 写入路径有 3 次 execute_query
    1. check existence → 返回 [] （不存在，继续创建）
    2. find previous → 返回 [] （无前驱事件）
    3. CREATE EventNode → 返回 [{"id": "event-emb-lb"}]
    """
    pool = MagicMock()
    # 按调用顺序返回：existence_check=[], find_prev=[], create=[{...}]
    pool.execute_query = AsyncMock(
        side_effect=[
            [],  # check existence → not exists
            [],  # find previous event → none
            [{"e.id": "event-emb-lb"}],  # CREATE returns
        ]
    )
    pool.database_type = DatabaseType.LADYBUG.value
    repo = TemporalGraphRepo(pool=pool)

    embedding = [0.5, 0.6, 0.7]
    event = EventNode(
        id="event-emb-lb",
        content="ladybug event with embedding",
        timestamp=datetime(2026, 6, 26, 13, 0, 0, tzinfo=UTC),
        embedding=embedding,
    )

    await repo.append_to_chain(event)

    # 第 3 次调用是 CREATE EventNode
    create_call = pool.execute_query.call_args_list[2]
    create_query = create_call[0][0]
    create_params = create_call[0][1]
    assert "CREATE" in create_query
    assert "EventNode" in create_query
    # CREATE 语句包含 embedding 字段
    assert "embedding: $embedding" in create_query
    # params 透传 embedding
    assert create_params["embedding"] == embedding


@pytest.mark.unit
@pytest.mark.asyncio
async def test_append_to_chain_embedding_none_does_not_fail(repo, mock_pool):
    """EventNode embedding=None 时写入不失败（Task 6.3 向后兼容）。

    老的 pipeline state 无 vectors.content，EventNode.embedding=None。
    Cypher 写入 null property 应被接受（Neo4j/LadybugDB 均支持）。
    """
    event = EventNode(
        id="event-no-emb",
        content="event without embedding",
        timestamp=datetime(2026, 6, 26, 14, 0, 0, tzinfo=UTC),
        embedding=None,
    )
    mock_pool.execute_query.return_value = [{"created": "event-no-emb"}]

    result = await repo.append_to_chain(event)

    assert result is True
    params = mock_pool.execute_query.call_args[0][1]
    assert params["embedding"] is None
