## 1. 代码修改

- [x] 1.1 修改 `LiteLLMCaller.chat()` 添加 `total_tokens` 字段到日志
- [x] 1.2 修改 `LiteLLMCaller.embed()` 添加完整的 token 使用日志
- [x] 1.3 修改 `LiteLLMCaller.rerank()` 添加 token 估算逻辑和日志

## 2. 验证

- [x] 2.1 运行相关单元测试确保无回归
- [x] 2.2 验证日志输出格式正确