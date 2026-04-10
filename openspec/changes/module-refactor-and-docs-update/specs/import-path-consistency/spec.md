## ADDED Requirements

### Requirement: 统一导入路径
系统 SHALL 使用重构后的新路径进行所有导入，不提供旧路径的向后兼容。

#### Scenario: 使用新路径导入 community 模块
- **WHEN** 代码需要导入 CommunityDetector
- **THEN** SHALL 使用 `from modules.knowledge.graph.community import CommunityDetector`
- **AND** SHALL NOT 使用 `from modules.knowledge.graph.community_detector import CommunityDetector`

#### Scenario: 使用新路径导入 llm 模块
- **WHEN** 代码需要导入 SmartRouter
- **THEN** SHALL 使用 `from core.llm.routing.smart_router import SmartRouter`
- **AND** SHALL NOT 使用 `from core.llm.smart_router import SmartRouter`

### Requirement: 所有引用同步更新
系统 SHALL 更新所有 src/ 和 tests/ 目录中的导入路径，确保无遗漏。

#### Scenario: src 目录导入更新
- **WHEN** 完成模块重构
- **THEN** SHALL 所有 `src/**/*.py` 文件中的导入路径已更新为新路径

#### Scenario: tests 目录导入更新
- **WHEN** 完成模块重构
- **THEN** SHALL 所有 `tests/**/*.py` 文件中的导入路径已更新为新路径

### Requirement: __init__.py 导出声明更新
系统 SHALL 更新所有受影响模块的 `__init__.py` 中的导入和 `__all__` 声明。

#### Scenario: graph/__init__.py 导出更新
- **WHEN** 查看 `modules/knowledge/graph/__init__.py`
- **THEN** SHALL 从 `community` 子模块导入，而非平铺文件
- **AND** SHALL 在 `__all__` 中包含所有公共 API

#### Scenario: knowledge/__init__.py 导出更新
- **WHEN** 查看 `modules/knowledge/__init__.py`
- **THEN** SHALL 使用 `from modules.knowledge.graph.community import ...` 导入

### Requirement: 导入路径验证
系统 SHALL 提供自动化脚本验证所有关键导入路径的有效性。

#### Scenario: 运行验证脚本
- **WHEN** 执行 `python scripts/verify_refactor.py`
- **THEN** SHALL 测试所有关键导入是否成功
- **AND** SHALL 报告任何 ImportError

#### Scenario: 验证失败阻止合并
- **WHEN** 验证脚本返回非零退出码
- **THEN** SHALL 拒绝合并重构分支
