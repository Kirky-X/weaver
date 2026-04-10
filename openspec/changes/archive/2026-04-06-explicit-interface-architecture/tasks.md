## 1. Protocol 目录结构重组

- [x] 1.1 创建 `src/core/protocols/` 目录结构（`__init__.py`, `pools.py`, `repositories.py`, `validation.py`）
- [x] 1.2 将 `src/core/db/pool_protocols.py` 中的 `RelationalPool` 和 `GraphPool` 迁移到 `pools.py`
- [x] 1.3 将 `src/core/protocols/__init__.py` 中的 Repository Protocol 迁移到 `repositories.py`
- [x] 1.4 更新 `src/core/protocols/__init__.py` 为重导出文件
- [x] 1.5 更新所有导入路径，使用 `from core.protocols import ...`
- [x] 1.6 删除旧的 `src/core/db/pool_protocols.py` 文件

## 2. 删除分散的 Protocol 定义

- [x] 2.1 删除 `src/modules/memory/graphs/base.py` 中的 `Neo4jPoolProtocol`，改用 `GraphPool`
- [x] 2.2 删除 `src/modules/memory/evolution/queue.py` 中的 `RedisClientProtocol`，改用 `CachePool`
- [x] 2.3 删除 `src/modules/memory/evolution/fast_path.py` 中的 `VectorRepoProtocol`，改用 `VectorRepository`
- [x] 2.4 更新所有引用这些分散 Protocol 的导入语句

## 3. 添加 CachePool Protocol

- [x] 3.1 在 `src/core/protocols/pools.py` 中定义 `CachePool` Protocol
- [x] 3.2 为 `RedisClient` 添加显式实现声明（文档字符串）
- [x] 3.3 为 `CashewsRedisFallback` 添加显式实现声明（文档字符串）
- [x] 3.4 验证两个实现类都满足 `CachePool` Protocol（运行时检查）

## 4. 实现 QueryBuilder 模式

- [x] 4.1 创建 `src/core/db/query_builders.py` 文件
- [x] 4.2 定义 `SimilarityQuery` 数据类
- [x] 4.3 定义 `VectorQueryBuilder` 抽象基类
- [x] 4.4 实现 `PgVectorQueryBuilder` 类
- [x] 4.5 实现 `DuckDBVectorQueryBuilder` 类
- [x] 4.6 编写 QueryBuilder 单元测试

## 5. 重构 VectorRepo

- [x] 5.1 修改 `VectorRepo.__init__` 接受 `RelationalPool` 和 `VectorQueryBuilder`
- [x] 5.2 重构 `find_similar` 使用 QueryBuilder
- [x] 5.3 重构 `find_similar_entities` 使用 QueryBuilder
- [x] 5.4 重构 `upsert_article_vectors` 使用 QueryBuilder
- [x] 5.5 重构 `bulk_upsert_article_vectors` 使用 QueryBuilder
- [x] 5.6 重构其他向量操作方法
- [x] 5.7 删除 `src/modules/storage/duckdb/vector_repo.py`
- [x] 5.8 更新 `src/modules/storage/duckdb/__init__.py` 移除 `DuckDBVectorRepo` 导出

## 6. 显式接口声明

- [x] 6.1 为 `PostgresPool` 添加显式实现声明
- [x] 6.2 为 `DuckDBPool` 添加显式实现声明
- [x] 6.3 为 `Neo4jPool` 添加显式实现声明
- [x] 6.4 为 `LadybugPool` 添加显式实现声明
- [x] 6.5 为 `Neo4jEntityRepo` 添加显式实现声明
- [x] 6.6 为 `LadybugEntityRepo` 添加显式实现声明
- [x] 6.7 为 `ArticleRepo` 添加显式实现声明
- [x] 6.8 为 `VectorRepo` 添加显式实现声明

## 7. Repository 构造函数类型修复

- [x] 7.1 修改 `VectorRepo.__init__` 参数类型为 `RelationalPool`
- [x] 7.2 修改 `ArticleRepo.__init__` 参数类型为 `RelationalPool`
- [x] 7.3 修改 `Neo4jEntityRepo.__init__` 参数类型为 `GraphPool`
- [x] 7.4 修改 `LadybugEntityRepo.__init__` 参数类型为 `GraphPool`
- [x] 7.5 修改其他 Repository 构造函数参数类型

## 8. Container 返回类型修复

- [x] 8.1 修改 `redis_client()` 返回类型为 `CachePool`
- [x] 8.2 修改 `vector_repo()` 返回类型为 `VectorRepository`
- [x] 8.3 确保 `relational_pool()` 返回类型为 `RelationalPool`
- [x] 8.4 确保 `graph_pool()` 返回类型为 `GraphPool | None`
- [x] 8.5 确保 `graph_entity_repo()` 返回类型为 `EntityRepository | None`
- [x] 8.6 更新 `vector_repo()` 实现，根据数据库类型选择 QueryBuilder
- [x] 8.7 为遗留访问器添加废弃警告（`postgres_pool`, `neo4j_pool`）

## 9. 添加运行时验证

- [x] 9.1 在 `src/core/protocols/validation.py` 中实现 `assert_implements` 函数
- [x] 9.2 添加 Protocol 验证单元测试
- [x] 9.3 在测试启动时验证所有实现类满足其声明的 Protocol

## 10. 测试和验证

- [x] 10.1 运行现有测试确保无回归
- [x] 10.2 添加 QueryBuilder 单元测试
- [x] 10.3 添加 Protocol 实现验证测试
- [x] 10.4 运行 `mypy --strict` 检查类型正确性
- [x] 10.5 验证 IDE 类型推断正常工作

## 11. 文档更新

- [x] 11.1 更新 `CLAUDE.md` 添加显式接口声明要求
- [x] 11.2 更新 `src/core/protocols/README.md`（如存在）或创建新文档
- [x] 11.3 更新相关模块的文档字符串