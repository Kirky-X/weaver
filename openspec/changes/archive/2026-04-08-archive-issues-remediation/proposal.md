# Proposal: Archive Issues Remediation

## Why

归档方案实施状态报告中识别了多个未完全实现的问题，经代码库探索发现：
1. **高优先级**：`disable_data_metrics_nodes` 配置已定义但未注入到 `EntityResolver`
2. **中优先级**：API 测试覆盖不足，7 个测试文件未创建
3. **中优先级**：测试覆盖率 83% 未达标 85%
4. **低优先级**：`token_budget.py` 中一处硬编码 `gpt-4o`

状态报告中还存在多个**过时描述**：`database-migration-tool` 已完全实现、`GraphQueryBuilder` 已实现、LadybugDB schema 已完整。

## What Changes

### 高优先级修复
- **修复配置注入**：在 `container.py` 的 `entity_resolver()` 方法中添加 `disable_data_metrics` 参数传递

### 中优先级修复
- **补充 API 测试**：创建 7 个缺失的测试文件
  - `tests/unit/api/test_search_api.py`
  - `tests/unit/api/test_graph_metrics_api.py`
  - `tests/unit/api/test_admin_llm_api.py`
  - `tests/unit/api/test_communities_api.py`
  - `tests/unit/api/test_graph_relations_api.py`
  - `tests/integration/test_api_integration.py`
  - `tests/e2e/test_api_user_flows.py`

### 低优先级修复
- **移除硬编码**：`token_budget.py:34` 的 `gpt-4o` 改为从配置读取或添加文档说明保留原因

## Capabilities

### New Capabilities

- `entity-settings-injection`: 将 EntitySettings 配置正确注入到相关组件
- `api-test-coverage`: 为 36 个 API 端点补充测试覆盖

### Modified Capabilities

无（本次修复不改变已有规格，仅补充实现）

## Impact

### 代码变更
- `src/container.py` — 修改 `entity_resolver()` 方法
- `tests/unit/api/` — 新增 5 个测试文件
- `tests/integration/` — 新增 1 个测试文件
- `tests/e2e/` — 新增 1 个测试文件
- `src/core/llm/token_budget.py` — 可选修改

### 影响范围
- 数据指标实体过滤功能将实际生效
- API 测试覆盖率从 34% 提升
- 整体测试覆盖率从 83% 提升至 85%+

### 依赖
- 无新增外部依赖
- 需现有测试基础设施支持