## Context

项目使用 `LiteLLMCaller` 作为统一的 LLM 调用封装，支持 chat、embedding、rerank 三种类型。当前日志在 debug 级别记录了部分 token 信息，但不完整。

**现有问题：**
- `chat()` 有 `input_tokens` 和 `output_tokens`，缺少 `total_tokens`
- `embed()` 有日志但无 token 信息
- `rerank()` 无 token 信息（API 不返回）

**依赖：** `litellm.utils.token_counter()` 已集成在项目中，可用于 token 估算。

## Goals / Non-Goals

**Goals:**
- 在所有 LLM 调用类型中输出完整的 token 使用日志
- 保持统一的日志格式
- 使用 debug 级别，不影响正常运行

**Non-Goals:**
- 不修改 `TokenUsage` 数据结构
- 不影响 `LLMClient` 层的日志
- 不添加新的依赖库

## Decisions

### 1. Token 来源策略

| 调用类型 | Token 来源 | 原因 |
|---------|-----------|------|
| chat | API 返回的 `usage` | 真实数据，最准确 |
| embedding | API 返回的 `usage` | 真实数据 |
| rerank | `litellm.utils.token_counter()` 估算 | API 不返回 token 信息 |

**替代方案：** 使用 tiktoken 库进行估算。弃用原因：需要额外依赖，且 litellm 已内置 token_counter。

### 2. 日志格式

采用项目现有的结构化 key-value 格式：

```python
log.debug(
    "llm_token_usage",
    type="chat",
    model="gpt-4o",
    input_tokens=256,
    output_tokens=128,
    total_tokens=384,
    latency_ms=150.5,
)
```

### 3. 实现位置

在 `LiteLLMCaller` 层（`src/core/llm/caller.py`）实现，因为：
- 能直接访问 API 返回的 usage 信息
- 与调用逻辑内聚，便于维护

## Risks / Trade-offs

| 风险 | 缓解措施 |
|-----|---------|
| rerank token 估算不准确 | 日志标记为估算值，明确告知用户 |
| token_counter 调用增加开销 | 仅在 debug 级别启用，生产环境影响最小 |