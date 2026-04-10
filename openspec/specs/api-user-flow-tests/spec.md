## ADDED Requirements

### Requirement: API 用户流程 E2E 测试

模拟真实用户使用场景，通过 HTTP API 端到端验证 4 条核心用户操作路径。

#### Scenario: 流程 1 - 资讯处理完整流程
- **WHEN** 用户按顺序执行以下操作：
  1. `POST /api/v1/sources` 创建数据源
  2. `POST /api/v1/pipeline/trigger` 触发爬取
  3. `GET /api/v1/pipeline/tasks/{task_id}` 查询状态直到完成
  4. `GET /api/v1/articles` 查看处理结果
  5. `GET /api/v1/graph/entities/{name}` 查看提取的实体
- **THEN** 每步的 HTTP 状态码和响应数据正确，流程无断裂

#### Scenario: 流程 2 - 知识图谱搜索流程
- **WHEN** 用户按顺序执行以下操作：
  1. `GET /api/v1/search?q=为什么AI会影响就业` 统一搜索
  2. `GET /api/v1/graph/visualization` 查看图谱可视化
  3. `GET /api/v1/graph/metrics?view=health` 检查图谱健康
- **THEN** 搜索返回意图路由结果，图谱可视化返回节点和边

#### Scenario: 流程 3 - 运维监控流程
- **WHEN** 运维人员按顺序执行以下操作：
  1. `GET /health` 健康检查
  2. `GET /metrics` Prometheus 指标
  3. `GET /api/v1/admin/llm-usage/summary?from=...&to=...` LLM 使用汇总
  4. `GET /api/v1/admin/llm-failures/stats` 失败统计
- **THEN** health 返回各服务状态，metrics 返回文本格式，LLM 统计返回聚合数据

#### Scenario: 流程 4 - 社区管理流程
- **WHEN** 管理员按顺序执行以下操作：
  1. `POST /api/v1/admin/communities/rebuild` 重建社区
  2. `POST /api/v1/admin/communities/reports/generate` 生成报告
  3. `GET /api/v1/graph/communities` 查看社区列表
  4. `GET /api/v1/graph/communities/{id}` 查看社区详情
- **THEN** 每步的返回数据结构正确，重建统计、报告生成计数、社区列表和详情一致

### Requirement: API 认证贯穿测试

所有 E2E 用户流程测试必须验证认证机制。

#### Scenario: 无 API Key 请求被拒绝
- **GIVEN** 请求未携带 X-API-Key 头
- **WHEN** 调用任意需要认证的端点
- **THEN** 返回 401 Unauthorized

#### Scenario: 无效 API Key 请求被拒绝
- **GIVEN** 请求携带无效的 X-API-Key
- **WHEN** 调用任意需要认证的端点
- **THEN** 返回 403 Forbidden

#### Scenario: 有效 API Key 请求通过
- **GIVEN** 请求携带有效的 X-API-Key
- **WHEN** 调用任意端点
- **THEN** 认证通过，正常处理请求
