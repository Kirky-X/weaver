# Weaver 部署指南

本文档详细说明 Weaver 应用的部署流程、环境变量配置、数据库迁移和监控集成。

## 目录

- [环境要求](#环境要求)
- [环境变量配置](#环境变量配置)
- [数据库迁移](#数据库迁移)
- [健康检查端点](#健康检查端点)
- [Prometheus 指标端点](#prometheus-指标端点)
- [监控系统集成](#监控系统集成)
- [故障排查](#故障排查)

---

## 环境要求

### 必需服务

- **PostgreSQL** 16+ (with pgvector extension, 使用 pgvector/pgvector:pg16 镜像)
- **Neo4j** 5.x (推荐使用 5.25)
- **Redis** 7.x (推荐使用 7.2)
- **Python** 3.12+

### 可选服务

- **Prometheus** - 用于指标收集和告警
- **Grafana** - 用于可视化监控
- **OpenTelemetry Collector** - 用于分布式追踪

---

## 环境变量配置

### 核心环境变量

#### 应用配置

```bash
# 应用基础配置
export ENVIRONMENT=production  # production | development

# API 配置
export WEAVER_API__API_KEY=<your-secure-api-key>  # 最少 32 字符
export WEAVER_API__HOST=0.0.0.0
export WEAVER_API__PORT=8000
export WEAVER_API__RATE_LIMIT=100/minute

# 端口自动检测配置
export WEAVER_API__PORT_AUTO_DETECT=true  # 启用端口自动检测
```

#### 数据库连接

**推荐方式**: 在 `config/settings.toml` 中配置服务地址,在 `.env` 中配置密码。

```bash
# PostgreSQL 密码 (服务地址在 settings.toml 中配置)
export WEAVER_POSTGRES__PASSWORD=your_secure_postgres_password

# Neo4j 密码 (服务地址在 settings.toml 中配置,生产环境必须设置)
export WEAVER_NEO4J__PASSWORD=your_secure_neo4j_password

# Redis 密码 (可选,留空表示无密码)
export WEAVER_REDIS__PASSWORD=
```

**对应的 settings.toml 配置**:

```toml
# config/settings.toml
[postgres]
host = "localhost"
port = 5432
database = "weaver"
user = "postgres"
pool_size = 20
max_overflow = 10
pool_timeout = 30.0

[neo4j]
uri = "bolt://localhost:7687"
user = "neo4j"
enabled = true

[redis]
host = "localhost"
port = 6379
db = 0
```

#### LLM 配置

**推荐方式**: 在 `config/llm.toml` 中配置 Provider 和模型,在 `.env` 中配置 API Key。

```bash
# LLM Provider API Keys (通过环境变量覆盖 llm.toml 中的配置)
export WEAVER_LLM__PROVIDERS__AIPING__API_KEY=your_aiping_api_key
export WEAVER_LLM__PROVIDERS__DMX__API_KEY=your_dmx_api_key
# Ollama 不需要真实 API Key
# export WEAVER_LLM__PROVIDERS__OLLAMA__API_KEY=ollama

# 也可以使用标准的 API Key 环境变量 (在 llm.toml 中通过 ${VAR_NAME} 引用)
# export OPENAI_API_KEY=your_openai_api_key
# export ANTHROPIC_API_KEY=your_anthropic_api_key
```

**对应的 llm.toml 配置**:

```toml
# config/llm.toml
[global]
circuit_breaker_threshold = 5
circuit_breaker_timeout = 60.0
default_timeout = 120.0

[providers.openai]
type = "openai"
base_url = "https://api.openai.com/v1"
api_key = "${OPENAI_API_KEY}"  # 会使用环境变量 OPENAI_API_KEY
rpm_limit = 500
concurrency = 10
timeout = 120.0
priority = 100
weight = 100

  [providers.openai.models.chat]
  model_id = "gpt-4o"
  temperature = 0.0
  max_tokens = 4096
  capabilities = ["chat", "vision"]

  [providers.openai.models.embedding]
  model_id = "text-embedding-3-large"
  capabilities = ["embedding"]

[providers.anthropic]
type = "anthropic"
base_url = ""
api_key = "${ANTHROPIC_API_KEY}"
rpm_limit = 60
concurrency = 5
timeout = 300.0
priority = 100
weight = 100

  [providers.anthropic.models.chat]
  model_id = "claude-sonnet-4-20250514"
  temperature = 0.0
  max_tokens = 4096
  capabilities = ["chat", "vision"]

# 调用点路由配置
[call-points.classifier]
primary = "chat.openai.gpt-4o"
fallbacks = ["chat.anthropic.claude-sonnet-4-20250514"]

[call-points.entity_extractor]
primary = "chat.openai.gpt-4o"
fallbacks = ["chat.anthropic.claude-sonnet-4-20250514"]

[call-points.embedding]
primary = "embedding.openai.text-embedding-3-large"
fallbacks = ["embedding.ollama.nomic-embed-text"]
```

**Smart Router 配置 (可选)**:

```toml
# Smart Router 评分权重配置
[routing.classifier]
mode = "auto"  # auto | fast | best

  [routing.classifier.weights]
  editorial = 0.35      # 预设优先级
  reliability = 0.25    # 历史成功率
  cost = 0.15           # 预估成本
  latency = 0.10        # 历史延迟

  [routing.classifier.bandit]
  enabled = true
  exploration_weight = 0.15
  warmup_calls = 3
```

**影子评估配置 (可选)**:

```toml
[eval]
enabled = false
sample_rate = 0.1
target_call_points = ["classifier", "entity_extractor"]
baseline_model = "chat.openai.gpt-4o"
candidate_models = ["chat.anthropic.claude-sonnet-4-20250514"]
```

#### 可观测性配置

```bash
# OpenTelemetry 追踪 (在 settings.toml 中配置)
# config/settings.toml:
# [observability]
# otlp_endpoint = "http://localhost:4317"

# 或通过环境变量覆盖
export WEAVER_OBSERVABILITY__OTLP_ENDPOINT=http://otel-collector:4317
```

#### HNSW 索引参数调优

```bash
# HNSW 索引参数 (在 01_initial 迁移时生效)
export HNSW_M=16                      # 每个节点的最大连接数 (默认: 16)
export HNSW_EF_CONSTRUCTION=64        # 构建时的候选列表大小 (默认: 64)
```

**参数调优建议:**

| 数据规模 | HNSW_M | HNSW_EF_CONSTRUCTION | 说明 |
|---------|--------|---------------------|------|
| < 1M 向量 | 16 | 64 | 默认配置，平衡性能和内存 |
| 1M - 5M 向量 | 24 | 96 | 中等规模，提高召回率 |
| > 5M 向量 | 32 | 128 | 大规模数据，最佳召回率 |

> 注意：更大的参数值会提高查询召回率，但也会增加索引构建时间和内存占用。

---

## 数据库迁移

### Alembic 迁移工具

Weaver 使用 Alembic 进行数据库版本管理。迁移脚本位于 `src/alembic/versions/` 目录。

#### 查看当前迁移状态

```bash
# 进入项目目录
cd /path/to/weaver

# 查看当前版本
uv run alembic current

# 查看迁移历史
uv run alembic history
```

#### 执行数据库迁移

```bash
# 执行所有待执行的迁移
uv run alembic upgrade head

# 执行到指定版本
uv run alembic upgrade <revision_id>
```

#### 回滚迁移

```bash
# 回滚一个版本
uv run alembic downgrade -1

# 回滚到指定版本
uv run alembic downgrade <revision_id>

# 回滚所有迁移
uv run alembic downgrade base
```

### HNSW 索引迁移

**重要迁移: `01_initial`**

此迁移为 `article_vectors` 和 `entity_vectors` 表添加 HNSW 索引，显著提升向量相似性搜索性能。

#### 执行前准备

1. **评估数据规模**

   如果是全新数据库，无需准备。如果是迁移现有数据：

   ```sql
   SELECT COUNT(*) FROM article_vectors;
   SELECT COUNT(*) FROM entity_vectors;
   ```

2. **检查磁盘空间**

   HNSW 索引大小约为数据大小的 1.5-2 倍。

   ```bash
   # PostgreSQL 数据目录
   df -h /var/lib/postgresql/data
   ```

3. **预估迁移时间**

   | 向量数量 | 预计时间 (HNSW_M=16) | 预计时间 (HNSW_M=32) |
   |---------|---------------------|---------------------|
   | 100K | ~2 分钟 | ~4 分钟 |
   | 1M | ~20 分钟 | ~40 分钟 |
   | 5M | ~2 小时 | ~4 小时 |

#### 执行迁移

```bash
# 使用默认参数
uv run alembic upgrade 01_initial

# 或自定义参数 (推荐生产环境)
export HNSW_M=32
export HNSW_EF_CONSTRUCTION=128
uv run alembic upgrade 01_initial
```

#### 验证索引创建

```sql
-- 检查索引是否存在
SELECT indexname, indexdef
FROM pg_indexes
WHERE indexname LIKE '%hnsw%';

-- 查看索引大小
SELECT
    schemaname,
    tablename,
    indexname,
    pg_size_pretty(pg_relation_size(indexrelid)) AS index_size
FROM pg_stat_user_indexes
WHERE indexrelname LIKE '%hnsw%';

-- 验证索引使用情况
EXPLAIN ANALYZE
SELECT embedding <=> '[0.1, 0.2, ...]'::vector AS distance
FROM article_vectors
ORDER BY distance
LIMIT 10;
```

预期输出应包含 `Index Scan using idx_article_vectors_hnsw`。

#### 迁移窗口建议

对于生产环境：

- **小型数据集 (< 100K)**: 任何时间窗口
- **中型数据集 (100K - 1M)**: 低峰期执行，建议维护窗口 1 小时
- **大型数据集 (> 1M)**: 专门维护窗口，提前通知用户

> 注意：迁移使用 `CONCURRENTLY` 选项，不会阻塞读写操作，但会增加系统负载。

---

## 健康检查端点

### `/health` 端点

Weaver 提供完整的健康检查端点，用于监控服务依赖状态。

#### 请求示例

```bash
curl http://localhost:8000/health
```

#### 成功响应 (HTTP 200)

响应被包装在 `APIResponse` 格式中：

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "status": "healthy",
    "checks": {
      "postgres": {
        "status": "ok",
        "latency_ms": 2.34,
        "error": null
      },
      "neo4j": {
        "status": "ok",
        "latency_ms": 5.67,
        "error": null
      },
      "redis": {
        "status": "ok",
        "latency_ms": 1.23,
        "error": null
      }
    }
  }
}
```

#### 失败响应 (HTTP 200, 但 status 为 "unhealthy")

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "status": "unhealthy",
    "checks": {
      "postgres": {
        "status": "error",
        "latency_ms": 5003.45,
        "error": "Connection refused"
      },
      "neo4j": {
        "status": "timeout",
        "latency_ms": 5001.23,
        "error": null
      },
      "redis": {
        "status": "ok",
        "latency_ms": 1.23,
        "error": null
      }
    }
  }
}
```

#### 状态值说明

| 状态值 | 含义 | 建议操作 |
|-------|------|---------|
| `ok` | 依赖服务正常 | 无需操作 |
| `error` | 连接或查询错误 | 检查服务状态和网络连接 |
| `timeout` | 5 秒超时 | 检查服务性能和网络延迟 |
| `unavailable` | 连接池未初始化 | 检查应用启动日志 |

#### 超时配置

每个健康检查的超时时间为 **5 秒**。如果某个依赖服务响应时间超过 5 秒，将返回 `timeout` 状态。

#### 负载均衡器配置

**Nginx 配置示例:**

```nginx
upstream weaver_backend {
    server 127.0.0.1:8000 max_fails=3 fail_timeout=30s;
    server 127.0.0.1:8001 max_fails=3 fail_timeout=30s;
}

server {
    location /health {
        proxy_pass http://weaver_backend/health;
        proxy_connect_timeout 5s;
        proxy_read_timeout 10s;
        access_log off;  # 不记录健康检查日志
    }
}
```

**Kubernetes 配置示例:**

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 30
  periodSeconds: 10
  timeoutSeconds: 10
  failureThreshold: 3

readinessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 5
  timeoutSeconds: 5
  failureThreshold: 3
```

**Docker 配置示例:**

```yaml
healthcheck:
  test: ["CMD", "python", "-c", "import httpx, os; port=os.getenv('WEAVER_API__PORT', '8000'); r=httpx.get(f'http://localhost:{port}/health'); exit(0 if r.status_code == 200 else 1)"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 40s
```

---

## Prometheus 指标端点

### `/metrics` 端点

Weaver 暴露 Prometheus 标准格式的指标端点。

#### 请求示例

```bash
curl http://localhost:8000/metrics
```

#### 响应格式

```
# HELP api_request_latency_seconds API 请求延迟
# TYPE api_request_latency_seconds histogram
api_request_latency_seconds_bucket{endpoint="/health",method="GET",status="200",le="0.01"} 45
api_request_latency_seconds_bucket{endpoint="/health",method="GET",status="200",le="0.05"} 89

# HELP api_request_total API 请求总数
# TYPE api_request_total counter
api_request_total{endpoint="/health",method="GET",status="200"} 1523

# HELP llm_call_total LLM 调用次数
# TYPE llm_call_total counter
llm_call_total{call_point="classifier",provider="openai",status="success"} 856
llm_call_total{call_point="classifier",provider="openai",status="error"} 12

# HELP llm_call_latency_seconds LLM 调用延迟
# TYPE llm_call_latency_seconds histogram
llm_call_latency_seconds_bucket{call_point="classifier",provider="openai",le="0.1"} 234
llm_call_latency_seconds_bucket{call_point="classifier",provider="openai",le="0.5"} 567

# HELP health_check_status 健康检查状态 (1=ok, 0=error, -1=timeout, -2=unavailable)
# TYPE health_check_status gauge
health_check_status{service="postgres"} 1
health_check_status{service="neo4j"} 1
health_check_status{service="redis"} 1

# HELP health_check_latency_seconds 健康检查延迟
# TYPE health_check_latency_seconds histogram
health_check_latency_seconds_bucket{service="postgres",le="0.001"} 123
health_check_latency_seconds_bucket{service="postgres",le="0.005"} 456

# HELP circuit_breaker_state 熔断器状态 (0=closed, 1=open, 2=half_open)
# TYPE circuit_breaker_state gauge
circuit_breaker_state{provider="openai"} 0
circuit_breaker_state{provider="ollama"} 0

# HELP db_pool_size 数据库连接池大小
# TYPE db_pool_size gauge
db_pool_size{pool="postgres"} 20
db_pool_size{pool="neo4j"} 10
```

#### Content-Type

```
Content-Type: text/plain; version=0.0.4; charset=utf-8
```

#### Prometheus 配置

**prometheus.yml 配置示例:**

```yaml
scrape_configs:
  - job_name: 'weaver'
    static_configs:
      - targets: ['weaver-host:8000']
    metrics_path: '/metrics'
    scrape_interval: 15s
    scrape_timeout: 10s
```

---

## 监控系统集成

### Prometheus 集成

#### 1. 安装 Prometheus

```bash
# Docker 方式
docker run -d \
  --name prometheus \
  -p 9090:9090 \
  -v /path/to/prometheus.yml:/etc/prometheus/prometheus.yml \
  prom/prometheus

# Kubernetes
kubectl apply -f monitoring/prometheus/
```

#### 2. 配置告警规则

告警规则已预配置在 `monitoring/prometheus/alerts.yml`，包含：

- Circuit Breaker 熔断告警 (3 条)
- LLM 服务质量告警 (3 条)
- API 性能告警 (2 条)
- 数据库连接池告警 (2 条)
- 健康检查告警 (3 条)
- 数据一致性告警 (5 条)

**启用告警规则:**

```yaml
# prometheus.yml
rule_files:
  - "alerts.yml"

alerting:
  alertmanagers:
    - static_configs:
        - targets:
          - alertmanager:9093
```

#### 3. 配置 Alertmanager

```yaml
# alertmanager.yml
global:
  smtp_smarthost: 'smtp.example.com:587'
  smtp_from: 'alerts@example.com'

route:
  receiver: 'team-email'
  group_wait: 10s
  group_interval: 10m
  repeat_interval: 1h

receivers:
  - name: 'team-email'
    email_configs:
      - to: 'team@example.com'
        send_resolved: true
```

### Grafana 集成

#### 1. 安装 Grafana

```bash
# Docker 方式
docker run -d \
  --name grafana \
  -p 3000:3000 \
  -v grafana-storage:/var/lib/grafana \
  grafana/grafana
```

#### 2. 添加 Prometheus 数据源

在 Grafana UI 中：

1. 导航到 **Configuration** → **Data Sources**
2. 点击 **Add data source**
3. 选择 **Prometheus**
4. 设置 URL: `http://prometheus:9090`
5. 点击 **Save & Test**

#### 3. 导入预配置仪表盘

预配置仪表盘位于 `monitoring/grafana/dashboards/`:

- `system-health-overview.json` - 系统健康概览
- `circuit-breaker-status.json` - Circuit Breaker 状态
- `database-consistency.json` - 数据库一致性状态

**导入方式:**

```bash
# 通过 API 导入
curl -X POST http://admin:admin@grafana:3000/api/dashboards/db \
  -H "Content-Type: application/json" \
  -d @monitoring/grafana/dashboards/system-health-overview.json

# 或在 Grafana UI 中手动导入
# Dashboards → Import → Upload JSON file
```

### OpenTelemetry 追踪集成

#### 1. 配置 OTLP Endpoint

```bash
export WEAVER_OBSERVABILITY__OTLP_ENDPOINT=http://otel-collector:4317
```

#### 2. 部署 OpenTelemetry Collector

**collector-config.yaml:**

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317

exporters:
  jaeger:
    endpoint: jaeger:14250
    tls:
      insecure: true

service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [jaeger]
```

**启动 Collector:**

```bash
docker run -d \
  --name otel-collector \
  -p 4317:4317 \
  -v /path/to/collector-config.yaml:/etc/otelcol/config.yaml \
  otel/opentelemetry-collector:latest
```

#### 3. 查看追踪数据

在 Jaeger UI 中查看分布式追踪：

```
http://jaeger:16686
```

---

## 故障排查

### 常见问题

#### 1. 健康检查失败

**症状:** `/health` 返回的 `data.status` 为 `unhealthy`

> **注意**: `/health` 端点始终返回 HTTP 200 状态码。需要检查响应体中的 `data.status` 字段来判断服务健康状况。

#### 诊断步骤:

```bash
# 检查具体失败的依赖
curl -s http://localhost:8000/health | jq '.data.checks'

# 检查 PostgreSQL 连接
psql -h localhost -U postgres -d weaver -c "SELECT 1"

# 检查 Neo4j 连接
cypher-shell -a bolt://localhost:7687 -u neo4j -p your_password "RETURN 1"

# 检查 Redis 连接
redis-cli -h localhost -p 6379 ping
```

**解决方案:**

- 检查服务是否启动
- 验证网络连接和防火墙规则
- 检查认证凭证
- 查看应用日志

#### 2. 迁移执行失败

**症状:** `alembic upgrade head` 失败

**诊断步骤:**

```bash
# 查看当前迁移状态
uv run alembic current

# 检查数据库连接
uv run alembic show current

# 查看详细错误日志
uv run alembic upgrade head --sql
```

**常见错误:**

- **权限不足:** 确保 PostgreSQL 用户有 CREATE INDEX 权限
- **磁盘空间不足:** 检查并清理磁盘空间
- **锁等待超时:** 检查是否有长时间运行的事务

**回滚迁移:**

```bash
uv run alembic downgrade -1
```

#### 3. HNSW 索引查询慢

**症状:** 向量相似性搜索慢于预期

**诊断步骤:**

```sql
-- 检查索引是否被使用
EXPLAIN ANALYZE
SELECT embedding <=> '[...]'::vector AS distance
FROM article_vectors
ORDER BY distance
LIMIT 10;

-- 检查索引大小
SELECT pg_size_pretty(pg_relation_size('idx_article_vectors_hnsw'));

-- 检查表统计信息
ANALYZE article_vectors;
```

**优化建议:**

- 增加 `HNSW_EF_CONSTRUCTION` 参数重新创建索引
- 查询时设置更高的 `ef_search` 参数:
  ```sql
  SET hnsw.ef_search = 100;
  ```
- 考虑分区表

#### 4. Prometheus 指标未收集

**症状:** Grafana 无数据

**诊断步骤:**

```bash
# 测试 /metrics 端点
curl http://localhost:8000/metrics

# 检查 Prometheus 配置
curl http://prometheus:9090/api/v1/targets

# 检查 Prometheus 日志
docker logs prometheus
```

**解决方案:**

- 验证 Prometheus scrape 配置
- 检查网络连通性
- 验证防火墙规则

#### 5. OpenTelemetry 追踪未显示

**症状:** Jaeger 中无追踪数据

**诊断步骤:**

```bash
# 检查环境变量
echo $WEAVER_OBSERVABILITY__OTLP_ENDPOINT

# 测试 Collector 连接
grpcurl otel-collector:4317 list

# 检查 Collector 日志
docker logs otel-collector
```

**解决方案:**

- 验证 OTLP Endpoint 配置
- 检查 Collector 运行状态
- 验证 Jaeger 和 Collector 集成

### 日志查看

```bash
# Docker 方式
docker logs weaver-app

# Kubernetes 方式
kubectl logs -f deployment/weaver

# 系统服务方式
journalctl -u weaver -f
```

### 性能监控

```bash
# 实时监控资源使用
docker stats weaver-app

# 监控数据库连接数
psql -c "SELECT count(*) FROM pg_stat_activity WHERE datname='weaver';"

# 监控 Redis 内存
redis-cli info memory
```

---

## 安全建议

### 生产环境检查清单

- [ ] 所有默认密码已修改
- [ ] API Key 长度 >= 32 字符 (通过 `WEAVER_API__API_KEY` 设置)
- [ ] Neo4j 密码已设置 (通过 `WEAVER_NEO4J__PASSWORD` 设置，生产环境必须)
- [ ] PostgreSQL 密码已设置 (通过 `WEAVER_POSTGRES__PASSWORD` 设置)
- [ ] 数据库连接使用 SSL/TLS
- [ ] Neo4j 认证已启用
- [ ] Redis 设置密码 (可选)
- [ ] 防火墙规则已配置
- [ ] 定期备份数据库
- [ ] 监控和告警已配置
- [ ] 日志级别设置为 INFO 或 WARNING
- [ ] URL 安全检查已启用 (`url_security.enabled = true`)

### 敏感信息保护

```bash
# 使用环境变量文件
export $(cat .env | xargs)

# 或使用密钥管理服务
# - AWS Secrets Manager
# - HashiCorp Vault
# - Kubernetes Secrets
```

---

## 联系与支持

如遇到问题，请参考：

- [监控文档](../monitoring/README.md)
- [开发文档](../development/README.md) (如果存在)
- [API 文档](../api/README.md) (如果存在)
- [项目 README](../README.md)
- 项目 Issues: https://github.com/your-org/weaver/issues