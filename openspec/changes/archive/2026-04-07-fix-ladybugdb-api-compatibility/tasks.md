# Implementation Tasks

## 1. Type Annotation Fixes

- [x] 1.1 修改 `src/api/endpoints/graph.py` 中的 `_pg_pool` 类型注解为 `RelationalPool | None`
- [x] 1.2 重命名 `set_postgres_pool` 为 `set_relational_pool`，参数类型改为 `RelationalPool`
- [x] 1.3 更新 `src/main.py` 中的调用：`set_graph_postgres_pool` → `set_graph_relational_pool`
- [x] 1.4 更新 `graph_relation_types` 端点使用 `_relational_pool` 变量

## 2. DRIFT Endpoint Dependency Injection

- [x] 2.1 修改 `src/api/endpoints/search.py` 中 `search_drift` 函数
- [x] 2.2 替换 `global_engine._pool` 为 `deps.Endpoints.get_neo4j_pool()`
- [x] 2.3 替换 `global_engine._llm` 为 `deps.Endpoints.get_llm()`
- [x] 2.4 确保 DRIFTSearchEngine 使用正确的 pool 和 llm 参数初始化

## 3. LadybugDB Schema Extension

- [x] 3.1 更新 `src/modules/storage/ladybug/schema.py` 中 Community 表定义
- [x] 3.2 添加 `parent_id STRING` 字段到 Community 节点表
- [x] 3.3 更新 EventNode 表定义：`description` → `content`，`event_time` → `timestamp`
- [x] 3.4 添加 `attributes STRING` 字段到 EventNode 节点表
- [x] 3.5 验证 schema 初始化成功

## 4. LadybugEntityRepo Implementation

- [x] 4.1 创建 `src/modules/storage/ladybug/entity_repo.py` 文件
- [x] 4.2 实现 `LadybugEntityRepo` 类，声明实现 EntityRepository Protocol
- [x] 4.3 实现 `get_relation_types` 方法，使用 `r.edge_type` 语法
- [x] 4.4 实现 `find_by_relation_types` 方法
- [x] 4.5 实现 `merge_entity` 方法（如需要）
- [x] 4.6 实现 `find_entity` 方法（如需要）

## 5. EntityRepo Factory Integration

- [x] 5.1 在 `src/api/endpoints/_deps.py` 添加 `get_entity_repo` 静态方法
- [x] 5.2 根据图数据库类型返回正确的 EntityRepo 实现
- [x] 5.3 更新 `graph.py` 端点使用 `deps.Endpoints.get_entity_repo()`
- [x] 5.4 更新 `graph_relations` 端点使用工厂方法
- [x] 5.5 更新 `graph_relations_search` 端点使用工厂方法

## 6. TemporalGraphRepo Query Fix

- [x] 6.1 修改 `src/modules/memory/graphs/temporal.py` 中的查询
- [x] 6.2 更新 `get_temporal_chain` 查询使用 `content` 和 `timestamp` 属性
- [x] 6.3 确保 `append_to_chain` 方法使用正确的属性名
- [x] 6.4 验证 LadybugDB 模式下 temporal 查询正常工作

## 7. Verification

- [x] 7.1 运行 `temp/test_all_apis.py` 验证所有端点返回 200
- [x] 7.2 确认 `graph_relation_types` 端点正常工作
- [x] 7.3 确认 `graph_relations` 端点正常工作
- [x] 7.4 确认 `graph_relations_search` 端点正常工作
- [x] 7.5 确认 `communities_list` 端点正常工作
- [x] 7.6 确认 `search_drift` 端点正常工作
- [x] 7.7 确认 `search_temporal` 端点正常工作
- [x] 7.8 验证 Neo4j/PostgreSQL 模式仍然正常工作（如环境可用）

## 8. Embedding Model Name Fix

- [x] 8.1 修复 `src/api/endpoints/search.py` 中的 embedding 模型名称
- [x] 8.2 修复 `src/modules/knowledge/search/context/ladybug_global_context.py` 中的 embedding 模型名称
- [x] 8.3 修复 `src/modules/knowledge/search/context/global_context.py` 中的 embedding 模型名称
- [x] 8.4 修复 `src/modules/knowledge/graph/community_report_generator.py` 中的 embedding 模型名称
- [x] 8.5 修复 `src/config/settings.py` 中的 `embedding_provider` 和 `rerank_provider` 设置

## 修复摘要

### 已修复的 500 错误
- `graph_relations` → 200 ✓
- `graph_relations_search` → 200 ✓
- `graph_relation_types` → 200 ✓
- `communities_list` → 200 ✓
- `search_drift` → 200 ✓
- `search_temporal` → 200 ✓
- `health` → 200 ✓ (测试脚本路径修复)
- `search_articles` → 200 ✓ (embedding 模型名称修复)

### 关键修改
1. **Protocol 类型注解**: `PostgresPool` → `RelationalPool`
2. **依赖注入**: `search_drift` 使用 `get_neo4j_pool()` 和 `get_llm()`
3. **LadybugDB Schema**: 添加 `parent_id`, `entity_count`, `period`, `modularity` 字段
4. **LadybugEntityRepo**: 使用 `r.edge_type` 语法，移除 `pruned` 过滤
5. **EntityRepo Factory**: `get_entity_repo()` 返回正确的实现
6. **SQL GROUP BY**: 添加所有非聚合列到 GROUP BY 子句（DuckDB 要求）
7. **测试脚本**: `health` 端点使用根路径而非 `/api/v1`
8. **Embedding 模型名称**: `aiping_embedding` → `aiping`（与 llm.toml 配置一致）