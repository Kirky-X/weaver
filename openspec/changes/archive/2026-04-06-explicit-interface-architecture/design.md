## Context

### 当前架构问题

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        当前架构问题诊断                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  问题 1: 隐式接口实现                                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Protocol: RelationalPool    ←── 定义了接口                          │   │
│  │       ↓                                                             │   │
│  │  class PostgresPool:         ←── 无显式继承声明                      │   │
│  │      def __init__(self, pool: PostgresPool)  ←── 硬编码具体类型      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  问题 2: Protocol 定义分散                                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  src/core/db/pool_protocols.py      → GraphPool, RelationalPool     │   │
│  │  src/core/protocols/__init__.py     → EntityRepository, VectorRepo  │   │
│  │  src/modules/memory/graphs/base.py  → Neo4jPoolProtocol (重复!)     │   │
│  │  src/modules/memory/evolution/queue.py → RedisClientProtocol (局部) │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  问题 3: Repository 代码重复                                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  VectorRepo (601 行)        vs   DuckDBVectorRepo (438 行)          │   │
│  │  - find_similar() 逻辑相同，仅 SQL 语法不同                          │   │
│  │  - find_similar_entities() 逻辑相同                                  │   │
│  │  - upsert_*() 逻辑相同                                               │   │
│  │  重复代码 ~80%                                                        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  问题 4: 缓存层无 Protocol                                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  def redis_client() -> RedisClient | CashewsRedisFallback           │   │
│  │                          ↑ 联合类型，非接口                          │   │
│  │  新增 Memcached 后端需要修改所有调用点                                │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 约束条件

- **向后兼容**：外部 API 不能变更
- **无运行时开销**：Protocol 验证仅在类型检查时生效
- **渐进式迁移**：可以分模块实施
- **测试连续性**：现有测试必须继续通过

## Goals / Non-Goals

**Goals:**

1. **显式接口声明**：所有实现类必须显式声明其实现的 Protocol
2. **统一 Protocol 定义**：将所有 Protocol 集中到 `src/core/protocols/`
3. **消除 Repository 重复**：通过 QueryBuilder 模式合并重复实现
4. **添加 CachePool Protocol**：为缓存层定义统一接口
5. **Container 类型清晰化**：返回类型统一使用 Protocol

**Non-Goals:**

- 不修改外部 HTTP API
- 不引入新的外部依赖
- 不重构图数据库 Repository（Neo4j/LadybugDB 语法差异太大，保持分离）
- 不修改数据库连接池的核心逻辑

## Decisions

### 决策 1: Protocol 组织结构

**选择**: 将所有 Protocol 集中到 `src/core/protocols/` 目录，按功能分层

**结构**:
```
src/core/protocols/
├── __init__.py           # 重导出所有 Protocol
├── pools.py              # RelationalPool, GraphPool, CachePool
├── repositories.py       # EntityRepository, ArticleRepository, VectorRepository
└── validation.py         # 接口验证工具函数
```

**替代方案**: 保持现状，每个模块定义自己的 Protocol
- **拒绝原因**: 导致重复定义和命名冲突

### 决策 2: 显式接口声明方式

**选择**: 使用文档字符串 + 类型注解 + 运行时验证工具函数

```python
class PostgresPool:
    """PostgreSQL connection pool.

    Implements:
        - RelationalPool: SQL database pool protocol
        - Supports startup/shutdown lifecycle
    """

    async def startup(self) -> None: ...
```

**验证工具**:
```python
# src/core/protocols/validation.py
def validate_implements(cls: type, protocol: type) -> bool:
    """Runtime check that cls implements all protocol methods."""
    if not issubclass(cls, protocol):
        return False
    # Check all required methods exist and have correct signatures
    ...
```

**替代方案 A**: 使用 ABC 抽象基类
- **拒绝原因**: Protocol 更灵活，支持结构化子类型

**替代方案 B**: 仅依赖静态类型检查
- **拒绝原因**: 无运行时保障，CI 中可能被绕过

### 决策 3: QueryBuilder 模式设计

**选择**: 为向量查询创建抽象 QueryBuilder，其他 Repository 保持原样

```python
# src/core/db/query_builders.py
class VectorQueryBuilder(ABC):
    @abstractmethod
    def build_find_similar(
        self, embedding: list[float], ...
    ) -> SimilarityQuery: ...

    @abstractmethod
    def build_find_similar_entities(
        self, embedding: list[float], ...
    ) -> SimilarityQuery: ...

class PgVectorQueryBuilder(VectorQueryBuilder):
    def build_find_similar(self, ...):
        return SimilarityQuery(
            query="SELECT ... 1 - (embedding <=> ...) as similarity",
            params={...}
        )

class DuckDBVectorQueryBuilder(VectorQueryBuilder):
    def build_find_similar(self, ...):
        return SimilarityQuery(
            query="SELECT ... array_cosine_similarity(...) as similarity",
            params={...}
        )
```

**统一 Repository**:
```python
class VectorRepo:
    """Unified vector repository using query builder pattern."""

    def __init__(
        self,
        pool: RelationalPool,  # ← 接口类型
        query_builder: VectorQueryBuilder,
    ) -> None:
        self._pool = pool
        self._query_builder = query_builder
```

**替代方案**: 使用 SQL 方言抽象层
- **拒绝原因**: 过度设计，只有向量查询有显著差异

### 决策 4: CachePool Protocol 设计

**选择**: 定义完整缓存操作接口

```python
@runtime_checkable
class CachePool(Protocol):
    """Protocol for cache implementations."""

    # 生命周期
    async def startup(self) -> None: ...
    async def shutdown(self) -> None: ...
    async def ping(self) -> bool: ...

    # Key/Value
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ex: int | None = None) -> None: ...
    async def delete(self, *keys: str) -> int: ...

    # Hash
    async def hget(self, name: str, key: str) -> str | None: ...
    async def hset(self, name: str, key: str, value: str) -> None: ...

    # List
    async def lpush(self, name: str, *values: str) -> int: ...
    async def rpop(self, name: str) -> str | None: ...

    # Sorted Set
    async def zadd(self, name: str, mapping: dict[str, float]) -> int: ...
    async def zrangebyscore(...) -> list[str]: ...
```

**替代方案**: 仅定义最小接口
- **拒绝原因**: 当前代码已使用这些方法，需要完整接口

### 决策 5: Container 返回类型策略

**选择**: 返回 Protocol 类型，通过属性暴露具体类型信息

```python
class Container:
    def relational_pool(self) -> RelationalPool:
        """Get relational database pool."""
        return self._strategy.relational_pool

    @property
    def relational_pool_type(self) -> str:
        """Get the actual pool type: 'postgresql' or 'duckdb'."""
        return self._strategy.relational_type

    def redis_client(self) -> CachePool:  # ← 返回 Protocol
        """Get cache client."""
        ...
```

**替代方案**: 使用泛型
- **拒绝原因**: 增加复杂度，当前需求不需要

## Risks / Trade-offs

### 风险 1: 类型检查覆盖率不足

**风险**: 如果项目中部分文件缺少类型注解，静态检查可能无法捕获所有问题

**缓解措施**:
- 在 CI 中强制运行 `mypy --strict`
- 添加运行时 Protocol 验证测试

### 风险 2: QueryBuilder 模式增加复杂度

**风险**: 对于简单查询可能显得过度设计

**缓解措施**:
- 仅对有明显差异的操作使用 QueryBuilder
- 纯 ORM 操作的 Repository（如 ArticleRepo）保持原样

### 风险 3: 迁移期间类型不兼容

**风险**: 修改构造函数签名可能导致现有调用代码报错

**缓解措施**:
- 保持向后兼容的别名方法
- 分阶段迁移，每个阶段独立验证

### 风险 4: 图数据库 Repository 无法合并

**风险**: Neo4j 和 LadybugDB 的 Cypher 语法差异太大

**缓解措施**:
- 保持分离实现
- 统一 Protocol 接口确保兼容性
- 通过 Container 动态选择实现

## Migration Plan

### 阶段 1: Protocol 整合（低风险）

1. 创建 `src/core/protocols/` 目录结构
2. 迁移现有 Protocol 定义
3. 删除重复定义
4. 更新导入路径

### 阶段 2: 添加 CachePool（低风险）

1. 定义 CachePool Protocol
2. 为 RedisClient 和 CashewsRedisFallback 添加实现声明
3. 修改 Container 返回类型

### 阶段 3: QueryBuilder 实现（中风险）

1. 创建 VectorQueryBuilder 抽象类
2. 实现 PgVectorQueryBuilder 和 DuckDBVectorQueryBuilder
3. 创建统一的 VectorRepo
4. 删除 DuckDBVectorRepo
5. 更新 Container 组装逻辑

### 阶段 4: 显式声明和类型修复（中风险）

1. 为所有 Pool 实现类添加 Protocol 实现声明
2. 修改 Repository 构造函数参数类型
3. 添加运行时验证测试

### 回滚策略

每个阶段独立提交，可通过 git revert 回滚。保留旧 API 别名 2 个版本后移除。

## Open Questions

1. **是否需要为 LadybugDB 创建单独的 QueryBuilder？**
   - 当前决策：不需要，LadybugDB 与 Neo4j 语法差异太大，保持分离实现

2. **Protocol 验证应该放在哪个阶段？**
   - 建议：阶段 4，在所有类型修复后添加

3. **是否需要更新 CLAUDE.md 中的接口规范？**
   - 建议：是，添加显式接口声明要求到编码规范