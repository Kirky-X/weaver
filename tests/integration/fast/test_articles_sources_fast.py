# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""F-C-01~05: 文章与源 API 快速集成测试。

覆盖端点：
- GET /api/v1/articles — 文章列表（分页/过滤/排序白名单）
- GET /api/v1/articles/{article_id} — 文章详情
- GET /api/v1/sources — 源列表
- GET /api/v1/sources/{source_id} — 源详情

依赖 conftest fixtures：async_client / real_article_id / real_source_id。

冲突说明（规则4 暴露冲突，不折中）：
1. articles 端点返回 APIResponse[ArticleListResponse]，``data`` 是对象
   （含 items/total/page/page_size/total_pages），而非裸列表。任务规格
   F-C-01 描述「data 是列表」与实际响应结构不符 —— 本测试按实际行为断言。
2. articles.py:242-243 对非白名单 sort_by 采取静默回退到 publish_time
   （返回 200），而非 422。任务规格 F-C-02 描述「sort_by 非白名单值
   返回 422」与代码行为不符 —— 本测试断言实际行为（200 静默回退），
   并通过非法 category 路径覆盖 422（articles.py:207-211）。
3. conftest real_article_id fixture（conftest.py:1035）将 data 当作列表
   访问（data[0]），但 data 实为对象，F-C-03 依赖该 fixture 时会触发
   KeyError —— 该 fixture 需修复为 data["items"][0]。
"""

import pytest


@pytest.mark.integration
async def test_fc_01_article_list_default_pagination(async_client):
    """F-C-01: 文章列表默认分页返回 200，data 为含 items 列表的对象。

    articles 端点返回 APIResponse[ArticleListResponse]，data 是分页对象
    （items/total/page/page_size/total_pages），items 才是文章列表。
    """
    resp = await async_client.get("/api/v1/articles")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert isinstance(data, dict)
    assert "items" in data
    assert isinstance(data["items"], list)
    for key in ("total", "page", "page_size", "total_pages"):
        assert key in data


@pytest.mark.integration
async def test_fc_02_article_list_multi_filter_and_sort_validation(async_client):
    """F-C-02: 文章列表多过滤组合（category + sort_by + page_size）。

    冲突说明：任务规格要求「sort_by 非白名单值返回 422」，但 articles.py
    对非白名单 sort_by 静默回退到 publish_time（返回 200）。仅非法 category
    返回 422。本测试覆盖三条路径：
    1. 合法多过滤组合（category=科技 + sort_by=score + page_size=5）→ 200
    2. 非白名单 sort_by → 200（静默回退，非 422）
    3. 非法 category → 422
    """
    # 1. 合法多过滤组合
    resp = await async_client.get(
        "/api/v1/articles",
        params={"category": "科技", "sort_by": "score", "page_size": 5},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert isinstance(data["items"], list)
    assert data["page_size"] == 5

    # 2. 非白名单 sort_by：静默回退到 publish_time，返回 200（非 422）
    #    ALLOWED_SORT_COLUMNS = {publish_time, score, credibility_score, created_at}
    resp_invalid_sort = await async_client.get(
        "/api/v1/articles",
        params={"sort_by": "malicious_field"},
    )
    assert resp_invalid_sort.status_code == 200

    # 3. 非法 category：返回 422（articles.py:207-211）
    resp_invalid_cat = await async_client.get(
        "/api/v1/articles",
        params={"category": "not_a_valid_category"},
    )
    assert resp_invalid_cat.status_code == 422


@pytest.mark.integration
async def test_fc_03_article_detail(async_client, real_article_id):
    """F-C-03: 文章详情返回 200 且 id 匹配。

    依赖 real_article_id fixture（见模块 docstring 冲突说明 3）。
    """
    resp = await async_client.get(f"/api/v1/articles/{real_article_id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == real_article_id


@pytest.mark.integration
async def test_fc_04_source_list(async_client):
    """F-C-04: 源列表返回 200，data 为列表。

    sources 端点返回 APIResponse[list[SourceResponse]]，data 直接是列表。
    """
    resp = await async_client.get("/api/v1/sources")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert isinstance(data, list)


@pytest.mark.integration
async def test_fc_05_source_detail(async_client, real_source_id):
    """F-C-05: 源详情返回 200。

    依赖 real_source_id fixture（无可用 source 时为 None，跳过）。
    """
    if real_source_id is None:
        pytest.skip("无可用 source")
    resp = await async_client.get(f"/api/v1/sources/{real_source_id}")
    assert resp.status_code == 200
