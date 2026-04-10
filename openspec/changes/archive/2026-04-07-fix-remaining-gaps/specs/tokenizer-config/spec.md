## Requirements

### REQ-001: tokenizer_model 配置项

`LLMSettings` 或 `EntitySettings` 应包含可选的 `tokenizer_model: str | None` 配置项。

- 默认值为 `None`（表示使用 fallback "gpt-4o"）
- 配置位于 `[llm]` 段下的 `tokenizer_model` 字段

### REQ-002: TokenBudgetManager 配置化

`TokenBudgetManager.__init__` 应优先从 settings 读取 `tokenizer_model`。

- 当 `settings.llm.tokenizer_model` 有值时使用该值
- 当配置为 `None` 时使用 "gpt-4o" 作为默认值
- tiktoken 降级逻辑不变（未知模型 fallback 到 cl100k_base）

### REQ-003: 向后兼容

- 无配置文件时不改变任何行为
- 不修改 `TokenBudgetManager` 的公共 API
- 所有调用点不需要修改
