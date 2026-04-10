## 1. CLI 参数解析

- [x] 1.1 添加 `rows` 子命令到 argparse
- [x] 1.2 实现 `--table` 位置参数
- [x] 1.3 实现 `--db` 参数（默认 postgres）
- [x] 1.4 实现 `--columns` 参数（可选，逗号分隔）
- [x] 1.5 实现 `--limit` 参数（默认 20）
- [x] 1.6 实现 `--page` 参数（默认 1）
- [x] 1.7 实现 `--order-by` 参数（支持多值和升降序）
- [x] 1.8 实现 `--format` 参数（table/json，默认 table）

## 2. 数据库查询实现

- [x] 2.1 实现 `_rows_postgres()` 函数（asyncpg）
- [x] 2.2 实现 `_rows_duckdb()` 函数（DuckDBPool + SQLAlchemy）
- [x] 2.3 实现 `_rows_neo4j()` 函数（neo4j driver）
- [x] 2.4 实现 `_rows_ladybug()` 函数（LadybugPool）
- [x] 2.5 实现表名验证函数（防注入）

## 3. 输出格式化

- [x] 3.1 实现表格输出函数（使用 rich.table）
- [x] 3.2 实现 JSON 输出函数
- [x] 3.3 实现长文本截断逻辑

## 4. 命令整合

- [x] 4.1 实现 `cmd_rows()` 主函数
- [x] 4.2 注册 `rows` 子命令到 main()
- [x] 4.3 更新模块文档字符串

## 5. 测试

- [x] 5.1 测试 PostgreSQL 行查询（基础、分页、排序）
- [x] 5.2 测试 DuckDB 行查询
- [x] 5.3 测试 Neo4j 节点查询
- [x] 5.4 测试 LadybugDB 节点查询
- [x] 5.5 测试表名验证
- [x] 5.6 测试输出格式（table/json）