## MODIFIED Requirements

### Requirement: Memory 服务初始化使用正确的属性引用
container.py 的 `init_memory_service()` 方法 SHALL 使用 `self.graph_pool()` 方法获取图数据库连接池，而非直接引用 `self._neo4j_pool` 属性（该属性不存在于 `__init__` 中）。

#### Scenario: Memory 服务在有 Neo4j 时正确初始化
- **WHEN** Neo4j 连接可用且调用 `init_memory_service()`
- **THEN** 服务使用 `graph_pool()` 获取的连接池成功初始化

#### Scenario: Memory 服务在无 Neo4j 时安全跳过
- **WHEN** Neo4j 不可用
- **THEN** `init_memory_service()` 返回 None 并记录 info 日志

### Requirement: LadybugWriter 初始化包含 relation_type_normalizer
container.py 中 LadybugWriter 的初始化 SHALL 传入 `relation_type_normalizer` 参数，与 Neo4jWriter 保持一致。

#### Scenario: LadybugDB 路径下关系类型被标准化
- **WHEN** 使用 LadybugDB 作为图数据库并写入关系
- **THEN** 关系类型经过 normalizer 标准化处理
