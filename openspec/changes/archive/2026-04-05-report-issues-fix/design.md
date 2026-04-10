## Context

经过代码验证，确认以下 6 个问题需要修复：

| 问题 | 当前状态 | 影响 |
|------|----------|------|
| Thread 类冗余 | 3个 Thread 类存在，但 scheduler 直接调用内部方法 | 代码冗余 |
| vector_repo 未注入 | `memory_service.py:158` 为 `None` | Fast Path 向量索引不可用 |
| entity_repo 未注入 | `memory_service.py:159` 为 `None` | Fast Path 实体链接不更新 |
| 实体链接发现未实现 | `slow_path.py:113` 硬编码 `entity_links_added = 0` | Slow Path 功能受限 |
| retrieval 组件孤立 | 3个组件存在但未被使用 | 代码孤立 |
| 未使用事件类型 | 2个事件类型定义但无发布/订阅 | 代码冗余 |

**关键依赖**：
- `VectorRepo` 位于 `src/modules/storage/vector/`
- `EntityGraphRepo` 位于 `src/modules/knowledge/entity/`
- Scheduler 已通过 `jobs.py` 使用内部方法（`_flush()`, `cleanup_older_than()`）

## Goals / Non-Goals

**Goals:**
1. 删除 3 个冗余 Thread 类，保留其核心方法作为静态方法或移至 repo
2. 在 memory_service 中注入 vector_repo 和 entity_repo
3. 明确实体链接发现的实现状态（添加 TODO 注释或删除硬编码）
4. 决定 retrieval 组件的处理方式（接入或删除）
5. 删除未使用的事件类型

**Non-Goals:**
- 不实现完整的实体链接发现逻辑（需要独立的 entity extraction pipeline）
- 不修改 scheduler 的任务调度逻辑
- 不修改现有的测试覆盖策略

## Decisions

### 决策 1: Thread 类处理方式

**选择**: 删除 Thread 类，保留核心方法在 Repo 中

**理由**:
- Scheduler 已通过 `LLMUsageRepo.cleanup_older_than()` 和 `LLMUsageAggregatorThread._flush()` 实现功能
- Thread 类的 `start()` 和 `_run()` 方法从未被调用
- 保留 Thread 类会增加维护负担和代码困惑

**替代方案**:
- 保留 Thread 类并添加文档说明（不推荐：代码仍冗余）
- 将 Thread 方法提取为独立函数（可选，但增加文件数量）

### 决策 2: vector_repo 和 entity_repo 注入

**选择**: 在 container.py 中创建并注入实际实现

**理由**:
- `VectorRepo` 和 `EntityGraphRepo` 已存在于项目中
- 注入后 Fast Path 功能完整可用
- 符合依赖注入模式

**替代方案**:
- 保持 `None` 并添加注释（不推荐：功能受限）
- 使用懒加载模式（可行，但增加复杂度）

### 决策 3: 实体链接发现处理

**选择**: 添加详细注释说明未实现原因，保留硬编码的 0

**理由**:
- 完整实现需要 entity extraction pipeline 集成
- 当前阶段不宜引入新的复杂依赖
- 注释可防止误解

**替代方案**:
- 删除硬编码并抛出 NotImplementedError（不推荐：破坏现有流程）
- 完整实现（超出当前范围）

### 决策 4: retrieval 组件处理

**选择**: 在 memory_service 中添加 `search_with_context()` 方法接入这些组件

**理由**:
- 组件已实现完整功能，删除是浪费
- 接入后可提供更丰富的搜索响应
- 符合报告建议

**替代方案**:
- 删除孤立组件（不推荐：丢失已实现的功能）
- 保持现状（不推荐：代码孤立）

### 决策 5: 未使用事件类型处理

**选择**: 删除 `FallbackEvent` 和 `PipelineStageCompletedEvent`，保留 `CredibilityComputedEvent`

**理由**:
- `FallbackEvent` 和 `PipelineStageCompletedEvent` 无发布者也无订阅者
- `CredibilityComputedEvent` 在 `credibility_checker.py:142` 有发布，可保留供未来使用

## Risks / Trade-offs

| 风险 | 缓解措施 |
|------|----------|
| 删除 Thread 类后，直接调用这些类的代码会失败 | Grep 搜索确认无直接调用；保留核心方法在 Repo 中 |
| 注入 vector_repo/entity_repo 可能引入新 bug | 运行完整测试套件验证 |
| retrieval 组件接入可能影响现有 search API | 作为新方法添加，不影响现有 `search()` 方法 |
| 删除事件类型可能影响未来扩展 | 事件类型定义简单，可在需要时重新添加 |

## Migration Plan

1. **Phase 1: 代码清理**（低风险）
   - 删除 3 个 Thread 类
   - 删除 2 个未使用事件类型
   - 运行测试验证

2. **Phase 2: 功能增强**（中风险）
   - 注入 vector_repo 和 entity_repo
   - 添加实体链接发现注释
   - 运行测试验证

3. **Phase 3: API 扩展**（低风险）
   - 在 memory_service 中添加 `search_with_context()` 方法
   - 运行测试验证

每个阶段完成后单独提交，便于回滚。

## Open Questions

1. **vector_repo 的具体实现选择** - 是否使用现有的 `VectorRepo` 或需要新实现？
2. **entity_repo 的依赖** - 是否需要 `EntityGraphRepo` 或其他实现？
3. **retrieval 组件的 API 设计** - `search_with_context()` 的具体参数和返回值？

这些问题将在 specs 阶段详细定义。