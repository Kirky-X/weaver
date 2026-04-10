## Requirements

### REQ-001: DuckDB handler 单元测试文件

创建 `tests/unit/core/db/test_duckdb_handler.py`，使用内存 DuckDB 实例测试核心功能。

### REQ-002: 测试覆盖范围

必须覆盖以下场景：

1. **连接管理**: 内存数据库创建、关闭、连接池
2. **DDL 操作**: 表创建、schema 初始化
3. **DML 操作**: INSERT、UPDATE、DELETE、SELECT
4. **查询功能**: 参数化查询、分页查询、聚合查询
5. **错误处理**: 无效 SQL、连接失败、类型错误
6. **数据类型**: 常见 SQL 类型正确处理（INTEGER、TEXT、FLOAT、TIMESTAMP、BOOLEAN）

### REQ-003: 测试质量

- 使用 DuckDB 内存模式（`duckdb.connect(":memory:")`）
- 每个测试独立，不依赖其他测试的副作用
- 覆盖率目标：DuckDB handler 模块 80%+
