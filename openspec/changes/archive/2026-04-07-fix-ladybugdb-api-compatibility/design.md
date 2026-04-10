## Context

项目使用 Protocol 抽象层实现数据库故障转移：
- **PostgreSQL → DuckDB** (关系型数据库)
- **Neo4j → LadybugDB** (图数据库)

当前状态：`src/container.py` 已正确检测数据库可用性并选择对应实现，但部分代码绕过 Protocol 层直接依赖具体实现类，导致 DuckDB+LadybugDB 模式下 7 个 API 端点返回 500 错误。

### 架构约束

```
┌─────────────────────────────────────────────────────────────────┐
│                      API Endpoints                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ 应该依赖 Protocol
┌─────────────────────────────────────────────────────────────────┐
│  Protocol Layer                                                  │
│  ┌──────────────┐  ┌──────────┐  ┌──────────────┐               │
│  │RelationalPool│  │GraphPool │  │EntityRepo    │               │
│  └──────────────┘  └──────────┘  └──────────────┘               │
└─────────────────────────────────────────────────────────────────┘
            │                    │                    │
            ▼                    ▼                    ▼
┌───────────────────┐  ┌───────────────────┐  ┌───────────────────┐
│   PostgreSQL      │  │     Neo4j         │  │ Neo4jEntityRepo   │
│   DuckDB          │  │   LadybugDB       │  │ LadybugEntityRepo │
└───────────────────┘  └───────────────────┘  └───────────────────┘
```

## Goals / Non-Goals

**Goals:**
- 修复所有 500 错误，确保 DuckDB+LadybugDB 模式完全可用
- 保持 Neo4j/PostgreSQL 模式兼容性
- 遵循现有 Protocol 抽象模式
- 最小化代码变更范围

**Non-Goals:**
- 不重构整体架构
- 不添加新功能
- 不优化性能

## Decisions

### D1: graph.py 类型修复

**问题**: `_pg_pool: PostgresPool | None` 限制只能接受 PostgresPool

**方案**: 使用 Protocol 类型

```python
# 修改前
from core.db.postgres import PostgresPool
_pg_pool: PostgresPool | None = None

def set_postgres_pool(pool: PostgresPool) -> None:
    global _pg_pool
    _pg_pool = pool

# 修改后
from core.protocols import RelationalPool
_relational_pool: RelationalPool | None = None

def set_relational_pool(pool: RelationalPool) -> None:
    global _relational_pool
    _relational_pool = pool
```

**替代方案**: 使用 `Any` 类型 — 放弃类型安全，不推荐

### D2: DRIFT 端点依赖注入

**问题**: `search.py:476-478` 直接访问 `global_engine._pool`

**方案**: 从依赖注入获取

```python
# 修改前
pool = global_engine._pool  # ❌ LadybugDB 模式下不存在
llm = global_engine._llm

# 修改后
from api.endpoints import _deps as deps
pool = deps.Endpoints.get_neo4j_pool()
llm = deps.Endpoints.get_llm()
```

**替代方案**: 在 GlobalSearchEngine 中添加 getter 方法 — 增加复杂度

### D3: LadybugDB Schema 扩展

**问题**: Community 缺少 `parent_id`，EventNode 属性名不匹配

**方案 A (选择)**: 统一属性命名，修改 Schema

```python
# ladybug/schema.py - Community
CREATE NODE TABLE IF NOT EXISTS Community (
    id STRING PRIMARY KEY,
    title STRING,
    summary STRING,
    level INT64,
    rank DOUBLE,
    parent_id STRING,  # 新增
    created_at INT64
)

# ladybug/schema.py - EventNode
CREATE NODE TABLE IF NOT EXISTS EventNode (
    id STRING PRIMARY KEY,
    event_type STRING,
    name STRING,
    content STRING,        # description → content
    timestamp INT64,       # event_time → timestamp
    attributes STRING,     # 新增 (JSON)
    created_at INT64
)
```

**方案 B**: 创建适配层转换属性名 — 增加运行时开销

**选择**: 方案 A，保持一致性

### D4: LadybugEntityRepo 实现

**问题**: `Neo4jEntityRepo` 使用 `type(r)` 函数，LadybugDB 不支持

**方案**: 创建 `LadybugEntityRepo` 实现

```python
# src/modules/storage/ladybug/entity_repo.py
class LadybugEntityRepo:
    """LadybugDB entity repository.

    Implements: EntityRepository
    """

    async def get_relation_types(
        self,
        canonical_name: str,
        entity_type: str,
    ) -> list[dict[str, Any]]:
        """Layer 1: Discover all relation types."""
        query = """
        MATCH (e:Entity {canonical_name: $name, type: $type})-[r:RELATED_TO]-(other:Entity)
        WHERE r.edge_type <> 'MENTIONS' AND r.edge_type <> 'FOLLOWED_BY'
          AND NOT other.pruned = true
        RETURN r.edge_type AS relation_type,  -- LadybugDB 语法
               count(DISTINCT other) AS target_count
        ORDER BY target_count DESC
        """
```

**替代方案**: 在 GraphQueryBuilder 中抽象关系类型查询 — 已有部分支持

**选择**: 两者结合，GraphQueryBuilder 扩展 + LadybugEntityRepo

### D5: 工厂模式选择 Repo

**问题**: 端点需要根据数据库类型选择正确的 Repo

**方案**: 在 container 或 _deps 中提供工厂

```python
# api/endpoints/_deps.py
@staticmethod
def get_entity_repo() -> EntityRepository:
    """Get entity repo based on current graph database type."""
    pool = Endpoints.get_neo4j_pool()
    if isinstance(pool, LadybugPool):
        from modules.storage.ladybug.entity_repo import LadybugEntityRepo
        return LadybugEntityRepo(pool)
    else:
        from modules.storage.neo4j.entity_repo import Neo4jEntityRepo
        return Neo4jEntityRepo(pool)
```

## Risks / Trade-offs

| 风险 | 缓解措施 |
|------|----------|
| Schema 变更需要数据迁移 | 新字段为可选，旧数据兼容 |
| LadybugEntityRepo 测试覆盖 | 复用 Neo4jEntityRepo 测试用例 |
| 双模式维护成本 | 统一使用 GraphQueryBuilder 抽象 |
| DRIFT 功能依赖图数据库 | 降级处理，返回明确错误 |

## Migration Plan

1. **Phase 1: 代码修复** (无数据影响)
   - 修复类型注解
   - 修复依赖注入
   - 创建 LadybugEntityRepo

2. **Phase 2: Schema 更新**
   - 添加 `Community.parent_id`
   - 重命名 `EventNode` 属性
   - 重新初始化 schema

3. **Phase 3: 验证**
   - 运行 API 测试
   - 验证所有端点返回 200

### 回滚策略

- 代码变更：Git revert
- Schema 变更：删除新字段不影响功能

## Open Questions

1. ~~是否需要支持 Neo4j 和 LadybugDB 同时运行？~~ **已决定**: 单一模式，故障转移
2. EventNode 现有数据是否需要迁移？**待定**: 检查生产数据量