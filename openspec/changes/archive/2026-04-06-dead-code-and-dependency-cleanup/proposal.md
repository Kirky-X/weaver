## Why

通过报告与代码的交叉验证，发现两个需要修正的问题：

1. **TemporalParser 死代码残留**：在 `IntentRouter` 中实例化但从未被调用，属于结构性死代码，应该删除。

2. **依赖状态不一致**：
   - `flashrank` 被注释但代码保留——实际上 FlashrankReranker 是可选增强功能，依赖应作为可选依赖保留
   - `langchain` 系列依赖被注释而非删除——既然代码中已无导入，应彻底删除依赖声明

## What Changes

- 删除 `src/modules/knowledge/search/temporal/` 目录（TemporalParser 相关代码）
- 从 `IntentRouter` 移除 `_temporal` 属性及相关导入
- 将 `flashrank>=0.2.10` 移至 `[project.optional-dependencies]`（搜索增强功能）
- 彻底移除 `langchain` 系列依赖声明（而非注释保留）
- 清理 `build_nuitka.py` 中的 langchain include 条目（已注释的应删除）

## Capabilities

### New Capabilities

- `optional-search-reranking`: 将 reranking 功能定义为可选增强，flashrank 作为可选依赖

### Modified Capabilities

- `redis-fallback`: 无变更，仅确认 CashewsRedisFallback 保留正确

## Impact

**代码删除**:
- `src/modules/knowledge/search/temporal/` 目录（~100 行）

**依赖变更**:
- `pyproject.toml`: 移除 langchain 系列，flashrank 移至 optional-dependencies
- `uv.lock`: 相应更新

**构建配置**:
- `scripts/build_nuitka.py`: 删除已注释的 langchain 条目

**风险评估**:
- TemporalParser 删除：🟢 低风险（从未被调用）
- flashrank 移至可选依赖：🟢 低风险（已有优雅降级机制）
- langchain 移除：🟢 低风险（代码中无导入）