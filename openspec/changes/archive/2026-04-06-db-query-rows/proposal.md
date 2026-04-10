## Why

`db_query.py` 当前只提供了表统计（`stats`）、单篇查询（`article`）和随机查询（`random`）功能，缺少查看表中具体数据记录的能力。开发者在调试数据时需要手动连接数据库或使用其他工具，效率低下。

需要一个 `rows` 子命令来直接查询指定表的数据行，支持分页、列选择、排序和多种输出格式。

## What Changes

- 新增 `rows` 子命令，查询指定表的数据行
- 支持 PostgreSQL、DuckDB、Neo4j、LadybugDB 四种数据库
- 支持分页控制：`--limit` 和 `--page` 参数
- 支持列选择：`--columns` 参数（可选，默认返回所有列）
- 支持排序：`--order-by` 参数，支持多列和升降序
- 支持两种输出格式：表格（默认）和 JSON（`--format` 切换）

## Capabilities

### New Capabilities

- `db-query-rows`: 数据库表行数据查询能力，支持分页、列选择、排序和格式化输出

### Modified Capabilities

- `db-query-cli`: 新增 `--format` 通用输出格式参数，可被所有子命令复用

## Impact

- **新增文件**: 无（修改现有 `scripts/db_query.py`）
- **修改文件**: `scripts/db_query.py`（新增 `rows` 子命令实现）
- **依赖**: 使用现有依赖（`rich` 或 `tabulate` 用于表格输出，项目已有 `rich`）
- **兼容性**: 完全向后兼容，新增功能不影响现有子命令