# Weaver API 文档

本文档详细说明 Weaver 系统 RESTful API 端点的请求/响应格式、状态码和错误处理。

## 目录

- [文章端点](#文章端点)
  - [GET /api/v1/articles](#get-apiv1articles)
  - [GET /api/v1/articles/{article_id}](#get-apiv1articlesarticle_id)
- [源管理端点](#源管理端点)
  - [GET /api/v1/sources](#get-apiv1sources)
  - [POST /api/v1/sources](#post-apiv1sources)
  - [PUT /api/v1/sources/{source_id}](#put-apiv1sourcessource_id)
  - [DELETE /api/v1/sources/{source_id}](#delete-apiv1sourcessource_id)
- [搜索端点](#搜索端点)
  - [GET /api/v1/search](#get-apiv1search)
  - [GET /api/v1/search/local](#get-apiv1searchlocal)
  - [GET /api/v1/search/global](#get-apiv1searchglobal)
  - [GET /api/v1/search/articles](#get-apiv1searcharticles)
- [Pipeline 端点](#pipeline-端点)
  - [POST /api/v1/pipeline/trigger](#post-apiv1pipelinetrigger)
  - [GET /api/v1/pipeline/tasks/{task_id}](#get-apiv1pipelinetaskstask_id)
  - [GET /api/v1/pipeline/queue/stats](#get-apiv1pipelinequeuestats)
- [图谱端点](#图谱端点)
  - [GET /api/v1/graph/entities/{name}](#get-apiv1graphentitiesname)
  - [GET /api/v1/graph/articles/{article_id}/graph](#get-apiv1grapharticlesarticle_idgraph)
  - [GET /api/v1/graph/metrics/health](#get-apiv1graphmetricshealth)
  - [GET /api/v1/graph/metrics/full](#get-apiv1graphmetricsfull)
  - [GET /api/v1/graph/metrics/components](#get-apiv1graphmetricscomponents)
  - [GET /api/v1/graph/metrics/orphans](#get-apiv1graphmetricsorphans)
  - [GET /api/v1/graph/metrics/high-degree](#get-apiv1graphmetricshigh-degree)
  - [GET /api/v1/graph/metrics/modularity](#get-apiv1graphmetricsmodularity)
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

---

## 文章端点

### GET /api/v1/articles

获取分页文章列表，支持过滤和排序。

#### 请求

```http
GET /api/v1/articles?page=1&page_size=20&category=政治&min_credibility=0.7&sort_by=publish_time&sort_order=desc HTTP/1.1
Host: api.weaver.example.com
X-API-Key: your-api-key
```

**查询参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `page` | integer | 1 | 页码（从1开始） |
| `page_size` | integer | 20 | 每页数量（最大100） |
| `category` | string | - | 按类别过滤（如 `政治`、`军事`、`经济`） |
| `source_host` | string | - | 按来源主机名过滤 |
| `min_score` | float | - | 最低评分过滤（0-1） |
| `min_credibility` | float | - | 最低可信度过滤（0-1） |
| `sort_by` | string | `publish_time` | 排序字段：`publish_time`、`score`、`credibility_score`、`created_at` |
| `sort_order` | string | `desc` | 排序方向：`asc` 或 `desc` |

#### 响应

**成功响应 (200 OK)**

```json
{
  "items": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "source_url": "https://example.com/article",
      "source_host": "example.com",
      "is_news": true,
      "title": "文章标题",
      "body": "文章内容...",
      "category": "政治",
      "language": "zh",
      "region": "中国",
      "summary": "摘要内容",
      "event_time": "2024-01-15T10:00:00+08:00",
      "subjects": ["主题A", "主题B"],
      "key_data": ["关键数据1"],
      "impact": "高",
      "score": 0.85,
      "sentiment": "positive",
      "sentiment_score": 0.72,
      "primary_emotion": "中性",
      "credibility_score": 0.88,
      "source_credibility": 0.95,
      "cross_verification": 0.82,
      "content_check_score": 0.87,
      "publish_time": "2024-01-15T09:30:00+08:00",
      "created_at": "2024-01-15T10:30:00Z",
      "updated_at": "2024-01-15T10:30:00Z"
    }
  ],
  "total": 150,
  "page": 1,
  "page_size": 20,
  "total_pages": 8
}
```

#### 状态码

| 状态码 | 说明 |
|--------|------|
| 200 OK | 成功返回文章列表 |
| 401 Unauthorized | API Key 无效或缺失 |
| 503 Service Unavailable | 数据库服务不可用 |

---

### GET /api/v1/articles/{article_id}

获取指定文章的详细信息。

#### 请求

```http
GET /api/v1/articles/550e8400-e29b-41d4-a716-446655440000 HTTP/1.1
Host: api.weaver.example.com
X-API-Key: your-api-key
```

#### 响应

**成功响应 (200 OK)**

返回与列表接口相同的完整文章对象。

#### 状态码

| 状态码 | 说明 |
|--------|------|
| 200 OK | 成功返回文章详情 |
| 400 Bad Request | 无效的文章 ID 格式 |
| 401 Unauthorized | API Key 无效或缺失 |
| 404 Not Found | 文章不存在 |

---

## 源管理端点

### GET /api/v1/sources

获取所有注册的新闻源列表。

#### 请求

```http
GET /api/v1/sources?enabled_only=true HTTP/1.1
Host: api.weaver.example.com
X-API-Key: your-api-key
```

**查询参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enabled_only` | boolean | true | 是否仅返回已启用的源 |

#### 响应

**成功响应 (200 OK)**

```json
[
  {
    "id": "xinhua-news",
    "name": "新华社",
    "url": "http://www.xinhuanet.com/politics/news_politics.xml",
    "source_type": "rss",
    "enabled": true,
    "interval_minutes": 30,
    "per_host_concurrency": 2,
    "credibility": 0.98,
    "tier": 1,
    "last_crawl_time": "2024-01-15T09:00:00Z"
  }
]
```

---

### POST /api/v1/sources

创建新的新闻源。

#### 请求

```http
POST /api/v1/sources HTTP/1.1
Host: api.weaver.example.com
X-API-Key: your-api-key
Content-Type: application/json

{
  "id": "xinhua-news",
  "name": "新华社",
  "url": "http://www.xinhuanet.com/politics/news_politics.xml",
  "source_type": "rss",
  "enabled": true,
  "interval_minutes": 30,
  "credibility": 0.98,
  "tier": 1
}
```

**请求字段：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | 是 | 唯一标识符 |
| `name` | string | 是 | 显示名称 |
| `url` | string | 是 | RSS/Atom 订阅地址 |
| `source_type` | string | 否 | 源类型，默认 `rss` |
| `enabled` | boolean | 否 | 是否启用，默认 `true` |
| `interval_minutes` | integer | 否 | 抓取间隔（分钟），默认30 |
| `per_host_concurrency` | integer | 否 | 每主机并发数，默认2 |
| `credibility` | float | 否 | 预设可信度（0.0-1.0） |
| `tier` | integer | 否 | 层级：1=权威，2=可信，3=普通 |

#### 状态码

| 状态码 | 说明 |
|--------|------|
| 201 Created | 源创建成功 |
| 401 Unauthorized | API Key 无效或缺失 |
| 409 Conflict | 源 ID 已存在 |

---

### PUT /api/v1/sources/{source_id}

更新指定新闻源的配置。

#### 请求

```http
PUT /api/v1/sources/xinhua-news HTTP/1.1
Host: api.weaver.example.com
X-API-Key: your-api-key
Content-Type: application/json

{
  "enabled": false,
  "interval_minutes": 60
}
```

#### 状态码

| 状态码 | 说明 |
|--------|------|
| 200 OK | 源更新成功 |
| 401 Unauthorized | API Key 无效或缺失 |
| 404 Not Found | 源不存在 |

---

### DELETE /api/v1/sources/{source_id}

删除指定的新闻源。

#### 请求

```http
DELETE /api/v1/sources/xinhua-news HTTP/1.1
Host: api.weaver.example.com
X-API-Key: your-api-key
```

#### 状态码

| 状态码 | 说明 |
|--------|------|
| 204 No Content | 删除成功 |
| 401 Unauthorized | API Key 无效或缺失 |
| 404 Not Found | 源不存在 |

---

## 搜索端点

### GET /api/v1/search

统一搜索端点，根据 `mode` 参数自动路由到合适的搜索引擎。

#### 请求

```http
GET /api/v1/search?q=小米汽车&mode=auto&threshold=0.7 HTTP/1.1
Host: api.weaver.example.com
X-API-Key: your-api-key
```

**查询参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `q` | string | - | 搜索查询（必填） |
| `mode` | string | `auto` | 搜索模式：`auto`、`local`、`global`、`articles` |
| `entity_names` | string | - | 逗号分隔的实体名（local 模式） |
| `max_tokens` | integer | - | 最大上下文 token 数（local/global 模式） |
| `community_level` | integer | 0 | 社区层级（global 模式，0-10） |
| `threshold` | float | 0.0 | 最低相似度（articles 模式，0-1） |
| `limit` | integer | 20 | 最大结果数（articles 模式，1-100） |
| `category` | string | - | 文章类别过滤（articles 模式） |

**mode 说明：**
- `auto`：自动选择（默认路由到 global）
- `local`：实体聚焦的图谱问答，适合"X 是谁？"、"X 和 Y 的关系？"等实体查询
- `global`：社区级聚合搜索，适合跨多个话题的探索性查询
- `articles`：基于 pgvector 的混合向量+关键词相似文章搜索

#### 响应

**成功响应 (200 OK)**

```json
{
  "query": "小米汽车",
  "answer": "Found 5 similar articles.",
  "context_tokens": 0,
  "confidence": 0.82,
  "search_type": "articles",
  "entities": [],
  "sources": [
    {
      "article_id": "uuid-xxx",
      "similarity": 0.75,
      "category": "科技",
      "hybrid_score": 0.82
    }
  ],
  "metadata": {
    "total_results": 5,
    "threshold": 0.7
  }
}
```

---

### GET /api/v1/search/local

实体聚焦的知识图谱问答搜索。

#### 请求

```http
GET /api/v1/search/local?q=雷军和小米的关系&entity_names=雷军,小米 HTTP/1.1
Host: api.weaver.example.com
X-API-Key: your-api-key
```

**查询参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `q` | string | 是 | 搜索查询 |
| `entity_names` | string | 否 | 逗号分隔的实体名，用于聚焦查询 |
| `max_tokens` | integer | 否 | 最大上下文 token 数 |

**适用场景：** "Who is X?"、"How are X and Y related?"、特定实体查询

**注意：** 当前实现默认跳过LLM生成步骤(`use_llm=False`)，直接返回构建的知识图谱上下文。

---

### GET /api/v1/search/global

社区级聚合搜索（Map-Reduce 模式）。

#### 请求

```http
GET /api/v1/search/global?q=中国经济&community_level=0&mode=map_reduce HTTP/1.1
Host: api.weaver.example.com
X-API-Key: your-api-key
```

**查询参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `q` | string | - | 搜索查询（必填） |
| `community_level` | integer | 0 | 社区层级（0-10） |
| `mode` | string | `map_reduce` | 搜索模式：`map_reduce` 或 `simple` |

**适用场景：** 跨多个话题的宽泛探索性查询

**注意：** 当前实现默认跳过LLM生成步骤(`use_llm=False`)，直接返回社区级聚合的上下文。

---

### GET /api/v1/search/articles

基于混合检索（向量+BM25+重排）的相似文章搜索。

#### 请求

```http
GET /api/v1/search/articles?q=人工智能&threshold=0.7&limit=20&category=科技&mode=hybrid HTTP/1.1
Host: api.weaver.example.com
X-API-Key: your-api-key
```

**查询参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `q` | string | - | 搜索查询文本（必填） |
| `threshold` | float | 0.0 | 最低混合评分阈值（0-1） |
| `limit` | integer | 20 | 最大返回结果数（1-100） |
| `category` | string | - | 按文章类别过滤 |
| `mode` | string | hybrid | 搜索模式：`hybrid`（混合）、`vector`（向量）、`bm25`（词法） |

**混合搜索特性：**

1. **BM25 词法检索**：使用 bm25s 库实现高性能中文分词检索
2. **向量语义检索**：基于 pgvector 的语义相似度搜索
3. **RRF 融合**：Reciprocal Rank Fusion 算法合并多路检索结果
4. **可选重排**：Flashrank cross-encoder 重排提升精度
5. **多样性支持**：MMR 算法增加结果多样性

**响应字段：**

```json
{
  "query": "人工智能",
  "results": [
    {
      "id": "article-uuid",
      "title": "人工智能发展报告",
      "summary": "文章摘要...",
      "score": 0.95,
      "category": "科技",
      "published_at": "2024-01-15T10:00:00Z"
    }
  ],
  "metadata": {
    "search_mode": "hybrid",
    "hybrid_used": true,
    "total_count": 15,
    "category_filter": "科技"
  }
}
```

---

## Pipeline 端点

### POST /api/v1/pipeline/trigger

触发 Pipeline 任务，开始抓取和处理新闻。

#### 请求

```http
POST /api/v1/pipeline/trigger HTTP/1.1
Host: api.weaver.example.com
X-API-Key: your-api-key
Content-Type: application/json

{
  "source_id": null,
  "force": false,
  "max_items": null
}
```

**请求字段：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `source_id` | string | 否 | 指定抓取的源 ID，为 `null` 时抓取所有已启用源 |
| `force` | boolean | 否 | 是否强制重新抓取最近已抓取的 URL |
| `max_items` | integer | 否 | 每个源的最大处理数量，`null` 表示无限制 |

#### 响应

**成功响应 (200 OK)**

```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "queued_at": "2024-01-15T10:30:00Z"
}
```

#### 状态码

| 状态码 | 说明 |
|--------|------|
| 200 OK | 任务已入队 |
| 401 Unauthorized | API Key 无效或缺失 |
| 500 Internal Server Error | Pipeline 触发失败 |

---

### GET /api/v1/pipeline/tasks/{task_id}

查询 Pipeline 任务状态。

#### 请求

```http
GET /api/v1/pipeline/tasks/550e8400-e29b-41d4-a716-446655440000 HTTP/1.1
Host: api.weaver.example.com
X-API-Key: your-api-key
```

#### 响应

**成功响应 (200 OK)**

```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "running",
  "source_id": null,
  "queued_at": "2024-01-15T10:30:00Z",
  "started_at": "2024-01-15T10:30:01Z",
  "completed_at": null,
  "progress": null,
  "total": null,
  "error": null,
  "total_processed": 15,
  "processing_count": 3,
  "completed_count": 10,
  "failed_count": 2,
  "pending_count": 5
}
```

#### 状态码

| 状态码 | 说明 |
|--------|------|
| 200 OK | 成功返回任务状态 |
| 401 Unauthorized | API Key 无效或缺失 |
| 404 Not Found | 任务不存在 |

---

### GET /api/v1/pipeline/queue/stats

获取 Pipeline 队列统计信息。

#### 请求

```http
GET /api/v1/pipeline/queue/stats HTTP/1.1
Host: api.weaver.example.com
X-API-Key: your-api-key
```

#### 响应

**成功响应 (200 OK)**

```json
{
  "queue_depth": 5,
  "status_counts": {
    "running": 2,
    "completed": 10,
    "failed": 3
  },
  "total_tasks": 15,
  "article_stats": {
    "total_articles": 1500,
    "processing_count": 25,
    "completed_count": 1200,
    "failed_count": 50,
    "pending_count": 275
  }
}
```

---

## 图谱端点

### GET /api/v1/graph/entities/{name}

查询指定实体的信息及其关系。

#### 请求

```http
GET /api/v1/graph/entities/雷军?limit=10 HTTP/1.1
Host: api.weaver.example.com
X-API-Key: your-api-key
```

**路径参数：**
- `name`：实体规范名称（URL 编码）

**查询参数：**
- `limit`：最大返回关联实体数（默认10，最大100）

#### 响应

**成功响应 (200 OK)**

```json
{
  "entity": {
    "id": "entity-uuid",
    "canonical_name": "雷军",
    "type": "人物",
    "aliases": ["雷布斯"],
    "description": "小米科技创始人",
    "updated_at": "2024-01-15T10:30:00Z"
  },
  "relationships": [
    {
      "target": "小米",
      "relation_type": "创立",
      "source_article_id": "article-uuid",
      "created_at": "2024-01-15T10:30:00Z"
    }
  ],
  "related_entities": [
    {
      "id": "entity-uuid-2",
      "canonical_name": "小米",
      "type": "组织机构",
      "aliases": null,
      "description": null,
      "updated_at": null
    }
  ],
  "mentioned_in_articles": [
    {
      "id": "article-uuid",
      "title": "雷军演讲全文",
      "category": "科技",
      "publish_time": "2024-01-15T09:00:00+08:00",
      "score": 0.85
    }
  ]
}
```

---

### GET /api/v1/graph/articles/{article_id}/graph

获取文章的知识图谱视图。

#### 请求

```http
GET /api/v1/graph/articles/550e8400-e29b-41d4-a716-446655440000/graph HTTP/1.1
Host: api.weaver.example.com
X-API-Key: your-api-key
```

#### 响应

**成功响应 (200 OK)**

```json
{
  "article": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "title": "小米发布新手机",
    "category": "科技",
    "publish_time": "2024-01-15T09:00:00+08:00",
    "score": 0.85
  },
  "entities": [
    {
      "id": "entity-uuid",
      "canonical_name": "小米",
      "type": "组织机构",
      "aliases": null
    }
  ],
  "relationships": [
    {
      "source_id": "小米",
      "target_id": "高通",
      "relation_type": "合作",
      "properties": {
        "source_article_id": "550e8400-e29b-41d4-a716-446655440000",
        "created_at": "2024-01-15T10:30:00Z"
      }
    }
  ],
  "related_articles": [
    {
      "id": "uuid-xxx",
      "title": "高通发布新芯片",
      "category": "科技",
      "publish_time": "2024-01-14T14:00:00+08:00",
      "score": 0.82
    }
  ]
}
```

---

### GET /api/v1/graph/metrics/health

获取图谱健康度摘要。

#### 请求

```http
GET /api/v1/graph/metrics/health HTTP/1.1
Host: api.weaver.example.com
X-API-Key: your-api-key
```

#### 响应

**成功响应 (200 OK)**

```json
{
  "health_score": 78.5,
  "status": "moderate",
  "entity_count": 15000,
  "relationship_count": 45000,
  "orphan_ratio": 0.12,
  "connectedness": 0.85,
  "average_degree": 6.2,
  "recommendations": [
    "孤立实体比例偏高，建议增加文章覆盖",
    "平均度数偏低，图谱连接性有待提升"
  ]
}
```

---

### GET /api/v1/graph/metrics/full

获取完整的图谱质量指标。

#### 请求

```http
GET /api/v1/graph/metrics/full HTTP/1.1
Host: api.weaver.example.com
X-API-Key: your-api-key
```

#### 响应

**成功响应 (200 OK)**

```json
{
  "total_entities": 15000,
  "total_articles": 8000,
  "total_relationships": 45000,
  "total_mentions": 120000,
  "connected_components": 150,
  "largest_component_size": 12000,
  "average_degree": 6.2,
  "modularity_score": 0.45,
  "orphan_entities": 1800,
  "high_degree_entities": [
    {"canonical_name": "中国", "degree": 500},
    {"canonical_name": "美国", "degree": 450}
  ],
  "entity_type_distribution": {"人物": 5000, "组织机构": 4000, "地点": 3000},
  "relationship_type_distribution": {"合作": 15000, "竞争": 8000, "投资": 5000},
  "computed_at": "2024-01-15T10:30:00Z"
}
```

---

### GET /api/v1/graph/metrics/components

获取图谱连通分量列表。

#### 请求

```http
GET /api/v1/graph/metrics/components?limit=10&min_size=5 HTTP/1.1
Host: api.weaver.example.com
X-API-Key: your-api-key
```

**查询参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `limit` | integer | 10 | 最大返回分量数（1-100） |
| `min_size` | integer | 1 | 最小分量大小 |

---

### GET /api/v1/graph/metrics/orphans

获取孤立实体列表。

#### 请求

```http
GET /api/v1/graph/metrics/orphans?limit=100 HTTP/1.1
Host: api.weaver.example.com
X-API-Key: your-api-key
```

---

### GET /api/v1/graph/metrics/high-degree

获取高度数实体列表。

#### 请求

```http
GET /api/v1/graph/metrics/high-degree?min_degree=10&limit=50 HTTP/1.1
Host: api.weaver.example.com
X-API-Key: your-api-key
```

---

### GET /api/v1/graph/metrics/modularity

获取图谱模块度评分。

#### 请求

```http
GET /api/v1/graph/metrics/modularity?resolution=1.0 HTTP/1.1
Host: api.weaver.example.com
X-API-Key: your-api-key
```

**查询参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `resolution` | float | 1.0 | 模块度计算的分辨率参数（0.1-10.0） |

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