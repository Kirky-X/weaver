## Goals / Non-Goals

### Goals
- 清理代码库中已确认的幽灵文件和空目录
- 修复 Memory 模块的关键功能缺陷使其可正常工作
- 确保所有剩余模块有明确的集成点

### Non-Goals
- 不重构模块间的架构（保持现有结构）
- 不新增业务功能
- 不修改 API 接口或数据库 schema

## Decisions

1. **幽灵文件直接删除** — 无断引用，可安全删除
   - `ingestion/processor.py`: container.py 使用 `domain/processor.py`
   - `storage/llm_usage_buffer.py`: container.py 使用 `analytics/llm_usage/buffer.py`
   - `knowledge/graph/writer.py`: 0 引用

2. **GraphPruner 暂时删除** — 已实现但无调用方，优先清理而非强行接入，待有明确需求时再引入

3. **Memory embedding 修复策略** — 使用 VectorRepo 已有的 embedding 能力替代占位符，而非引入新的 embedding 服务

4. **Memory → Pipeline 集成暂不实施** — 需要更深入的设计（事件模型、数据流），作为独立变更处理

5. **分阶段提交** — 按风险从低到高：先删除幽灵 → 修复属性引用 → 修复 embedding → 修复 LadybugWriter

## Risk / Trade-offs

| 风险 | 缓解措施 |
|------|---------|
| 删除文件后测试断引用 | 先 grep 验证 0 引用，再删除 |
| 修改 container.py 影响启动流程 | 逐个修复，每步验证 |
| embedding 修复可能影响 Memory 检索质量 | 使用 VectorRepo 保证一致性 |
| LadybugWriter 参数缺失导致关系类型未标准化 | 传入与 Neo4jWriter 相同的 normalizer |
