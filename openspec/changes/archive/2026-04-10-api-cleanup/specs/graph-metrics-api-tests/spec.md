## MODIFIED Requirements

### Requirement: Graph Metrics API 单元测试覆盖

Graph Metrics 模块的统一视图端点（GET /graph/metrics）的测试覆盖范围变更：移除 `community` 视图测试场景。社区健康评分统一由 `/admin/communities/health` 模块负责，`/graph/metrics` 不再提供 `community` view。

#### Scenario: community 视图返回 400
- **WHEN** user calls `GET /api/v1/graph/metrics?view=community`
- **THEN** returns HTTPException status_code=400 with message indicating community view removed

#### Scenario: health 视图 - 正常返回
- **GIVEN** Neo4jPool 可用，图谱包含实体和关系
- **WHEN** 调用 `GET /graph/metrics?view=health`
- **THEN** 返回 health_score(0-100)、status(healthy/moderate/degraded/critical)、recommendations

#### Scenario: full 视图 - 包含所有指标
- **GIVEN** Neo4jPool 可用
- **WHEN** 调用 `GET /api/v1/graph/metrics?view=full`
- **THEN** 返回 total_entities、total_relationships、connected_components、modularity_score 等

#### Scenario: full 视图 - include 过滤
- **GIVEN** 用户只请求 orphans 和 modularity
- **WHEN** 调用 `GET /api/v1/graph/metrics?view=full&include=orphans,modularity`
- **THEN** 只返回请求的指标子集，跳过昂贵的组件分析

#### Scenario: 无效视图参数
- **GIVEN** 用户请求未知视图
- **WHEN** 调用 `GET /api/v1/graph/metrics?view=invalid`
- **THEN** 返回 HTTPException status_code=400

#### Scenario: 缓存机制验证
- **GIVEN** full 视图无 include 过滤时使用 Redis 缓存
- **WHEN** 首次计算后再次请求
- **THEN** 从缓存读取，不重新计算
