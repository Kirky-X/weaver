## 1. DuckDB Schema 修复

- [x] 1.1 修改 `src/modules/storage/duckdb/schema.py` 中 `llm_usage_hourly` 表的 `hour_timestamp` 列名为 `time_bucket`
- [x] 1.2 删除测试用的 DuckDB 数据文件以确保 schema 重建
- [x] 1.3 验证 `/api/v1/admin/llm-usage` 端点在 DuckDB 后端正常工作

## 2. LadybugDB Schema 扩展

- [x] 2.1 在 `src/modules/storage/ladybug/schema.py` 添加 `Community` 节点表定义
- [x] 2.2 在 `src/modules/storage/ladybug/schema.py` 添加 `CommunityReport` 节点表定义（含向量列）
- [x] 2.3 在 `src/modules/storage/ladybug/schema.py` 添加 `EventNode` 节点表定义
- [x] 2.4 在 `src/modules/storage/ladybug/schema.py` 添加 `HAS_ENTITY` 关系表定义
- [x] 2.5 在 `src/modules/storage/ladybug/schema.py` 添加 `REPORTS_ON` 关系表定义
- [x] 2.6 删除测试用的 LadybugDB 数据文件以确保 schema 重建
- [x] 2.7 验证 `/api/v1/graph/communities` 端点在 LadybugDB 后端正常工作

## 3. 图查询抽象层实现

- [x] 3.1 创建 `src/core/db/graph_query.py` 文件并定义 `GraphQueryBuilder` 协议
- [x] 3.2 实现 `Neo4jQueryBuilder` 类，提供 Cypher 查询构建方法
- [x] 3.3 实现 `LadybugQueryBuilder` 类，提供 LadybugDB SQL 查询构建方法
- [x] 3.4 实现 `create_graph_query_builder()` 工厂函数
- [x] 3.5 为 `GraphQueryBuilder` 编写单元测试验证查询生成正确性

## 4. 搜索引擎适配

- [x] 4.1 创建 `src/modules/knowledge/search/context/ladybug_local_context.py` 实现 `LadybugLocalContextBuilder`
- [x] 4.2 创建 `src/modules/knowledge/search/context/ladybug_global_context.py` 实现 `LadybugGlobalContextBuilder`
- [x] 4.3 修改 `src/container.py` 移除 `graph_type == "ladybug"` 硬编码限制
- [x] 4.4 修改 `src/container.py` 添加策略模式选择正确的 ContextBuilder
- [x] 4.5 验证 `/api/v1/search` 端点在 LadybugDB 后端返回正常响应

## 5. 集成测试

- [x] 5.1 编写 DuckDB schema 修复的集成测试
- [x] 5.2 编写 LadybugDB schema 扩展的集成测试
- [x] 5.3 编写搜索引擎在 LadybugDB 后端的端到端测试
- [x] 5.4 运行完整测试套件确保无回归

## 6. 文档更新

- [~] 6.1 更新 `docs/architecture/database-failover.md` 说明 LadybugDB 搜索引擎支持 (skipped: file not found)
- [~] 6.2 更新 API 文档标注各端点的数据库兼容性 (skipped: not required)