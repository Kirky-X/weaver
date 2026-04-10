## ADDED Requirements

### Requirement: Rich 进度条显示

系统 SHALL 使用 Rich 库在终端显示迁移进度条。

#### Scenario: 显示关系型迁移进度
- **WHEN** 执行关系型数据库迁移
- **THEN** 系统显示 Panel 标题 "📊 关系型迁移 postgres → duckdb"
- **AND** 每个表显示独立进度条

#### Scenario: 显示图迁移进度
- **WHEN** 执行图数据库迁移
- **THEN** 系统显示 Panel 标题 "🕸 图数据迁移 neo4j → ladybug"
- **AND** 节点标签显示 ● 图标
- **AND** 关系类型显示 ○ 图标

#### Scenario: 进度条更新
- **WHEN** 一批数据写入完成
- **THEN** 进度条实时更新已处理数量
- **AND** 显示当前速率（rows/s）

### Requirement: 进度信息展示

系统 SHALL 在进度条中展示详细信息。

#### Scenario: 显示完整进度信息
- **WHEN** 进度条运行中
- **THEN** 显示以下信息：
  - 任务描述
  - 进度条（图形）
  - 百分比
  - 已处理/总数
  - 处理速率
  - 已用时间
  - 预计剩余时间

#### Scenario: 完成状态显示
- **WHEN** 单个表迁移完成
- **THEN** 进度条变为绿色
- **AND** 描述前添加 ✅ 图标

#### Scenario: 失败状态显示
- **WHEN** 单个表迁移失败
- **THEN** 描述前添加 ❌ 图标
- **AND** 下方显示红色错误消息

### Requirement: 迁移摘要

系统 SHALL 在迁移完成后显示摘要表格。

#### Scenario: 显示迁移摘要表格
- **WHEN** 所有迁移任务完成
- **THEN** 系统显示 Rich Table 包含：
  - 表/标签名称
  - 总数
  - 已迁移数
  - 状态（✅/❌）

#### Scenario: 显示总计时
- **WHEN** 摘要表格显示完成
- **THEN** 系统显示总迁移数量和总耗时

### Requirement: API 进度查询

系统 SHALL 提供 HTTP API 查询迁移进度。

#### Scenario: 查询迁移进度
- **WHEN** 客户端 GET /migration/relational/{task_id}/progress
- **THEN** 系统返回 JSON 包含：
  - task_id
  - source_db / target_db
  - items: 每个表的进度详情
  - total_migrated / total_expected
  - started_at / elapsed_seconds
  - status

#### Scenario: 任务不存在
- **WHEN** 查询不存在的 task_id
- **THEN** 系统返回 404 Not Found

### Requirement: 进度数据结构

系统 SHALL 维护结构化的进度数据。

#### Scenario: 进度数据更新
- **WHEN** 一批数据写入成功
- **THEN** 系统更新 MigrationProgress 对象：
  - migrated 字段增加写入数量
  - status 保持 "running"

#### Scenario: 进度数据完成
- **WHEN** 表迁移完成
- **THEN** 系统更新 MigrationProgress：
  - status 设为 "completed"
  - migrated 等于 total

### Requirement: 取消迁移

系统 SHALL 支持取消正在运行的迁移任务。

#### Scenario: 通过 API 取消
- **WHEN** 客户端 POST /migration/relational/{task_id}/cancel
- **THEN** 系统设置取消标志
- **AND** 当前批次完成后停止迁移
- **AND** 返回已迁移数量

#### Scenario: 通过 CLI 取消
- **WHEN** 用户按下 Ctrl+C
- **THEN** 系统优雅停止迁移
- **AND** 显示已迁移数量