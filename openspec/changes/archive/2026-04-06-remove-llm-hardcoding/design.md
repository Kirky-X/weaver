## Context

当前 LLM 客户端提供了两种调用方式：
1. **显式标签**: `embed("embedding.aiping.Qwen3-...", texts)` — 需要硬编码标签
2. **配置路由**: `embed_default(texts)` — 使用 `llm.toml` 中的配置

`llm.toml` 已正确配置了 defaults 和 call-points：
```toml
[defaults.embedding]
label = "embedding.aiping.Qwen3-Embedding-0.6B"
fallbacks = ["embedding.ollama.qwen3-embedding:0.6b"]
```

但代码中 8 处使用了硬编码标签，绕过了配置系统。

## Goals / Non-Goals

**Goals:**
- 统一使用 `embed_default()` 替换硬编码标签
- 保持 API 行为不变（向后兼容）
- 使模型配置完全通过 `llm.toml` 管理

**Non-Goals:**
- 不修改 `llm.toml` 配置文件
- 不修改其他正常使用 `call_at()` 或 `embed_default()` 的代码
- 不修改 LLM 客户端接口

## Decisions

### 决策 1: 使用 `embed_default()` 而非 `call_at("embedding", ...)`

**选择**: `embed_default()`

**原因**:
- `embed_default()` 内部已调用 `get_default(LLMType.EMBEDDING)`，直接使用 `[defaults.embedding]` 配置
- 更简洁，语义更清晰
- 已有代码（如 `container.py:874`）使用此模式

**备选方案**: `call_at(CallPoint.EMBEDDING, payload)`
- 更复杂，需要构造 payload 结构
- 适用于需要 prompt 模板的场景，embedding 不需要

### 决策 2: 不添加额外的错误处理

**选择**: 保持现有错误处理逻辑

**原因**:
- `embed_default()` 内部已有 fallback 机制
- 如果主 provider 失败，自动切换到 `fallbacks` 中的 ollama
- 上层代码已有 try/except 处理（如 `search.py:128`）

## Risks / Trade-offs

| 风险 | 缓解措施 |
|------|----------|
| `embed_default()` 返回零向量（缓存未命中时） | 已有逻辑处理：`[e or [0.0] * 1024 for e in all_embeddings]` |
| 配置文件缺失 `[defaults.embedding]` | 启动时验证，`LLMClient.create_from_config()` 会失败 |
| 模型名称不一致导致向量维度变化 | 配置中的模型与硬编码的相同，维度一致（1024）|

## Migration Plan

无需迁移 — 这是一个内部重构，API 行为不变。

**验证步骤**:
1. 重启服务
2. 运行 `temp/test_all_apis.py` 验证所有端点
3. 确认 `search_articles` 仍返回 200