## Why

Weaver 的数据库故障转移策略要求在 PostgreSQL/Neo4j 不可用时自动降级到嵌入式数据库（DuckDB/LadybugDB）。当前实现存在多处兼容性问题，导致使用嵌入式数据库时多个 API 端点返回 500 错误，影响开发和测试体验。

## What Changes

### DuckDB 兼容性修复
- 修复 `llm_usage_hourly` 表列名不匹配：schema 使用 `hour_timestamp`，但 SQLAlchemy model 使用 `time_bucket`
- 修复 SQLAlchemy session 管理问题，避免 lazy loading 时 session 已关闭

### LadybugDB Schema 扩展
- 添加 `Community` 节点表，支持社区检测 API
- 添加 `CommunityReport` 节点表，支持社区报告 API  
- 添加 `EventNode` 节点表，支持时序搜索 API
- 添加 `HAS_ENTITY`、`REPORTS_ON` 关系表

### 搜索引擎抽象层
- 创建 `GraphQueryBuilder` 协议，抽象 Cypher/Ladybug 查询差异
- 实现 `LadybugLocalContextBuilder`，支持 LadybugDB 本地搜索
- 移除 `container.py:677` 硬编码限制，启用 LadybugDB 搜索引擎

## Capabilities

### New Capabilities
- `graph-query-abstraction`: 图数据库查询抽象层，统一 Neo4j Cypher 与 LadybugDB SQL 变体
- `ladybug-community-schema`: LadybugDB 社区检测相关表结构定义
- `ladybug-temporal-schema`: LadybugDB 时序事件相关表结构定义

### Modified Capabilities
- `duckdb-schema`: 修复 `llm_usage_hourly` 表列名定义
- `search-engine`: 扩展支持 LadybugDB 作为图数据库后端

## Impact

### 直接影响文件
- `src/modules/storage/duckdb/schema.py` - 列名修复
- `src/modules/storage/ladybug/schema.py` - 表结构扩展
- `src/container.py` - 移除硬编码限制
- `src/modules/knowledge/search/context/local_context.py` - 抽象层适配
- `src/modules/knowledge/search/context/global_context.py` - 抽象层适配

### API 端点恢复
| 端点 | 当前状态 | 修复后 |
|-----|---------|--------|
| `/api/v1/admin/llm-usage` | 500 (列名错误) | 200 |
| `/api/v1/graph/communities` | 500 (表不存在) | 200 |
| `/api/v1/search/temporal` | 500 (表不存在) | 200 |
| `/api/v1/search` | 503 (引擎未初始化) | 200 |
| `/api/v1/admin/authorities` | 500 (session 问题) | 200 |

### 兼容性保证
- 所有修改保持向后兼容
- PostgreSQL + Neo4j 组合行为不变
- DuckDB + LadybugDB 组合功能完整