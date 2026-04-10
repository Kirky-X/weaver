## Why

代码审查发现多个 P0 级别安全漏洞（SQL/Cypher注入、pickle反序列化风险）和 P1 级别架构违规问题（模块耦合、全局变量）。这些问题可能导致数据泄露、系统被接管，需要立即修复。

## What Changes

### 安全漏洞修复（P0）

- **SQL注入修复**: migration模块 `ladybug_source.py`、core模块 `graph_query.py` 改用参数化查询
- **Cypher注入修复**: migration模块 `neo4j_source.py`、knowledge模块 `local_context.py` 使用参数化查询和输入验证
- **Pickle反序列化**: `bm25_retriever.py` 改用 JSON 或签名验证机制
- **管理模块耦合**: `repair_articles.py` 通过服务层解耦，移除对pipeline内部方法的直接调用

### 架构违规修复（P1）

- **API全局变量**: `graph.py` 移除 `_pg_pool` 全局变量，改用依赖注入
- **私有属性访问**: `health.py` 通过公共接口访问容器状态
- **description字段**: `admin.py` 传递description字段到update_authority
- **后台任务追踪**: `pipeline.py` 使用TaskRegistry追踪后台任务

## Capabilities

### New Capabilities

- `query-safety`: 参数化查询和输入验证规范，覆盖SQL和Cypher查询安全
- `safe-serialization`: 安全序列化规范，替代pickle反序列化
- `api-dependency-injection`: API端点依赖注入规范，消除全局变量和私有属性访问

### Modified Capabilities

- `security-hardening`: 扩展安全审计要求，增加注入漏洞检测
- `explicit-interface-contract`: 扩展接口契约，增加服务层接口定义

## Impact

**受影响模块**:
- `src/modules/migration/adapters/` - ladybug_source.py, neo4j_source.py
- `src/modules/knowledge/search/` - bm25_retriever.py, local_context.py
- `src/modules/management/commands/` - repair_articles.py
- `src/core/db/` - graph_query.py
- `src/api/endpoints/` - graph.py, health.py, admin.py, pipeline.py

**API变更**: 无破坏性变更，内部重构

**依赖**: 无新增依赖，使用现有QueryBuilder模式和Protocol接口