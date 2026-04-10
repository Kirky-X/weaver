## ADDED Requirements

### Requirement: 迁移引擎初始化

系统 SHALL 根据 MigrationConfig 创建 MigrationEngine 实例，配置源数据库、目标数据库、批处理大小等参数。

#### Scenario: 创建关系型迁移引擎
- **WHEN** 用户配置 source_db="postgres", target_db="duckdb"
- **THEN** 系统创建 MigrationEngine 实例，自动识别为关系型迁移

#### Scenario: 创建图迁移引擎
- **WHEN** 用户配置 source_db="neo4j", target_db="ladybug"
- **THEN** 系统创建 MigrationEngine 实例，自动识别为图迁移

### Requirement: 全量表迁移

系统 SHALL 支持将源数据库的所有用户表迁移到目标数据库。

#### Scenario: 全量迁移 PostgreSQL 到 DuckDB
- **WHEN** 用户执行迁移且未指定 tables 参数
- **THEN** 系统读取 PostgreSQL 中 public schema 的所有表
- **AND** 按表名字母顺序依次迁移每张表

#### Scenario: 全量迁移包含表结构
- **WHEN** 目标数据库中不存在对应表
- **THEN** 系统根据源表结构在目标数据库创建表
- **AND** 正确转换数据类型（如 jsonb → JSON）

### Requirement: 指定表迁移

系统 SHALL 支持仅迁移用户指定的表列表。

#### Scenario: 迁移指定表
- **WHEN** 用户配置 tables=["articles", "entities"]
- **THEN** 系统仅迁移 articles 和 entities 表
- **AND** 跳过其他表

#### Scenario: 指定表不存在
- **WHEN** 用户指定的表在源数据库中不存在
- **THEN** 系统记录警告并跳过该表
- **AND** 继续迁移其他指定的表

### Requirement: 数据类型转换

系统 SHALL 自动转换源数据库和目标数据库之间的数据类型差异。

#### Scenario: PostgreSQL 类型转换为 DuckDB 类型
- **WHEN** 源字段类型为 "uuid"
- **THEN** 系统将其映射为 DuckDB 的 "UUID" 类型
- **AND** 值保持不变

#### Scenario: pgvector 类型转换
- **WHEN** 源字段类型为 "vector(1024)"
- **THEN** 系统将其映射为 DuckDB 的 "FLOAT[1024]" 类型
- **AND** 向量值正确转换

#### Scenario: 类型转换失败
- **WHEN** 某个值无法转换为目标类型
- **THEN** 系统记录错误行（表名、偏移量、字段名、值）
- **AND** 在非严格模式下跳过该行继续处理

### Requirement: 批量读写

系统 SHALL 使用批处理方式读写数据，控制内存使用。

#### Scenario: 默认批处理
- **WHEN** 用户未指定 batch_size
- **THEN** 系统使用默认值 5000 行每批

#### Scenario: 自定义批大小
- **WHEN** 用户指定 batch_size=10000
- **THEN** 系统每次读取 10000 行数据

#### Scenario: 批量写入事务
- **WHEN** 批量写入过程中发生错误
- **THEN** 系统回滚当前批次
- **AND** 保留已成功的批次

### Requirement: 增量迁移

系统 SHALL 支持基于时间戳或 ID 的增量迁移。

#### Scenario: 基于时间戳增量迁移
- **WHEN** 用户指定 incremental_key="updated_at", incremental_since="2024-01-01T00:00:00"
- **THEN** 系统仅迁移 updated_at > "2024-01-01T00:00:00" 的记录

#### Scenario: 基于 ID 增量迁移
- **WHEN** 用户指定 incremental_key="id", incremental_since="1000"
- **THEN** 系统仅迁移 id > 1000 的记录

#### Scenario: Keyset pagination
- **WHEN** 执行增量迁移
- **THEN** 系统使用 WHERE key > last_value 方式分页
- **AND** 避免使用 OFFSET 以保证性能

### Requirement: 数据验证

系统 SHALL 在迁移完成后验证数据完整性。

#### Scenario: 行数验证
- **WHEN** 表迁移完成
- **THEN** 系统比较源表和目标表的行数
- **AND** 报告差异

#### Scenario: 主键完整性验证
- **WHEN** 表迁移完成
- **THEN** 系统验证目标表主键无重复
- **AND** 验证无 NULL 主键

### Requirement: 错误处理

系统 SHALL 提供完善的错误处理机制。

#### Scenario: 连接失败重试
- **WHEN** 数据库连接失败
- **THEN** 系统进行指数退避重试（最多 3 次）
- **AND** 重试间隔为 1s, 2s, 4s

#### Scenario: 迁移失败报告
- **WHEN** 迁移过程中发生错误
- **THEN** 系统记录错误详情（表名、偏移量、错误消息）
- **AND** 在 MigrationResult 中返回错误信息