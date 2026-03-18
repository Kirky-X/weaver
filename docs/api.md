# Weaver API 文档

本文档详细说明 Weaver 系统 RESTful API 端点的请求/响应格式、状态码和错误处理。

## 目录

- [健康检查端点](#健康检查端点)
  - [GET /health](#get-health)
- [监控指标端点](#监控指标端点)
  - [GET /metrics](#get-metrics)
- [错误响应格式](#错误响应格式)
- [通用规范](#通用规范)

---

## 健康检查端点

### GET /health

健康检查端点用于监控服务及其依赖项的运行状态，支持 Kubernetes 探针和负载均衡器健康检查。

#### 请求

```http
GET /health HTTP/1.1
Host: api.weaver.example.com
```

**请求参数**: 无

**请求头**: 无特殊要求

#### 响应

**成功响应 (200 OK)**

当所有依赖项健康时返回：

```json
{
  "status": "healthy",
  "checks": {
    "postgres": {
      "status": "ok",
      "latency_ms": 12.34
    },
    "neo4j": {
      "status": "ok",
      "latency_ms": 23.45
    },
    "redis": {
      "status": "ok",
      "latency_ms": 5.67
    }
  }
}
```

**失败响应 (503 Service Unavailable)**

当任一依赖项不健康时返回：

```json
{
  "status": "unhealthy",
  "checks": {
    "postgres": {
      "status": "ok",
      "latency_ms": 10.23
    },
    "neo4j": {
      "status": "error",
      "latency_ms": 5001.23,
      "error": "Connection refused"
    },
    "redis": {
      "status": "ok",
      "latency_ms": 3.45
    }
  }
}
```

#### 状态码

| 状态码 | 说明 |
|--------|------|
| 200 OK | 所有依赖项健康 |
| 503 Service Unavailable | 至少一个依赖项不健康 |

#### 检查状态说明

每个依赖项的检查结果包含 `status` 字段，可能的值包括：

| status 值 | 说明 | 示例场景 |
|-----------|------|----------|
| `ok` | 依赖项健康 | 连接正常，响应时间在阈值内 |
| `timeout` | 检查超时 | 5 秒内未响应 |
| `error` | 检查失败 | 连接失败、认证错误、查询异常 |
| `unavailable` | 服务未初始化 | 数据库池未创建或未配置 |

#### 响应字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | string | 整体健康状态：`healthy` 或 `unhealthy` |
| `checks` | object | 各依赖项检查结果 |
| `checks.<name>.status` | string | 该依赖项的健康状态 |
| `checks.<name>.latency_ms` | number | 检查耗时（毫秒） |
| `checks.<name>.error` | string | 错误信息（仅失败时存在） |

#### 使用示例

**cURL 示例**

```bash
# 健康检查
curl -i https://api.weaver.example.com/health

# 输出示例
HTTP/2 200
content-type: application/json

{
  "status": "healthy",
  "checks": {
    "postgres": {"status": "ok", "latency_ms": 8.12},
    "neo4j": {"status": "ok", "latency_ms": 15.34},
    "redis": {"status": "ok", "latency_ms": 2.56}
  }
}
```

**Python 示例**

```python
import httpx
import asyncio

async def check_health():
    async with httpx.AsyncClient() as client:
        response = await client.get("https://api.weaver.example.com/health")

        if response.status_code == 200:
            data = response.json()
            print(f"服务健康: {data['status']}")
            for name, check in data["checks"].items():
                print(f"  {name}: {check['status']} ({check['latency_ms']:.2f}ms)")
        else:
            print(f"服务不健康: {response.status_code}")
            print(response.json())

asyncio.run(check_health())
```

**Kubernetes 探针配置**

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 30
  timeoutSeconds: 5
  failureThreshold: 3

readinessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3
```

#### 实现细节

- **超时设置**: 每个依赖项检查设置 5 秒超时
- **并发检查**: 所有依赖项并发检查，减少总响应时间
- **连接池**: 使用预初始化的连接池，避免每次创建新连接
- **错误隔离**: 单个依赖项失败不影响其他依赖项的检查

```python
async def check_postgres_health(pool: PostgresPool) -> dict[str, Any]:
    """PostgreSQL 健康检查。"""
    start = time.monotonic()
    try:
        async with asyncio.timeout(5):  # 5秒超时
            async with pool.session_context() as session:
                await session.execute(text("SELECT 1"))
        latency_ms = (time.monotonic() - start) * 1000
        return {"status": "ok", "latency_ms": latency_ms}
    except asyncio.TimeoutError:
        latency_ms = (time.monotonic() - start) * 1000
        return {"status": "timeout", "latency_ms": latency_ms}
    except Exception as e:
        latency_ms = (time.monotonic() - start) * 1000
        return {"status": "error", "latency_ms": latency_ms, "error": str(e)}
```

---

## 监控指标端点

### GET /metrics

Prometheus 指标端点用于暴露系统运行时指标，支持 Prometheus 抓取和 Grafana 可视化。

#### 请求

```http
GET /metrics HTTP/1.1
Host: api.weaver.example.com
Accept: text/plain
```

**请求参数**: 无

**请求头**: 无特殊要求

#### 响应

**成功响应 (200 OK)**

返回 Prometheus 文本格式指标：

```prometheus
# HELP python_info Python platform information
# TYPE python_info gauge
python_info{implementation="CPython",major="3",minor="11",version="3.11.5"} 1.0

# HELP process_cpu_seconds_total Total user and system CPU seconds spent
# TYPE process_cpu_seconds_total counter
process_cpu_seconds_total 1234.56

# HELP process_resident_memory_bytes Resident memory size in bytes
# TYPE process_resident_memory_bytes gauge
process_resident_memory_bytes 1.342148e+08

# HELP http_requests_total Total HTTP requests
# TYPE http_requests_total counter
http_requests_total{method="GET",endpoint="/health",status="200"} 1523
http_requests_total{method="GET",endpoint="/metrics",status="200"} 892

# HELP http_request_duration_seconds HTTP request latency
# TYPE http_request_duration_seconds histogram
http_request_duration_seconds_bucket{method="GET",endpoint="/health",le="0.005"} 1200
http_request_duration_seconds_bucket{method="GET",endpoint="/health",le="0.01"} 1450
http_request_duration_seconds_bucket{method="GET",endpoint="/health",le="0.025"} 1510
http_request_duration_seconds_bucket{method="GET",endpoint="/health",le="0.05"} 1520
http_request_duration_seconds_bucket{method="GET",endpoint="/health",le="0.1"} 1522
http_request_duration_seconds_bucket{method="GET",endpoint="/health",le="+Inf"} 1523
http_request_duration_seconds_sum{method="GET",endpoint="/health"} 4.567
http_request_duration_seconds_count{method="GET",endpoint="/health"} 1523

# HELP circuit_breaker_state Circuit breaker state (0=CLOSED, 1=OPEN, 2=HALF_OPEN)
# TYPE circuit_breaker_state gauge
circuit_breaker_state{service="neo4j"} 0
circuit_breaker_state{service="llm"} 0

# HELP db_connection_pool_size Database connection pool size
# TYPE db_connection_pool_size gauge
db_connection_pool_size{database="postgres"} 10
db_connection_pool_size{database="neo4j"} 5

# HELP articles_processed_total Total articles processed by pipeline
# TYPE articles_processed_total counter
articles_processed_total{status="success"} 45678
articles_processed_total{status="failed"} 123
```

**Content-Type**

```
Content-Type: text/plain; version=0.0.4; charset=utf-8
```

#### 状态码

| 状态码 | 说明 |
|--------|------|
| 200 OK | 成功返回指标数据 |

#### 核心指标列表

##### 1. 系统指标

| 指标名称 | 类型 | 说明 |
|----------|------|------|
| `python_info` | Gauge | Python 版本信息 |
| `process_cpu_seconds_total` | Counter | CPU 使用总时间（秒） |
| `process_resident_memory_bytes` | Gauge | 驻留内存大小（字节） |
| `process_start_time_seconds` | Gauge | 进程启动时间（Unix 时间戳） |

##### 2. HTTP 指标

| 指标名称 | 类型 | 标签 | 说明 |
|----------|------|------|------|
| `http_requests_total` | Counter | `method`, `endpoint`, `status` | HTTP 请求总数 |
| `http_request_duration_seconds` | Histogram | `method`, `endpoint` | HTTP 请求延迟分布 |
| `http_requests_in_progress` | Gauge | `method`, `endpoint` | 正在处理的请求数 |

##### 3. Circuit Breaker 指标

| 指标名称 | 类型 | 标签 | 说明 |
|----------|------|------|------|
| `circuit_breaker_state` | Gauge | `service` | 熔断器状态 (0=CLOSED, 1=OPEN, 2=HALF_OPEN) |
| `circuit_breaker_fail_count` | Gauge | `service` | 当前失败计数 |
| `circuit_breaker_open_total` | Counter | `service` | 熔断器打开总次数 |
| `circuit_breaker_half_open_total` | Counter | `service` | 进入半开状态总次数 |

##### 4. 数据库连接池指标

| 指标名称 | 类型 | 标签 | 说明 |
|----------|------|------|------|
| `db_connection_pool_size` | Gauge | `database` | 连接池大小 |
| `db_connection_pool_available` | Gauge | `database` | 可用连接数 |
| `db_connection_pool_checked_out` | Gauge | `database` | 已检出连接数 |
| `db_connection_errors_total` | Counter | `database`, `error_type` | 连接错误总数 |

##### 5. Pipeline 指标

| 指标名称 | 类型 | 标签 | 说明 |
|----------|------|------|------|
| `articles_processed_total` | Counter | `status` | 处理的文章总数 |
| `pipeline_stage_duration_seconds` | Histogram | `stage` | 各阶段处理时长 |
| `llm_calls_total` | Counter | `model`, `status` | LLM 调用总数 |
| `llm_call_duration_seconds` | Histogram | `model` | LLM 调用延迟分布 |

##### 6. 数据一致性指标

| 指标名称 | 类型 | 标签 | 说明 |
|----------|------|------|------|
| `saga_transactions_total` | Counter | `status` | Saga 事务总数 |
| `saga_compensation_total` | Counter | `reason` | 补偿事务总数 |
| `persist_status_articles` | Gauge | `status` | 各状态文章数量 |

#### 使用示例

**Prometheus 配置**

```yaml
scrape_configs:
  - job_name: 'weaver'
    scrape_interval: 15s
    static_configs:
      - targets: ['api.weaver.example.com:8000']
    metrics_path: /metrics
```

**Grafana 查询示例**

```promql
# HTTP 请求速率 (QPS)
rate(http_requests_total[5m])

# P95 请求延迟
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))

# Circuit Breaker 熔断次数
rate(circuit_breaker_open_total[1h])

# 文章处理成功率
sum(rate(articles_processed_total{status="success"}[1h]))
/
sum(rate(articles_processed_total[1h]))

# 数据库连接池使用率
db_connection_pool_checked_out{database="postgres"}
/
db_connection_pool_size{database="postgres"}
```

**Python 客户端示例**

```python
import httpx

def fetch_metrics():
    """获取 Prometheus 指标。"""
    response = httpx.get("https://api.weaver.example.com/metrics")

    if response.status_code == 200:
        metrics_text = response.text
        # 解析指标
        for line in metrics_text.split("\n"):
            if line and not line.startswith("#"):
                print(line)

fetch_metrics()
```

#### 安全注意事项

- **生产环境**: 建议通过防火墙规则限制 `/metrics` 端点访问，仅允许 Prometheus 服务器访问
- **敏感信息**: 确保指标中不包含敏感信息（密码、API 密钥等）
- **性能影响**: 指标收集和暴露对性能影响极小（< 1% CPU）

---

## 错误响应格式

### 统一错误响应结构

所有 API 错误响应使用统一格式：

```json
{
  "code": 1001,
  "message": "文章不存在"
}
```

#### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | integer | 业务错误码，用于程序识别 |
| `message` | string | 人类可读的错误描述 |

### HTTP 状态码规范

| 状态码 | 说明 | 使用场景 |
|--------|------|----------|
| 200 OK | 请求成功 | 成功的 GET、PUT、PATCH 请求 |
| 201 Created | 资源创建成功 | 成功的 POST 请求 |
| 204 No Content | 无内容 | 成功的 DELETE 请求 |
| 400 Bad Request | 请求参数错误 | 参数验证失败、格式错误 |
| 401 Unauthorized | 未认证 | 缺少或无效的认证信息 |
| 403 Forbidden | 无权限 | 已认证但权限不足 |
| 404 Not Found | 资源不存在 | 请求的资源不存在 |
| 409 Conflict | 资源冲突 | 违反唯一性约束 |
| 422 Unprocessable Entity | 业务逻辑错误 | 请求格式正确但无法处理 |
| 429 Too Many Requests | 请求过于频繁 | 触发速率限制 |
| 500 Internal Server Error | 服务器内部错误 | 未预期的异常 |
| 503 Service Unavailable | 服务不可用 | 依赖服务不健康 |

### 业务错误码

#### 通用错误 (1000-1999)

| 错误码 | HTTP 状态码 | 说明 |
|--------|-------------|------|
| 1000 | 400 | 请求参数错误 |
| 1001 | 404 | 资源不存在 |
| 1002 | 409 | 资源已存在 |
| 1003 | 422 | 业务逻辑验证失败 |

#### 认证授权错误 (2000-2999)

| 错误码 | HTTP 状态码 | 说明 |
|--------|-------------|------|
| 2000 | 401 | 未提供认证信息 |
| 2001 | 401 | 认证信息无效 |
| 2002 | 403 | 权限不足 |
| 2003 | 401 | Token 已过期 |

#### Pipeline 错误 (3000-3999)

| 错误码 | HTTP 状态码 | 说明 |
|--------|-------------|------|
| 3000 | 422 | Pipeline 执行失败 |
| 3001 | 422 | 文章解析失败 |
| 3002 | 422 | LLM 调用失败 |
| 3003 | 422 | 向量生成失败 |
| 3004 | 422 | 实体抽取失败 |
| 3005 | 422 | Neo4j 写入失败 |

#### 数据库错误 (4000-4999)

| 错误码 | HTTP 状态码 | 说明 |
|--------|-------------|------|
| 4000 | 503 | 数据库连接失败 |
| 4001 | 500 | 数据库查询错误 |
| 4002 | 500 | 数据库写入错误 |
| 4003 | 422 | 状态转换非法 |

#### 限流错误 (5000-5999)

| 错误码 | HTTP 状态码 | 说明 |
|--------|-------------|------|
| 5000 | 429 | 请求速率超限 |
| 5001 | 429 | 并发请求数超限 |

### 错误响应示例

#### 参数验证错误

```http
HTTP/1.1 400 Bad Request
Content-Type: application/json

{
  "code": 1000,
  "message": "参数验证失败: 'category' 必须是 ['政治', '军事', '经济'] 之一"
}
```

#### 资源不存在

```http
HTTP/1.1 404 Not Found
Content-Type: application/json

{
  "code": 1001,
  "message": "文章不存在: article_id=550e8400-e29b-41d4-a716-446655440000"
}
```

#### 未认证

```http
HTTP/1.1 401 Unauthorized
Content-Type: application/json
WWW-Authenticate: Bearer

{
  "code": 2000,
  "message": "未提供认证信息，请提供有效的 Bearer Token"
}
```

#### 权限不足

```http
HTTP/1.1 403 Forbidden
Content-Type: application/json

{
  "code": 2002,
  "message": "权限不足: 需要 'admin' 角色"
}
```

#### 速率限制

```http
HTTP/1.1 429 Too Many Requests
Content-Type: application/json
Retry-After: 60
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1609459200

{
  "code": 5000,
  "message": "请求速率超限，请 60 秒后重试"
}
```

#### 服务器内部错误

```http
HTTP/1.1 500 Internal Server Error
Content-Type: application/json

{
  "code": 500,
  "message": "内部服务器错误，请稍后重试"
}
```

**注意**: 生产环境中，500 错误不暴露详细堆栈信息，仅返回通用错误消息。详细信息记录在服务器日志中。

#### 服务不可用

```http
HTTP/1.1 503 Service Unavailable
Content-Type: application/json
Retry-After: 120

{
  "code": 4000,
  "message": "数据库服务不可用，请稍后重试"
}
```

### 异常处理最佳实践

#### 客户端处理示例

```python
import httpx
from typing import Optional

class APIError(Exception):
    """API 错误异常。"""
    def __init__(self, code: int, message: str, status_code: int):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(f"[{code}] {message}")

async def call_api():
    """调用 API 并处理错误。"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                "https://api.weaver.example.com/api/articles",
                json={"title": "Test", "body": "Content"},
            )
            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            # 解析错误响应
            try:
                error_data = e.response.json()
                raise APIError(
                    code=error_data.get("code", 500),
                    message=error_data.get("message", "Unknown error"),
                    status_code=e.response.status_code,
                )
            except ValueError:
                raise APIError(
                    code=500,
                    message="Invalid error response",
                    status_code=e.response.status_code,
                )

        except httpx.TimeoutException:
            raise APIError(
                code=500,
                message="Request timeout",
                status_code=504,
            )

        except httpx.RequestError as e:
            raise APIError(
                code=500,
                message=f"Network error: {str(e)}",
                status_code=503,
            )
```

#### 重试策略

```python
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry_error_callback=lambda e: None,
)
async def call_api_with_retry():
    """带重试的 API 调用。"""
    try:
        return await call_api()
    except APIError as e:
        # 仅对可重试错误进行重试
        if e.status_code in [429, 500, 502, 503, 504]:
            print(f"请求失败 ({e.status_code})，准备重试...")
            raise
        else:
            # 不可重试错误直接返回
            raise
```

---

## 通用规范

### 请求规范

#### 内容类型

- **请求体**: `application/json`
- **响应体**: `application/json` (除 `/metrics` 端点)

#### 字符编码

所有请求和响应使用 **UTF-8** 编码。

#### 日期时间格式

使用 **ISO 8601** 格式：

```
2024-01-15T10:30:00Z                    # UTC
2024-01-15T18:30:00+08:00              # 带时区
```

#### 分页参数

```
GET /api/articles?page=2&page_size=20
```

- `page`: 页码，从 1 开始（默认: 1）
- `page_size`: 每页数量（默认: 20，最大: 100）

#### 排序参数

```
GET /api/articles?sort=publish_time&order=desc
```

- `sort`: 排序字段
- `order`: 排序方向（`asc` 或 `desc`）

### 响应规范

#### 成功响应

**单个资源**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "文章标题",
  "body": "文章内容",
  "created_at": "2024-01-15T10:30:00Z"
}
```

**资源列表**

```json
{
  "items": [
    {"id": "...", "title": "..."},
    {"id": "...", "title": "..."}
  ],
  "total": 100,
  "page": 1,
  "page_size": 20,
  "total_pages": 5
}
```

#### 响应头

```
Content-Type: application/json; charset=utf-8
X-Request-ID: 550e8400-e29b-41d4-a716-446655440000
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1609459200
```

### 认证

使用 **Bearer Token** 认证：

```http
Authorization: Bearer <token>
```

### 速率限制

默认限制：**100 请求/分钟**

响应头包含限制信息：

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1609459200
```

超过限制返回 **429 Too Many Requests**。

### 版本控制

API 版本通过 URL 前缀指定：

```
/api/v1/articles
/api/v2/articles
```

当前版本: **v1**

---

## 总结

Weaver API 遵循 RESTful 设计原则，提供：

1. **健康检查端点** (`/health`)：监控服务及依赖项状态
2. **监控指标端点** (`/metrics`)：Prometheus 格式的运行时指标
3. **统一错误格式**：结构化的错误响应，便于客户端处理
4. **完善的文档**：详细的请求/响应示例和状态码说明

所有端点均支持高并发访问，并配备完善的监控和告警机制。