## ADDED Requirements

### Requirement: 文档代码路径准确性
系统 SHALL 确保所有文档中的代码路径引用与实际文件系统路径完全一致。

#### Scenario: ARCHITECTURE.md 中的导入示例
- **WHEN** 查看 `docs/ARCHITECTURE.md` 中的代码示例
- **THEN** SHALL 所有 `from xxx import yyy` 路径在代码库中存在
- **AND** SHALL 可直接复制运行而不产生 ImportError

#### Scenario: 目录结构图准确性
- **WHEN** 查看文档中的目录树示例
- **THEN** SHALL 与实际 `tree src/` 输出一致

### Requirement: API 端点文档完整性
系统 SHALL 在 API 文档中包含所有实际存在的端点，参数说明完整准确。

#### Scenario: 新增端点文档
- **WHEN** 查看 `docs/API.md`
- **THEN** SHALL 包含 `GET /api/v1/status` 端点说明
- **AND** SHALL 包含 `GET /api/v1/config` 端点说明

#### Scenario: 搜索端点参数更新
- **WHEN** 查看搜索端点文档
- **THEN** SHALL 包含 `output_mode` 和 `enrich_entities` 参数
- **AND** SHALL 不包含已废弃的 `mode`、`entity_names`、`max_tokens` 参数

### Requirement: 环境变量文档准确性
系统 SHALL 确保部署文档中的环境变量与实际代码中的定义完全匹配。

#### Scenario: 环境变量格式正确
- **WHEN** 查看 `docs/DEPLOYMENT.md` 中的环境变量示例
- **THEN** SHALL 使用双下划线分隔格式（如 `WEAVER_POSTGRES__HOST`）
- **AND** SHALL 不包含代码中未使用的变量（如 `HNSW_M`）

#### Scenario: 新增环境变量文档
- **WHEN** 查看部署文档
- **THEN** SHALL 包含 `WEAVER_DUCKDB__PATH`、`WEAVER_LADYBUG__PATH`、`WEAVER_SCHEDULER__ENABLED` 等新增变量

### Requirement: 用户指南实用性
系统 SHALL 提供基于实际功能的完整使用流程，所有示例可直接运行。

#### Scenario: Intent-Aware Routing 示例
- **WHEN** 查看 `docs/USER_GUIDE.md` 中的搜索示例
- **THEN** SHALL 包含 WHY、WHEN、ENTITY、MULTI_HOP、OPEN 查询示例
- **AND** SHALL 示例中的 API 调用与实际端点匹配

#### Scenario: Output Mode 使用指南
- **WHEN** 查看搜索使用指南
- **THEN** SHALL 说明 `output_mode=context` 和 `output_mode=narrative` 的区别
- **AND** SHALL 提供两种模式的响应示例

### Requirement: 导入路径变更日志
系统 SHALL 维护导入路径变更日志，帮助开发者迁移代码。

#### Scenario: 变更日志完整性
- **WHEN** 查看文档中的"导入路径变更"章节
- **THEN** SHALL 列出所有重构前后的路径映射
- **AND** SHALL 格式为表格（旧路径、新路径、变更版本）

#### Scenario: 变更日志可执行性
- **WHEN** 开发者根据变更日志更新自己的代码
- **THEN** SHALL 所有旧路径替换为新路径后导入成功

### Requirement: 文档验证自动化
系统 SHALL 提供自动化脚本验证文档中的代码路径引用。

#### Scenario: 运行文档路径检查
- **WHEN** 执行 `python scripts/verify_refactor.py`
- **THEN** SHALL 扫描所有文档中的 `src/` 路径引用
- **AND** SHALL 报告不存在的路径

#### Scenario: 文档链接检查
- **WHEN** 运行 markdown-link-check
- **THEN** SHALL 所有内部链接有效
- **AND** SHALL 无断裂链接
