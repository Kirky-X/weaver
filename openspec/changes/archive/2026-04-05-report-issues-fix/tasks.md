## 1. Analytics 模块清理

- [x] 1.1 删除 `src/modules/analytics/llm_failure/cleanup.py` 中的 `LLMFailureCleanupThread` 类
- [x] 1.2 删除 `src/modules/analytics/llm_usage/aggregator.py` 中的 `LLMUsageAggregatorThread` 和 `RawCleanupThread` 类
- [x] 1.3 更新 `src/modules/analytics/__init__.py` 移除已删除类的导出
- [x] 1.4 运行测试验证 Analytics 模块功能正常

## 2. 事件类型清理

- [x] 2.1 从 `src/core/event/bus.py` 删除 `FallbackEvent` 类
- [x] 2.2 从 `src/core/event/bus.py` 删除 `PipelineStageCompletedEvent` 类
- [x] 2.3 更新 `src/core/event/__init__.py` 移除已删除事件的导出
- [x] 2.4 运行测试验证事件系统正常

## 3. Memory 服务依赖注入

- [x] 3.1 在 `src/container.py` 中添加 `vector_repo` 创建逻辑
- [x] 3.2 在 `src/container.py` 中添加 `entity_repo` 创建逻辑
- [x] 3.3 修改 `MemoryIntegrationService.__init__()` 接受 `vector_repo` 和 `entity_repo` 参数
- [x] 3.4 在 `container.py` 的 `init_memory_service()` 中注入 `vector_repo` 和 `entity_repo`
- [x] 3.5 运行测试验证 Memory 服务初始化正常

## 4. 实体链接发现注释

- [x] 4.1 在 `src/modules/memory/evolution/slow_path.py` 中添加详细注释说明 `entity_links_added = 0` 的原因
- [x] 4.2 添加 TODO 注释说明完整实现所需的依赖

## 5. Retrieval 组件接入

- [x] 5.1 在 `src/modules/memory/integration/memory_service.py` 中添加 `search_with_context()` 方法
- [x] 5.2 在 `search_with_context()` 中集成 `EntityAggregator`
- [x] 5.3 在 `search_with_context()` 中集成 `NarrativeSynthesizer`
- [x] 5.4 在 `search_with_context()` 中集成 `SearchResponseBuilder`
- [x] 5.5 添加 `search_with_context()` 的单元测试
- [x] 5.6 运行测试验证检索功能正常

## 6. 最终验证

- [x] 6.1 运行完整测试套件 `uv run pytest`
- [x] 6.2 验证测试覆盖率 >= 80%
- [x] 6.3 运行 ruff check 验证代码质量
- [x] 6.4 更新相关文档（如有）