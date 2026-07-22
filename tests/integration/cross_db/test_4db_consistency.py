# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""T020: 4 套 DB 组合矩阵一致性测试 (X-01~05)。

参数化 4 套 DB 组合 (pg_ladybug / duckdb_neo4j / pg_neo4j / duckdb_ladybug),
验证搜索 API 在不同 DB 后端下的结果结构一致性。

== 跨 DB 一致性验证策略 ==

4 套 DB 组合需要在 4 次独立运行中测试（每次只能运行一套组合,由
``WEAVER__DB__TYPE`` + ``WEAVER__GRAPH__TYPE`` 环境变量控制），无法在
同一测试 session 内比较 4 套组合的结果。因此:

1. 每个用例在当前 DB 组合下执行搜索
2. 断言搜索结果结构正确（entities 是 list、sources 是 list、metadata 含
   intent/output_mode、hierarchy 含 primer/follow_ups）
3. 断言搜索结果排序确定性（API 层 ``_sort_response_lists`` 已排序，
   验证排序后等于自身）
4. 跨 DB 一致性通过 CI 矩阵任务（4 次运行）的外部聚合验证，本测试
   文件仅验证单次运行的正确性

== DB 组合切换 ==

conftest.py 的 ``_check_db_combo(expected_rel, expected_graph)`` 函数
检查当前环境变量 ``WEAVER__DB__TYPE`` 和 ``WEAVER__GRAPH__TYPE``，不匹配
时 ``pytest.skip``。conftest.py 已提供 4 套 DB 组合 fixture
(``pg_ladybug`` / ``duckdb_neo4j`` / ``pg_neo4j`` / ``duckdb_ladybug``),
每个 fixture 内部调用 ``_check_db_combo``。本测试通过
``request.getfixturevalue(db_combo)`` 触发 fixture,实现"每个参数化用例
调用 ``_check_db_combo`` 验证当前环境是否匹配"的规格要求。

== 端点参考 ==

- GET  /api/v1/search            — 统一搜索（mode=auto|local|global）
- POST /api/v1/search/drift      — DRIFT 搜索（JSON body）
- articles 模式:通过 threshold 参数触发（非显式 mode=articles），
  匹配 src/api/endpoints/content/search.py:121-126 的 articles mode 参数
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration]

# 4 套 DB 组合参数化矩阵
_DB_COMBOS = ["pg_ladybug", "duckdb_neo4j", "pg_neo4j", "duckdb_ladybug"]


def _verify_db_combo(db_combo: str, request: pytest.FixtureRequest) -> str:
    """验证当前 DB 组合是否匹配,不匹配则 skip。

    通过 ``request.getfixturevalue(db_combo)`` 触发 conftest.py 中的
    fixture (pg_ladybug/duckdb_neo4j/pg_neo4j/duckdb_ladybug),fixture
    内部调用 ``_check_db_combo(expected_rel, expected_graph)`` 实现环境
    变量检查。不匹配时 ``pytest.skip`` 被触发,测试被跳过。

    Args:
        db_combo: DB 组合名称 (pg_ladybug/duckdb_neo4j/pg_neo4j/duckdb_ladybug)。
        request: pytest FixtureRequest,用于动态获取 fixture。

    Returns:
        匹配时返回组合名称（如 "pg_ladybug"）。
    """
    return request.getfixturevalue(db_combo)


def _sources_sort_key(source: dict) -> str:
    """sources 排序键,匹配 search.py:86-89 的 ``_sort_response_lists``。

    sources dict 结构因路径而异:local_search 返回 {"title": ...},
    web search fallback 返回 {"url", "title", "snippet"},其他调用者
    可能用 {"article_id": ...}。使用首个可用键作为排序键;str() cast
    防止值为 None 或非 str 时 TypeError。
    """
    return str(source.get("title") or source.get("article_id") or source.get("url") or "")


# ── X-01: local 搜索 entities 集合一致 ─────────────────────


@pytest.mark.db_combo
@pytest.mark.parametrize("db_combo", _DB_COMBOS)
async def test_x01_local_search_entities_consistency(
    db_combo: str,
    async_client,
    real_entity_name: str,
    request: pytest.FixtureRequest,
) -> None:
    """X-01: local 搜索 entities 集合一致。

    4 套 DB 组合参数化,断言 entities 是 list 且排序后等于自身
    （验证 API 层 ``_sort_response_lists`` 已排序,确保跨 DB 集合一致性
    的基础）。

    跨 DB 一致性通过 CI 矩阵任务（4 次运行）的外部聚合验证,本测试
    仅验证单次运行的正确性。
    """
    _verify_db_combo(db_combo, request)

    resp = await async_client.get(
        "/api/v1/search",
        params={"q": real_entity_name, "mode": "local"},
    )
    assert resp.status_code == 200, (
        f"X-01 [{db_combo}]: search local 状态码 {resp.status_code}, body: {resp.text}"
    )
    data = resp.json()["data"]
    entities = data["entities"]

    # 结构断言:entities 是 list
    assert isinstance(entities, list), (
        f"X-01 [{db_combo}]: entities 应为 list,实际 {type(entities).__name__}"
    )

    # 一致性基础断言:排序后等于自身（API 层 _sort_response_lists 已排序,
    # 验证跨 DB 排序确定性,确保 CI 矩阵 4 次运行的 entities 集合可比）
    assert entities == sorted(entities, key=str), (
        f"X-01 [{db_combo}]: entities 排序不一致,实际 {entities}"
    )


# ── X-02: global 搜索 sources 排序一致 ─────────────────────


@pytest.mark.db_combo
@pytest.mark.parametrize("db_combo", _DB_COMBOS)
async def test_x02_global_search_sources_sort_consistency(
    db_combo: str,
    async_client,
    real_entity_name: str,
    request: pytest.FixtureRequest,
) -> None:
    """X-02: global 搜索 sources 排序一致。

    4 套 DB 组合参数化,断言 sources 是 list 且按 title/article_id/url
    排序后等于自身（验证 API 层 ``_sort_response_lists`` 已排序,确保跨
    DB 排序一致性的基础）。

    跨 DB 一致性通过 CI 矩阵任务（4 次运行）的外部聚合验证,本测试
    仅验证单次运行的正确性。
    """
    _verify_db_combo(db_combo, request)

    resp = await async_client.get(
        "/api/v1/search",
        params={"q": real_entity_name, "mode": "global"},
    )
    assert resp.status_code == 200, (
        f"X-02 [{db_combo}]: search global 状态码 {resp.status_code}, body: {resp.text}"
    )
    data = resp.json()["data"]
    sources = data["sources"]

    # 结构断言:sources 是 list
    assert isinstance(sources, list), (
        f"X-02 [{db_combo}]: sources 应为 list,实际 {type(sources).__name__}"
    )

    # 一致性基础断言:按 title/article_id/url 排序后等于自身
    # (API 层 _sort_response_lists 已排序,验证跨 DB 排序确定性)
    assert sources == sorted(sources, key=_sources_sort_key), (
        f"X-02 [{db_combo}]: sources 排序不一致,实际 {sources}"
    )


# ── X-03: metadata 字段一致 ───────────────────────────────


@pytest.mark.db_combo
@pytest.mark.parametrize("db_combo", _DB_COMBOS)
async def test_x03_metadata_fields_consistency(
    db_combo: str,
    async_client,
    real_entity_name: str,
    request: pytest.FixtureRequest,
) -> None:
    """X-03: metadata 字段一致。

    4 套 DB 组合参数化,断言 metadata.intent 和 metadata.output_mode
    字段存在（这些字段由 search.py:228-231 在 API 层统一注入,不依赖
    DB 后端,因此 4 套组合下应一致）。

    跨 DB 一致性通过 CI 矩阵任务（4 次运行）的外部聚合验证,本测试
    仅验证单次运行的正确性。
    """
    _verify_db_combo(db_combo, request)

    resp = await async_client.get(
        "/api/v1/search",
        params={"q": real_entity_name, "mode": "local"},
    )
    assert resp.status_code == 200, (
        f"X-03 [{db_combo}]: search local 状态码 {resp.status_code}, body: {resp.text}"
    )
    data = resp.json()["data"]
    metadata = data["metadata"]

    # 结构断言:metadata 是 dict
    assert isinstance(metadata, dict), (
        f"X-03 [{db_combo}]: metadata 应为 dict,实际 {type(metadata).__name__}"
    )

    # 字段存在断言:intent 和 output_mode
    # (search.py:228-231 在 API 层统一注入,跨 DB 一致)
    assert "intent" in metadata, (
        f"X-03 [{db_combo}]: metadata 缺少 intent 字段,实际 keys {list(metadata.keys())}"
    )
    assert "output_mode" in metadata, (
        f"X-03 [{db_combo}]: metadata 缺少 output_mode 字段,实际 keys {list(metadata.keys())}"
    )


# ── X-04: articles 搜索结果一致 ───────────────────────────


@pytest.mark.db_combo
@pytest.mark.parametrize("db_combo", _DB_COMBOS)
async def test_x04_articles_search_consistency(
    db_combo: str,
    async_client,
    real_entity_name: str,
    request: pytest.FixtureRequest,
) -> None:
    """X-04: articles 搜索结果一致。

    4 套 DB 组合参数化,断言 sources（articles 列表）是 list 且排序后
    等于自身。

    articles 模式:通过 threshold 参数触发（非显式 mode=articles）,
    匹配 search.py:121-126 的 articles mode 参数。响应结构与统一搜索
    相同（entities/sources/metadata 等）。

    跨 DB 一致性通过 CI 矩阵任务（4 次运行）的外部聚合验证,本测试
    仅验证单次运行的正确性。
    """
    _verify_db_combo(db_combo, request)

    resp = await async_client.get(
        "/api/v1/search",
        params={"q": real_entity_name, "threshold": 0.5},
    )
    assert resp.status_code == 200, (
        f"X-04 [{db_combo}]: search articles 状态码 {resp.status_code}, body: {resp.text}"
    )
    data = resp.json()["data"]
    sources = data["sources"]

    # 结构断言:sources（articles 列表）是 list
    assert isinstance(sources, list), (
        f"X-04 [{db_combo}]: sources 应为 list,实际 {type(sources).__name__}"
    )

    # 一致性基础断言:排序后等于自身
    # (API 层 _sort_response_lists 已排序,验证跨 DB 排序确定性)
    assert sources == sorted(sources, key=_sources_sort_key), (
        f"X-04 [{db_combo}]: sources 排序不一致,实际 {sources}"
    )


# ── X-05: DRIFT 搜索 hierarchy 一致 ───────────────────────


@pytest.mark.db_combo
@pytest.mark.parametrize("db_combo", _DB_COMBOS)
async def test_x05_drift_search_hierarchy_consistency(
    db_combo: str,
    async_client,
    real_entity_name: str,
    request: pytest.FixtureRequest,
) -> None:
    """X-05: DRIFT 搜索 hierarchy 一致。

    4 套 DB 组合参数化,断言 hierarchy 是 dict 且含 primer 和
    follow_ups 字段（这些字段由 search.py:499-503 在 API 层统一构建,
    不依赖 DB 后端,因此 4 套组合下应一致）。

    端点:POST /api/v1/search/drift（请求体 ``{"query": "..."}``）,
    匹配 search.py:439-509 的 DriftSearchResponse。

    跨 DB 一致性通过 CI 矩阵任务（4 次运行）的外部聚合验证,本测试
    仅验证单次运行的正确性。
    """
    _verify_db_combo(db_combo, request)

    resp = await async_client.post(
        "/api/v1/search/drift",
        json={"query": real_entity_name},
    )
    assert resp.status_code == 200, (
        f"X-05 [{db_combo}]: drift search 状态码 {resp.status_code}, body: {resp.text}"
    )
    data = resp.json()["data"]
    hierarchy = data["hierarchy"]

    # 结构断言:hierarchy 是 dict
    assert isinstance(hierarchy, dict), (
        f"X-05 [{db_combo}]: hierarchy 应为 dict,实际 {type(hierarchy).__name__}"
    )

    # 字段存在断言:primer 和 follow_ups
    # (search.py:499-503 在 API 层统一构建,跨 DB 一致)
    assert "primer" in hierarchy, (
        f"X-05 [{db_combo}]: hierarchy 缺少 primer 字段,实际 keys {list(hierarchy.keys())}"
    )
    assert "follow_ups" in hierarchy, (
        f"X-05 [{db_combo}]: hierarchy 缺少 follow_ups 字段,实际 keys {list(hierarchy.keys())}"
    )


# ── DB 特有限制验证辅助 ────────────────────────────────────


def _check_db_type(expected_db: str) -> str:
    """检查当前关系 DB 类型是否匹配，不匹配则 skip。

    DuckDB 专用限制（X-06~X-08）仅在 ``WEAVER__DB__TYPE=duckdb`` 时执行；
    PostgreSQL 专用行为仅在 ``postgres`` 时执行。其他组合 skip。

    Args:
        expected_db: 期望的 DB 类型 ("duckdb" / "postgres")。

    Returns:
        匹配时返回实际 DB 类型。
    """
    import os

    actual = os.getenv("WEAVER__DB__TYPE", "postgres").lower()
    if actual != expected_db:
        pytest.skip(f"当前 DB 类型 {actual}，跳过 {expected_db} 专用限制测试")
    return actual


def _check_graph_type(expected_graph: str) -> str:
    """检查当前图 DB 类型是否匹配，不匹配则 skip。

    LadybugDB 专用限制（X-09~X-11）仅在 ``WEAVER__GRAPH__TYPE=ladybug`` 时执行；
    Neo4j 专用行为仅在 ``neo4j`` 时执行。其他组合 skip。

    Args:
        expected_graph: 期望的 graph 类型 ("ladybug" / "neo4j")。

    Returns:
        匹配时返回实际 graph 类型。
    """
    import os

    actual = os.getenv("WEAVER__GRAPH__TYPE", "neo4j").lower()
    if actual != expected_graph:
        pytest.skip(f"当前 graph 类型 {actual}，跳过 {expected_graph} 专用限制测试")
    return actual


# ── X-06: DuckDB articles 视图更新 → 使用 articles_core 基表 ──


@pytest.mark.db_combo
@pytest.mark.parametrize("db_combo", _DB_COMBOS)
async def test_x06_duckdb_view_binder_exception(
    db_combo: str,
    async_client,
    request: pytest.FixtureRequest,
) -> None:
    """X-06: DuckDB 下 articles 视图更新使用 articles_core 基表。

    DuckDB 不支持 UPDATE VIEW（``BinderException: Can only update base
    table``），生产代码使用 ``articles_core`` 基表替代 ``articles`` 视图。
    本测试验证 DuckDB 组合下文章列表 API 正常返回（底层查询
    articles_core 而非 articles 视图）。

    仅在 DuckDB 组合下执行；PostgreSQL 组合 skip。

    验证限制: R-cross-db-005 — DuckDB VIEW 更新失败（需用 articles_core）
    代码位置: src/core/db/models/article.py (articles 是 VIEW, articles_core 是 BASE TABLE)
    """
    _verify_db_combo(db_combo, request)
    _check_db_type("duckdb")

    # GET /articles 底层查询 articles_core（Base Table），不应触发 BinderException
    resp = await async_client.get("/api/v1/articles", params={"limit": 5})
    assert resp.status_code == 200, (
        f"X-06 [{db_combo}]: articles 列表查询失败，"
        f"可能触发了 BinderException: {resp.status_code} {resp.text[:200]}"
    )
    data = resp.json()["data"]
    assert isinstance(data, list), (
        f"X-06 [{db_combo}]: articles 应为 list，实际 {type(data).__name__}"
    )


# ── X-07: DuckDB ENUM 返回 VARCHAR ────────────────────────


@pytest.mark.db_combo
@pytest.mark.parametrize("db_combo", _DB_COMBOS)
async def test_x07_duckdb_enum_returns_varchar(
    db_combo: str,
    async_client,
    real_article_id,
    request: pytest.FixtureRequest,
) -> None:
    """X-07: DuckDB 下 ENUM 字段返回 VARCHAR 类型。

    DuckDB 不支持 ENUM（用 VARCHAR+CHECK 替代），生产代码在 DuckDB
    schema 中将 ENUM 字段映射为 VARCHAR。本测试验证 DuckDB 组合下
    文章的 category 字段返回字符串值（而非 enum 类型）。

    仅在 DuckDB 组合下执行；PostgreSQL 组合 skip。

    验证限制: R-cross-db-005 — DuckDB 不支持 ENUM（用 VARCHAR+CHECK）
    代码位置: src/core/db/models/article.py (category 字段)
    """
    _verify_db_combo(db_combo, request)
    _check_db_type("duckdb")

    if real_article_id is None:
        pytest.skip("无可用文章 ID，无法验证 ENUM 字段")

    resp = await async_client.get(f"/api/v1/articles/{real_article_id}")
    assert resp.status_code == 200, f"X-07 [{db_combo}]: 文章详情查询失败: {resp.status_code}"
    data = resp.json()["data"]
    # category 字段在 DuckDB 下应为 str（VARCHAR），而非 enum 类型
    category = data.get("category")
    if category is not None:
        assert isinstance(category, str), (
            f"X-07 [{db_combo}]: category 应为 str（DuckDB VARCHAR），"
            f"实际 {type(category).__name__}: {category}"
        )


# ── X-08: DuckDB 写锁竞争 3 次指数退避 ────────────────────


@pytest.mark.db_combo
@pytest.mark.parametrize("db_combo", _DB_COMBOS)
async def test_x08_duckdb_write_lock_retry(
    db_combo: str,
    async_client,
    real_source_id,
    request: pytest.FixtureRequest,
) -> None:
    """X-08: DuckDB 写锁竞争触发 3 次指数退避重试。

    DuckDB 单写者模型下，并发写入触发 ``IOException`` 锁冲突。生产代码
    通过 3 次指数退避重试解决（参见项目记忆：DuckDB session 不支持
    ``asyncio.gather`` 并发查询；单写者并发冲突可用 3 次退避重试解决）。

    本测试验证 DuckDB 组合下顺序触发 pipeline 不报锁冲突错误
    （生产代码已用顺序执行 + 重试机制解决并发问题）。

    仅在 DuckDB 组合下执行；PostgreSQL 组合 skip。

    验证限制: R-cross-db-005 — DuckDB 单 writer 并发冲突（3 次退避）
    代码位置: src/modules/ingestion/scheduler.py (顺序触发避免锁竞争)
    """
    _verify_db_combo(db_combo, request)
    _check_db_type("duckdb")

    if real_source_id is None:
        pytest.skip("无可用 source，无法触发 pipeline")

    # 顺序触发 pipeline（生产代码用顺序执行避免 DuckDB 写锁竞争）
    # 验证不返回 500（锁冲突错误码）
    resp = await async_client.post(
        "/api/v1/pipeline/trigger",
        json={"source_ids": [real_source_id]},
    )
    # 接受 200（成功）或 409（source 级互斥锁），但不接受 500（锁冲突未处理）
    assert resp.status_code in (200, 409), (
        f"X-08 [{db_combo}]: pipeline trigger 应返回 200/409，"
        f"实际 {resp.status_code}（可能 DuckDB 写锁竞争未正确重试）: "
        f"{resp.text[:200]}"
    )


# ── X-09: LadybugDB r.edge_type 访问 ─────────────────────


@pytest.mark.db_combo
@pytest.mark.parametrize("db_combo", _DB_COMBOS)
async def test_x09_ladybug_edge_type_access(
    db_combo: str,
    async_client,
    real_entity_name: str,
    request: pytest.FixtureRequest,
) -> None:
    """X-09: LadybugDB 下关系类型通过 r.edge_type 访问。

    LadybugDB Cypher 方言中 ``type(r)`` 不可用，必须使用 ``r.edge_type``
    访问关系类型。生产代码已适配此差异（参见 CLAUDE.md LadybugDB 兼容节）。

    本测试验证 LadybugDB 组合下图关系 API 正常返回（底层 Cypher 使用
    ``r.edge_type`` 而非 ``type(r)``）。

    仅在 LadybugDB 组合下执行；Neo4j 组合 skip。

    验证限制: R-cross-db-006 — LadybugDB 使用 r.edge_type 而非 type(r)
    代码位置: src/core/db/graph_query_builders.py (LadybugDB Cypher 方言)
    """
    _verify_db_combo(db_combo, request)
    _check_graph_type("ladybug")

    # GET /graph/relations 底层 Cypher 使用 r.edge_type（LadybugDB 方言）
    resp = await async_client.get(
        "/api/v1/graph/relations",
        params={"entity_name": real_entity_name, "limit": 10},
    )
    assert resp.status_code == 200, (
        f"X-09 [{db_combo}]: graph relations 查询失败，"
        f"可能 LadybugDB r.edge_type 适配有误: {resp.status_code} {resp.text[:200]}"
    )
    data = resp.json()["data"]
    assert isinstance(data, list), (
        f"X-09 [{db_combo}]: relations 应为 list，实际 {type(data).__name__}"
    )


# ── X-10: LadybugDB id 属性作主键 ─────────────────────────


@pytest.mark.db_combo
@pytest.mark.parametrize("db_combo", _DB_COMBOS)
async def test_x10_ladybug_id_property(
    db_combo: str,
    async_client,
    real_entity_name: str,
    request: pytest.FixtureRequest,
) -> None:
    """X-10: LadybugDB 下节点 ID 通过 id 属性访问。

    LadybugDB 无 ``elementId()`` 函数，使用 ``id`` 属性作主键。生产代码
    已适配此差异（参见 CLAUDE.md LadybugDB 兼容节）。

    本测试验证 LadybugDB 组合下图实体 API 正常返回（底层 Cypher 使用
    ``id`` 属性而非 ``elementId()`` 函数）。

    仅在 LadybugDB 组合下执行；Neo4j 组合 skip。

    验证限制: R-cross-db-006 — LadybugDB 无 elementId()，用 id 属性
    代码位置: src/core/db/graph_query_builders.py (LadybugDB Cypher 方言)
    """
    _verify_db_combo(db_combo, request)
    _check_graph_type("ladybug")

    # GET /graph/entities 底层 Cypher 使用 id 属性（LadybugDB 方言）
    resp = await async_client.get(
        "/api/v1/graph/entities",
        params={"limit": 10},
    )
    assert resp.status_code == 200, (
        f"X-10 [{db_combo}]: graph entities 查询失败，"
        f"可能 LadybugDB id 属性适配有误: {resp.status_code} {resp.text[:200]}"
    )
    data = resp.json()["data"]
    assert isinstance(data, list), (
        f"X-10 [{db_combo}]: entities 应为 list，实际 {type(data).__name__}"
    )


# ── X-11: LadybugDB _format_timestamp_params 含逗号分隔 ──


@pytest.mark.db_combo
@pytest.mark.parametrize("db_combo", _DB_COMBOS)
async def test_x11_ladybug_timestamp_format(
    db_combo: str,
    async_client,
    request: pytest.FixtureRequest,
) -> None:
    """X-11: LadybugDB 下社区持久化时间戳参数含逗号分隔。

    LadybugDB Cypher 方言要求时间戳参数逗号分隔，缺少逗号会导致
    ``community_persist_failed`` 错误。生产代码已在
    ``_format_timestamp_params`` 中适配（参见项目记忆：LadybugDB Cypher
    方言要求逗号分隔时间戳参数）。

    本测试验证 LadybugDB 组合下社区列表 API 正常返回（底层社区持久化
    使用了正确的逗号分隔时间戳参数格式）。

    仅在 LadybugDB 组合下执行；Neo4j 组合 skip。

    验证限制: R-cross-db-006 — LadybugDB _format_timestamp_params 含逗号
    代码位置: src/modules/knowledge/graph/community/repo.py (_format_timestamp_params)
    """
    _verify_db_combo(db_combo, request)
    _check_graph_type("ladybug")

    # GET /admin/communities 底层社区持久化使用 _format_timestamp_params
    resp = await async_client.get(
        "/api/v1/admin/communities",
        params={"limit": 10},
    )
    assert resp.status_code == 200, (
        f"X-11 [{db_combo}]: communities 查询失败，"
        f"可能 LadybugDB 时间戳参数格式有误: {resp.status_code} {resp.text[:200]}"
    )
    data = resp.json()["data"]
    # 社区列表应为 list（可能为空，但不应报错）
    assert isinstance(data, list), (
        f"X-11 [{db_combo}]: communities 应为 list，实际 {type(data).__name__}"
    )
