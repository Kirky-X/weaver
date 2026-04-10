## Why

当前 LLM 调用的日志中缺少完整的 token 使用信息，难以调试和监控 token 消耗。需要在 debug 级别输出详细的 token 统计，包括输入、输出和总 token 数。

## What Changes

- 在 `LiteLLMCaller.chat()` 补充 `total_tokens` 字段到现有日志
- 在 `LiteLLMCaller.embed()` 添加完整的 token 使用日志
- 在 `LiteLLMCaller.rerank()` 使用 `litellm.utils.token_counter()` 估算 token 并输出日志

## Capabilities

### New Capabilities

- `llm-token-logging`: 在 LLM 调用时输出 debug 级别的 token 使用日志

### Modified Capabilities

<!-- 无现有 capability 需要修改 -->

## Impact

- **代码修改**: `src/core/llm/caller.py`
- **依赖**: 使用已有的 `litellm.utils.token_counter()` 进行 token 估算
- **日志输出**: DEBUG 级别，不影响正常运行时的日志