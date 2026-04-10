# LadybugEntityRepo Specification

## Overview

LadybugDB 兼容的实体仓库实现，支持实体关系查询操作。解决 Neo4jEntityRepo 中使用 Neo4j 特有 Cypher 语法 (`type(r)`) 在 LadybugDB 上不可用的问题。

---

## ADDED Requirements

### Requirement: Get relation types for entity

系统 SHALL 支持查询实体的所有关系类型，使用 LadybugDB 兼容语法。

#### Scenario: Query relation types successfully
- **WHEN** 调用 `get_relation_types("阿里巴巴", "组织机构")`
- **THEN** 返回该实体的所有关系类型列表，包含 `relation_type`, `target_count`, `primary_direction`

#### Scenario: Entity not found
- **WHEN** 实体不存在
- **THEN** 返回空列表

### Requirement: Find entities by relation types

系统 SHALL 支持按关系类型搜索相关实体。

#### Scenario: Search with specific relation types
- **WHEN** 调用 `find_by_relation_types("阿里巴巴", "组织机构", ["投资", "合作"], 50)`
- **THEN** 返回匹配关系的实体列表

#### Scenario: Search without relation type filter
- **WHEN** 不指定关系类型
- **THEN** 返回所有关联实体

### Requirement: Cypher syntax compatibility

系统 SHALL 使用 LadybugDB 兼容的 Cypher 语法。

#### Scenario: Relation type access
- **WHEN** 查询关系类型
- **THEN** 使用 `r.edge_type` 而非 `type(r)`

#### Scenario: Node property access
- **WHEN** 访问节点属性
- **THEN** 使用 LadybugDB 支持的属性名

### Requirement: Protocol implementation

系统 SHALL 实现 EntityRepository Protocol。

#### Scenario: Interface compliance
- **WHEN** 实例化 LadybugEntityRepo
- **THEN** 满足 EntityRepository Protocol 的所有方法签名