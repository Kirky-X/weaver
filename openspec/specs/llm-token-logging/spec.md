## ADDED Requirements

### Requirement: Chat 调用输出完整 token 日志

`LiteLLMCaller.chat()` 方法 SHALL 在 debug 级别输出包含 `input_tokens`、`output_tokens`、`total_tokens` 的日志。

#### Scenario: Chat 调用成功
- **WHEN** chat 调用完成并返回 usage 信息
- **THEN** 输出 debug 日志 `llm_token_usage`，包含 type、model、input_tokens、output_tokens、total_tokens、latency_ms

### Requirement: Embedding 调用输出 token 日志

`LiteLLMCaller.embed()` 方法 SHALL 在 debug 级别输出包含 token 使用信息的日志。

#### Scenario: Embedding 调用成功
- **WHEN** embedding 调用完成并返回 usage 信息
- **THEN** 输出 debug 日志 `llm_token_usage`，包含 type、model、input_tokens、output_tokens=0、total_tokens、latency_ms、num_texts

### Requirement: Rerank 调用输出估算 token 日志

`LiteLLMCaller.rerank()` 方法 SHALL 使用 `litellm.utils.token_counter()` 估算 token 数，并在 debug 级别输出日志。

#### Scenario: Rerank 调用成功
- **WHEN** rerank 调用完成
- **THEN** 使用 token_counter 估算 query + documents 的 token 数
- **THEN** 输出 debug 日志 `llm_token_usage`，包含 type、model、input_tokens（估算）、output_tokens=0、total_tokens（估算）、latency_ms、num_documents