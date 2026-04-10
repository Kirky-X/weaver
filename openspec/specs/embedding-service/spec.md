## ADDED Requirements

### Requirement: EmbeddingServiceWrapper 提供真实嵌入向量
container.py 中 `EmbeddingServiceWrapper` SHALL 使用实际的 embedding 服务生成文本嵌入向量，而非返回固定的零向量 `[0.0] * 384`。

实现方式：委托给 `VectorRepo` 已有的 embedding 能力（通过调用 `vector_repo.embed(text)` 或类似接口）。

#### Scenario: Memory 语义检索返回有意义的相似度分数
- **WHEN** Memory 服务执行语义搜索
- **THEN** embedding 向量非全零，语义相似度计算返回真实分数

#### Scenario: 无 embedding 服务时安全降级
- **WHEN** embedding 服务不可用
- **THEN** Memory 服务记录 warning 日志并禁用语义搜索路径，仅使用结构化搜索
