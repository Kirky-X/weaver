## 1. 幽灵文件与空目录清理

- [x] 1.1 删除 `src/modules/ingestion/processor.py`（与 `domain/processor.py` 重复的幽灵文件）
- [x] 1.2 删除 `src/modules/storage/llm_usage_buffer.py`（与 `analytics/llm_usage/buffer.py` 重复的幽灵文件）
- [x] 1.3 删除 `src/modules/knowledge/graph/writer.py`（Writer 类 0 引用的幽灵文件）
- [x] 1.4 从 `src/modules/knowledge/graph/__init__.py` 移除 Writer 导出
- [x] 1.5 删除 `src/modules/analytics/metrics/` 空占位符目录
- [x] 1.6 删除 `src/modules/knowledge/metrics/` 空占位符目录
- [x] 1.7 删除 `src/modules/knowledge/graph/graph_pruner.py`（孤立模块，无调用者）
- [x] 1.8 从 `src/modules/knowledge/graph/__init__.py` 移除 GraphPruner/PruneResult 导出
- [x] 1.9 运行测试验证删除后无断引用：`uv run pytest --tb=short -q 2>&1 | head -30`

## 2. Container 修复

- [x] 2.1 修复 `container.py` L767 `self._neo4j_pool` → 使用 `self.graph_pool()` 方法获取图数据库池
- [x] 2.2 修复 `container.py` 中 LadybugWriter 初始化，传入 `relation_type_normalizer` 参数（与 Neo4jWriter 一致）
- [x] 2.3 替换 `EmbeddingServiceWrapper` 占位符实现，接入 LLM client 的 embed_default 方法
- [x] 2.4 运行 container 相关测试验证修复：3133 passed

## 3. Memory → Pipeline 集成

- [x] 3.1 定义 `MemoryIngestEvent` 事件类型（在 `core/event/bus.py` 中）
- [x] 3.2 在 Pipeline 末尾（CheckpointCleanup 节点之后）发布 `MemoryIngestEvent`
- [x] 3.3 在 `container.py` 中订阅 `MemoryIngestEvent`，调用 `memory_service.ingest()`
- [x] 3.4 确保 Memory 服务不可用时 Pipeline 正常运行（安全跳过）
- [x] 3.5 编写 Memory 集成测试：4 passed
