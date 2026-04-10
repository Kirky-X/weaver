## ADDED Requirements

### Requirement: VectorQueryBuilder Abstract Class

系统 SHALL 定义 `VectorQueryBuilder` 抽象基类，封装不同数据库的向量查询语法差异。

`VectorQueryBuilder` MUST 定义以下抽象方法：

```python
class VectorQueryBuilder(ABC):
    @abstractmethod
    def build_find_similar(
        self,
        embedding: list[float],
        category: str | None,
        threshold: float,
        limit: int,
        model_id: str | None,
    ) -> SimilarityQuery: ...

    @abstractmethod
    def build_find_similar_entities(
        self,
        embedding: list[float],
        threshold: float,
        limit: int,
    ) -> SimilarityQuery: ...

    @abstractmethod
    def build_upsert_article_vectors(
        self,
        article_id: uuid.UUID,
        title_embedding: list[float] | None,
        content_embedding: list[float] | None,
        model_id: str,
    ) -> list[SimilarityQuery]: ...
```

#### Scenario: QueryBuilder returns query and params

- **WHEN** 调用 `PgVectorQueryBuilder().build_find_similar(embedding, ...)`
- **THEN** 返回 `SimilarityQuery` 对象，包含 `query` 字符串和 `params` 字典

### Requirement: SimilarityQuery Dataclass

系统 SHALL 定义 `SimilarityQuery` 数据类，封装查询语句和参数：

```python
@dataclass
class SimilarityQuery:
    query: str
    params: dict[str, Any]
```

#### Scenario: SimilarityQuery structure

- **WHEN** 创建 `SimilarityQuery(query="SELECT ...", params={"threshold": 0.8})`
- **THEN** 对象具有 `query` 和 `params` 属性

### Requirement: PgVectorQueryBuilder Implementation

系统 SHALL 提供 `PgVectorQueryBuilder` 实现，生成 PostgreSQL pgvector 兼容的 SQL 查询：

- 相似度计算使用 `<=>` 操作符
- 向量类型使用 `vector` 类型转换
- 支持设置 `SET hnsw.ef_search = 200`

#### Scenario: PostgreSQL similarity query

- **WHEN** 调用 `PgVectorQueryBuilder().build_find_similar([0.1, 0.2, ...], threshold=0.8)`
- **THEN** 返回的 `query` 包含 `1 - (embedding <=> cast(:embedding as vector)) as similarity`
- **AND** 返回的 `query` 包含 `> :threshold` 条件

### Requirement: DuckDBVectorQueryBuilder Implementation

系统 SHALL 提供 `DuckDBVectorQueryBuilder` 实现，生成 DuckDB 兼容的 SQL 查询：

- 相似度计算使用 `array_cosine_similarity()` 函数
- 向量类型使用 `FLOAT[1024]` 类型转换
- 使用 `INSERT OR REPLACE` 进行 upsert

#### Scenario: DuckDB similarity query

- **WHEN** 调用 `DuckDBVectorQueryBuilder().build_find_similar([0.1, 0.2, ...], threshold=0.8)`
- **THEN** 返回的 `query` 包含 `array_cosine_similarity(av.embedding, CAST(:embedding AS FLOAT[1024]))`
- **AND** 返回的 `query` 包含 `> :threshold` 条件

### Requirement: Unified VectorRepo

系统 SHALL 提供统一的 `VectorRepo` 实现，通过依赖注入 `VectorQueryBuilder` 支持多种数据库后端：

```python
class VectorRepo:
    def __init__(
        self,
        pool: RelationalPool,
        query_builder: VectorQueryBuilder,
    ) -> None:
        self._pool = pool
        self._query_builder = query_builder
```

#### Scenario: VectorRepo with PostgreSQL

- **WHEN** 使用 `VectorRepo(pool, PgVectorQueryBuilder())` 创建实例
- **THEN** `find_similar()` 方法使用 pgvector 语法执行查询

#### Scenario: VectorRepo with DuckDB

- **WHEN** 使用 `VectorRepo(pool, DuckDBVectorQueryBuilder())` 创建实例
- **THEN** `find_similar()` 方法使用 DuckDB 语法执行查询

### Requirement: QueryBuilder Registration

`VectorQueryBuilder` 的具体实现 MUST 在 `src/core/db/query_builders.py` 中定义。

#### Scenario: QueryBuilder import path

- **WHEN** 需要使用 QueryBuilder
- **THEN** 可以通过 `from core.db.query_builders import PgVectorQueryBuilder, DuckDBVectorQueryBuilder` 导入

### Requirement: Delete Duplicate DuckDBVectorRepo

系统 MUST 删除 `src/modules/storage/duckdb/vector_repo.py` 文件，其功能由统一 `VectorRepo` 替代。

#### Scenario: DuckDBVectorRepo removed

- **WHEN** 查看 `src/modules/storage/duckdb/` 目录
- **THEN** 不存在 `vector_repo.py` 文件