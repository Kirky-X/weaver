## ADDED Requirements

### Requirement: 模块按功能域分组
系统 SHALL 将相关功能的文件组织到同一子目录中，确保功能内聚性。

#### Scenario: community 子模块组织
- **WHEN** 开发者查看 `modules/knowledge/graph/community/` 目录
- **THEN**  SHALL 看到所有 community 相关文件（detector、models、repo、health、report_generator、repair_service、incremental_updater）

#### Scenario: llm 功能域分组
- **WHEN** 开发者查看 `core/llm/` 目录
- **THEN** SHALL 看到 6 个功能子目录（core、routing、config、resilience、validation、evaluation）

### Requirement: 子模块规模控制
系统 SHALL 控制单个文件不超过 500 行，子模块不超过 2,000 行。

#### Scenario: 单文件大小检查
- **WHEN** 运行代码质量检查
- **THEN** SHALL 报告所有超过 500 行的 Python 文件

#### Scenario: 子模块规模检查
- **WHEN** 评估模块重构效果
- **THEN** SHALL 验证每个子模块总行数不超过 2,000 行

### Requirement: 清晰的模块边界
系统 SHALL 通过 `__init__.py` 明确定义每个子模块的公共 API。

#### Scenario: community 子模块导出
- **WHEN** 导入 `from modules.knowledge.graph.community import CommunityDetector`
- **THEN** SHALL 成功导入，无需指定完整路径 `community.detector`

#### Scenario: 子模块内部实现隐藏
- **WHEN** 开发者查看子模块 `__init__.py`
- **THEN** SHALL 仅导出公共 API，内部实现类不在 `__all__` 中

### Requirement: 依赖方向一致性
系统 SHALL 保持原有的模块依赖方向，不引入循环导入。

#### Scenario: 单向依赖检查
- **WHEN** 运行导入验证
- **THEN** SHALL 不存在 A 导入 B、B 又导入 A 的循环

#### Scenario: TYPE_CHECKING 打破循环
- **WHEN** 模块需要引用彼此的类型
- **THEN** SHALL 使用 `TYPE_CHECKING` 和字符串注解避免运行时循环导入
