## Why

根据 `analytics-memory-modules-report.md` 和 `modules-integration-audit.md` 两份报告的验证结果，发现 6 个遗留问题需要修复。这些问题包括：冗余代码、未完成的功能集成、孤立组件和未使用的事件类型。修复这些问题将减少代码维护负担，提高代码质量和一致性。

## What Changes

1. **删除冗余 Thread 类** - 移除 `LLMFailureCleanupThread`、`LLMUsageAggregatorThread`、`RawCleanupThread` 三个未被正确使用的线程类
2. **注入 vector_repo 和 entity_repo** - 在 Memory 服务中注入实际的向量仓库和实体仓库实现
3. **完善实体链接发现** - 在 slow_path.py 中实现或明确注释实体链接发现逻辑
4. **接入孤立 retrieval 组件** - 将 `EntityAggregator`、`NarrativeSynthesizer`、`SearchResponseBuilder` 接入 memory_service 或删除
5. **清理未使用事件类型** - 删除 `FallbackEvent`、`PipelineStageCompletedEvent`；保留 `CredibilityComputedEvent`（有发布者）

## Capabilities

### New Capabilities

无新增能力，此变更专注于清理和修复现有代码。

### Modified Capabilities

- `memory-service`: 完善向量仓库和实体仓库注入，接入 retrieval 组件
- `analytics-module`: 移除冗余 Thread 类，保留核心功能

## Impact

**代码删除**：
- `src/modules/analytics/llm_failure/cleanup.py` - 删除 `LLMFailureCleanupThread` 类
- `src/modules/analytics/llm_usage/aggregator.py` - 删除 `LLMUsageAggregatorThread` 和 `RawCleanupThread` 类
- `src/core/event/bus.py` - 删除 `FallbackEvent`、`PipelineStageCompletedEvent` 类

**代码修改**：
- `src/modules/memory/integration/memory_service.py` - 注入 vector_repo、entity_repo
- `src/modules/memory/evolution/slow_path.py` - 实现或注释实体链接发现
- `src/modules/memory/retrieval/` - 接入或删除孤立组件

**影响范围**：
- Analytics 模块：无功能变化（scheduler 已使用内部方法）
- Memory 模块：功能增强（向量索引、实体链接）
- 事件系统：无功能变化（删除的事件从未被使用）