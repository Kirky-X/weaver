# Explicit Interface Contract Specification

## Overview

更新 `graph.py` 端点使用 Protocol 类型而非具体实现类，确保 DuckDB 模式下正常工作。

---

## ADDED Requirements

### Requirement: API endpoint pool type annotations

API 端点中的数据库池类型注解 MUST 使用 Protocol 类型。

#### Scenario: graph.py uses RelationalPool type
- **WHEN** 查看 `src/api/endpoints/graph.py` 中的 `_pg_pool` 变量声明
- **THEN** 类型注解为 `RelationalPool | None`（而非 `PostgresPool | None`）

#### Scenario: graph.py setter uses Protocol type
- **WHEN** 查看 `set_postgres_pool` 函数（或重命名后的 `set_relational_pool`）
- **THEN** 参数类型为 `RelationalPool`（而非 `PostgresPool`）

#### Scenario: DuckDB pool accepted by setter
- **WHEN** 传入 `DuckDBPool` 实例
- **THEN** 类型检查通过
- **AND** 变量被正确设置

### Requirement: API endpoint function signatures

API 端点函数签名 MUST 使用依赖注入获取 Protocol 类型的实例。

#### Scenario: Endpoint uses Depends for pool
- **WHEN** 端点需要关系型数据库连接
- **THEN** 使用 `Depends(get_relational_pool)` 而非硬编码 `PostgresPool`

#### Scenario: Endpoint uses Depends for graph pool
- **WHEN** 端点需要图数据库连接
- **THEN** 使用 `Depends(get_neo4j_pool)` （返回 `GraphPool` Protocol）