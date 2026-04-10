## Context

当前系统通过 `POST /pipeline/trigger` 触发批量源爬取，任务状态存储在 Redis `pipeline:task_status` key，可通过 `GET /pipeline/tasks/{task_id}` 查询。现有管道 `Pipeline.process_batch()` 已实现完整的文章处理流程。

本设计新增单 URL 处理入口，复用现有组件：`Crawler`、`Pipeline`、`URLValidator`、Redis 任务存储。

## Goals / Non-Goals

**Goals:**
- 提供单 URL 异步处理 API
- 复用现有管道组件和任务管理机制
- 支持 SSRF 防护和可选白名单验证
- 与现有任务查询端点兼容

**Non-Goals:**
- 不修改管道处理逻辑
- 不新增独立 worker 进程
- 不支持批量 URL 提交（保持简单，后续可扩展）

## Decisions

### 1. 异步处理方式

**选择**: `asyncio.create_task()` 后台协程

**替代方案**:
| 方案 | 优点 | 缺点 |
|------|------|------|
| BackgroundTasks | 简单 | 任务无状态跟踪 |
| Redis 队列 + Worker | 可靠持久化 | 需新增 worker 进程 |
| `asyncio.create_task()` | 简单、复用现有状态存储 | 进程重启丢失任务 |

**理由**: 与现有 `/pipeline/trigger` 实现一致，复用 Redis 状态存储，无需额外组件。

### 2. URL 验证策略

**选择**: SSRF 防护必选 + 白名单可选

**理由**:
- SSRF 防护为安全基线，强制启用
- 白名单模式为可选增强，由配置决定
- 复用现有 `URLValidator`，避免重复实现

### 3. 任务存储

**选择**: 复用 `pipeline:task_status` Redis key

**理由**: 与现有任务查询端点 `/pipeline/tasks/{task_id}` 完全兼容，用户无需区分任务来源。

## Risks / Trade-offs

| 风险 | 缓解措施 |
|------|----------|
| 后台任务进程重启丢失 | 任务状态存 Redis，可追踪失败原因；关键场景可后续增强为持久队列 |
| 单 URL 抓取失败 | 返回详细错误信息，任务状态标记 `failed` |
| 恶意 URL 提交攻击 | SSRF 防护 + 可选白名单 + API Key 认证 + 应用级限流 |