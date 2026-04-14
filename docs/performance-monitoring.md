# 性能监控方案

## 概述

本文档定义 weaver 项目的性能监控策略，包括数据库慢查询日志、API 响应时间监控和索引使用情况监控。

---

## 1. 数据库慢查询日志

### 1.1 PostgreSQL 慢查询配置

**文件**: `config/settings.toml` 或环境变量

```toml
[database]
# 慢查询阈值（毫秒）
slow_query_threshold_ms = 100

# 启用查询日志
log_slow_queries = true
```

### 1.2 SQLAlchemy 事件监听

**文件**: `src/core/db/events.py`（新建）

```python
"""SQLAlchemy event listeners for performance monitoring."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from sqlalchemy import event

from core.observability import get_logger

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

log = get_logger(__name__)


@event.listens_for(Connection, "before_cursor_execute")
def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    """Record query start time."""
    conn.info.setdefault("query_start_time", []).append(time.time())
    log.debug("query_start", statement=statement[:100])


@event.listens_for(Connection, "after_cursor_execute")
def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    """Log slow queries."""
    total_time = time.time() - conn.info["query_start_time"].pop(-1)
    threshold_ms = getattr(conn.info.get("slow_query_threshold_ms"), 100)

    if total_time * 1000 > threshold_ms:
        log.warning(
            "slow_query_detected",
            duration_ms=round(total_time * 1000, 2),
            threshold_ms=threshold_ms,
            statement=statement[:200],
            parameters=str(parameters)[:100],
        )
```

### 1.3 启用监听器

**文件**: `src/container.py`

在数据库引擎创建后添加：

```python
from sqlalchemy import event
from core.db.events import before_cursor_execute, after_cursor_execute

# 注册事件监听
event.listen(engine, "before_cursor_execute", before_cursor_execute)
event.listen(engine, "after_cursor_execute", after_cursor_execute)
```

---

## 2. API P95/P99 响应时间监控

### 2.1 FastAPI 中间件

**文件**: `src/api/middleware/performance.py`（新建）

```python
"""Performance monitoring middleware for API response times."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware

from core.observability import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

log = get_logger(__name__)

# 响应时间阈值（毫秒）
P95_THRESHOLD_MS = 500
P99_THRESHOLD_MS = 1000


class PerformanceMonitoringMiddleware(BaseHTTPMiddleware):
    """Monitor API response times and log slow endpoints."""

    async def dispatch(self, request: Request, call_next) -> Response:
        """Measure request duration and log slow responses."""
        start_time = time.time()

        response = await call_next(request)

        duration_ms = (time.time() - start_time) * 1000

        # Log all requests with duration
        log.debug(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 2),
        )

        # Warn on slow responses
        if duration_ms > P99_THRESHOLD_MS:
            log.error(
                "very_slow_response",
                method=request.method,
                path=request.url.path,
                duration_ms=round(duration_ms, 2),
                threshold_ms=P99_THRESHOLD_MS,
            )
        elif duration_ms > P95_THRESHOLD_MS:
            log.warning(
                "slow_response",
                method=request.method,
                path=request.url.path,
                duration_ms=round(duration_ms, 2),
                threshold_ms=P95_THRESHOLD_MS,
            )

        # Add timing header
        response.headers["X-Response-Time-Ms"] = str(round(duration_ms, 2))

        return response
```

### 2.2 注册中间件

**文件**: `src/main.py`

在现有中间件之后添加：

```python
from api.middleware.performance import PerformanceMonitoringMiddleware

app.add_middleware(PerformanceMonitoringMiddleware)
```

---

## 3. 索引使用情况监控

### 3.1 PostgreSQL 索引统计查询

**文件**: `src/api/endpoints/admin/monitoring.py`（新建）

```python
"""Database monitoring endpoints for performance analysis."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends
from sqlalchemy import text

from api.dependencies import get_container
from api.middleware.auth import verify_admin_api_key
from api.schemas.response import APIResponse, success_response

if TYPE_CHECKING:
    from container import Container

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/database/indexes")
async def get_index_usage(
    _: str = Depends(verify_admin_api_key),
    container: Container = Depends(get_container),
) -> APIResponse:
    """Get PostgreSQL index usage statistics.

    Returns information about:
    - Index scan counts
    - Index size
    - Unused indexes (candidates for removal)
    - Missing index candidates
    """
    pool = container.relational_pool()

    async with pool.connect() as conn:
        # Index usage statistics
        result = await conn.execute(text("""
            SELECT
                schemaname || '.' || relname AS table,
                indexrelname AS index,
                idx_scan AS index_scans,
                idx_tup_read AS tuples_read,
                idx_tup_fetch AS tuples_fetched,
                pg_size_pretty(pg_relation_size(indexrelid)) AS index_size
            FROM pg_stat_user_indexes
            ORDER BY idx_scan ASC
            LIMIT 50
        """))

        indexes = [dict(row) for row in result]

    return success_response({
        "indexes": indexes,
        "total_count": len(indexes),
    })


@router.get("/database/slow-queries")
async def get_slow_queries(
    limit: int = 20,
    _: str = Depends(verify_admin_api_key),
    container: Container = Depends(get_container),
) -> APIResponse:
    """Get recent slow queries from pg_stat_statements.

    Requires pg_stat_statements extension to be enabled.
    """
    pool = container.relational_pool()

    async with pool.connect() as conn:
        result = await conn.execute(text("""
            SELECT
                query,
                calls,
                mean_exec_time AS avg_duration_ms,
                total_exec_time AS total_duration_ms,
                rows_retrieved
            FROM pg_stat_statements
            WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
            ORDER BY mean_exec_time DESC
            LIMIT :limit
        """), {"limit": limit})

        queries = [dict(row) for row in result]

    return success_response({
        "slow_queries": queries,
        "limit": limit,
    })
```

### 3.2 定期索引检查脚本

**文件**: `scripts/monitor_indexes.py`（子命令）

添加到 `scripts/tools.py`:

```python
def check_indexes(args):
    """Check database index usage and health."""
    import asyncio
    from container import Container

    async def _run():
        container = Container().configure()
        pool = container.relational_pool()

        async with pool.connect() as conn:
            # Find unused indexes (scanned < 10 times)
            result = await conn.execute(text("""
                SELECT
                    schemaname || '.' || relname AS table,
                    indexrelname AS index,
                    idx_scan AS scans,
                    pg_size_pretty(pg_relation_size(indexrelid)) AS size
                FROM pg_stat_user_indexes
                WHERE idx_scan < 10
                ORDER BY idx_scan ASC
            """))

            unused = [dict(row) for row in result]

            if unused:
                print(f"\n⚠️  Found {len(unused)} potentially unused indexes:")
                for idx in unused:
                    print(f"  - {idx['table']}.{idx['index']} (scans: {idx['scans']}, size: {idx['size']})")
            else:
                print("\n✅ All indexes are being used effectively")

    asyncio.run(_run())
```

---

## 4. Grafana 监控面板

### 4.1 Prometheus 指标

**文件**: `monitoring/prometheus/rules/performance.yml`

```yaml
groups:
  - name: performance_alerts
    rules:
      - alert: SlowAPIEndpoint
        expr: histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m])) > 0.5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "API endpoint P95 response time > 500ms"
          description: "{{ $labels.path }} has P95 response time of {{ $value }}s"

      - alert: VerySlowQueries
        expr: rate(slow_query_total[5m]) > 10
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "High rate of slow database queries"
          description: "{{ $value }} slow queries per second"
```

### 4.2 监控面板 JSON

**文件**: `monitoring/grafana/dashboards/performance.json`

关键指标：
- API P50/P95/P99 响应时间趋势
- 慢查询数量趋势
- 索引命中率
- 数据库连接池使用率
- 缓存命中率

---

## 5. 实施步骤

### Phase 1: 基础监控（立即）
1. ✅ 添加 SQLAlchemy 慢查询监听器
2. ✅ 添加 FastAPI 性能中间件
3. ✅ 配置日志输出格式

### Phase 2: 数据库监控（本周）
1. 创建 `/admin/monitoring/database/indexes` 端点
2. 创建 `/admin/monitoring/database/slow-queries` 端点
3. 添加索引检查脚本

### Phase 3: 可视化监控（下周）
1. 配置 Prometheus 指标收集
2. 创建 Grafana 监控面板
3. 设置告警规则

---

## 6. 性能基线

### 6.1 目标指标

| 指标 | P50 | P95 | P99 |
|------|-----|-----|-----|
| **文章列表 API** | <50ms | <200ms | <500ms |
| **文章详情 API** | <30ms | <100ms | <300ms |
| **管理员 API** | <100ms | <500ms | <1000ms |
| **数据库查询** | <10ms | <50ms | <100ms |

### 6.2 告警阈值

| 场景 | 警告 (Warning) | 严重 (Critical) |
|------|---------------|----------------|
| API 响应时间 | P95 > 500ms | P99 > 1000ms |
| 数据库查询 | >100ms | >500ms |
| 慢查询率 | >5/min | >20/min |
| 索引命中率 | <90% | <80% |

---

## 7. 验证测试

运行性能测试验证监控是否正常工作：

```bash
# 1. 启动应用
cd /home/dev/projects/weaver
uv run uvicorn src.main:app --reload

# 2. 运行性能测试
pytest tests/performance/test_query_performance.py -v

# 3. 检查日志输出
tail -f logs/app.log | grep -E "slow_query|slow_response"

# 4. 访问监控端点（需要 admin key）
curl -H "X-API-Key: $ADMIN_API_KEY" \
  http://localhost:8000/api/v1/admin/monitoring/database/indexes
```

---

## 8. 后续优化建议

1. **分布式追踪**: 集成 Jaeger/Zipkin 追踪跨服务调用
2. **APM 工具**: 考虑使用 DataDog/New Relic 等专业 APM
3. **自动扩展**: 基于 P95 响应时间自动扩展实例
4. **查询优化**: 定期分析慢查询日志，优化 SQL
5. **索引优化**: 基于查询模式添加/删除索引

---

**文档版本**: 1.0  
**创建日期**: 2026-04-14  
**最后更新**: 2026-04-14
