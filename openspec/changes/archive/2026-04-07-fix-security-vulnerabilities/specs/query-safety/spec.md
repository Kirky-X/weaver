## ADDED Requirements

### Requirement: Parameterized SQL queries

所有 SQL 查询 MUST 使用参数化查询，禁止使用 f-string 或字符串拼接构造查询。

#### Scenario: ladybug_source.py uses parameterized queries

- **WHEN** 查看 `src/modules/migration/adapters/ladybug_source.py` 的数据库查询代码
- **THEN** 所有查询使用 `$1`, `$2` 占位符而非 f-string 插入变量
- **AND** 参数通过 execute_query 的 params 参数传递

#### Scenario: graph_query.py uses parameterized queries

- **WHEN** 查看 `src/core/db/graph_query.py` 的 SQL 查询构造
- **THEN** 所有 WHERE、JOIN、INSERT 条件使用参数占位符
- **AND** 禁止存在 `WHERE label = '{label}'` 类型的 f-string

### Requirement: Parameterized Cypher queries

所有 Neo4j Cypher 查询 MUST 使用参数化查询，变量值通过 `$param` 占位符传递。

#### Scenario: neo4j_source.py uses parameterized Cypher

- **WHEN** 查看 `src/modules/migration/adapters/neo4j_source.py` 的 Cypher 查询代码
- **THEN** 所有 MATCH、WHERE、SET 子句使用 `$param` 占位符
- **AND** 参数通过 execute_query 的 parameters 参数传递
- **AND** 禁止存在 `MATCH (n:{label})` 类型的 f-string

#### Scenario: local_context.py uses parameterized Cypher

- **WHEN** 查看 `src/modules/knowledge/search/context/local_context.py` 的 Cypher 构造
- **THEN** 所有查询使用 `$param` 占位符传递 entity_id、community_id 等参数
- **AND** 禁止存在字符串拼接构造节点标签

### Requirement: Input validation for identifiers

用户提供的标识符（表名、字段名、edge_type）MUST 经过白名单验证后再用于查询构造。

#### Scenario: edge_type validation

- **WHEN** edge_type 参数用于 Cypher 关系创建
- **THEN** edge_type MUST 匹配正则 `^[A-Z_\u4e00-\u9fff][A-Z_\u4e00-\u9fff0-9]*$`
- **AND** 不匹配时抛出 ValueError

#### Scenario: label validation for graph queries

- **WHEN** label 参数用于 Neo4j/Ladybug 节点查询
- **THEN** label MUST 匹配有效标签格式（字母、数字、下划线、中文）
- **AND** 不匹配时抛出 ValueError

### Requirement: QueryBuilder pattern for database abstraction

数据库查询 MUST 通过 QueryBuilder 抽象层构造，而非直接拼接字符串。

#### Scenario: VectorQueryBuilder usage

- **WHEN** 构造向量相似度查询
- **THEN** 使用 `VectorQueryBuilder` 类方法构造查询
- **AND** 返回的 SQL/Cypher 使用参数占位符

#### Scenario: QueryBuilder factory selection

- **WHEN** 创建 QueryBuilder 实例
- **THEN** 使用 `create_vector_query_builder("postgres")` 或 `create_vector_query_builder("neo4j")` 工厂函数
- **AND** 返回正确的数据库类型 builder