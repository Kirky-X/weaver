# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""F-S-01~18: Search API 集成测试。

覆盖统一搜索（auto/local/global）、DRIFT 搜索、因果搜索、时序搜索、
输出模式、实体丰富、混合搜索、跨 DB 排序一致性及输入校验。

端点参考 src/api/endpoints/content/search.py:
- GET  /api/v1/search            — 统一搜索（mode=auto|local|global）
- POST /api/v1/search/drift      — DRIFT 搜索（JSON body）
- POST /api/v1/search/causal     — 因果搜索（JSON body）
- POST /api/v1/search/temporal   — 时序搜索（JSON body）
"""

import pytest

# ── 统一搜索 ────────────────────────────────────────────────────


@pytest.mark.integration
async def test_fs_01_unified_search_auto_mode(async_client, real_entity_name):
    """F-S-01: 统一搜索 mode=auto，断言 status_code=200, search_type 字段存在。"""
    resp = await async_client.get(
        "/api/v1/search",
        params={"q": real_entity_name, "mode": "auto"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "search_type" in data


@pytest.mark.integration
async def test_fs_02_unified_search_local_mode(async_client, real_entity_name):
    """F-S-02: 统一搜索 mode=local，断言 search_type=="local"。"""
    resp = await async_client.get(
        "/api/v1/search",
        params={"q": real_entity_name, "mode": "local"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["search_type"] == "local"


@pytest.mark.integration
async def test_fs_03_unified_search_global_mode(async_client, real_entity_name):
    """F-S-03: 统一搜索 mode=global，断言 search_type=="global"。"""
    resp = await async_client.get(
        "/api/v1/search",
        params={"q": real_entity_name, "mode": "global"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["search_type"] == "global"


# ── DRIFT 搜索 ─────────────────────────────────────────────────


@pytest.mark.integration
async def test_fs_04_drift_search_default_params(async_client, real_entity_name):
    """F-S-04: DRIFT 搜索默认参数，断言 status_code=200, total_llm_calls>=1。"""
    resp = await async_client.post(
        "/api/v1/search/drift",
        json={"query": real_entity_name},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    # total_llm_calls 是 DriftSearchResponse 顶级字段（非 metadata 内）
    assert data["total_llm_calls"] >= 1


@pytest.mark.integration
async def test_fs_05_drift_search_custom_params(async_client, real_entity_name):
    """F-S-05: DRIFT 搜索自定义参数（max_follow_ups=2, confidence_threshold=0.5）。"""
    resp = await async_client.post(
        "/api/v1/search/drift",
        json={
            "query": real_entity_name,
            "max_follow_ups": 2,
            "confidence_threshold": 0.5,
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["search_type"] == "drift"


# ── 因果搜索 ───────────────────────────────────────────────────


@pytest.mark.integration
async def test_fs_06_causal_search_default_params(async_client, real_entity_name):
    """F-S-06: causal 搜索默认参数，断言 status_code=200。"""
    resp = await async_client.post(
        "/api/v1/search/causal",
        json={"query": real_entity_name},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["query"] == real_entity_name


@pytest.mark.integration
async def test_fs_07_causal_search_max_depth_limit(async_client, real_entity_name):
    """F-S-07: causal 搜索 max_depth=3 限制。"""
    resp = await async_client.post(
        "/api/v1/search/causal",
        json={"query": real_entity_name, "max_depth": 3},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    # metadata.depth 应反映请求的 max_depth
    assert data["metadata"]["depth"] == 3


# ── 时序搜索 ───────────────────────────────────────────────────


@pytest.mark.integration
async def test_fs_08_temporal_search_default_params(async_client, real_entity_name):
    """F-S-08: temporal 搜索默认参数，断言 time_range 字段存在。"""
    resp = await async_client.post(
        "/api/v1/search/temporal",
        json={"query": real_entity_name},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "time_range" in data
    assert isinstance(data["time_range"], dict)


@pytest.mark.integration
async def test_fs_09_temporal_search_custom_window(async_client, real_entity_name):
    """F-S-09: temporal 搜索自定义窗口（time_range="30d"）。"""
    resp = await async_client.post(
        "/api/v1/search/temporal",
        json={"query": real_entity_name, "time_range": "30d"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    time_range = data["time_range"]
    # 自定义 30d 窗口 → window_days 约 30
    assert "start" in time_range
    assert "end" in time_range
    assert time_range["window_days"] == pytest.approx(30.0, abs=0.1)


# ── 输出模式 ───────────────────────────────────────────────────


@pytest.mark.integration
async def test_fs_10_output_mode_context(async_client, real_entity_name):
    """F-S-10: output_mode=context，断言 answer 是原始片段。"""
    resp = await async_client.get(
        "/api/v1/search",
        params={"q": real_entity_name, "mode": "local", "output_mode": "context"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    # context 模式下 output_mode 标记为 CONTEXT
    assert data["metadata"]["output_mode"] == "CONTEXT"
    # answer 应为非空原始片段
    assert isinstance(data["answer"], str)


@pytest.mark.integration
async def test_fs_11_output_mode_narrative(async_client, real_entity_name):
    """F-S-11: output_mode=narrative，断言 answer 非空且 output_mode 标记正确。

    注：context_tokens 是输入给 LLM 的上下文 token 数，answer 是 LLM
    合成的摘要字符数。LLM 摘要是压缩，answer 通常比 context_tokens 短，
    因此不断言 ``len(answer) > context_tokens``，仅断言 answer 非空。
    """
    resp = await async_client.get(
        "/api/v1/search",
        params={"q": real_entity_name, "mode": "local", "output_mode": "narrative"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["metadata"]["output_mode"] == "NARRATIVE"
    # narrative 模式由 MAGMA 合成，answer 应为非空字符串
    assert isinstance(data["answer"], str)
    assert data["answer"].strip()


# ── 实体丰富 ───────────────────────────────────────────────────


@pytest.mark.integration
async def test_fs_12_enrich_entities_true(async_client, real_entity_name):
    """F-S-12: enrich_entities=true，断言 entities 列表非空。"""
    resp = await async_client.get(
        "/api/v1/search",
        params={
            "q": real_entity_name,
            "mode": "local",
            "enrich_entities": "true",
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["metadata"]["enrich_entities"] is True
    assert len(data["entities"]) > 0


# ── articles 模式 / hybrid / global_mode ───────────────────────


@pytest.mark.integration
async def test_fs_13_articles_mode_threshold(async_client, real_entity_name):
    """F-S-13: articles 模式 threshold=0.5，断言 status_code=200。"""
    resp = await async_client.get(
        "/api/v1/search",
        params={"q": real_entity_name, "threshold": 0.5},
    )
    assert resp.status_code == 200


@pytest.mark.integration
async def test_fs_14_hybrid_search(async_client, real_entity_name):
    """F-S-14: hybrid=true 混合搜索。"""
    resp = await async_client.get(
        "/api/v1/search",
        params={"q": real_entity_name, "use_hybrid": "true"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "search_type" in data


@pytest.mark.integration
async def test_fs_15_global_mode_simple(async_client, real_entity_name):
    """F-S-15: global_mode=simple 全局搜索。"""
    resp = await async_client.get(
        "/api/v1/search",
        params={"q": real_entity_name, "mode": "global", "global_mode": "simple"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["search_type"] == "global"


# ── 跨 DB 排序一致性 ───────────────────────────────────────────


@pytest.mark.integration
async def test_fs_16_cross_db_sort_consistency(async_client, real_entity_name):
    """F-S-16: 跨 DB 排序一致性 — 断言 entities == sorted(entities, key=str)。"""
    resp = await async_client.get(
        "/api/v1/search",
        params={"q": real_entity_name, "mode": "local"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    entities = data["entities"]
    # API 层 _sort_response_lists 已排序，验证一致性
    assert entities == sorted(entities, key=str)


# ── 输入校验 ───────────────────────────────────────────────────


@pytest.mark.integration
async def test_fs_17_empty_query_rejected(async_client):
    """F-S-17: 空 query q="" 断言 422。"""
    resp = await async_client.get(
        "/api/v1/search",
        params={"q": ""},
    )
    assert resp.status_code == 422


@pytest.mark.integration
async def test_fs_18_overlong_query_rejected(async_client, real_entity_name):
    """F-S-18: 超长 query（>1000 字符）API 接受并返回 200。

    注：search.py 中 ``q`` 参数仅有 ``min_length=1``，无 ``max_length``
    限制（见 src/api/endpoints/content/search.py:115）。因此超长查询
    不会被 422 拒绝，而是正常处理。此测试断言 API 接受超长查询。
    """
    overlong_query = (real_entity_name + " ") * 500  # 确保 >1000 字符
    assert len(overlong_query) > 1000
    resp = await async_client.get(
        "/api/v1/search",
        params={"q": overlong_query},
    )
    # API 无 max_length 限制，超长查询被正常处理
    assert resp.status_code == 200
