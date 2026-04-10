# LadybugTemporalRepo Specification

## Overview

LadybugDB 兼容的时序图仓库实现，支持事件链查询和时序推理。解决 TemporalGraphRepo 中属性名不匹配问题。

---

## ADDED Requirements

### Requirement: EventNode schema compatibility

系统 SHALL 使用与 LadybugDB schema 匹配的属性名。

#### Scenario: Property mapping
- **WHEN** 查询 EventNode
- **THEN** 使用 `content` 而非 `description`
- **AND** 使用 `timestamp` 而非 `event_time`
- **AND** 支持 `attributes` JSON 字段

### Requirement: Get temporal chain

系统 SHALL 支持获取按时间排序的事件链。

#### Scenario: Retrieve ordered events
- **WHEN** 调用 `get_temporal_chain(limit=100)`
- **THEN** 返回按 `timestamp` 升序排列的事件列表

#### Scenario: Empty chain
- **WHEN** 没有事件数据
- **THEN** 返回空列表

### Requirement: Append to chain

系统 SHALL 支持追加事件到时序链。

#### Scenario: Append new event
- **WHEN** 调用 `append_to_chain(event)`
- **THEN** 创建 EventNode 并建立 FOLLOWED_BY 关系

### Requirement: Cypher syntax adaptation

系统 SHALL 使用 LadybugDB 兼容的时序查询语法。

#### Scenario: DateTime function compatibility
- **WHEN** 查询涉及时间比较
- **THEN** 使用 INT64 timestamp 而非 Neo4j datetime 函数

### Requirement: Protocol implementation

系统 SHALL 实现与 TemporalGraphRepo 相同的接口。

#### Scenario: Drop-in replacement
- **WHEN** 使用 LadybugTemporalRepo 替换 TemporalGraphRepo
- **THEN** 所有公共方法行为一致