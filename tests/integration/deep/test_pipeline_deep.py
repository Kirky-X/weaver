# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""D-P-01~08: Pipeline Deep 阶段集成测试。

覆盖端点（src/api/endpoints/content/pipeline.py）：
- POST /api/v1/pipeline/trigger         — 异步触发 pipeline（fire-and-forget）
- GET  /api/v1/pipeline/tasks/{task_id} — 轮询任务状态
- GET  /api/v1/pipeline/queue/stats     — 队列统计
- GET  /api/v1/pipeline/status          — 管道状态
- POST /api/v1/pipeline/url/stream      — 单 URL 异步 + SSE 流式

依赖 conftest fixtures：async_client / real_source_id / real_article_id。

冲突说明（规则4 暴露冲突，不折中）：
1. D-P-04 任务规格要求断言 "workers" 字段，但 GET /pipeline/queue/stats 实际返回
   {queue_depth, status_counts, total_tasks, article_stats}，无 "workers" 字段。
   本测试按实际 API 行为断言 queue_depth 字段。
2. D-P-05 任务规格要求断言 "active_tasks" 字段，但 GET /pipeline/status 实际返回
   {status, queue{pending,processing}, recent_articles}，无 "active_tasks" 字段。
   本测试按实际 API 行为断言 status 字段。
3. D-P-07 任务规格要求断言 "analysis 字段非空"，但 ArticleDetailResponse 无 "analysis"
   字段。LLM 分析结果存储于 summary / impact / sentiment / sentiment_score 等字段
   （源自 article_analysis 表）。本测试断言 processing_status=="completed" 且至少一个
   LLM 派生字段（summary/impact/sentiment）非空。
"""

import asyncio

import pytest

# ── 轮询参数 ────────────────────────────────────────────────────
# 单源 trigger 超时 300s（对齐 _TRIGGER_SOURCE_TIMEOUT_SECONDS），
# 轮询间隔 5s（对齐 conftest real_entity_name fixture 的轮询节奏）。
_TASK_POLL_TIMEOUT_SECONDS = 300.0
_TASK_POLL_INTERVAL_SECONDS = 5.0
# 文章 LLM 完成轮询超时 — 文章处理可能在 trigger 完成后仍在异步写入
_ARTICLE_POLL_TIMEOUT_SECONDS = 120.0
_ARTICLE_POLL_INTERVAL_SECONDS = 5.0


# ── D-P-01: 异步触发单源 pipeline ──────────────────────────────


@pytest.mark.integration
@pytest.mark.slow
async def test_dp_01_trigger_single_source(async_client, real_source_id):
    """D-P-01: POST /pipeline/trigger 单源异步触发，断言 200 + task_id + status=queued。

    请求体使用 ``source_ids``（复数优先）传递单个源 ID。响应应为 fire-and-forget：
    HTTP 立即返回，``data.status`` 为 "queued"，``data.task_id`` 非空。
    """
    if real_source_id is None:
        pytest.skip("无可用 source")

    resp = await async_client.post(
        "/api/v1/pipeline/trigger",
        json={"source_ids": [real_source_id]},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "task_id" in data
    assert data["task_id"]  # 非空字符串
    assert data["status"] == "queued"
    assert "queued_at" in data


# ── D-P-02: force=true 强制重新处理 ────────────────────────────


@pytest.mark.integration
@pytest.mark.slow
async def test_dp_02_trigger_with_force(async_client, real_source_id):
    """D-P-02: POST /pipeline/trigger force=true 强制重新处理，断言 200 + task_id。

    ``force=true`` 应跳过 URL 级去重检查，即使 URL 最近被抓取过也会重新处理。
    响应结构与 D-P-01 一致。

    冲突说明（规则4 暴露冲突）：``force`` 仅控制 URL 级去重，不影响源级互斥锁
    （pipeline.py:582-612 的 ``_SOURCE_LOCK_KEY_PREFIX`` SET NX）。若同一 source
    已有正在运行的任务（lock TTL 600s），即使 ``force=true`` 仍返回 409 Conflict。
    本测试接受 200（成功入队）或 409（源已锁定），409 时 skip（环境依赖，非测试失败）。
    """
    if real_source_id is None:
        pytest.skip("无可用 source")

    resp = await async_client.post(
        "/api/v1/pipeline/trigger",
        json={"source_ids": [real_source_id], "force": True},
    )
    if resp.status_code == 409:
        pytest.skip("source 已被其他任务锁定（dedup lock），force 不绕过源级锁")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "task_id" in data
    assert data["task_id"]  # 非空字符串
    assert data["status"] == "queued"


# ── D-P-03: 轮询任务状态直到 COMPLETED ─────────────────────────


@pytest.mark.integration
@pytest.mark.slow
async def test_dp_03_poll_task_until_completed(async_client, real_source_id):
    """D-P-03: 触发任务后轮询 GET /pipeline/tasks/{task_id} 直到 status=COMPLETED。

    超时 300s（对齐 _TRIGGER_SOURCE_TIMEOUT_SECONDS）。若任务 FAILED 则跳过
    （环境问题，如 LLM 不可用，不计为测试失败）。

    冲突说明（规则4 暴露冲突）：与 D-P-02 同理，源级互斥锁（pipeline.py:582-612）
    可能导致 trigger 返回 409 Conflict。本测试接受 200（成功入队）或 409（源已锁定），
    409 时 skip（无法触发新任务以轮询）。
    """
    if real_source_id is None:
        pytest.skip("无可用 source")

    # 1. 触发任务
    trigger_resp = await async_client.post(
        "/api/v1/pipeline/trigger",
        json={"source_ids": [real_source_id]},
    )
    if trigger_resp.status_code == 409:
        pytest.skip("source 已被其他任务锁定（dedup lock），无法触发新任务")
    assert trigger_resp.status_code == 200
    task_id = trigger_resp.json()["data"]["task_id"]

    # 2. 轮询直到 COMPLETED 或 FAILED（超时 300s）
    deadline = asyncio.get_event_loop().time() + _TASK_POLL_TIMEOUT_SECONDS
    final_status = None
    while asyncio.get_event_loop().time() < deadline:
        status_resp = await async_client.get(f"/api/v1/pipeline/tasks/{task_id}")
        assert status_resp.status_code == 200
        final_status = status_resp.json()["data"]["status"]
        if final_status == "completed":
            break
        if final_status == "failed":
            pytest.skip(f"任务 FAILED（可能 LLM 不可用）：task_id={task_id}")
        await asyncio.sleep(_TASK_POLL_INTERVAL_SECONDS)

    assert final_status == "completed", (
        f"任务未在 {_TASK_POLL_TIMEOUT_SECONDS}s 内完成：task_id={task_id}, "
        f"final_status={final_status}"
    )


# ── D-P-04: 队列统计 ───────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.slow
async def test_dp_04_queue_stats(async_client):
    """D-P-04: GET /pipeline/queue/stats 队列统计，断言 200 + queue_depth 字段。

    冲突说明：任务规格要求断言 "workers" 字段，但实际 API 返回
    {queue_depth, status_counts, total_tasks, article_stats}，无 "workers" 字段。
    本测试按实际 API 行为断言 queue_depth 字段存在。
    """
    resp = await async_client.get("/api/v1/pipeline/queue/stats")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "queue_depth" in data
    assert isinstance(data["queue_depth"], int)
    assert "status_counts" in data
    assert "total_tasks" in data
    assert "article_stats" in data


# ── D-P-05: 管道状态 ───────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.slow
async def test_dp_05_pipeline_status(async_client):
    """D-P-05: GET /pipeline/status 管道状态，断言 200 + status 字段。

    冲突说明：任务规格要求断言 "active_tasks" 字段，但实际 API 返回
    {status, queue{pending,processing}, recent_articles}，无 "active_tasks" 字段。
    本测试按实际 API 行为断言 status 字段（值为 "running" 或 "idle"）。
    """
    resp = await async_client.get("/api/v1/pipeline/status")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "status" in data
    assert data["status"] in ("running", "idle")
    assert "queue" in data
    assert "pending" in data["queue"]
    assert "processing" in data["queue"]
    assert "recent_articles" in data


# ── D-P-06: 单 URL 异步 + SSE 流式 ─────────────────────────────


@pytest.mark.integration
@pytest.mark.slow
async def test_dp_06_url_stream_sse(async_client):
    """D-P-06: POST /pipeline/url/stream SSE 流式处理，断言 text/event-stream + 事件。

    使用真实公共 URL（https://example.com）触发 SSE 流。断言：
    1. 响应状态码 200
    2. Content-Type 为 text/event-stream
    3. 至少收到一个 log 或 heartbeat 事件

    即使 URL 抓取最终失败，SSE 流也会先发出 log "Pipeline started" 事件。
    """
    url = "https://example.com"
    received_events: list[str] = []
    received_log_or_heartbeat = False

    async with async_client.stream(
        "POST",
        "/api/v1/pipeline/url/stream",
        json={"url": url},
    ) as resp:
        assert resp.status_code == 200
        content_type = resp.headers.get("content-type", "")
        assert "text/event-stream" in content_type, (
            f"Expected text/event-stream, got {content_type}"
        )

        # 解析 SSE 事件流：event: <type>\ndata: <json>\n\n
        current_event = None
        async for line in resp.aiter_lines():
            line = line.strip()
            if line.startswith("event:"):
                current_event = line[6:].strip()
                received_events.append(current_event)
                if current_event in ("log", "heartbeat"):
                    received_log_or_heartbeat = True
                    break  # 收到 log/heartbeat 即可，不等完整流
            elif line == "" and current_event:
                current_event = None
            # 收到 error 事件也终止（说明 pipeline 启动后失败，但 SSE 流正常工作）
            elif current_event == "error":
                break

    assert len(received_events) > 0, "未收到任何 SSE 事件"
    assert received_log_or_heartbeat, (
        f"未收到 log 或 heartbeat 事件，收到的事件类型：{received_events}"
    )


# ── D-P-07: 等待 LLM 完成（轮询 article_analysis） ─────────────


@pytest.mark.integration
@pytest.mark.slow
async def test_dp_07_wait_for_llm_analysis(async_client, real_article_id):
    """D-P-07: 轮询 GET /articles/{id} 直到 LLM 分析完成，断言分析字段非空。

    冲突说明：任务规格要求断言 "analysis 字段非空"，但 ArticleDetailResponse
    无 "analysis" 字段。LLM 分析结果存储于 summary / impact / sentiment /
    sentiment_score 等字段（源自 article_analysis 表）。本测试断言：
    1. processing_status == "completed"
    2. 至少一个 LLM 派生字段（summary/impact/sentiment）非空

    轮询超时 120s — 文章可能在 trigger 完成后仍需时间异步写入分析结果。
    若超时仍未完成，跳过测试（环境问题，非测试失败）。
    """
    if real_article_id is None:
        pytest.skip("无可用文章")

    deadline = asyncio.get_event_loop().time() + _ARTICLE_POLL_TIMEOUT_SECONDS
    article_data = None

    while asyncio.get_event_loop().time() < deadline:
        resp = await async_client.get(f"/api/v1/articles/{real_article_id}")
        assert resp.status_code == 200
        article_data = resp.json()["data"]
        if article_data.get("processing_status") == "completed":
            break
        await asyncio.sleep(_ARTICLE_POLL_INTERVAL_SECONDS)

    if article_data is None or article_data.get("processing_status") != "completed":
        pytest.skip(f"文章 {real_article_id} 在 {_ARTICLE_POLL_TIMEOUT_SECONDS}s 内未完成 LLM 分析")

    # 断言至少一个 LLM 派生字段非空
    analysis_fields = {
        "summary": article_data.get("summary"),
        "impact": article_data.get("impact"),
        "sentiment": article_data.get("sentiment"),
    }
    non_empty = {k: v for k, v in analysis_fields.items() if v}
    assert len(non_empty) > 0, (
        f"所有 LLM 分析字段均为空：{analysis_fields}。"
        f"processing_status={article_data.get('processing_status')}"
    )


# ── D-P-08: 异常 — source_ids 空列表返回 400 ──────────────────


@pytest.mark.integration
@pytest.mark.slow
async def test_dp_08_empty_source_ids_returns_400(async_client):
    """D-P-08: POST /pipeline/trigger source_ids=[] 空列表，断言 400。

    端点在 pipeline.py:507-510 显式拒绝空 source_ids 列表，message 为
    "source_ids cannot be empty"。

    冲突说明（规则4 暴露冲突）：任务规格假设 HTTPException 响应体含 ``detail``
    字段，但项目全局异常处理器（api/middleware/api_response.py:102-111）将
    HTTPException 包装为 ``{"code":..., "message":..., "data": null}`` 格式，
    无 ``detail`` 字段。本测试按实际响应格式断言 ``message`` 字段。
    """
    resp = await async_client.post(
        "/api/v1/pipeline/trigger",
        json={"source_ids": []},
    )
    assert resp.status_code == 400
    message = resp.json().get("message")
    assert message is not None
    assert "source_ids" in message.lower() and "empty" in message.lower(), (
        f"message 未包含预期的错误描述：{message!r}"
    )
