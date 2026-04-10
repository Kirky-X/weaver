# Graph Query Abstraction Specification

## Overview

扩展 GraphQueryBuilder 支持更多查询模式，特别是关系类型查询和实体仓库操作。

---

## ADDED Requirements

### Requirement: Relation type discovery query

系统 SHALL 支持构建查询实体所有关系类型的 Cypher。

#### Scenario: Build relation types query
- **WHEN** 调用 `build_relation_types_query(entity_name, entity_type)`
- **THEN** 返回查询该实体所有关系类型的 Cypher
- **AND** Neo4j 版本使用 `type(r)`
- **AND** LadybugDB 版本使用 `r.edge_type`

#### Scenario: Exclude system relations
- **WHEN** 构建关系类型查询
- **THEN** 排除 MENTIONS 和 FOLLOWED_BY 关系

### Requirement: Related entities with relation filter query

系统 SHALL 支持构建按关系类型过滤的相关实体查询。

#### Scenario: Build filtered related entities query
- **WHEN** 调用 `build_related_entities_by_relation_query(entity_name, relation_types)`
- **THEN** 返回过滤特定关系类型的查询
- **AND** 支持多个关系类型同时过滤

### Requirement: Entity repository query support

系统 SHALL 支持 EntityRepository 所需的所有查询模式。

#### Scenario: Merge entity query
- **WHEN** 构建实体 MERGE 查询
- **THEN** 使用数据库兼容的语法

#### Scenario: Find entity query
- **WHEN** 构建实体查找查询
- **THEN** 支持按名称和类型查找