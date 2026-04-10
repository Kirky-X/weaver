# Ladybug Temporal Schema Specification

## Overview

统一 LadybugDB EventNode 属性命名，与 Neo4j EventNode schema 保持一致。

---

## MODIFIED Requirements

### Requirement: EventNode node table

系统 SHALL 定义一个 `EventNode` 节点表，使用与 Neo4j 兼容的属性名。

#### Scenario: EventNode table creation
- **WHEN** LadybugDB schema 初始化
- **THEN** EventNode 表创建 id, event_type, name, content, timestamp, attributes, created_at 列

#### Scenario: EventNode primary key
- **WHEN** 创建 EventNode 表
- **THEN** id 列定义为 PRIMARY KEY

#### Scenario: EventNode content property
- **WHEN** 存储 EventNode 内容
- **THEN** 使用 `content` 列存储事件描述
- **AND** 该属性与 Neo4j EventNode.content 一致

#### Scenario: EventNode timestamp property
- **WHEN** 存储 EventNode 时间戳
- **THEN** 使用 `timestamp` 列存储 INT64 Unix 时间戳
- **AND** 该属性与 Neo4j EventNode.timestamp 一致

#### Scenario: EventNode attributes property
- **WHEN** 存储 EventNode 扩展属性
- **THEN** 使用 `attributes` 列存储 JSON 字符串
- **AND** 该属性与 Neo4j EventNode.attributes 一致

#### Scenario: Event timeline query
- **WHEN** 按时间排序查询事件
- **THEN** `timestamp` 列支持 ORDER BY 和范围查询