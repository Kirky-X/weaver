## ADDED Requirements

### Requirement: 图迁移引擎初始化

系统 SHALL 根据 MigrationConfig 创建图迁移引擎，识别源图数据库和目标图数据库。

#### Scenario: 创建 Neo4j 到 LadybugDB 迁移引擎
- **WHEN** 用户配置 source_db="neo4j", target_db="ladybug"
- **THEN** 系统创建 Neo4jSource 和 LadybugTarget 适配器

#### Scenario: 创建 LadybugDB 到 Neo4j 迁移引擎
- **WHEN** 用户配置 source_db="ladybug", target_db="neo4j"
- **THEN** 系统创建 LadybugSource 和 Neo4jTarget 适配器

### Requirement: 节点标签发现

系统 SHALL 自动发现源图数据库中的所有节点标签。

#### Scenario: Neo4j 节点标签发现
- **WHEN** 执行图迁移且未指定 node_labels
- **THEN** 系统调用 `CALL db.schema.nodeTypeProperties()` 获取所有标签
- **AND** 返回每个标签的属性列表

#### Scenario: LadybugDB 节点标签发现
- **WHEN** 执行从 LadybugDB 的迁移
- **THEN** 系统查询系统表获取所有节点表
- **AND** 解析每个节点表的 schema

### Requirement: 关系类型发现

系统 SHALL 自动发现源图数据库中的所有关系类型。

#### Scenario: Neo4j 关系类型发现
- **WHEN** 执行图迁移且未指定 rel_types
- **THEN** 系统调用 `CALL db.schema.relTypeProperties()` 获取所有关系类型
- **AND** 返回每种关系的源/目标标签

### Requirement: 节点优先迁移

系统 SHALL 先迁移所有节点，再迁移所有关系，保证引用完整性。

#### Scenario: 节点优先迁移顺序
- **WHEN** 执行图迁移
- **THEN** 系统按以下顺序执行：
  1. 创建所有节点表 schema
  2. 迁移所有节点数据
  3. 创建所有关系表 schema
  4. 迁移所有关系数据

#### Scenario: 跳过孤立关系
- **WHEN** 关系引用的源节点或目标节点不存在于目标数据库
- **THEN** 系统记录警告并跳过该关系
- **AND** 继续迁移其他关系

### Requirement: 指定节点标签迁移

系统 SHALL 支持仅迁移用户指定的节点标签。

#### Scenario: 迁移指定节点标签
- **WHEN** 用户指定 node_labels=["Entity", "Article"]
- **THEN** 系统仅迁移 Entity 和 Article 节点
- **AND** 仅迁移这两个标签之间的关系

### Requirement: 节点数据迁移

系统 SHALL 批量读取和写入节点数据。

#### Scenario: 批量读取 Neo4j 节点
- **WHEN** 迁移 Neo4j 节点
- **THEN** 系统执行 `MATCH (n:Label) RETURN n SKIP $skip LIMIT $limit`
- **AND** 提取节点属性和主键

#### Scenario: 批量写入 LadybugDB 节点
- **WHEN** 写入节点到 LadybugDB
- **THEN** 系统使用批量 COPY 命令
- **AND** 正确处理主键约束

### Requirement: 关系数据迁移

系统 SHALL 批量读取和写入关系数据，保持源/目标节点引用。

#### Scenario: 批量读取 Neo4j 关系
- **WHEN** 迁移 Neo4j 关系
- **THEN** 系统执行 `MATCH (a)-[r:TYPE]->(b) RETURN properties(r), elementId(a), elementId(b)`
- **AND** 提取关系属性和端点 ID

#### Scenario: ID 映射
- **WHEN** Neo4j 使用 elementId 而 LadybugDB 使用字符串主键
- **THEN** 系统维护 ID 映射表
- **AND** 正确转换关系端点引用

### Requirement: 图类型转换

系统 SHALL 转换 Neo4j 和 LadybugDB 之间的属性类型差异。

#### Scenario: DateTime 类型转换
- **WHEN** Neo4j 属性为 DateTime 类型
- **THEN** 系统转换为 LadybugDB 的 INT64（epoch 毫秒）

#### Scenario: List 类型转换
- **WHEN** Neo4j 属性为 List 类型
- **THEN** 系统序列化为 JSON 字符串存储到 LadybugDB

### Requirement: 图数据验证

系统 SHALL 验证迁移后的图数据完整性。

#### Scenario: 节点数量验证
- **WHEN** 节点迁移完成
- **THEN** 系统比较源和目标的节点数量
- **AND** 报告差异

#### Scenario: 关系完整性验证
- **WHEN** 关系迁移完成
- **THEN** 系统验证所有关系的端点节点存在
- **AND** 报告孤立关系