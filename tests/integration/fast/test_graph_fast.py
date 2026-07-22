# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""F-G-01~11: Graph API 集成测试（Fast 层）。

覆盖实体、关系、遍历、指标、可视化等图谱 API 端点。边界用例
（limit=0 / max_hops=-1 / max_depth=-1 → 422）合并到对应主用例中。

端点映射说明
-------------
任务描述中部分端点路径与代码实际实现不一致，已按实际路由调整：

- F-G-04 文章图谱：实际路径 ``/graph/articles/{article_id}/graph``（带 ``/graph`` 后缀）。
- F-G-05 关系类型发现：``/graph/types/discover`` 不存在；改用 ``GET /graph/relations``
  （返回某实体的关系类型摘要列表，即 RelationTypeSummary）。
- F-G-06 关系类型搜索：``/graph/types/search`` 不存在；改用 ``GET /graph/relations/search``
  （按关系类型搜索关联实体）。
- F-G-07/08 图遍历：``/graph/traverse`` 实际为 POST，请求体为 TraverseRequest；
  任务中的 ``max_hops`` 对应 schema 的 ``max_depth``。
- F-G-11 子图提取：``/graph/visualization/subgraph`` 实际为 POST ``/graph/visualization``
  （SubgraphRequest 请求体）。
"""

from __future__ import annotations

import urllib.parse

import pytest


@pytest.mark.integration
async def test_fg_01_list_entities(async_client):
    """F-G-01: 实体列表 limit=10，断言 200 + data 是列表。

    边界: limit=0 → 422（Query ``ge=1`` 校验）。
    """
    resp = await async_client.get("/api/v1/graph/entities", params={"limit": 10})
    assert resp.status_code == 200
    data = resp.json().get("data", [])
    assert isinstance(data, list)

    # 边界: limit=0 → 422
    resp_invalid = await async_client.get("/api/v1/graph/entities", params={"limit": 0})
    assert resp_invalid.status_code == 422


@pytest.mark.integration
async def test_fg_02_entity_detail(async_client, real_entity_name):
    """F-G-02: 实体详情，断言 200。"""
    encoded = urllib.parse.quote(real_entity_name, safe="")
    resp = await async_client.get(f"/api/v1/graph/entities/{encoded}")
    assert resp.status_code == 200


@pytest.mark.integration
async def test_fg_03_relations(async_client, real_entity_name):
    """F-G-03: 关系列表，断言 200。"""
    resp = await async_client.get("/api/v1/graph/relations", params={"entity": real_entity_name})
    assert resp.status_code == 200


@pytest.mark.integration
async def test_fg_04_article_graph(async_client, real_article_id):
    """F-G-04: 文章图谱，断言 200。

    使用 ``real_article_id`` fixture（无文章时自动 skip）。

    注：``real_article_id`` 从关系数据库（PG/DuckDB）获取文章 ID，
    但 ``/graph/articles/{id}/graph`` 从图数据库（Neo4j/LadybugDB）
    查询。文章可能存在于关系数据库但未同步到图数据库（如 pipeline
    图谱构建步骤未完成），此时返回 404。测试 skip 而非失败。
    """
    resp = await async_client.get(f"/api/v1/graph/articles/{real_article_id}/graph")
    if resp.status_code == 404:
        pytest.skip(
            f"Article {real_article_id} 存在于关系数据库但未同步到图数据库"
            "（Neo4j/LadybugDB）— pipeline 图谱构建步骤可能未完成"
        )
    assert resp.status_code == 200


@pytest.mark.integration
async def test_fg_05_relation_types_discover(async_client, real_entity_name):
    """F-G-05: 关系类型发现，断言 200。

    ``/graph/types/discover`` 不存在；改用 ``GET /graph/relations``，
    返回该实体的关系类型摘要（relation_type / target_count / primary_direction）。
    """
    resp = await async_client.get("/api/v1/graph/relations", params={"entity": real_entity_name})
    assert resp.status_code == 200


@pytest.mark.integration
async def test_fg_06_relation_types_search(async_client, real_entity_name):
    """F-G-06: 关系类型搜索，断言 200。

    ``/graph/types/search`` 不存在；改用 ``GET /graph/relations/search``，
    按关系类型搜索关联实体（不传 relation_types 即返回全部）。
    """
    resp = await async_client.get(
        "/api/v1/graph/relations/search", params={"entity": real_entity_name}
    )
    assert resp.status_code == 200


@pytest.mark.integration
async def test_fg_07_traverse_aggregate(async_client, real_entity_name):
    """F-G-07: 图遍历聚合模式 max_depth=2，断言 200。

    ``/graph/traverse`` 为 POST；任务中的 ``max_hops`` 对应 schema 的 ``max_depth``。
    边界: max_depth=-1 → 422（Field ``ge=1`` 校验）。
    """
    resp = await async_client.post(
        "/api/v1/graph/traverse",
        json={
            "start_entity": real_entity_name,
            "max_depth": 2,
            "mode": "aggregate",
        },
    )
    assert resp.status_code == 200

    # 边界: max_depth=-1 → 422
    resp_invalid = await async_client.post(
        "/api/v1/graph/traverse",
        json={
            "start_entity": real_entity_name,
            "max_depth": -1,
            "mode": "aggregate",
        },
    )
    assert resp_invalid.status_code == 422


@pytest.mark.integration
async def test_fg_08_traverse_paths(async_client, real_entity_name):
    """F-G-08: 图遍历路径模式 max_depth=2，断言 200。

    ``return_paths=True`` + ``mode='full'`` 返回完整路径。
    """
    resp = await async_client.post(
        "/api/v1/graph/traverse",
        json={
            "start_entity": real_entity_name,
            "max_depth": 2,
            "return_paths": True,
            "mode": "full",
        },
    )
    assert resp.status_code == 200


@pytest.mark.integration
async def test_fg_09_metrics_health(async_client):
    """F-G-09: 图指标 view=health，断言 200 + 含 health_score 字段。"""
    resp = await async_client.get("/api/v1/graph/metrics", params={"view": "health"})
    assert resp.status_code == 200
    data = resp.json().get("data", {})
    assert "health_score" in data


@pytest.mark.integration
async def test_fg_10_visualization(async_client):
    """F-G-10: 可视化快照，断言 200。"""
    resp = await async_client.get("/api/v1/graph/visualization")
    assert resp.status_code == 200


@pytest.mark.integration
async def test_fg_11_subgraph(async_client, real_entity_name):
    """F-G-11: 子图提取 max_hops=1，断言 200。

    ``/graph/visualization/subgraph`` 实际为 POST ``/graph/visualization``，
    请求体 SubgraphRequest（center_entity / max_hops）。
    边界: max_hops=-1 → 422（Field ``ge=1`` 校验）。
    """
    resp = await async_client.post(
        "/api/v1/graph/visualization",
        json={
            "center_entity": real_entity_name,
            "max_hops": 1,
        },
    )
    assert resp.status_code == 200

    # 边界: max_hops=-1 → 422
    resp_invalid = await async_client.post(
        "/api/v1/graph/visualization",
        json={
            "center_entity": real_entity_name,
            "max_hops": -1,
        },
    )
    assert resp_invalid.status_code == 422
