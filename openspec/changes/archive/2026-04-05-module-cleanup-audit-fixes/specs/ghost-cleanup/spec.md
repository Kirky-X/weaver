## ADDED Requirements

### Requirement: 删除幽灵文件
系统 SHALL 在代码库中删除以下已确认无引用的幽灵文件：
- `src/modules/ingestion/processor.py`（与 `domain/processor.py` 重复）
- `src/modules/storage/llm_usage_buffer.py`（与 `analytics/llm_usage/buffer.py` 重复）
- `src/modules/knowledge/graph/writer.py`（Writer 类 0 引用，与 Neo4jWriter 重复）

#### Scenario: 幽灵文件已删除无断引用
- **WHEN** 删除上述 3 个文件后运行完整测试套件
- **THEN** 所有测试通过，无 ImportError

### Requirement: 清理空占位符目录
系统 SHALL 删除以下空占位符目录：
- `src/modules/analytics/metrics/`（仅含 `# Phase 5 完成后迁移` 注释）
- `src/modules/knowledge/metrics/`（仅含 `# Phase 4 完成后从 modules.knowledge.graph.metrics 迁移` 注释）

#### Scenario: 空目录已清理
- **WHEN** 删除空目录后运行测试
- **THEN** 无 import 错误，测试通过

### Requirement: 清理孤立的 GraphPruner 导出
系统 SHALL 从 `knowledge/graph/__init__.py` 的 `__all__` 中移除 `GraphPruner` 和 `PruneResult`，并删除 `graph_pruner.py` 文件。

#### Scenario: GraphPruner 已清理
- **WHEN** 删除 graph_pruner.py 并清理 __init__.py 导出
- **THEN** 无断引用，`from modules.knowledge.graph import GraphPruner` 抛出 ImportError
