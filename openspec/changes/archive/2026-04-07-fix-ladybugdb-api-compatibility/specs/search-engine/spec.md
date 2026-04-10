# Search Engine Specification

## Overview

修复 DRIFT 搜索端点的依赖注入问题，确保 LadybugDB 模式下正常工作。

---

## ADDED Requirements

### Requirement: DRIFT search endpoint dependencies

系统 SHALL 通过依赖注入而非直接属性访问获取数据库连接和 LLM 客户端。

#### Scenario: DRIFT search with dependency injection
- **WHEN** 调用 `/search/drift` 端点
- **THEN** 从 `deps.Endpoints` 获取 `neo4j_pool` 和 `llm_client`
- **AND** 不直接访问 `global_engine._pool` 或 `global_engine._llm`

#### Scenario: DRIFT search LadybugDB compatibility
- **WHEN** 使用 LadybugDB 后端
- **THEN** DRIFT 搜索成功返回结果
- **AND** 不抛出 AttributeError

### Requirement: DRIFT engine initialization

系统 SHALL 使用正确的初始化参数创建 DRIFTSearchEngine。

#### Scenario: DRIFT engine pool access
- **WHEN** 创建 DRIFTSearchEngine
- **THEN** 从依赖注入获取 pool 参数
- **AND** pool 可能是 Neo4jPool 或 LadybugPool

#### Scenario: DRIFT engine LLM access
- **WHEN** 创建 DRIFTSearchEngine
- **THEN** 从依赖注入获取 llm 参数