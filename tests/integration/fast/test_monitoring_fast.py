# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""F-M-01~12：监控 API 快速集成测试。

覆盖系统状态、依赖健康、告警规则/事件、LLM 用量/失败、Saga 失败、
社区列表/健康、简报查询、趋势情感、因果监控统计共 12 个只读端点。

端点路径以源文件实际注册为准（见 src/api/router.py 与各 endpoints 模块）：
- /api/v1/system/status                       (system.py)
- /api/v1/system/health/dependencies          (system.py — 返回 dependencies 字段)
- /api/v1/monitoring/alerts/rules|events      (monitoring/alerts.py)
- /api/v1/monitoring/llm/usage|failures       (monitoring/llm.py)
- /api/v1/saga/failed/list                    (saga.py)
- /api/v1/admin/communities                   (communities.py)
- /api/v1/admin/communities/health            (communities.py)
- /api/v1/briefings/daily                     (briefings.py)
- /api/v1/trends/sentiment                    (trends.py — 需 entity 参数)
- /api/v1/monitoring/causal/stats             (monitoring/causal.py)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.integration
async def test_fm_01_system_status(async_client):
    """F-M-01: GET /api/v1/status 返回 200。

    注：system_router 无 prefix（见 src/api/endpoints/system.py:34），
    实际路径为 /api/v1/status，非 /api/v1/system/status。
    """
    resp = await async_client.get("/api/v1/status")
    assert resp.status_code == 200


@pytest.mark.integration
async def test_fm_02_health_dependencies(async_client):
    """F-M-02: GET /api/v1/health/dependencies 返回 200 且含 dependencies 字段。

    注：system_router 无 prefix（见 src/api/endpoints/system.py:34），
    实际路径为 /api/v1/health/dependencies，非 /api/v1/system/health/dependencies。
    带 ``dependencies`` 字段的是 admin 端点（需 verify_admin_api_key）。
    """
    resp = await async_client.get("/api/v1/health/dependencies")
    assert resp.status_code == 200
    payload = resp.json()
    data = payload.get("data") if isinstance(payload, dict) else payload
    assert isinstance(data, dict)
    assert "dependencies" in data
    assert isinstance(data["dependencies"], dict)


@pytest.mark.integration
async def test_fm_03_alert_rules_list(async_client):
    """F-M-03: GET /api/v1/monitoring/alerts/rules 返回 200。"""
    resp = await async_client.get("/api/v1/monitoring/alerts/rules")
    assert resp.status_code == 200


@pytest.mark.integration
async def test_fm_04_alert_events_list(async_client):
    """F-M-04: GET /api/v1/monitoring/alerts/events 返回 200。"""
    resp = await async_client.get("/api/v1/monitoring/alerts/events")
    assert resp.status_code == 200


@pytest.mark.integration
async def test_fm_05_llm_usage(async_client):
    """F-M-05: GET /api/v1/monitoring/llm/usage 返回 200。

    端点要求 ``from`` 与 ``to`` ISO 时间戳查询参数（见 monitoring/llm.py:151-153）。
    """
    to_ts = datetime.now(timezone.utc)
    from_ts = to_ts - timedelta(days=30)
    resp = await async_client.get(
        "/api/v1/monitoring/llm/usage",
        params={
            "from": from_ts.isoformat(),
            "to": to_ts.isoformat(),
            "group_by": "summary",
        },
    )
    assert resp.status_code == 200


@pytest.mark.integration
async def test_fm_06_llm_failures_list(async_client):
    """F-M-06: GET /api/v1/monitoring/llm/failures 返回 200。"""
    resp = await async_client.get("/api/v1/monitoring/llm/failures")
    assert resp.status_code == 200


@pytest.mark.integration
async def test_fm_07_saga_failures_list(async_client):
    """F-M-07: GET /api/v1/saga/failed/list 返回 200。

    注：saga 失败列表实际路径为 /api/v1/saga/failed/list
    （见 src/api/endpoints/saga.py:199-232），非 /admin/monitoring/saga/failures。
    """
    resp = await async_client.get("/api/v1/saga/failed/list")
    assert resp.status_code == 200


@pytest.mark.integration
async def test_fm_08_communities_list(async_client):
    """F-M-08: GET /api/v1/admin/communities 返回 200。"""
    resp = await async_client.get("/api/v1/admin/communities")
    assert resp.status_code == 200


@pytest.mark.integration
async def test_fm_09_communities_health(async_client):
    """F-M-09: GET /api/v1/admin/communities/health 返回 200。"""
    resp = await async_client.get("/api/v1/admin/communities/health")
    assert resp.status_code == 200


@pytest.mark.integration
async def test_fm_10_briefings_query(async_client):
    """F-M-10: GET /api/v1/briefings/daily 返回 200。

    注：简报查询实际路径为 /api/v1/briefings/daily
    （见 src/api/endpoints/briefings.py:149-191），非 /api/v1/briefings。
    无简报时返回 data=null，仍为 200（R-briefing-004）。
    """
    resp = await async_client.get("/api/v1/briefings/daily")
    assert resp.status_code == 200


@pytest.mark.integration
async def test_fm_11_trends_sentiment(async_client):
    """F-M-11: GET /api/v1/trends/sentiment 返回 200。

    端点要求 ``entity`` 查询参数非空（见 trends.py:195-203）；
    无数据时返回 200 + stable 趋势（R-sentiment-002）。
    """
    resp = await async_client.get(
        "/api/v1/trends/sentiment",
        params={"entity": "test-entity", "window": "7d"},
    )
    assert resp.status_code == 200


@pytest.mark.integration
async def test_fm_12_causal_stats(async_client):
    """F-M-12: GET /api/v1/monitoring/causal/stats 返回 200。

    当 causal_repo 不可用时端点返回 503（见 monitoring/causal.py:43-47），
    此处仅断言成功路径；若环境未配置因果图仓库，本测试可能失败。
    """
    resp = await async_client.get("/api/v1/monitoring/causal/stats")
    assert resp.status_code == 200
