## Why

模块审计发现 3 个幽灵文件（遗留重复代码）、1 个孤立模块（已实现未接入）、2 个空占位符目录、以及 4 个功能缺陷（Memory 系统的 embedding 占位符、neo4j_pool 属性引用错误、Memory 未接入 Pipeline、LadybugWriter 缺少参数）。这些问题导致代码库膨胀、Memory 语义检索完全无效、LadybugDB 路径行为不一致。现在修复可避免技术债积累。

## What Changes

- 删除 3 个幽灵文件：`ingestion/processor.py`、`storage/llm_usage_buffer.py`、`knowledge/graph/writer.py`
- 从 `knowledge/graph/__init__.py` 移除 Writer 导出
- 清理 2 个空占位符目录：`analytics/metrics/`、`knowledge/metrics/`
- 接入或删除孤立模块 `knowledge/graph/graph_pruner.py`
- 修复 `container.py` 中 `self._neo4j_pool` 属性引用（改为 `self.graph_pool()`）
- 修复 `EmbeddingServiceWrapper` 占位符（接入实际 embedding 服务）
- 修复 `LadybugWriter` 初始化缺少 `relation_type_normalizer` 参数
- 评估 Memory → Pipeline 集成方案

## Capabilities

### New Capabilities
- `memory-pipeline-integration`: 将 MemoryService.ingest() 接入处理 Pipeline，使 Pipeline 处理结果写入记忆图谱
- `embedding-service`: 替换占位符 EmbeddingServiceWrapper，提供真实的文本嵌入向量生成能力

### Modified Capabilities
<!-- 无现有 spec 需要修改 -->

## Impact

- **代码删除**: 3 个幽灵文件 + 2 个空目录，约 500+ 行冗余代码
- **container.py**: 修改 `init_memory_service()` 方法，修复属性引用和 embedding 服务
- **knowledge/graph/__init__.py**: 移除 Writer/GraphPruner 导出
- **storage/ladybug/**: 修复 Writer 初始化参数
- **modules/processing/pipeline/**: 可能需要添加 Memory 写入节点（取决于集成方案）
- **测试**: 需要验证删除后无断引用，验证 embedding 服务替换后的行为
