## Why

当前项目的数据库访问架构存在"半面向接口"问题：虽然定义了 Protocol 接口，但实现类未显式声明关系、Repository 构造函数硬编码具体类型、缓存层完全缺少 Protocol、数据库特定语法散落在多个 Repository 实现中。这导致：

1. **类型安全缺失**：IDE 无法推断接口关系，静态检查无法捕获不兼容实现
2. **代码重复严重**：`VectorRepo` 和 `DuckDBVectorRepo` 有 ~80% 代码相似（~1000 行重复）
3. **扩展困难**：新增数据库后端需要修改多处硬编码类型
4. **维护负担**：Protocol 定义分散在 4 个位置，存在重复和不一致

## What Changes

### 新增

- **CachePool Protocol**：为 Redis/Cashews 定义统一缓存接口
- **VectorQueryBuilder 抽象层**：封装 PostgreSQL pgvector 和 DuckDB 向量查询差异
- **ExplicitInterfaceMixin**：提供运行时接口验证的工具类
- **统一 Protocol 目录结构**：将所有 Protocol 定义集中到 `src/core/protocols/`

### 修改

- **Pool 实现类**：添加显式 Protocol 实现声明和类型注解
- **Repository 构造函数**：改为依赖 Protocol 类型而非具体实现类
- **Container 返回类型**：从具体类型改为 Protocol 类型
- **消除重复 Repository**：合并 `VectorRepo` 和 `DuckDBVectorRepo` 为单一实现

### 移除

- **分散的 Protocol 定义**：删除 `modules/memory/` 下的重复 Protocol
- **DuckDBVectorRepo**：合并到统一的 VectorRepo

### **BREAKING** 变更

- `Container.vector_repo()` 返回类型从 `VectorRepo` 改为 `VectorRepository` Protocol
- `Container.redis_client()` 返回类型从联合类型改为 `CachePool` Protocol
- Repository 构造函数签名变更（参数类型从具体类改为 Protocol）

## Capabilities

### New Capabilities

- `cache-pool-protocol`: 统一缓存接口定义，支持 Redis/Cashews/Memcached 等多种后端
- `query-builder-pattern`: 数据库查询构造器模式，封装数据库特定语法差异
- `explicit-interface-contract`: 接口显式声明规范，强制实现类声明其实现的 Protocol

### Modified Capabilities

- `container-architecture`: Container 的依赖注入返回类型改为 Protocol 类型，实现真正的数据库无关性

## Impact

### 代码变更范围

| 文件/目录 | 变更类型 | 影响行数 |
|-----------|----------|----------|
| `src/core/protocols/` | 新增/重构 | ~300 行 |
| `src/core/cache/` | 修改 | ~50 行 |
| `src/core/db/pool_protocols.py` | 修改 | ~30 行 |
| `src/core/db/query_builders.py` | 新增 | ~200 行 |
| `src/modules/storage/postgres/vector_repo.py` | 重构 | ~400 行 |
| `src/modules/storage/duckdb/vector_repo.py` | 删除 | -438 行 |
| `src/modules/storage/*/entity_repo.py` | 修改 | ~20 行 |
| `src/container.py` | 修改 | ~100 行 |
| `src/modules/memory/` | 删除重复 Protocol | ~50 行 |

### API 兼容性

- 外部 API 无变更（HTTP 端点保持不变）
- 内部 API 变更：Repository 构造函数签名
- 类型注解变更：不影响运行时行为

### 依赖影响

- 无新增外部依赖
- 内部模块依赖关系简化

### 测试影响

- 需新增 Protocol 实现验证测试
- 需新增 QueryBuilder 单元测试
- 现有测试无需修改（接口不变）