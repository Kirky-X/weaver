# Grafana 监控仪表盘

本目录包含 Weaver 项目的 Grafana 仪表盘配置文件。

## 仪表盘列表

### 1. 系统健康概览 (`system-health-overview.json`)

**用途**: 监控系统整体健康状态和关键性能指标

**主要面板**:
- **数据库健康状态**: PostgreSQL、Neo4j、Redis 的实时健康状态（健康/错误/超时/不可用）
- **数据库延迟趋势**: 各数据库的响应延迟时序图
- **数据库连接池利用率**: 连接池使用情况监控
- **API 请求成功率**: 各端点的请求成功率趋势
- **API 响应时间分布**: P50、P95、P99 响应时间

**关键指标**:
- `health_check_status` - 健康检查状态
- `health_check_latency_ms` - 健康检查延迟
- `db_pool_utilization` - 连接池利用率
- `api_request_total` - API 请求总数
- `api_request_latency_seconds` - API 请求延迟

**使用场景**:
- 快速了解系统整体健康状况
- 发现数据库连接问题
- 监控 API 性能瓶颈

---

### 2. Circuit Breaker 状态 (`circuit-breaker-status.json`)

**用途**: 监控熔断器状态和 LLM 服务调用情况

**主要面板**:
- **Circuit Breaker 当前状态**: 所有 provider 的熔断器状态（CLOSED/OPEN/HALF_OPEN）
- **熔断次数统计**: 5 分钟内的熔断次数趋势
- **LLM 调用失败率趋势**: 各 provider 的失败率百分比
- **Fallback 事件统计**: 按原因分类的降级事件统计
- **LLM 调用延迟**: P95、P99 延迟监控
- **Provider 调用统计**: 24 小时内各 provider 的调用次数和失败次数表格

**关键指标**:
- `circuit_breaker_state` - 熔断器状态 (0=CLOSED, 1=OPEN, 2=HALF_OPEN)
- `circuit_breaker_failures_total` - 熔断失败次数
- `llm_call_total` - LLM 调用总数
- `llm_call_latency_seconds` - LLM 调用延迟
- `llm_fallback_total` - Fallback 事件次数

**使用场景**:
- 监控 LLM 服务稳定性
- 发现 provider 故障
- 分析 fallback 触发原因
- 评估 LLM 服务质量

---

### 3. 数据库一致性状态 (`database-consistency.json`)

**用途**: 监控 PostgreSQL 和 Neo4j 之间的数据一致性

**主要面板**:
- **PostgreSQL 记录数**: PostgreSQL 中的记录总数
- **Neo4j 实体数**: Neo4j 中的实体总数
- **记录数差异**: 两个数据库之间的记录数差异
- **PostgreSQL vs Neo4j 记录数趋势**: 双数据库记录数对比时序图
- **同步延迟**: Batch Merger 和 Entity Extractor 的处理延迟
- **错误事务计数**: 5 分钟内的错误事务统计
- **Pipeline 队列深度**: 待处理任务队列深度
- **持久化状态分布**: 各状态（PENDING/PROCESSING/PG_DONE/NEO4J_DONE/FAILED）的记录数

**关键指标**:
- `pg_stat_user_tables_n_live_tup` - PostgreSQL 记录数
- `neo4j_node_count` - Neo4j 节点数
- `pipeline_stage_latency_seconds` - Pipeline 阶段延迟
- `db_transaction_errors_total` - 数据库事务错误
- `pipeline_queue_depth` - Pipeline 队列深度
- `persist_status_count` - 持久化状态计数

**使用场景**:
- 检测数据库同步问题
- 监控数据一致性
- 发现事务错误
- 评估 Pipeline 处理能力

---

## 配置要求

### Prometheus 数据源

所有仪表盘使用 Prometheus 作为数据源，需要配置：

1. **数据源名称**: `prometheus`
2. **访问地址**: 通常为 `http://prometheus:9090`
3. **数据源 UID**: `prometheus`

### 必需的 Prometheus 指标

确保以下指标已正确配置并暴露：

#### 健康检查指标
```promql
health_check_status{service="postgres|neo4j|redis"}
health_check_latency_ms{service="postgres|neo4j|redis"}
```

#### Circuit Breaker 指标
```promql
circuit_breaker_state{provider="..."}
circuit_breaker_failures_total{provider="..."}
llm_call_total{provider="...", status="success|error"}
llm_call_latency_seconds{provider="..."}
llm_fallback_total{from_provider="...", reason="..."}
```

#### 数据库一致性指标
```promql
pg_stat_user_tables_n_live_tup{datname="weaver"}
neo4j_node_count{label="Entity"}
pipeline_stage_latency_seconds{stage="..."}
db_transaction_errors_total{database="...", error_type="..."}
pipeline_queue_depth
persist_status_count{status="..."}
```

## 导入仪表盘

### 方法 1: 通过 Grafana UI 导入

1. 登录 Grafana
2. 点击左侧菜单 **Dashboards** → **Import**
3. 点击 **Upload JSON file**
4. 选择对应的 JSON 文件
5. 选择 Prometheus 数据源
6. 点击 **Import**

### 方法 2: 通过 API 导入

```bash
# 设置环境变量
GRAFANA_URL="http://localhost:3000"
GRAFANA_API_KEY="your-api-key"

# 导入系统健康概览仪表盘
curl -X POST \
  -H "Authorization: Bearer $GRAFANA_API_KEY" \
  -H "Content-Type: application/json" \
  -d @monitoring/grafana/dashboards/system-health-overview.json \
  "$GRAFANA_URL/api/dashboards/db"

# 导入 Circuit Breaker 状态仪表盘
curl -X POST \
  -H "Authorization: Bearer $GRAFANA_API_KEY" \
  -H "Content-Type: application/json" \
  -d @monitoring/grafana/dashboards/circuit-breaker-status.json \
  "$GRAFANA_URL/api/dashboards/db"

# 导入数据库一致性状态仪表盘
curl -X POST \
  -H "Authorization: Bearer $GRAFANA_API_KEY" \
  -H "Content-Type: application/json" \
  -d @monitoring/grafana/dashboards/database-consistency.json \
  "$GRAFANA_URL/api/dashboards/db"
```

### 方法 3: 使用配置文件自动加载

将仪表盘文件放置在 Grafana 的 provisioning 目录：

```yaml
# grafana/provisioning/dashboards/dashboards.yml
apiVersion: 1

providers:
  - name: 'Weaver Dashboards'
    orgId: 1
    folder: ''
    folderUid: ''
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30
    allowUiUpdates: true
    options:
      path: /etc/grafana/provisioning/dashboards
```

## 变量使用

部分仪表盘支持动态变量：

### 系统健康概览
- **endpoint**: 按 API 端点筛选数据

### Circuit Breaker 状态
- **provider**: 按 LLM provider 筛选数据

## 刷新间隔

所有仪表盘默认刷新间隔：**30 秒**

可选手动刷新间隔：
- 5s、10s、30s、1m、5m、15m、30m、1h、2h、1d

## 时间范围

默认时间范围：**最近 1 小时**

可通过时间选择器调整：
- Last 5 minutes
- Last 15 minutes
- Last 1 hour
- Last 3 hours
- Last 6 hours
- Last 12 hours
- Last 24 hours
- Last 2 days
- Last 7 days
- Custom range

## 告警集成

建议为以下指标配置告警：

### 系统健康
- 健康检查状态为 `error` 或 `timeout` 超过 2 分钟
- 数据库延迟 > 500ms 超过 5 分钟
- 连接池利用率 > 90% 超过 5 分钟

### Circuit Breaker
- 熔断器状态为 `OPEN` 超过 5 分钟
- LLM 调用失败率 > 20% 超过 5 分钟
- Fallback 触发次数异常增长

### 数据库一致性
- PostgreSQL vs Neo4j 记录数差异 > 50
- 同步延迟 > 10s 超过 5 分钟
- 错误事务数 > 10 次/分钟

## 最佳实践

1. **定期检查仪表盘**: 建议每天至少查看一次系统健康概览
2. **设置关键告警**: 为 P0 级指标配置告警规则
3. **调整刷新间隔**: 根据实际需求调整刷新频率，避免过度查询 Prometheus
4. **保存快照**: 定期保存关键时间点的仪表盘快照用于历史对比
5. **团队共享**: 将仪表盘分享给团队成员，确保所有人都能监控系统状态

## 故障排查

### 仪表盘显示 "No Data"

**可能原因**:
1. Prometheus 数据源未配置
2. 对应的指标未暴露或无数据
3. 查询语句错误
4. 时间范围内没有数据

**解决方法**:
1. 检查 Prometheus 数据源配置
2. 访问 `/metrics` 端点确认指标存在
3. 在 Prometheus UI 中测试查询语句
4. 调整时间范围

### 面板加载缓慢

**可能原因**:
1. 查询时间范围过大
2. Prometheus 性能不足
3. 网络延迟

**解决方法**:
1. 缩小时间范围
2. 优化 Prometheus 查询
3. 检查网络连接

## 更新日志

- **2026-03-18**: 初始版本，创建三个核心仪表盘
  - 系统健康概览
  - Circuit Breaker 状态
  - 数据库一致性状态

## 相关文档

- [Prometheus 配置](../../prometheus/README.md)
- [健康检查端点文档](../../../src/api/endpoints/health.py)
- [监控指标定义](../../../src/core/observability/metrics.py)
- [Circuit Breaker 文档](../../../src/core/resilience/circuit_breaker.py)