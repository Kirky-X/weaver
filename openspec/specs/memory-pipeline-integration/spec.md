## ADDED Requirements

### Requirement: Pipeline 处理完成后触发 Memory 写入
Pipeline 处理完成 SHALL 通过 EventBus 发布事件，使 MemoryService 接收到处理结果并写入记忆图谱。

实现方式：Pipeline 的最后一个节点（CheckpointCleanup）处理完成后，通过 EventBus 发布 `MemoryIngestEvent`，MemoryService 订阅此事件。

#### Scenario: Pipeline 处理结果写入记忆图谱
- **WHEN** Pipeline 成功处理一批文章
- **THEN** MemoryService 接收到包含处理结果的事件，调用 `ingest()` 写入记忆图谱

#### Scenario: Memory 服务不可用时 Pipeline 正常运行
- **WHEN** Memory 服务未初始化（如 Neo4j 不可用）
- **THEN** Pipeline 正常完成处理，跳过 Memory 写入，记录 info 日志
