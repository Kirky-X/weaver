# Weaver 监控指南

本文档详细说明 Weaver 应用的监控系统配置、使用方法和故障排查。

## 目录

- [监控系统概览](#监控系统概览)
- [健康检查端点](#健康检查端点)
- [Prometheus 指标](#prometheus-指标)
- [OpenTelemetry 追踪](#opentelemetry-追踪)
- [Grafana 仪表盘](#grafana-仪表盘)
- [告警规则配置](#告警规则配置)
- [故障排查指南](#故障排查指南)

---

## 监控系统概览

Weaver 采用三层监控架构：

```mermaid
flowchart TB
    subgraph Monitoring["监控系统架构"]
        subgraph Collection["数据采集层"]
            HC["健康检查<br/>/health"]
            PM["Prometheus<br/>/metrics"]
            OT["OpenTelemetry<br/>Tracing"]
        end

        subgraph Processing["处理层"]
            PS["Prometheus<br/>Server"]
            OC["OTLP<br/>Collector"]
        end

        subgraph Visualization["可视化层"]
            GF["Grafana<br/>Dashboard"]
            JG["Jaeger<br/>UI"]
        end
    end

    HC -->|健康状态| PS
    PM -->|指标数据| PS
    OT -->|追踪数据| OC
    PS -->|告警/指标| GF
    OC -->|追踪数据| JG
    HC -.->|可选| GF
```

### 监控组件

| 组件 | 用途 | 端点 | 文档位置 |
|------|------|------|---------|
| 健康检查 | 服务存活和依赖检查 | `/health` | 本文档 |
| Prometheus | 指标收集和告警 | `/metrics` | 本文档 |
| OpenTelemetry | 分布式追踪 | OTLP (4317) | 本文档 |
| Grafana | 可视化仪表盘 | 3000 | 本文档 |
| 告警规则 | 自动告警 | - | `monitoring/prometheus/alerts.yml` |

---

## 健康检查端点

### `/health` 端点使用

健康检查端点用于监控服务及其依赖（PostgreSQL, Neo4j, Redis）的状态。

#### 基本用法

```bash
# 简单健康检查
curl http://localhost:8000/health

# 检查状态码
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health

# 格式化输出
curl -s http://localhost:8000/health | jq '.'
```

#### 响应示例

**健康状态 (HTTP 200):**

```json
{
  "status": "healthy",
  "checks": {
    "postgres": {
      "status": "ok",
      "latency_ms": 2.34
    },
    "neo4j": {
      "status": "ok",
      "latency_ms": 5.67
    },
    "redis": {
      "status": "ok",
      "latency_ms": 1.23
    }
  }
}
```

**不健康状态 (HTTP 503):**

```json
{
  "detail": {
    "status": "unhealthy",
    "checks": {
      "postgres": {
        "status": "error",
        "latency_ms": 5003.45,
        "error": "Connection refused"
      },
      "neo4j": {
        "status": "timeout",
        "latency_ms": 5001.23
      },
      "redis": {
        "status": "ok",
        "latency_ms": 1.23
      }
    }
  }
}
```

#### 状态值含义

| 状态值 | 说明 | 常见原因 |
|--------|------|---------|
| `ok` | 依赖服务正常响应 | - |
| `error` | 连接或查询错误 | 服务未启动、认证失败、网络不通 |
| `timeout` | 响应超过 5 秒 | 服务负载高、网络延迟大 |
| `unavailable` | 连接池未初始化 | 应用未完全启动、配置错误 |

#### 使用场景

**1. 负载均衡器健康检查**

配置负载均衡器定期检查 `/health`，移除不健康实例。

**Nginx 示例:**

```nginx
upstream weaver {
    server 10.0.1.10:8000 max_fails=3 fail_timeout=30s;
    server 10.0.1.11:8000 max_fails=3 fail_timeout=30s;
}

server {
    location /health {
        proxy_pass http://weaver/health;
        proxy_connect_timeout 5s;
        proxy_read_timeout 10s;
        access_log off;
    }
}
```

**2. Kubernetes 健康检查**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: weaver
spec:
  template:
    spec:
      containers:
      - name: weaver
        image: weaver:latest
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

**3. 监控脚本**

```bash
#!/bin/bash
# health_monitor.sh

URL="http://localhost:8000/health"
ALERT_WEBHOOK="https://hooks.slack.com/services/YOUR/WEBHOOK"

response=$(curl -s -w "\n%{http_code}" $URL)
http_code=$(echo "$response" | tail -n1)
body=$(echo "$response" | sed '$d')

if [ "$http_code" != "200" ]; then
    echo "Health check failed: HTTP $http_code"
    echo "$body" | jq '.'

    # 发送告警
    curl -X POST $ALERT_WEBHOOK \
        -H 'Content-Type: application/json' \
        -d "{\"text\": \"Weaver health check failed: HTTP $http_code\"}"
    exit 1
fi

echo "Health check passed"
echo "$body" | jq '.checks'
```

#### 监控最佳实践

1. **检查频率**: 每 10-30 秒一次
2. **超时设置**: 10-15 秒（应用超时 5 秒 + 网络缓冲）
3. **失败阈值**: 连续 3 次失败后触发告警
4. **日志记录**: 避免记录健康检查日志，或使用独立 access log

---

## Prometheus 指标

### `/metrics` 端点使用

Prometheus 端点暴露应用运行指标，用于性能监控和告警。

#### 访问指标

```bash
# 查看所有指标
curl http://localhost:8000/metrics

# 过滤特定指标
curl http://localhost:8000/metrics | grep circuit_breaker

# 统计指标数量
curl -s http://localhost:8000/metrics | grep -v "^#" | wc -l
```

#### 主要指标类型

**1. Circuit Breaker 指标**

```promql
# Circuit Breaker 状态 (0=closed, 1=open, 2=half_open)
circuit_breaker_state{provider="openai"}

# Circuit Breaker 失败次数
circuit_breaker_failures_total{provider="openai"}
```

**2. LLM 调用指标**

```promql
# LLM 调用总数（需指定 call_point，如 classifier/cleaner/analyzer/search_local/search_global 等）
llm_call_total{call_point="classifier",provider="openai",status="success"}
llm_call_total{call_point="search_local",provider="ollama",status="success"}
llm_call_total{call_point="search_global",provider="ollama",status="success"}

# LLM 调用延迟直方图（需指定 call_point）
llm_call_latency_seconds_bucket{call_point="classifier",provider="openai",le="1"}
llm_call_latency_seconds_bucket{call_point="search_local",provider="ollama",le="1"}
llm_call_latency_seconds_bucket{call_point="search_global",provider="ollama",le="1"}

# Fallback 触发次数
llm_fallback_total{call_point="classifier",from_provider="ollama",reason="timeout"}
llm_fallback_total{call_point="search_local",from_provider="ollama",reason="timeout"}
```

**3. API 性能指标**

```promql
# API 请求总数
api_request_total{endpoint="/health",status="200"}

# API 请求延迟直方图
api_request_latency_seconds_bucket{endpoint="/health",le="0.1"}
```

**4. 数据库连接池指标**

```promql
# 连接池利用率
db_pool_utilization{pool="postgres"}
```

**5. 数据一致性指标**

```promql
# Pipeline 队列深度（积压量反映处理能力）
pipeline_queue_depth

# 已处理文章总数
weaver_articles_processed_total

# 被去重的文章总数
weaver_articles_deduped_total
```

#### PromQL 查询示例

**查询 LLM 错误率:**

```promql
(sum(rate(llm_call_total{call_point="classifier",status="error"}[5m])) by (provider) / sum(rate(llm_call_total{call_point="classifier"}[5m])) by (provider)) * 100
```

**查询 P99 延迟:**

```promql
histogram_quantile(0.99,
  sum(rate(llm_call_latency_seconds_bucket[5m])) by (le, call_point, provider)
)
```

**查询 Circuit Breaker 打开时间:**

```promql
time() - timestamp(circuit_breaker_state{provider="openai"} == 1)
```

### Prometheus 服务器配置

#### 基本配置

**prometheus.yml:**

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'weaver'
    static_configs:
      - targets: ['weaver-host:8000']
    metrics_path: '/metrics'
    scrape_interval: 15s
    scrape_timeout: 10s

rule_files:
  - "alerts.yml"

alerting:
  alertmanagers:
    - static_configs:
        - targets:
          - alertmanager:9093
```

#### 验证配置

```bash
# 检查配置语法
promtool check config prometheus.yml

# 测试 Prometheus 连接
curl http://prometheus:9090/api/v1/targets

# 测试查询
curl 'http://prometheus:9090/api/v1/query?query=up{job="weaver"}'
```

---

## OpenTelemetry 追踪

### 追踪配置

#### 环境变量配置

```bash
# OTLP Collector 端点
export OBS_OTLP_ENDPOINT=http://otel-collector:4317

# 或使用完整变量名
export WEAVER_OBSERVABILITY__OTLP_ENDPOINT=http://otel-collector:4317
```

#### 应用集成

Weaver 在应用启动时自动初始化 OpenTelemetry 追踪：

```python
# src/main.py
from core.observability.tracing import configure_tracing

configure_tracing(
    service_name="weaver",
    endpoint=container.settings.observability.otlp_endpoint
)
```

### OpenTelemetry Collector 部署

#### Collector 配置

**otel-collector-config.yaml:**

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:
    timeout: 1s
    send_batch_size: 1024

exporters:
  jaeger:
    endpoint: jaeger:14250
    tls:
      insecure: true

  logging:
    loglevel: debug

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [jaeger, logging]
```

#### 启动 Collector

**Docker Compose:**

```yaml
version: '3.8'

services:
  otel-collector:
    image: otel/opentelemetry-collector:latest
    command: ["--config=/etc/otelcol/config.yaml"]
    volumes:
      - ./otel-collector-config.yaml:/etc/otelcol/config.yaml
    ports:
      - "4317:4317"   # OTLP gRPC
      - "4318:4318"   # OTLP HTTP
    depends_on:
      - jaeger

  jaeger:
    image: jaegertracing/all-in-one:latest
    ports:
      - "16686:16686"  # Jaeger UI
      - "14250:14250"  # gRPC
```

**启动命令:**

```bash
docker-compose up -d
```

### Jaeger UI 使用

#### 访问 Jaeger

```
http://localhost:16686
```

#### 查询追踪

1. **选择服务**: 在 "Service" 下拉菜单选择 "weaver"
2. **设置时间范围**: 选择最近 1 小时或自定义时间
3. **查找追踪**: 点击 "Find Traces"
4. **查看详情**: 点击具体追踪查看详细信息

#### 追踪信息解读

每个追踪 (Trace) 包含多个 Span，展示请求处理流程：

```
Trace: /api/v1/articles/123
├─ Span: process_request (200ms)
│  ├─ Span: fetch_article (50ms)
│  │  └─ Span: postgres_query (45ms)
│  ├─ Span: extract_entities (100ms)
│  │  └─ Span: llm_call (95ms)
│  └─ Span: update_neo4j (40ms)
```

#### 性能分析

**识别慢请求:**

1. 在 Jaeger UI 中按 Duration 排序
2. 找到耗时最长的追踪
3. 分析 Span 层级，定位瓶颈

**常见性能问题:**

- **LLM 调用慢**: 检查 LLM provider 性能
- **数据库查询慢**: 检查索引和查询计划
- **网络延迟高**: 检查网络连接和带宽

### 追踪上下文传播

Weaver 自动在请求链路中传播追踪上下文：

```
Client Request → API Gateway → Weaver → LLM Provider
  (Trace ID)      (Same ID)    (Same ID)  (Same ID)
```

这允许在整个请求链路中追踪单个请求。

---

## Grafana 仪表盘

### 预配置仪表盘

Weaver 提供 3 个预配置 Grafana 仪表盘：

#### 1. 系统健康概览 (`system-health-overview.json`)

**监控内容:**
- 服务健康状态
- 依赖健康检查延迟
- 请求成功率
- API 响应时间分布

**关键面板:**
- 健康检查状态总览
- 各依赖延迟趋势
- 错误率统计
- 请求吞吐量

#### 2. Circuit Breaker 状态 (`circuit-breaker-status.json`)

**监控内容:**
- Circuit Breaker 状态变化
- 熔断触发频率
- LLM Provider 性能对比
- Fallback 触发统计

**关键面板:**
- Circuit Breaker 状态面板
- Provider 健康状态
- 失败原因分析
- 恢复时间统计

#### 3. 数据库一致性 (`database-consistency.json`)

**监控内容:**
- PostgreSQL 与 Neo4j 数据一致性
- 持久化状态分布
- Pipeline 处理延迟
- 队列深度趋势

**关键面板:**
- 数据一致性对比
- 持久化状态饼图
- 同步延迟趋势
- 失败文章列表

### 导入仪表盘

#### 方式 1: 通过 Grafana UI

1. 登录 Grafana (http://localhost:3000)
2. 导航到 **Dashboards** → **Import**
3. 点击 **Upload JSON file**
4. 选择 `monitoring/grafana/dashboards/*.json` 文件
5. 选择 Prometheus 数据源
6. 点击 **Import**

#### 方式 2: 通过 API

```bash
# 导入系统健康概览仪表盘
curl -X POST http://admin:admin@grafana:3000/api/dashboards/db \
  -H "Content-Type: application/json" \
  -d @monitoring/grafana/dashboards/system-health-overview.json

# 导入 Circuit Breaker 状态仪表盘
curl -X POST http://admin:admin@grafana:3000/api/dashboards/db \
  -H "Content-Type: application/json" \
  -d @monitoring/grafana/dashboards/circuit-breaker-status.json

# 导入数据库一致性仪表盘
curl -X POST http://admin:admin@grafana:3000/api/dashboards/db \
  -H "Content-Type: application/json" \
  -d @monitoring/grafana/dashboards/database-consistency.json
```

#### 方式 3: 自动导入 (Docker Compose)

```yaml
version: '3.8'

services:
  grafana:
    image: grafana/grafana:latest
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    volumes:
      - ./monitoring/grafana/dashboards:/etc/grafana/provisioning/dashboards
      - ./monitoring/grafana/datasources:/etc/grafana/provisioning/datasources
    ports:
      - "3000:3000"
```

### 自定义仪表盘

#### 创建自定义仪表盘

1. 在 Grafana 中点击 **+** → **Dashboard**
2. 添加新面板
3. 选择 Prometheus 数据源
4. 输入 PromQL 查询
5. 配置可视化类型
6. 保存仪表盘

#### 推荐面板

**LLM 性能面板:**

```promql
# 查询: LLM 调用成功率
(sum(rate(llm_call_total{call_point="classifier",status="success"}[5m])) by (provider) / sum(rate(llm_call_total{call_point="classifier"}[5m])) by (provider)) * 100

# 查询: LLM P95 延迟
histogram_quantile(0.95,
  sum(rate(llm_call_latency_seconds_bucket[5m])) by (le, call_point, provider)
)

# 查询: 每分钟请求数
sum(rate(llm_call_total[1m])) by (provider)
```

**API 性能面板:**

```promql
# 查询: API 错误率
(sum(rate(api_request_total{status=~"5.."}[5m])) by (endpoint) / sum(rate(api_request_total[5m])) by (endpoint)) * 100

# 查询: API P99 延迟
histogram_quantile(0.99,
  sum(rate(api_request_latency_seconds_bucket[5m])) by (le, endpoint)
)
```

---

## 告警规则配置

### 告警规则概览

预配置的告警规则位于 `monitoring/prometheus/alerts.yml`，包含 6 大类 18 条规则：

#### 1. Circuit Breaker 告警 (3 条)

| 告警名称 | 严重级别 | 触发条件 | 持续时间 |
|---------|---------|---------|---------|
| CircuitBreakerOpen | critical | 熔断器打开 | 1 分钟 |
| CircuitBreakerHalfOpen | warning | 熔断器半开 | 5 分钟 |
| HighCircuitBreakerFailureRate | warning | 5 分钟内 >5 次失败 | 2 分钟 |

#### 2. LLM 服务质量告警 (3 条)

| 告警名称 | 严重级别 | 触发条件 | 持续时间 |
|---------|---------|---------|---------|
| LLMHighErrorRate | critical | 错误率 > 10% | 5 分钟 |
| LLMHighLatency | warning | P99 延迟 > 10s | 5 分钟 |
| FrequentFallbackTriggered | warning | 1 小时内 >10 次 | 5 分钟 |

#### 3. API 性能告警 (2 条)

| 告警名称 | 严重级别 | 触发条件 | 持续时间 |
|---------|---------|---------|---------|
| APIHighLatency | warning | P99 延迟 > 1s | 5 分钟 |
| APIHighErrorRate | critical | 5xx 错误率 > 5% | 5 分钟 |

#### 4. 数据库连接池告警 (2 条)

| 告警名称 | 严重级别 | 触发条件 | 持续时间 |
|---------|---------|---------|---------|
| DatabasePoolSaturation | warning | 连接池利用率 > 90% | 5 分钟 |
| DatabasePoolExhausted | critical | 连接池利用率 > 95% | 2 分钟 |

#### 5. 健康检查告警 (3 条)

| 告警名称 | 严重级别 | 触发条件 | 持续时间 |
|---------|---------|---------|---------|
| ServiceHealthCheckFailed | critical | 健康检查失败 | 2 分钟 |
| HealthCheckHighLatency | warning | 延迟 > 1000ms | 5 分钟 |
| MultipleServicesUnhealthy | critical | >= 2 个服务失败 | 1 分钟 |

#### 6. 数据一致性告警 (5 条)

| 告警名称 | 严重级别 | 触发条件 | 持续时间 |
|---------|---------|---------|---------|
| DataInconsistencyDetected | warning | 数据差异 > 50 条 | 10 分钟 |
| SevereDataInconsistency | critical | 数据差异 > 100 条 | 15 分钟 |
| HighTransactionErrorRate | warning | 5 分钟内 >10 次错误 | 5 分钟 |
| PipelineQueueBacklog | warning | 队列深度 > 1000 | 10 分钟 |
| HighPersistenceFailureRate | warning | 失败率 > 5% | 10 分钟 |

### 配置告警规则

#### 1. 在 Prometheus 中启用告警规则

**prometheus.yml:**

```yaml
rule_files:
  - "alerts.yml"

alerting:
  alertmanagers:
    - static_configs:
        - targets:
          - alertmanager:9093
```

#### 2. 验证告警规则

```bash
# 检查告警规则语法
promtool check rules alerts.yml

# 测试告警规则
curl http://prometheus:9090/api/v1/rules

# 查看活跃告警
curl http://prometheus:9090/api/v1/alerts
```

### Alertmanager 配置

#### 基本配置

**alertmanager.yml:**

```yaml
global:
  resolve_timeout: 5m
  smtp_smarthost: 'smtp.example.com:587'
  smtp_from: 'alerts@example.com'
  smtp_auth_username: 'alerts@example.com'
  smtp_auth_password: 'your-password'

route:
  receiver: 'team-email'
  group_wait: 10s
  group_interval: 10m
  repeat_interval: 1h
  group_by: ['alertname', 'severity']

receivers:
  - name: 'team-email'
    email_configs:
      - to: 'team@example.com'
        send_resolved: true

  - name: 'slack'
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/YOUR/WEBHOOK'
        channel: '#alerts'
        send_resolved: true

inhibit_rules:
  - source_match:
      severity: 'critical'
    target_match:
      severity: 'warning'
    equal: ['alertname', 'instance']
```

#### 多通道告警

```yaml
route:
  receiver: 'default'
  routes:
    - match:
        severity: critical
      receiver: 'team-email'
      continue: true

    - match:
        severity: warning
      receiver: 'slack'

receivers:
  - name: 'default'
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/YOUR/WEBHOOK'
        channel: '#alerts'

  - name: 'team-email'
    email_configs:
      - to: 'team@example.com'

  - name: 'slack'
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/YOUR/WEBHOOK'
        channel: '#alerts'
```

### 测试告警

#### 手动触发告警

```bash
# 临时停止一个服务以触发告警
docker stop neo4j

# 观察告警触发
watch -n 5 'curl -s http://prometheus:9090/api/v1/alerts | jq ".data.alerts[] | select(.state==\"firing\")"'

# 恢复服务
docker start neo4j
```

#### 验证告警通知

```bash
# 检查 Alertmanager 状态
curl http://alertmanager:9093/api/v2/status

# 查看活跃告警
curl http://alertmanager:9093/api/v2/alerts

# 测试发送告警
curl -X POST http://alertmanager:9093/api/v2/alerts \
  -H "Content-Type: application/json" \
  -d '[{
    "labels": {
      "alertname": "TestAlert",
      "severity": "warning"
    },
    "annotations": {
      "summary": "Test alert from Weaver"
    }
  }]'
```

---

## 故障排查指南

### 健康检查失败

#### PostgreSQL 健康检查失败

**症状:** `postgres.status = "error"`

**诊断:**

```bash
# 检查 PostgreSQL 是否运行
docker ps | grep postgres
# 或
systemctl status postgresql

# 测试连接
psql $POSTGRES_DSN -c "SELECT 1"

# 检查日志
docker logs postgres
# 或
journalctl -u postgresql
```

**常见原因:**
- PostgreSQL 未启动
- 认证凭证错误
- 网络不通
- 数据库不存在

**解决方案:**
- 启动 PostgreSQL 服务
- 验证 `POSTGRES_DSN` 环境变量
- 检查防火墙规则
- 创建数据库

#### Neo4j 健康检查失败

**症状:** `neo4j.status = "timeout"`

**诊断:**

```bash
# 检查 Neo4j 是否运行
docker ps | grep neo4j

# 测试连接
cypher-shell -a $NEO4J_URI -u $NEO4J_USER -p $NEO4J_PASSWORD "RETURN 1"

# 检查日志
docker logs neo4j
```

**常见原因:**
- Neo4j 启动缓慢（需要等待）
- JVM 内存不足
- 数据库正在恢复

**解决方案:**
- 等待 Neo4j 完全启动（可能需要 1-2 分钟）
- 增加 Neo4j 内存限制
- 检查 Neo4j 日志排查启动问题

#### Redis 健康检查失败

**症状:** `redis.status = "error"`

**诊断:**

```bash
# 检查 Redis 是否运行
docker ps | grep redis

# 测试连接
redis-cli -u $REDIS_URL ping

# 检查内存使用
redis-cli -u $REDIS_URL info memory
```

**常见原因:**
- Redis 未启动
- 密码认证失败
- 内存不足

**解决方案:**
- 启动 Redis 服务
- 验证 Redis 密码配置
- 检查 Redis 内存限制

### Prometheus 指标问题

#### 指标未收集

**症状:** Prometheus UI 中无数据

**诊断:**

```bash
# 测试 /metrics 端点
curl http://weaver:8000/metrics

# 检查 Prometheus targets
curl http://prometheus:9090/api/v1/targets

# 检查 Prometheus 日志
docker logs prometheus
```

**常见原因:**
- Prometheus 配置错误
- 网络不通
- 应用未启动

**解决方案:**
- 验证 `prometheus.yml` 配置
- 检查网络连接
- 重启 Prometheus

#### 指标值异常

**症状:** 指标值不符合预期

**诊断:**

```bash
# 查询原始指标
curl http://weaver:8000/metrics | grep <metric_name>

# 在 Prometheus 中查询
curl 'http://prometheus:9090/api/v1/query?query=<metric_name>'
```

**常见原因:**
- 应用逻辑错误
- 指标定义错误
- 数据采集延迟

**解决方案:**
- 检查应用日志
- 验证指标定义
- 等待数据更新

### OpenTelemetry 追踪问题

#### 追踪数据未显示

**症状:** Jaeger 中无追踪数据

**诊断:**

```bash
# 检查环境变量
echo $OBS_OTLP_ENDPOINT

# 测试 Collector 连接
grpcurl otel-collector:4317 list

# 检查 Collector 日志
docker logs otel-collector

# 检查 Jaeger 日志
docker logs jaeger
```

**常见原因:**
- OTLP endpoint 配置错误
- Collector 未启动
- Jaeger 未启动

**解决方案:**
- 验证 `OBS_OTLP_ENDPOINT` 环境变量
- 启动 OpenTelemetry Collector
- 启动 Jaeger

#### 追踪数据不完整

**症状:** 部分 Span 缺失

**诊断:**

```bash
# 检查 Collector 配置
cat otel-collector-config.yaml

# 检查应用日志
docker logs weaver | grep -i trace
```

**常见原因:**
- Span 处理失败
- 网络丢包
- Collector 过载

**解决方案:**
- 检查 Collector 配置
- 增加网络带宽
- 扩展 Collector 资源

### Grafana 仪表盘问题

#### 仪表盘无数据

**症状:** Grafana 面板显示 "N/A"

**诊断:**

```bash
# 检查 Prometheus 数据源
curl http://grafana:3000/api/datasources/proxy/1/api/v1/query?query=up

# 测试 PromQL 查询
curl 'http://prometheus:9090/api/v1/query?query=up{job="weaver"}'
```

**常见原因:**
- 数据源配置错误
- 指标不存在
- 查询时间范围错误

**解决方案:**
- 验证 Prometheus 数据源配置
- 检查指标名称
- 调整时间范围

### 告警问题

#### 告警未触发

**症状:** 问题存在但无告警

**诊断:**

```bash
# 查看告警规则
curl http://prometheus:9090/api/v1/rules

# 查看活跃告警
curl http://prometheus:9090/api/v1/alerts

# 检查 Alertmanager
curl http://alertmanager:9093/api/v2/alerts
```

**常见原因:**
- 告警规则未加载
- 持续时间未达到
- 告警被抑制

**解决方案:**
- 重启 Prometheus 加载规则
- 等待持续时间达到
- 检查 inhibit_rules

#### 告警风暴

**症状:** 短时间大量告警

**诊断:**

```bash
# 查看所有活跃告警
curl http://alertmanager:9093/api/v2/alerts | jq 'length'

# 检查告警分组
curl http://alertmanager:9093/api/v2/status
```

**解决方案:**
- 调整 `group_by` 配置
- 增加 `group_wait` 和 `group_interval`
- 使用告警抑制规则

---

## 监控最佳实践

### 监控指标

1. **设置合理的检查频率**
   - 健康检查: 10-30 秒
   - Prometheus 抓取: 15-60 秒

2. **定义清晰的告警阈值**
   - Critical: 立即响应（< 5 分钟）
   - Warning: 当日响应（< 4 小时）

3. **避免告警疲劳**
   - 使用告警分组和聚合
   - 设置合理的持续时间
   - 配置告警抑制

### 日志管理

1. **日志分级**
   - ERROR: 错误和异常
   - WARNING: 潜在问题
   - INFO: 重要事件
   - DEBUG: 调试信息（仅开发环境）

2. **日志保留策略**
   - 生产环境: 30 天
   - 开发环境: 7 天
   - 审计日志: 1 年

### 性能优化

1. **Prometheus 优化**
   - 减少不必要的指标
   - 优化查询语句
   - 增加存储容量

2. **Grafana 优化**
   - 减少面板刷新频率
   - 使用变量减少面板数量
   - 优化查询语句

---

## 相关文档

- [部署文档](../deployment/README.md) - 部署配置和环境变量
- [API 文档](../api/README.md) - API 端点文档
- [开发文档](../development/README.md) - 开发指南

---

## 联系与支持

如遇到问题，请：

1. 查阅本文档故障排查章节
2. 检查应用日志
3. 查看监控仪表盘
4. 提交 Issue: https://github.com/your-org/weaver/issues