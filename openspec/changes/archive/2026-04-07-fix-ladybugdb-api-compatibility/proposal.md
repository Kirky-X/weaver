## Why

配置使用 DuckDB + LadybugDB 作为故障转移数据库，但多个 API 端点返回 500 错误。根本原因是代码中存在硬编码的 Neo4j/PostgreSQL 依赖，没有完全适配 Protocol 抽象层。需要修复这些依赖，确保 DuckDB+LadybugDB 模式下所有 API 正常工作。

**当前错误状态**:
- 17 个端点正常 (200)
- 7 个端点失败 (500/503/404)

## What Changes

1. **修复类型注解** - `graph.py` 中 `set_postgres_pool` 使用具体类型 `PostgresPool`，改为 Protocol 类型 `RelationalPool`
2. **修复属性访问** - `search.py` 中 DRIFT 端点直接访问 `global_engine._pool`，LadybugDB 模式下此属性不存在
3. **完善 LadybugDB Schema** - Community 节点缺少 `parent_id` 字段，EventNode 属性名与查询不匹配
4. **创建 LadybugEntityRepo** - `Neo4jEntityRepo` 使用 Neo4j 特有 Cypher 语法 (`type(r)`)，LadybugDB 不支持
5. **修复 TemporalGraphRepo** - 查询使用 `content`/`timestamp`，但 LadybugDB schema 是 `description`/`event_time`

## Capabilities

### New Capabilities

- `ladybug-entity-repo`: LadybugDB 兼容的实体仓库实现，支持关系类型查询
- `ladybug-temporal-repo`: LadybugDB 兼容的时序图仓库实现

### Modified Capabilities

- `graph-query-abstraction`: 扩展 GraphQueryBuilder 支持更多查询模式
- `ladybug-community-schema`: 添加 `parent_id` 字段支持社区层次结构
- `ladybug-temporal-schema`: 统一属性命名 (`content`/`timestamp`/`attributes`)
- `search-engine`: 修复 DRIFT 搜索端点的依赖注入问题
- `explicit-interface-contract`: 更新 `graph.py` 使用 Protocol 类型

## Impact

### 代码变更

| 文件 | 变更类型 |
|------|----------|
| `src/api/endpoints/graph.py` | 类型注解修复 |
| `src/api/endpoints/search.py` | 依赖注入修复 |
| `src/modules/storage/ladybug/schema.py` | Schema 扩展 |
| `src/modules/storage/ladybug/entity_repo.py` | 新建 |
| `src/modules/memory/graphs/temporal.py` | 查询适配 |
| `src/core/db/graph_query.py` | 扩展支持 |

### API 影响

| 端点 | 当前状态 | 修复后 |
|------|----------|--------|
| `/graph/relation-types` | 500 | 200 |
| `/graph/relations` | 500 | 200 |
| `/graph/relations/search` | 500 | 200 |
| `/graph/communities` | 500 | 200 |
| `/search/drift` | 500 | 200 |
| `/search/temporal` | 500 | 200 |

### 依赖关系

- 无新外部依赖
- 需要重新初始化 LadybugDB schema（添加新字段）