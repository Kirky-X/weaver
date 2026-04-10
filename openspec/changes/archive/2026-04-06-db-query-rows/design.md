## Context

`scripts/db_query.py` 是 Weaver 项目的数据库查询工具，当前支持：
- `stats` - 表记录数统计
- `article` - 按 ID 查询单篇文章
- `random` - 随机查询文章及关联

现有实现使用异步 IO，支持 PostgreSQL（asyncpg）、DuckDB（SQLAlchemy async）、Neo4j（官方 driver）、LadybugDB（自定义 pool）。

## Goals / Non-Goals

**Goals:**
- 新增 `rows` 子命令，查询指定表的数据行
- 支持分页（`--limit`/`--page`）、列选择（`--columns`）、排序（`--order-by`）
- 支持表格和 JSON 两种输出格式
- 复用现有数据库连接逻辑

**Non-Goals:**
- 不支持复杂 WHERE 条件过滤（保持简单，需要复杂查询时用专业工具）
- 不支持 JOIN 查询（单表查询足够调试用途）
- 不实现数据修改功能（只读工具）

## Decisions

### 1. 子命令参数设计

**选择**: `rows <table> [options]`

**理由**: 与现有 `article --id` 和 `random --limit` 风格一致。`<table>` 作为位置参数，其他为可选参数。

**参数列表**:
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `table` | str | 必填 | 表名/节点标签 |
| `--db` | str | postgres | 数据库类型 |
| `--columns` | str | * | 列名，逗号分隔 |
| `--limit` | int | 20 | 每页行数 |
| `--page` | int | 1 | 页码 |
| `--order-by` | str | 无 | 排序列[:asc\|desc] |
| `--format` | str | table | 输出格式 |

### 2. 数据库适配策略

**选择**: 为每种数据库实现独立查询函数，复用现有连接池。

**理由**: 四种数据库查询语法差异较大：
- PostgreSQL/DuckDB: SQL `SELECT ... FROM table LIMIT ... OFFSET ...`
- Neo4j/LadybugDB: Cypher `MATCH (n:Label) RETURN n ... SKIP ... LIMIT ...`

**实现策略**:
- `_rows_postgres()`: 使用 asyncpg，动态构建 SQL
- `_rows_duckdb()`: 使用 DuckDBPool + SQLAlchemy
- `_rows_neo4j()`: 使用 neo4j driver，Cypher 查询
- `_rows_ladybug()`: 使用 LadybugPool，Cypher 查询

### 3. 图数据库"列"映射

**选择**: 将节点/关系属性映射为"列"。

**理由**: Neo4j/LadybugDB 的节点没有固定 schema，属性即列。`--columns` 参数过滤返回的属性。

**实现**: `MATCH (n:Label) RETURN n.col1, n.col2` 或 `RETURN n` 后在应用层提取属性。

### 4. 表格输出库

**选择**: 使用 `rich.table.Table`。

**理由**: 项目已有 rich 依赖，无需新增依赖。rich 提供自动换行、截断、颜色等功能。

**备选**: tabulate（更轻量但功能较少）、prettytable（已停止维护）。

## Risks / Trade-offs

### 风险 1: 大表查询性能

**风险**: 用户查询百万级大表时可能阻塞。

**缓解**:
- 默认 `--limit 20` 限制返回行数
- 不提供"查询全部"选项

### 风险 2: 图数据库无 Schema

**风险**: Neo4j/LadybugDB 同一标签节点可能有不同属性集。

**缓解**:
- 查询第一个节点的属性作为列
- 若指定 `--columns`，仅返回指定属性

### 风险 3: 特殊字符表名注入

**风险**: 用户输入的表名可能包含 SQL 注入字符。

**缓解**:
- 验证表名格式（仅允许字母、数字、下划线）
- 使用参数化查询（部分数据库）或白名单验证