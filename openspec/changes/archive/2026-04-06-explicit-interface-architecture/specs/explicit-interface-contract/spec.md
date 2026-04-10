## ADDED Requirements

### Requirement: Protocol Central Location

所有 Protocol 定义 MUST 集中在 `src/core/protocols/` 目录下：

```
src/core/protocols/
├── __init__.py        # 重导出所有 Protocol
├── pools.py           # RelationalPool, GraphPool, CachePool
├── repositories.py    # EntityRepository, ArticleRepository, VectorRepository
└── validation.py      # 接口验证工具函数
```

#### Scenario: Protocol import from central location

- **WHEN** 需要使用任何 Protocol
- **THEN** 可以通过 `from core.protocols import <ProtocolName>` 导入

#### Scenario: No duplicate Protocol definitions

- **WHEN** 搜索代码库中的 Protocol 定义
- **THEN** `src/modules/memory/graphs/base.py` 中不存在 `Neo4jPoolProtocol`
- **AND** `src/modules/memory/evolution/queue.py` 中不存在 `RedisClientProtocol`

### Requirement: Explicit Implementation Declaration

所有 Protocol 实现类 MUST 在其文档字符串中显式声明实现的 Protocol：

```python
class PostgresPool:
    """PostgreSQL connection pool.

    Implements:
        - RelationalPool: Async SQL database pool with session management
    """
```

#### Scenario: PostgresPool has explicit declaration

- **WHEN** 查看 `PostgresPool` 类的文档字符串
- **THEN** 文档字符串包含 "Implements:" 部分并声明 `RelationalPool`

#### Scenario: DuckDBPool has explicit declaration

- **WHEN** 查看 `DuckDBPool` 类的文档字符串
- **THEN** 文档字符串包含 "Implements:" 部分并声明 `RelationalPool`

#### Scenario: Neo4jPool has explicit declaration

- **WHEN** 查看 `Neo4jPool` 类的文档字符串
- **THEN** 文档字符串包含 "Implements:" 部分并声明 `GraphPool`

#### Scenario: LadybugPool has explicit declaration

- **WHEN** 查看 `LadybugPool` 类的文档字符串
- **THEN** 文档字符串包含 "Implements:" 部分并声明 `GraphPool`

### Requirement: Repository Constructor Protocol Types

所有 Repository 构造函数 MUST 使用 Protocol 类型作为参数类型，而非具体实现类：

```python
# ✅ 正确
class VectorRepo:
    def __init__(self, pool: RelationalPool) -> None: ...

# ❌ 错误
class VectorRepo:
    def __init__(self, pool: PostgresPool) -> None: ...
```

#### Scenario: VectorRepo uses RelationalPool type

- **WHEN** 查看 `VectorRepo.__init__` 方法的类型注解
- **THEN** `pool` 参数类型为 `RelationalPool`（而非 `PostgresPool`）

#### Scenario: Neo4jEntityRepo uses GraphPool type

- **WHEN** 查看 `Neo4jEntityRepo.__init__` 方法的类型注解
- **THEN** `pool` 参数类型为 `GraphPool`（而非 `Neo4jPool`）

#### Scenario: ArticleRepo uses RelationalPool type

- **WHEN** 查看 `ArticleRepo.__init__` 方法的类型注解
- **THEN** `pool` 参数类型为 `RelationalPool`

### Requirement: Runtime Protocol Validation

系统 SHALL 提供运行时 Protocol 验证工具函数：

```python
# src/core/protocols/validation.py
def assert_implements(obj: Any, protocol: type) -> None:
    """Assert that obj implements the given protocol.

    Raises:
        TypeError: If obj does not implement all required methods.
    """
```

#### Scenario: Validation passes for correct implementation

- **WHEN** 调用 `assert_implements(PostgresPool(), RelationalPool)`
- **THEN** 不抛出异常

#### Scenario: Validation fails for missing method

- **WHEN** 一个类缺少 Protocol 要求的方法
- **THEN** `assert_implements()` 抛出 `TypeError` 并指出缺失的方法

### Requirement: Remove Scattered Protocol Definitions

以下分散的 Protocol 定义 MUST 被移除并替换为中心化导入：

| 原位置 | 原名称 | 替换为 |
|--------|--------|--------|
| `src/modules/memory/graphs/base.py` | `Neo4jPoolProtocol` | `from core.protocols import GraphPool` |
| `src/modules/memory/evolution/queue.py` | `RedisClientProtocol` | `from core.protocols import CachePool` |
| `src/modules/memory/evolution/fast_path.py` | `VectorRepoProtocol` | `from core.protocols import VectorRepository` |

#### Scenario: Neo4jPoolProtocol removed

- **WHEN** 查看 `src/modules/memory/graphs/base.py`
- **THEN** 文件不存在 `Neo4jPoolProtocol` 类定义

#### Scenario: RedisClientProtocol removed

- **WHEN** 查看 `src/modules/memory/evolution/queue.py`
- **THEN** 文件不存在 `RedisClientProtocol` 类定义

### Requirement: Protocol Naming Convention

Protocol 命名 MUST 遵循以下规范：

- Pool 类 Protocol：`<Category>Pool`（如 `RelationalPool`, `GraphPool`, `CachePool`）
- Repository 类 Protocol：`<Entity>Repository`（如 `EntityRepository`, `ArticleRepository`）
- 不使用 `Protocol` 后缀（如 `CacheProtocol` 是错误的）

#### Scenario: Pool naming convention

- **WHEN** 检查 Pool Protocol 命名
- **THEN** 所有名称以 `Pool` 结尾（而非 `Protocol`）