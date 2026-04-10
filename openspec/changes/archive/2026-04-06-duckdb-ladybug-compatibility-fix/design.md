## Context

Weaver 采用数据库故障转移策略，优先使用外部数据库（PostgreSQL/Neo4j），失败时降级到嵌入式数据库（DuckDB/LadybugDB）。当前实现存在以下问题：

**DuckDB 问题**：
- `llm_usage_hourly` 表列名定义不一致：schema 使用 `hour_timestamp`，SQLAlchemy model 使用 `time_bucket`
- SQLAlchemy session 管理问题：DuckDB 会话关闭后尝试 lazy loading 属性

**LadybugDB 问题**：
- Schema 不完整，缺少 `Community`、`EventNode`、`CommunityReport` 表
- 搜索引擎硬编码跳过 LadybugDB（`container.py:677`）
- 查询语法差异：`TYPE()` 函数不存在，需要替代方案

**架构约束**：
- 必须保持 PostgreSQL + Neo4j 组合完全兼容
- DuckDB + LadybugDB 组合需要功能完整
- 查询层已有 `VectorQueryBuilder` 抽象模式可参考

## Goals / Non-Goals

**Goals:**
- 修复 DuckDB schema 列名，恢复 LLM 使用统计 API
- 扩展 LadybugDB schema，支持社区和时序功能
- 创建图查询抽象层，统一 Cypher 和 LadybugDB SQL
- 移除硬编码限制，让搜索引擎支持 LadybugDB

**Non-Goals:**
- 不修改 PostgreSQL 或 Neo4j 相关实现
- 不添加新的 API 端点
- 不优化查询性能（仅修复兼容性）

## Decisions

### Decision 1: DuckDB Schema 列名修复方案

**选择**: 直接修改 schema 定义，将 `hour_timestamp` 改为 `time_bucket`

**理由**:
- SQLAlchemy model 是主要数据访问层，应作为列名权威来源
- 修改 schema 比修改 model 影响范围更小
- 现有数据迁移时列名会自动适配

**替代方案**: 修改 SQLAlchemy model 列名
- 否决：model 可能在多处使用，影响范围不可控

### Decision 2: LadybugDB Schema 扩展策略

**选择**: 在现有 schema 基础上追加新表定义

**理由**:
- LadybugDB 使用 `CREATE NODE TABLE IF NOT EXISTS`，幂等安全
- 与现有 schema 风格一致
- 数据迁移模块已支持 schema 自动创建

**新增表结构**:
```
Community:
  - id STRING PRIMARY KEY
  - title STRING
  - summary STRING
  - level INT64
  - rank DOUBLE
  - created_at INT64

CommunityReport:
  - id STRING PRIMARY KEY
  - community_id STRING
  - title STRING
  - summary STRING
  - full_content STRING
  - full_content_embedding FLOAT[1024]
  - created_at INT64

EventNode:
  - id STRING PRIMARY KEY
  - event_type STRING
  - name STRING
  - description STRING
  - event_time INT64
  - created_at INT64
```

### Decision 3: 图查询抽象层设计

**选择**: 创建 `GraphQueryBuilder` 协议 + 两种实现

**理由**:
- 与现有 `VectorQueryBuilder` 模式一致
- 协议定义清晰，易于测试
- 渐进式迁移，不影响现有代码

**结构**:
```
GraphQueryBuilder (Protocol)
├── Neo4jQueryBuilder    # Cypher 实现
└── LadybugQueryBuilder  # Ladybug SQL 实现

方法:
- build_entity_search_query()
- build_relationship_query()
- build_community_query()
- build_temporal_query()
```

### Decision 4: ContextBuilder 适配方案

**选择**: 使用策略模式，根据 `graph_type` 选择实现

**理由**:
- `LocalContextBuilder` 和 `GlobalContextBuilder` 已成型
- 策略模式避免大量 if-else
- 便于单元测试

**实现**:
```python
# container.py
def local_search_engine(self) -> LocalSearchEngine | None:
    if graph_pool is None or self._llm_client is None:
        return None

    # 根据 graph_type 选择 ContextBuilder
    if self._strategy.graph_type == "ladybug":
        context_builder = LadybugLocalContextBuilder(graph_pool)
    else:
        context_builder = LocalContextBuilder(graph_pool)

    return LocalSearchEngine(graph_pool, self._llm_client, context_builder)
```

## Risks / Trade-offs

### Risk 1: LadybugDB Cypher 兼容性不完整
- **风险**: LadybugDB 支持的 Cypher 语法子集可能不足以覆盖所有查询
- **缓解**: 在 `GraphQueryBuilder` 中标记不支持的特性，fallback 到简化查询

### Risk 2: Schema 迁移数据丢失
- **风险**: 修改 DuckDB schema 可能影响已有测试数据
- **缓解**: 仅影响开发/测试环境，生产环境使用 PostgreSQL

### Risk 3: 抽象层增加复杂度
- **风险**: 新抽象层增加代码量和维护成本
- **缓解**: 仅抽象必要查询，不过度设计；复用 `VectorQueryBuilder` 模式

### Trade-off: 社区报告向量搜索
- **取舍**: LadybugDB 不支持向量索引，社区报告的向量搜索将使用全表扫描
- **接受理由**: LadybugDB 用于开发/测试，性能要求较低

## Migration Plan

### Phase 1: Schema 修复（低风险）
1. 修改 `src/modules/storage/duckdb/schema.py` 列名
2. 扩展 `src/modules/storage/ladybug/schema.py` 新表
3. 删除已有 DuckDB/LadybugDB 数据文件
4. 重启服务自动重建 schema

### Phase 2: 查询抽象层（中风险）
1. 创建 `src/core/db/graph_query.py` 抽象协议
2. 实现 `Neo4jQueryBuilder` 和 `LadybugQueryBuilder`
3. 编写单元测试验证查询等价性

### Phase 3: 搜索引擎适配（中风险）
1. 创建 `LadybugLocalContextBuilder` 实现
2. 修改 `container.py` 策略选择逻辑
3. 移除硬编码 `graph_type == "ladybug"` 检查
4. 集成测试验证端到端流程

### Rollback
- Schema 修改通过 git revert 即可回滚
- 抽象层代码独立文件，删除不影响现有功能