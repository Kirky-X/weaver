# Prometheus 告警规则使用指南

本文档说明如何配置和使用 Weaver 项目的 Prometheus 告警规则。

## 概述

本项目实现了 6 大类共 18 条告警规则，覆盖以下关键领域：

| 类别 | 告警数量 | 严重级别 | 覆盖范围 |
|------|---------|---------|---------|
| Circuit Breaker 熔断 | 3 | Critical/Warning | 熔断器状态、失败频率 |
| LLM 服务质量 | 3 | Critical/Warning | 错误率、延迟、Fallback |
| API 性能 | 2 | Critical/Warning | 延迟、错误率 |
| 数据库连接池 | 2 | Critical/Warning | 连接池利用率 |
| 健康检查 | 3 | Critical | 服务健康状态、延迟 |
| 数据一致性 | 5 | Critical/Warning | 数据同步、事务错误、队列积压 |

## 快速开始

### 1. 部署告警规则

将 `alerts.yml` 文件复制到 Prometheus 配置目录：

```bash
# 如果使用 Docker Compose
cp monitoring/prometheus/alerts.yml /path/to/prometheus/config/

# 如果使用 Kubernetes ConfigMap
kubectl create configmap prometheus-alerts --from-file=alerts.yml
```

### 2. 配置 Prometheus

在 `prometheus.yml` 中引用告警规则文件：

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

# 告警规则文件
rule_files:
  - "alerts.yml"

# Alertmanager 配置
alerting:
  alertmanagers:
    - static_configs:
        - targets:
          - alertmanager:9093
```

### 3. 重启 Prometheus

```bash
# Docker Compose
docker-compose restart prometheus

# Kubernetes
kubectl rollout restart deployment/prometheus
```

### 4. 验证告警规则

访问 Prometheus UI 验证告警规则已加载：

```
http://localhost:9090/rules
```

## 告警规则详细说明

### 1. Circuit Breaker 熔断告警

#### CircuitBreakerOpen (Critical)
- **触发条件**: Circuit Breaker 状态为 OPEN (值为 1)
- **持续时间**: 1 分钟
- **影响**: 所有请求快速失败，服务不可用
- **处理步骤**:
  1. 检查上游服务状态
  2. 查看 Circuit Breaker 日志
  3. 修复上游服务或调整熔断阈值

#### CircuitBreakerHalfOpen (Warning)
- **触发条件**: Circuit Breaker 状态为 HALF_OPEN (值为 2)
- **持续时间**: 5 分钟
- **影响**: 服务正在尝试恢复
- **处理步骤**:
  1. 监控服务恢复进度
  2. 如果长时间未恢复，检查上游服务

#### HighCircuitBreakerFailureRate (Warning)
- **触发条件**: 5 分钟内熔断次数 > 5 次
- **持续时间**: 2 分钟
- **影响**: 上游服务不稳定
- **处理步骤**:
  1. 分析熔断原因
  2. 考虑降低熔断阈值或增加重试

### 2. LLM 服务质量告警

#### LLMHighErrorRate (Critical)
- **触发条件**: LLM 调用错误率 > 10%
- **持续时间**: 5 分钟
- **影响**: AI 功能不可用或降级
- **处理步骤**:
  1. 检查 LLM Provider 状态
  2. 检查 API Key 是否有效
  3. 查看 Fallback 是否正常工作

#### LLMHighLatency (Warning)
- **触发条件**: LLM 调用 P99 延迟 > 10s
- **持续时间**: 5 分钟
- **影响**: 用户体验下降
- **处理步骤**:
  1. 检查网络连接
  2. 考虑使用更快的模型
  3. 检查是否需要调整超时配置

#### FrequentFallbackTriggered (Warning)
- **触发条件**: 1 小时内 Fallback > 10 次
- **持续时间**: 5 分钟
- **影响**: 主 Provider 不稳定
- **处理步骤**:
  1. 分析 Fallback 原因
  2. 优化主 Provider 配置
  3. 考虑增加备用 Provider

### 3. API 性能告警

#### APIHighLatency (Warning)
- **触发条件**: API P99 延迟 > 1s
- **持续时间**: 5 分钟
- **影响**: 用户请求慢
- **处理步骤**:
  1. 检查慢查询日志
  2. 分析数据库性能
  3. 考虑增加缓存

#### APIHighErrorRate (Critical)
- **触发条件**: API 5xx 错误率 > 5%
- **持续时间**: 5 分钟
- **影响**: 功能不可用
- **处理步骤**:
  1. 查看错误日志
  2. 检查依赖服务状态
  3. 必要时回滚最近变更

### 4. 数据库连接池告警

#### DatabasePoolSaturation (Warning)
- **触发条件**: 连接池利用率 > 90%
- **持续时间**: 5 分钟
- **影响**: 请求可能排队或超时
- **处理步骤**:
  1. 检查连接泄漏
  2. 优化查询性能
  3. 考虑增加连接池大小

#### DatabasePoolExhausted (Critical)
- **触发条件**: 连接池利用率 > 95%
- **持续时间**: 2 分钟
- **影响**: 数据库访问失败
- **处理步骤**:
  1. 紧急扩容连接池
  2. 优化长事务
  3. 重启服务释放连接

### 5. 健康检查告警

#### ServiceHealthCheckFailed (Critical)
- **触发条件**: 健康检查状态 != 1 (ok)
- **持续时间**: 2 分钟
- **影响**: 依赖服务不可用
- **处理步骤**:
  1. 检查服务日志
  2. 验证网络连接
  3. 重启服务

#### HealthCheckHighLatency (Warning)
- **触发条件**: 健康检查延迟 > 1s
- **持续时间**: 5 分钟
- **影响**: 服务响应慢
- **处理步骤**:
  1. 检查数据库性能
  2. 检查网络延迟
  3. 优化健康检查逻辑

#### MultipleServicesUnhealthy (Critical)
- **触发条件**: >= 2 个服务健康检查失败
- **持续时间**: 1 分钟
- **影响**: 系统级故障
- **处理步骤**:
  1. 检查共享基础设施
  2. 检查网络和存储
  3. 考虑切换到备用环境

### 6. 数据一致性告警

#### DataInconsistencyDetected (Warning)
- **触发条件**: PostgreSQL 与 Neo4j 记录数差异 > 50
- **持续时间**: 10 分钟
- **影响**: 数据可能不一致
- **处理步骤**:
  1. 检查同步任务日志
  2. 手动触发同步
  3. 验证数据完整性

#### SevereDataInconsistency (Critical)
- **触发条件**: PostgreSQL 与 Neo4j 记录数差异 > 100
- **持续时间**: 15 分钟
- **影响**: 数据严重不一致
- **处理步骤**:
  1. 停止写入操作
  2. 手动对账
  3. 从备份恢复

#### HighTransactionErrorRate (Warning)
- **触发条件**: 5 分钟内事务错误 > 10 次
- **持续时间**: 5 分钟
- **影响**: 写入操作失败
- **处理步骤**:
  1. 查看错误类型
  2. 检查数据库约束
  3. 优化事务逻辑

#### PipelineQueueBacklog (Warning)
- **触发条件**: 队列深度 > 1000
- **持续时间**: 10 分钟
- **影响**: 处理延迟增加
- **处理步骤**:
  1. 增加消费者数量
  2. 优化处理性能
  3. 检查下游服务

#### HighPersistenceFailureRate (Warning)
- **触发条件**: 持久化失败率 > 5%
- **持续时间**: 10 分钟
- **影响**: 数据丢失风险
- **处理步骤**:
  1. 检查失败原因
  2. 优化持久化逻辑
  3. 考虑重试机制

## Alertmanager 配置示例

### 基础配置

```yaml
global:
  resolve_timeout: 5m
  smtp_smarthost: 'smtp.example.com:587'
  smtp_from: 'alerts@example.com'
  smtp_auth_username: 'alerts@example.com'
  smtp_auth_password: 'password'

route:
  group_by: ['alertname', 'severity']
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 12h
  receiver: 'default-receiver'

  routes:
    # Critical 告警立即发送
    - match:
        severity: critical
      receiver: 'critical-receiver'
      continue: false

    # Warning 告警汇总发送
    - match:
        severity: warning
      receiver: 'warning-receiver'
      group_wait: 5m

receivers:
  - name: 'default-receiver'
    email_configs:
      - to: 'team@example.com'

  - name: 'critical-receiver'
    email_configs:
      - to: 'oncall@example.com'
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/XXX'
        channel: '#alerts-critical'
        send_resolved: true

  - name: 'warning-receiver'
    email_configs:
      - to: 'team@example.com'
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/XXX'
        channel: '#alerts-warning'
```

### 告警静默

临时静默告警：

```bash
# 静默特定告警
amtool silence add alertname=CircuitBreakerOpen provider=openai duration=1h

# 静默所有 warning 级别告警
amtool silence add severity=warning duration=30m

# 查看静默规则
amtool silence query

# 删除静默规则
amtool silence expire <silence_id>
```

## 监控最佳实践

### 1. 告警分级

- **Critical**: 立即处理，设置 PagerDuty/短信通知
- **Warning**: 工作时间处理，设置邮件/Slack 通知

### 2. 告警抑制

避免告警风暴：

```yaml
# 在 Alertmanager 中配置抑制规则
inhibit_rules:
  # 如果系统级告警触发，抑制服务级告警
  - source_match:
      severity: 'critical'
      component: 'health'
    target_match:
      severity: 'warning'
    equal: ['instance']
```

### 3. 告警调优

定期回顾告警效果：

```bash
# 查看告警历史
curl http://localhost:9090/api/v1/alerts

# 查看告警触发频率
rate(ALERTS{alertstate="firing"}[1h])

# 调整阈值建议
# - 误报多：提高阈值或延长持续时间
# - 漏报多：降低阈值或缩短持续时间
```

### 4. 告警文档

每个告警都应包含：
- 清晰的 summary 和 description
- runbook_url 指向处理文档
- 严重级别标签
- 组件标签

## 测试告警

### 手动触发告警测试

```bash
# 测试 Circuit Breaker 告警
curl -X POST http://localhost:9090/api/v1/admin/tsdb/delete_series?match[]={__name__=~"circuit_breaker.*"}

# 测试 API 延迟告警
# 故意制造延迟请求
ab -n 1000 -c 10 http://localhost:8000/api/slow-endpoint

# 测试健康检查告警
docker stop weaver-postgres
# 等待 2 分钟，观察告警
docker start weaver-postgres
```

### 验证告警通知

1. 检查 Prometheus UI: http://localhost:9090/alerts
2. 检查 Alertmanager UI: http://localhost:9093
3. 验证邮件/Slack 通知

## 依赖指标清单

确保以下指标已正确暴露：

| 指标名称 | 类型 | 来源 | 说明 |
|---------|------|------|------|
| `circuit_breaker_state` | Gauge | Circuit Breaker | 熔断器状态 |
| `circuit_breaker_failures_total` | Counter | Circuit Breaker | 熔断失败计数 |
| `llm_call_total` | Counter | LLM Client | LLM 调用计数 |
| `llm_call_latency_seconds` | Histogram | LLM Client | LLM 调用延迟 |
| `llm_fallback_total` | Counter | LLM Client | Fallback 计数 |
| `api_request_total` | Counter | API | API 请求计数 |
| `api_request_latency_seconds` | Histogram | API | API 延迟 |
| `db_pool_utilization` | Gauge | Database Pool | 连接池利用率 |
| `health_check_status` | Gauge | Health Check | 健康检查状态 |
| `health_check_latency_ms` | Gauge | Health Check | 健康检查延迟 |
| `pg_stat_user_tables_n_live_tup` | Gauge | PostgreSQL | 表记录数 |
| `neo4j_node_count` | Gauge | Neo4j | 节点数 |
| `pipeline_stage_latency_seconds` | Gauge | Pipeline | 同步延迟 |
| `db_transaction_errors_total` | Counter | Database | 事务错误计数 |
| `pipeline_queue_depth` | Gauge | Pipeline | 队列深度 |
| `persist_status_count` | Gauge | Persistence | 持久化状态计数 |

## 故障排查

### 告警未触发

1. 检查指标是否正常暴露：`curl http://localhost:8000/metrics`
2. 检查 Prometheus 是否正常抓取：`curl http://localhost:9090/targets`
3. 检查告警规则语法：`promtool check rules alerts.yml`
4. 检查告警规则是否加载：访问 http://localhost:9090/rules

### 告警风暴

1. 临时静默：`amtool silence add severity=warning duration=1h`
2. 调整告警持续时间（`for` 参数）
3. 添加告警抑制规则
4. 提高告警阈值

### 误报频繁

1. 分析历史数据：`curl http://localhost:9090/api/v1/query?query=ALERTS`
2. 调整阈值和持续时间
3. 优化指标采集逻辑
4. 添加额外的过滤条件

## 参考资源

- [Prometheus 告警文档](https://prometheus.io/docs/alerting/latest/alertmanager/)
- [Alertmanager 配置指南](https://prometheus.io/docs/alerting/latest/configuration/)
- [告警最佳实践](https://sre.google/sre-book/practical-alerting/)
- [Weaver 监控文档](../../docs/MONITORING.md)

## 更新日志

- 2026-03-18: 初始版本，实现 6 大类 18 条告警规则