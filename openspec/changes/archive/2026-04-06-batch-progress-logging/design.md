## Context

Pipeline 的 `process_batch` 方法负责批量处理资讯，当前仅在开始和结束时输出日志。Phase 3 使用 semaphore 控制并发（默认 5 个），analyze 和 quality_scorer 并行执行。持久化在 `_persist_batch` 中批量完成。

## Goals / Non-Goals

**Goals:**
- 在每条资讯处理完成后输出进度日志
- 统计成功/失败数量和成功率
- 基于 pipeline 实例追踪，批次隔离

**Non-Goals:**
- 不追踪单个 LLM 调用进度
- 不实现进度条或可视化
- 不添加外部监控集成

## Decisions

### 计数器位置：Pipeline 实例属性

**选择**: 在 `Pipeline` 类中添加 `_batch_total`、`_batch_completed`、`_batch_failed` 实例属性。

**理由**:
- 改动最小，无需修改函数签名
- 与现有 Pipeline 结构一致
- `process_batch` 入口重置计数器，天然批次隔离

**替代方案**:
- 批次上下文对象：职责分离更清晰，但需修改多处函数签名
- 闭包变量：代码隐式，不够清晰

### 日志输出位置：`_persist_batch` 内逐条输出

**选择**: 在 `_persist_batch` 方法中，每条资讯持久化完成后立即输出进度日志。

**理由**:
- 持久化是最终处理步骤，能准确判断成功/失败
- 无需等待整批次完成
- 与现有日志风格一致

### 失败定义：持久化失败

**选择**: 仅持久化失败（Postgres 或 Neo4j 任一失败）计入失败。

**理由**:
- Terminal 状态（非新闻）是正常流程，不是失败
- LLM 降级但持久化成功，文章已入库，计为成功
- 与业务逻辑一致

### 日志格式：简洁百分比

**格式**: `[{completed}/{total}] {success_rate}% success ({failed} failed) | {url}`

**示例**: `[32/50] 91.4% success (3 failed) | https://example.com/article/123`

**理由**:
- 信息完整且易读
- 与用户需求一致
- 简洁不冗余

## Risks / Trade-offs

**并发计数安全** → 使用实例属性在单线程 asyncio 中安全，无需锁

**日志量增加** → 每条资讯一条日志，相比现有日志量增加有限，可接受

**Pipeline 实例复用** → `process_batch` 入口重置计数器，确保批次隔离