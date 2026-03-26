# Weaver 数据一致性问题修复方案

本文档详细说明 PostgreSQL 与 Neo4j 之间数据一致性问题的检测、修复和预防机制。

## 目录

- [概述](#概述)
- [数据一致性机制分析](#数据一致性机制分析)
- [问题检测机制](#问题检测机制)
- [自动修复机制](#自动修复机制)
- [手动干预步骤](#手动干预步骤)
- [回滚和补偿策略](#回滚和补偿策略)
- [告警配置与处理](#告警配置与处理)
- [故障排除指南](#故障排除指南)
- [常见问题解决方案](#常见问题解决方案)

---

## 概述

### 系统架构

Weaver 采用双数据库架构：
- **PostgreSQL**: 存储文章元数据、向量嵌入、持久化状态
- **Neo4j**: 存储知识图谱（文章节点、实体节点、关系）

```
┌─────────────────────────────────────────────────────────────────┐
│                     Weaver 数据流架构                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────┐    ┌──────────────────┐    ┌──────────────────┐   │
│  │ Pipeline │───▶│  PostgreSQL      │───▶│  Neo4j           │   │
│  │         │    │  - articles      │    │  - Article nodes │   │
│  │         │    │  - article_vectors│   │  - Entity nodes  │   │
│  │         │    │  - entity_vectors │   │  - Relationships │   │
│  │         │    │  - persist_status │   │                  │   │
│  └─────────┘    └──────────────────┘    └──────────────────┘   │
│       │                  ▲                       │              │
│       │                  │                       │              │
│       │           ┌──────┴──────┐                │              │
│       │           │ Saga 补偿    │◀───────────────┘              │
│       │           │ 重试机制     │                               │
│       │           └─────────────┘                                │
│       │                                                         │
│       ▼                                                         │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                   后台调度任务                            │   │
│  │  - retry_neo4j_writes (10min)                            │   │
│  │  - sync_neo4j_with_postgres (1h)                         │   │
│  │  - retry_pipeline_processing (15min)                     │   │
│  │  - update_persist_status_metrics (5min)                  │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 一致性问题类型

| 问题类型 | 描述 | 严重程度 |
|----------|------|----------|
| PostgreSQL 成功，Neo4j 失败 | 文章存在于 PG 但不在 Neo4j | 高 |
| Neo4j 孤儿节点 | 文章存在于 Neo4j 但不在 PostgreSQL | 中 |
| 向量数据不一致 | 文章有向量但无正文数据 | 低 |
| 状态标记错误 | NEO4J_DONE 但缺少数据字段 | 中 |
| 实体向量孤儿 | entity_vectors 中存在无效引用 | 低 |

---

## 数据一致性机制分析

### 1. Saga 模式持久化流程

**代码位置**: `src/modules/pipeline/nodes/batch_merger.py:275-488`

```python
async def persist_batch_saga(self, states: list[PipelineState]) -> dict[str, Any]:
    """两阶段提交 Saga 模式"""
    # Phase 1: PostgreSQL 持久化
    # 1. 幂等性检查（URL 去重）
    # 2. bulk_upsert 到 articles 表
    # 3. 更新状态为 PG_DONE
    # 4. 写入向量到 article_vectors

    # Phase 2: Neo4j 持久化
    # 1. 逐文章写入 Neo4j
    # 2. 创建 Article 节点
    # 3. 创建 Entity 节点和 MENTIONS 关系
    # 4. 更新状态为 NEO4J_DONE

    # 补偿事务（Phase 2 失败时）
    # 删除 PostgreSQL 中已写入的记录
```

**关键特性**:
- **幂等性**: 通过 URL 去重避免重复写入
- **两阶段提交**: PostgreSQL 先写，Neo4j 后写
- **补偿事务**: Neo4j 失败时回滚 PostgreSQL

### 2. PersistStatus 状态机

**代码位置**: `src/core/db/models.py`

```
状态转换图:

    PENDING ──────▶ PROCESSING ──────▶ PG_DONE ──────▶ NEO4J_DONE
        │               │                  │                  │
        │               │                  │                  │
        ▼               ▼                  ▼                  ▼
      FAILED ◀─────────FAILED ◀──────────FAILED              (终态)
        │
        │ (允许重试)
        ▼
      PENDING
```

**状态验证规则**:
```python
valid_transitions = {
    cls.PENDING: {cls.PROCESSING, cls.FAILED},
    cls.PROCESSING: {cls.PG_DONE, cls.FAILED},
    cls.PG_DONE: {cls.NEO4J_DONE, cls.FAILED},
    cls.FAILED: {cls.PENDING},  # 允许重试
    cls.NEO4J_DONE: set(),      # 终态
}
```

### 3. 后台调度任务

**代码位置**: `src/main.py:84-158`

| 任务名称 | 执行频率 | 功能描述 |
|----------|----------|----------|
| `retry_neo4j_writes` | 每 10 分钟 | 重试 PG_DONE 超过 10 分钟的文章 |
| `sync_neo4j_with_postgres` | 每小时 | 检测并修复数据不一致 |
| `retry_pipeline_processing` | 每 15 分钟 | 重试失败/卡住的处理 |
| `update_persist_status_metrics` | 每 5 分钟 | 更新 Prometheus 状态指标 |
| `cleanup_orphan_entity_vectors` | 每周六 3:00 | 清理孤儿实体向量 |

---

## 问题检测机制

### 1. 自动检测方法

#### 1.1 状态监控检测

**代码位置**: `src/modules/scheduler/jobs.py:271-317`

```python
async def sync_neo4j_with_postgres(self) -> int:
    """检测两种不一致:
    1. Neo4j 孤儿节点 (在 Neo4j 但不在 PostgreSQL)
    2. 富化缺口 (NEO4J_DONE 但缺少数据字段)
    """
    # 获取所有 PostgreSQL 文章 ID
    pg_ids = await self._article_repo.get_all_article_ids()

    # 获取所有 Neo4j 文章 ID
    neo4j_ids = await self._neo4j_writer.article_repo.list_all_article_pg_ids()

    # 计算孤儿节点
    orphan_ids = set(neo4j_ids) - pg_ids

    # 检测富化缺口
    incomplete = await self._article_repo.get_incomplete_articles(limit=100)
```

#### 1.2 Prometheus 指标检测

**代码位置**: `src/modules/scheduler/jobs.py:441-473`

```python
async def update_persist_status_metrics(self) -> None:
    """更新持久化状态计数器，用于告警"""
    for status in PersistStatus:
        metrics.persist_status_count.labels(status=status.value).set(0)

    for row in rows:
        metrics.persist_status_count.labels(status=status_value).set(count)
```

#### 1.3 健康检查端点

**端点**: `GET /health`

**代码位置**: `src/api/endpoints/health.py`

```json
{
  "status": "healthy",
  "checks": {
    "postgres": {"status": "ok", "latency_ms": 2.34},
    "neo4j": {"status": "ok", "latency_ms": 5.67},
    "redis": {"status": "ok", "latency_ms": 1.23}
  }
}
```

### 2. 手动检测命令

#### 2.1 检查数据一致性

```bash
# 检查 PostgreSQL 文章数
psql $POSTGRES_DSN -c "SELECT COUNT(*) FROM articles WHERE persist_status = 'neo4j_done'"

# 检查 Neo4j 文章节点数
cypher-shell -a $NEO4J_URI -u $NEO4J_USER -p $NEO4J_PASSWORD \
  "MATCH (a:Article) RETURN count(a)"

# 检查 PG_DONE 超过 10 分钟的文章（可能卡住）
psql $POSTGRES_DSN -c "
SELECT id, source_url, updated_at
FROM articles
WHERE persist_status = 'pg_done'
  AND updated_at < NOW() - INTERVAL '10 minutes'
ORDER BY updated_at
LIMIT 20;
"

# 检查孤儿 Neo4j 节点
cypher-shell -a $NEO4J_URI -u $NEO4J_USER -p $NEO4J_PASSWORD "
MATCH (a:Article)
WHERE NOT EXISTS {
  MATCH (pg:PGArticle {id: a.pg_id})
}
RETURN a.pg_id, a.title
LIMIT 50;
"
```

#### 2.2 检查向量一致性

```bash
# 检查文章向量孤儿
psql $POSTGRES_DSN -c "
SELECT av.article_id
FROM article_vectors av
LEFT JOIN articles a ON a.id = av.article_id
WHERE a.id IS NULL
LIMIT 50;
"

# 检查实体向量孤儿
psql $POSTGRES_DSN -c "
SELECT ev.neo4j_id
FROM entity_vectors ev
LEFT JOIN ... -- 需要与 Neo4j 实体对比
"
```

### 3. 告警规则

**配置文件**: `monitoring/prometheus/alerts.yml:198-282`

```yaml
# 数据不一致告警 (Warning)
- alert: DataInconsistencyDetected
  expr: |
    abs(
      pg_stat_user_tables_n_live_tup{datname="weaver"}
      -
      neo4j_node_count{label="Entity"}
    ) > 50
  for: 10m
  labels:
    severity: warning
    component: consistency

# 严重数据不一致告警 (Critical)
- alert: SevereDataInconsistency
  expr: |
    abs(
      pg_stat_user_tables_n_live_tup{datname="weaver"}
      -
      neo4j_node_count{label="Entity"}
    ) > 100
  for: 15m
  labels:
    severity: critical
    component: consistency

# 持久化失败率告警
- alert: HighPersistenceFailureRate
  expr: |
    (sum(persist_status_count{status="failed"})
    /
    sum(persist_status_count)) * 100 > 5
  for: 10m
```

---

## 自动修复机制

### 1. Neo4j 写入重试

**任务**: `retry_neo4j_writes`
**频率**: 每 10 分钟
**代码位置**: `src/modules/scheduler/jobs.py:60-120`

```python
async def retry_neo4j_writes(self) -> int:
    """重试卡在 PG_DONE 状态的文章"""
    # 查找 PG_DONE 超过 10 分钟的文章
    threshold = datetime.now(UTC) - timedelta(minutes=10)

    stmt = select(Article).where(
        and_(
            Article.persist_status == PersistStatus.PG_DONE,
            Article.updated_at < threshold,
        )
    ).limit(100)

    for article in articles:
        # 重构状态
        state = await self._reconstruct_state(article)

        # 尝试写入 Neo4j
        await self._neo4j_writer.write(state)

        # 更新状态
        article.persist_status = PersistStatus.NEO4J_DONE
```

**触发条件**:
- `persist_status = 'pg_done'`
- `updated_at < NOW() - 10 minutes`

**处理流程**:
```
┌─────────────────┐
│ PG_DONE > 10min │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 重构 Pipeline   │
│ State           │
└────────┬────────┘
         │
         ▼
┌─────────────────┐     失败
│ Neo4j 写入      │────────────▶ 保持 PG_DONE，下次重试
└────────┬────────┘
         │ 成功
         ▼
┌─────────────────┐
│ 更新为          │
│ NEO4J_DONE      │
└─────────────────┘
```

### 2. 数据同步对账

**任务**: `sync_neo4j_with_postgres`
**频率**: 每小时
**代码位置**: `src/modules/scheduler/jobs.py:271-317`

```python
async def sync_neo4j_with_postgres(self) -> int:
    """同步 Neo4j 与 PostgreSQL 数据"""
    # 1. 获取两边 ID 集合
    pg_ids = await self._article_repo.get_all_article_ids()
    neo4j_ids = await self._neo4j_writer.article_repo.list_all_article_pg_ids()

    # 2. 计算孤儿节点
    orphan_ids = set(neo4j_ids) - pg_ids

    # 3. 删除孤儿节点
    if orphan_ids:
        deleted = await self._neo4j_writer.article_repo.delete_orphan_articles(
            list(orphan_ids)
        )

    # 4. 检测富化缺口
    incomplete = await self._article_repo.get_incomplete_articles(limit=100)
    for article in incomplete:
        # 回退到 PG_DONE 触发重试
        await self._article_repo.revert_to_pg_done(article.id)
```

**处理逻辑**:

| 场景 | 处理方式 |
|------|----------|
| Neo4j 有，PostgreSQL 无 | 删除 Neo4j 孤儿节点 |
| NEO4J_DONE 但数据缺失 | 回退到 PG_DONE，触发重试 |

### 3. Pipeline 处理重试

**任务**: `retry_pipeline_processing`
**频率**: 每 15 分钟
**代码位置**: `src/modules/scheduler/jobs.py:319-439`

```python
async def retry_pipeline_processing(self) -> int:
    """重试失败或卡住的 Pipeline 处理"""
    # 1. 获取 PENDING 状态文章（从未处理）
    pending_articles = await self._article_repo.get_pending(limit=20)

    # 2. 获取卡住的文章（PROCESSING 超过 30 分钟）
    stuck_articles = await self._article_repo.get_stuck_articles(timeout_minutes=30)

    # 3. 获取失败但可重试的文章
    failed_articles = await self._article_repo.get_failed_articles(max_retries=3)

    # 4. 重新处理
    for article in articles:
        await self._pipeline.process_batch([raw], article_ids=[article.id])
```

**触发条件**:
- `persist_status = 'pending'`
- `persist_status = 'processing' AND updated_at < NOW() - 30min`
- `persist_status = 'failed' AND retry_count < 3`

### 4. Circuit Breaker 保护

**代码位置**: `src/core/resilience/circuit_breaker.py`

```python
class CircuitBreaker:
    """线程安全的熔断器"""

    # 状态: CLOSED -> OPEN -> HALF_OPEN -> CLOSED
    # 阈值: 5 次连续失败触发熔断
    # 冷却期: 60 秒后进入半开状态
```

**与数据一致性的关系**:
- Neo4j 连续失败时触发熔断，避免雪崩
- 半开状态允许探测请求
- 结合重试机制实现自动恢复

---

## 手动干预步骤

### 场景 1: 批量 Neo4j 写入失败

**症状**: 大量文章卡在 `PG_DONE` 状态

**诊断步骤**:

```bash
# 1. 检查 Neo4j 连接
cypher-shell -a $NEO4J_URI -u $NEO4J_USER -p $NEO4J_PASSWORD "RETURN 1"

# 2. 检查 Neo4j 日志
docker logs neo4j --tail 100

# 3. 统计 PG_DONE 文章数
psql $POSTGRES_DSN -c "
SELECT COUNT(*) FROM articles WHERE persist_status = 'pg_done'
"
```

**修复步骤**:

```bash
# 方法 1: 触发手动重试 (通过 API)
curl -X POST http://localhost:8000/api/v1/admin/retry/neo4j

# 方法 2: 手动执行重试任务
# 进入 Python 环境
uv run python -c "
import asyncio
from container import Container

async def main():
    container = Container().configure()
    await container.startup()
    jobs = container.scheduler_jobs()
    count = await jobs.retry_neo4j_writes()
    print(f'Retried {count} articles')

asyncio.run(main())
"

# 方法 3: 批量重置状态 (谨慎使用)
psql $POSTGRES_DSN -c "
UPDATE articles
SET persist_status = 'pg_done', updated_at = NOW() - INTERVAL '15 minutes'
WHERE persist_status = 'processing'
  AND updated_at < NOW() - INTERVAL '30 minutes';
"
```

### 场景 2: 数据不一致检测

**症状**: Prometheus 告警 `DataInconsistencyDetected` 触发

**诊断步骤**:

```bash
# 1. 获取两边数据量
PG_COUNT=$(psql $POSTGRES_DSN -t -c "SELECT COUNT(*) FROM articles")
NEO4J_COUNT=$(cypher-shell -a $NEO4J_URI -u $NEO4J_USER -p $NEO4J_PASSWORD \
  "MATCH (a:Article) RETURN count(a)" | head -1)

echo "PostgreSQL: $PG_COUNT, Neo4j: $NEO4J_COUNT"

# 2. 找出孤儿节点
cypher-shell -a $NEO4J_URI -u $NEO4J_USER -p $NEO4J_PASSWORD "
MATCH (a:Article)
WHERE NOT a.pg_id IN [可选的 PostgreSQL ID 列表]
RETURN a.pg_id, a.title
LIMIT 100;
"
```

**修复步骤**:

```bash
# 触发同步任务
uv run python -c "
import asyncio
from container import Container

async def main():
    container = Container().configure()
    await container.startup()
    jobs = container.scheduler_jobs()
    count = await jobs.sync_neo4j_with_postgres()
    print(f'Synced {count} articles')

asyncio.run(main())
"
```

### 场景 3: 实体向量孤儿清理

**症状**: `entity_vectors` 表中有无效引用

**修复步骤**:

```bash
# 运行清理任务
uv run python -c "
import asyncio
from container import Container

async def main():
    container = Container().configure()
    await container.startup()
    jobs = container.scheduler_jobs()
    count = await jobs.cleanup_orphan_entity_vectors()
    print(f'Cleaned {count} orphan vectors')

asyncio.run(main())
"
```

---

## 回滚和补偿策略

### 1. Saga 补偿事务

**触发条件**: Phase 2 (Neo4j 写入) 失败

**代码位置**: `src/modules/pipeline/nodes/batch_merger.py:446-479`

```python
# 补偿事务执行逻辑
if neo4j_errors:
    result["compensation_executed"] = True

    for pg_id_str, error_msg in neo4j_errors:
        try:
            pg_id = uuid.UUID(pg_id_str)
            # 删除 PostgreSQL 记录
            await self._article_repo.delete(pg_id)
            log.info("saga_compensation_deleted", article_id=str(pg_id))
        except Exception as comp_exc:
            log.error("saga_compensation_failed", error=str(comp_exc))
            # 依赖 sync_neo4j_with_postgres 后续修复
```

**补偿流程**:

```
┌──────────────────────────────────────────────────────────────────┐
│                     Saga 补偿流程                                 │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Phase 1 成功          Phase 2 失败          补偿事务            │
│  ┌──────────┐         ┌──────────┐         ┌──────────┐         │
│  │PostgreSQL│────────▶│ Neo4j    │────────▶│ 删除 PG  │         │
│  │ PG_DONE  │         │ 失败     │         │ 记录     │         │
│  └──────────┘         └──────────┘         └──────────┘         │
│                                                                  │
│  补偿失败? ────────────────────────────────────▶ 后台对账修复    │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### 2. 手动回滚操作

#### 2.1 单文章回滚

```python
# 通过 Python 代码
import asyncio
import uuid
from container import Container

async def rollback_article(article_id: str):
    """回滚单篇文章"""
    container = Container().configure()
    await container.startup()

    article_repo = container.article_repo()
    neo4j_writer = container.neo4j_writer()

    aid = uuid.UUID(article_id)

    # 1. 删除 Neo4j 节点
    await neo4j_writer.article_repo.delete_article_by_pg_id(article_id)

    # 2. 删除 PostgreSQL 记录
    await article_repo.delete(aid)

    print(f"Rolled back article {article_id}")

# 执行
asyncio.run(rollback_article("your-article-id"))
```

#### 2.2 批量回滚

```bash
# 使用 SQL 脚本
psql $POSTGRES_DSN << 'EOF'
-- 开始事务
BEGIN;

-- 1. 备份要删除的数据
CREATE TEMP TABLE articles_to_rollback AS
SELECT * FROM articles
WHERE persist_status = 'failed'
  AND created_at > NOW() - INTERVAL '1 hour';

-- 2. 删除向量
DELETE FROM article_vectors
WHERE article_id IN (SELECT id FROM articles_to_rollback);

-- 3. 删除文章
DELETE FROM articles
WHERE id IN (SELECT id FROM articles_to_rollback);

-- 4. 删除 Neo4j 节点 (需要单独执行 Cypher)
-- MATCH (a:Article) WHERE a.pg_id IN [...] DETACH DELETE a

-- 提交事务
COMMIT;
EOF
```

### 3. 数据恢复策略

#### 3.1 从 Neo4j 恢复到 PostgreSQL

```python
async def restore_from_neo4j():
    """从 Neo4j 恢复缺失的 PostgreSQL 数据"""
    container = Container().configure()
    await container.startup()

    article_repo = container.article_repo()
    neo4j_writer = container.neo4j_writer()

    # 获取 Neo4j 中所有文章
    neo4j_articles = await neo4j_writer.article_repo.list_all_articles()

    for article in neo4j_articles:
        pg_id = article["pg_id"]

        # 检查 PostgreSQL 是否存在
        existing = await article_repo.get(pg_id)
        if not existing:
            # 创建缺失的 PostgreSQL 记录
            await article_repo.create_from_neo4j(article)
```

#### 3.2 从 PostgreSQL 恢复到 Neo4j

```python
async def restore_to_neo4j():
    """将 PostgreSQL 数据恢复到 Neo4j"""
    container = Container().configure()
    await container.startup()

    article_repo = container.article_repo()
    neo4j_writer = container.neo4j_writer()

    # 获取 PostgreSQL 中 NEO4J_DONE 的文章
    articles = await article_repo.get_all_neo4j_done()

    for article in articles:
        # 检查 Neo4j 是否存在
        existing = await neo4j_writer.article_repo.find_article_by_pg_id(str(article.id))
        if not existing:
            # 重新写入 Neo4j
            state = await reconstruct_state(article)
            await neo4j_writer.write(state)
```

---

## 告警配置与处理

### 告警分级处理

| 告警名称 | 严重级别 | 响应时间 | 处理方式 |
|----------|----------|----------|----------|
| `SevereDataInconsistency` | Critical | < 5 分钟 | 立即执行同步修复 |
| `DataInconsistencyDetected` | Warning | < 4 小时 | 检查后台任务日志 |
| `HighPersistenceFailureRate` | Warning | < 1 小时 | 检查 Neo4j 连接状态 |
| `CircuitBreakerOpen` | Critical | < 5 分钟 | 检查下游服务状态 |

### 告警响应 Runbook

#### SevereDataInconsistency 响应流程

```mermaid
flowchart TD
    A[告警触发] --> B{数据差异 > 100?}
    B -->|是| C[立即响应]
    B -->|否| D[常规处理]

    C --> E[检查后台任务状态]
    E --> F{sync 任务运行中?}
    F -->|是| G[等待任务完成]
    F -->|否| H[手动触发同步]

    G --> I[验证修复结果]
    H --> I

    I --> J{差异 < 10?}
    J -->|是| K[告警解决]
    J -->|否| L[深入分析]

    L --> M[检查错误日志]
    M --> N[执行手动修复]
```

---

## 故障排除指南

### 问题 1: 后台任务未执行

**症状**: 数据不一致持续存在，未自动修复

**诊断**:

```bash
# 检查调度器状态
curl http://localhost:8000/api/v1/admin/scheduler/status

# 检查 APScheduler 日志
docker logs weaver 2>&1 | grep scheduler

# 检查任务执行历史
psql $POSTGRES_DSN -c "
SELECT * FROM apscheduler_jobs
ORDER BY next_run_time DESC
LIMIT 10;
"
```

**解决方案**:

```bash
# 重启调度器
curl -X POST http://localhost:8000/api/v1/admin/scheduler/restart

# 或重启应用
docker restart weaver
```

### 问题 2: Neo4j 连接超时

**症状**: 大量 `neo4j_write_failed` 错误

**诊断**:

```bash
# 检查 Neo4j 状态
curl http://neo4j:7474

# 检查连接池
cypher-shell -a $NEO4J_URI "CALL dbms.connectionPool()"

# 检查事务
cypher-shell -a $NEO4J_URI "CALL dbms.listTransactions()"
```

**解决方案**:

```bash
# 增加 Neo4j 内存
# 在 neo4j.conf 中:
# dbms.memory.heap.initial_size=2G
# dbms.memory.heap.max_size=4G

# 重启 Neo4j
docker restart neo4j
```

### 问题 3: Circuit Breaker 持续熔断

**症状**: Circuit Breaker 长期处于 OPEN 状态

**诊断**:

```bash
# 检查熔断器状态
curl http://localhost:8000/metrics | grep circuit_breaker_state

# 检查失败原因
curl http://localhost:8000/metrics | grep circuit_breaker_failures_total
```

**解决方案**:

```python
# 手动重置熔断器 (通过 API 或代码)
import asyncio
from core.llm.queue_manager import LLMQueueManager

async def reset_circuit_breaker(provider: str):
    manager = LLMQueueManager.get_instance()
    cb = manager.get_circuit_breaker(provider)
    await cb.reset()

asyncio.run(reset_circuit_breaker("neo4j"))
```

---

## 常见问题解决方案

### Q1: 如何判断数据是否一致？

**回答**: 执行以下检查:

```bash
# 1. 比较 PostgreSQL 和 Neo4j 文章数
PG_COUNT=$(psql $POSTGRES_DSN -t -c "SELECT COUNT(*) FROM articles WHERE persist_status = 'neo4j_done'")
NEO4J_COUNT=$(cypher-shell -a $NEO4J_URI "MATCH (a:Article) RETURN count(a)" | head -1)

if [ "$PG_COUNT" -eq "$NEO4J_COUNT" ]; then
    echo "数据一致"
else
    echo "数据不一致: PG=$PG_COUNT, Neo4j=$NEO4J_COUNT"
fi

# 2. 检查状态分布
psql $POSTGRES_DSN -c "
SELECT persist_status, COUNT(*)
FROM articles
GROUP BY persist_status
ORDER BY COUNT(*) DESC;
"
```

### Q2: 文章卡在 PROCESSING 状态怎么办？

**回答**:

```bash
# 1. 检查是否真的在处理
psql $POSTGRES_DSN -c "
SELECT id, processing_stage, updated_at
FROM articles
WHERE persist_status = 'processing'
ORDER BY updated_at;
"

# 2. 如果确认卡住，重置状态
psql $POSTGRES_DSN -c "
UPDATE articles
SET persist_status = 'pending', processing_error = 'Manual reset'
WHERE persist_status = 'processing'
  AND updated_at < NOW() - INTERVAL '30 minutes';
"

# 3. 触发重试任务
curl -X POST http://localhost:8000/api/v1/admin/retry/pipeline
```

### Q3: 如何手动修复孤儿实体向量？

**回答**:

```python
import asyncio
from container import Container

async def cleanup_orphan_vectors():
    container = Container().configure()
    await container.startup()

    # 获取 Neo4j 所有实体 ID
    neo4j_pool = container.neo4j_pool()
    result = await neo4j_pool.execute_query(
        "MATCH (e:Entity) RETURN e.id as id", {}
    )
    active_ids = {r["id"] for r in result}

    # 获取 PostgreSQL 实体向量 ID
    pg_ids = await get_entity_vector_ids()  # 需要实现

    # 计算孤儿
    orphan_ids = pg_ids - active_ids

    # 删除孤儿向量
    if orphan_ids:
        vector_repo = container.vector_repo()
        count = await vector_repo.delete_entity_vectors_by_neo4j_ids(list(orphan_ids))
        print(f"Deleted {count} orphan vectors")

asyncio.run(cleanup_orphan_vectors())
```

### Q4: 如何验证 Saga 补偿是否正确执行？

**回答**:

```bash
# 检查补偿执行日志
docker logs weaver 2>&1 | grep saga_compensation

# 验证一致性
psql $POSTGRES_DSN -c "
SELECT COUNT(*) as pg_done_count
FROM articles
WHERE persist_status = 'pg_done';
"

cypher-shell -a $NEO4J_URI "
MATCH (a:Article)
WHERE NOT EXISTS {
  MATCH (a)-[:MENTIONS]->()
}
RETURN count(a) as potential_orphans;
"
```

### Q5: 如何监控数据一致性趋势？

**回答**:

使用 Grafana 仪表盘 `database-consistency.json`，或执行以下 PromQL 查询:

```promql
# 数据差异趋势
abs(
  pg_stat_user_tables_n_live_tup{datname="weaver"}
  -
  neo4j_node_count{label="Article"}
)

# 持久化失败率趋势
sum(persist_status_count{status="failed"})
/
sum(persist_status_count)

# PG_DONE 积压趋势
persist_status_count{status="pg_done"}
```

---

## 配置要求

### 环境变量

```bash
# PostgreSQL
POSTGRES_DSN=postgresql://user:pass@host:5432/weaver

# Neo4j
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password

# Redis (用于任务状态)
REDIS_URL=redis://localhost:6379/0

# 监控
OBS_OTLP_ENDPOINT=http://otel-collector:4317
```

### 调度器配置

**代码位置**: `src/main.py:84-158`

```python
# 可在 main.py 中调整任务频率
scheduler.add_job(
    jobs.retry_neo4j_writes,
    trigger=IntervalTrigger(minutes=10),  # 调整频率
    id="retry_neo4j_writes",
    max_instances=1,  # 防止并发执行
    coalesce=True,    # 合并错过的执行
)
```

### Circuit Breaker 配置

```python
# 可在 circuit_breaker.py 或初始化时调整
CircuitBreaker(
    threshold=5,        # 连续失败次数阈值
    timeout_secs=60.0,  # 冷却期（秒）
)
```

---

## 验证方法

### 1. 自动验证脚本

```bash
#!/bin/bash
# verify_consistency.sh

set -e

echo "=== Weaver 数据一致性验证 ==="

# 1. 健康检查
echo "1. 检查服务健康状态..."
HEALTH=$(curl -s http://localhost:8000/health)
echo "$HEALTH" | jq '.checks'

# 2. 数据量对比
echo "2. 对比数据量..."
PG_COUNT=$(psql $POSTGRES_DSN -t -c "SELECT COUNT(*) FROM articles WHERE persist_status = 'neo4j_done'" | tr -d ' ')
NEO4J_COUNT=$(cypher-shell -a $NEO4J_URI -u $NEO4J_USER -p $NEO4J_PASSWORD "MATCH (a:Article) RETURN count(a)" 2>/dev/null | head -1 | tr -d ' ')

echo "PostgreSQL NEO4J_DONE: $PG_COUNT"
echo "Neo4j Articles: $NEO4J_COUNT"

if [ "$PG_COUNT" -eq "$NEO4J_COUNT" ]; then
    echo "✅ 数据量一致"
else
    DIFF=$((PG_COUNT - NEO4J_COUNT))
    echo "⚠️ 数据量差异: $DIFF"
fi

# 3. 状态分布
echo "3. 状态分布..."
psql $POSTGRES_DSN -c "
SELECT persist_status, COUNT(*)
FROM articles
GROUP BY persist_status
ORDER BY COUNT(*) DESC;
"

# 4. 检查卡住的文章
echo "4. 检查卡住的文章..."
STUCK=$(psql $POSTGRES_DSN -t -c "
SELECT COUNT(*) FROM articles
WHERE persist_status IN ('pending', 'pg_done', 'processing')
  AND updated_at < NOW() - INTERVAL '30 minutes'
" | tr -d ' ')

if [ "$STUCK" -gt 0 ]; then
    echo "⚠️ 发现 $STUCK 篇卡住的文章"
else
    echo "✅ 无卡住文章"
fi

echo "=== 验证完成 ==="
```

### 2. 集成测试验证

```bash
# 运行一致性测试
uv run pytest tests/unit/test_saga_persistence.py -v

# 运行调度任务测试
uv run pytest tests/unit/test_scheduler_jobs.py -v
```

---

## 相关文档

- [架构文档](./architecture.md) - Saga 模式和状态机详细说明
- [监控指南](./monitoring.md) - Prometheus 和 Grafana 配置
- [API 文档](./api.md) - 相关 API 端点

---

## 变更历史

| 日期 | 版本 | 变更内容 |
|------|------|----------|
| 2026-03-27 | 1.0 | 初始版本 |