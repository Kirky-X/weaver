# Ladybug Community Schema Specification

## Overview

扩展 LadybugDB Community schema 添加 `parent_id` 字段，支持社区层次结构查询。

---

## MODIFIED Requirements

### Requirement: Community node table

系统 SHALL 定义一个 `Community` 节点表，包含支持层次结构的属性。

#### Scenario: Community table creation
- **WHEN** LadybugDB schema 初始化
- **THEN** Community 表创建 id, title, summary, level, rank, parent_id, created_at 列

#### Scenario: Community primary key
- **WHEN** 创建 Community 表
- **THEN** id 列定义为 PRIMARY KEY

#### Scenario: Community hierarchy support
- **WHEN** 创建 Community 表
- **THEN** parent_id 列支持存储父社区 ID
- **AND** parent_id 可为 NULL（根社区）

#### Scenario: Community hierarchy query
- **WHEN** 查询社区层次结构
- **THEN** 可通过 parent_id 查找子社区
- **AND** 可追溯父社区链