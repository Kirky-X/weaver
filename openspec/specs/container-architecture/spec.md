## MODIFIED Requirements

### Requirement: Container Returns Protocol Types

Container 的依赖注入方法 MUST 返回 Protocol 类型而非具体实现类型：

**变更前:**
```python
def postgres_pool(self) -> RelationalPool: ...
def neo4j_pool(self) -> GraphPool | None: ...
def redis_client(self) -> RedisClient | CashewsRedisFallback: ...
def vector_repo(self) -> VectorRepo: ...
```

**变更后:**
```python
def relational_pool(self) -> RelationalPool: ...
def graph_pool(self) -> GraphPool | None: ...
def redis_client(self) -> CachePool: ...
def vector_repo(self) -> VectorRepository: ...
```

#### Scenario: redis_client returns CachePool

- **WHEN** 调用 `container.redis_client()`
- **THEN** 返回类型注解为 `CachePool`（而非 `RedisClient | CashewsRedisFallback`）

#### Scenario: vector_repo returns VectorRepository

- **WHEN** 调用 `container.vector_repo()`
- **THEN** 返回类型注解为 `VectorRepository` Protocol

### Requirement: Container Provides Type Information

Container MUST 通过属性或方法提供实际实现类型信息：

```python
@property
def relational_pool_type(self) -> str:
    """Return 'postgresql' or 'duckdb'."""
    return self._strategy.relational_type

@property
def graph_pool_type(self) -> str:
    """Return 'neo4j', 'ladybug', or 'none'."""
    return self._strategy.graph_type
```

#### Scenario: Get relational pool type

- **WHEN** 调用 `container.relational_pool_type`
- **THEN** 返回 `"postgresql"` 或 `"duckdb"` 字符串

#### Scenario: Get graph pool type

- **WHEN** 调用 `container.graph_pool_type`
- **THEN** 返回 `"neo4j"`, `"ladybug"`, 或 `"none"` 字符串

### Requirement: Container QueryBuilder Selection

Container MUST 根据数据库类型选择正确的 QueryBuilder：

```python
def vector_repo(self) -> VectorRepository:
    if self._strategy.relational_type == "duckdb":
        builder = DuckDBVectorQueryBuilder()
    else:
        builder = PgVectorQueryBuilder()
    return VectorRepo(self._strategy.relational_pool, builder)
```

#### Scenario: PostgreSQL uses PgVectorQueryBuilder

- **WHEN** `relational_pool_type` 为 `"postgresql"`
- **THEN** `vector_repo()` 使用 `PgVectorQueryBuilder`

#### Scenario: DuckDB uses DuckDBVectorQueryBuilder

- **WHEN** `relational_pool_type` 为 `"duckdb"`
- **THEN** `vector_repo()` 使用 `DuckDBVectorQueryBuilder`

### Requirement: Container Graph Repository Selection

Container MUST 根据图数据库类型选择正确的 Repository 实现：

```python
def graph_entity_repo(self) -> EntityRepository | None:
    if self._strategy.graph_type == "ladybug":
        return LadybugEntityRepo(graph_pool)
    else:
        return Neo4jEntityRepo(graph_pool)
```

#### Scenario: Neo4j uses Neo4jEntityRepo

- **WHEN** `graph_pool_type` 为 `"neo4j"`
- **THEN** `graph_entity_repo()` 返回 `Neo4jEntityRepo` 实例

#### Scenario: LadybugDB uses LadybugEntityRepo

- **WHEN** `graph_pool_type` 为 `"ladybug"`
- **THEN** `graph_entity_repo()` 返回 `LadybugEntityRepo` 实例

## ADDED Requirements

### Requirement: Deprecation of Legacy Accessors

以下遗留访问器 MUST 标记为废弃，但保持向后兼容：

- `postgres_pool()` → 使用 `relational_pool()`
- `neo4j_pool()` → 使用 `graph_pool()`

废弃方法 MUST 在文档字符串中说明迁移路径：

```python
def postgres_pool(self) -> RelationalPool:
    """Get relational pool (PostgreSQL or DuckDB fallback).

    .. deprecated:: Use relational_pool() instead.
    """
    return self.relational_pool()
```

#### Scenario: Legacy postgres_pool works

- **WHEN** 调用 `container.postgres_pool()`
- **THEN** 返回与 `container.relational_pool()` 相同的实例

#### Scenario: Legacy neo4j_pool works

- **WHEN** 调用 `container.neo4j_pool()`
- **THEN** 返回与 `container.graph_pool()` 相同的实例