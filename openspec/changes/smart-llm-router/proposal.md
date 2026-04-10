## Why

当前的 LLM 路由仅依赖静态 fallback 链（TOML 中配置的固定顺序），无法根据实时性能数据（延迟、成功率、成本）做智能选择。随着新增 provider 和模型，手动维护 fallback 链变得越来越低效且容易出错。同时，缺少模型对比评测机制，无法量化评估不同模型在同一任务上的表现差异。

## What Changes

- 引入 **SmartRouter** 作为统一路由门面，协调规则检测管道和多维权重评分引擎
- 用动态评分排序替代固定 fallback 链，评分维度：editorial（预设优先级）、reliability（历史成功率）、cost（预估成本）、latency（历史延迟）
- 新增 **LiveConfig** 支持 TOML 配置文件热更新，无需重启服务
- 新增 **ExperienceStore** 订阅现有 LLMUsageEvent 流，实时记录每个 (call_point, provider, model) 三元组的运行经验
- 新增 **EvalRunner** 影子调用机制，按采样率并行发送请求到对比模型，结果写入 Redis 缓冲 → relational_pool 聚合
- 增强 **CircuitBreaker** 支持慢请求也纳入熔断考量（不仅是失败）
- **llm.toml** 配置扩展：新增 `[routing.<call_point>]` 段（mode + weights + bandit）和 `[eval]` 段
- 现有 LLMClient.call() / call_at() API 向后兼容，显式 label 调用保持直通行为

## Capabilities

### New Capabilities
- `model-routing`: 多维权重评分模型选择，按模式（auto/fast/best）动态调整权重，生成排序后的 fallback 链
- `live-config`: LLM 配置文件热更新，watchfiles 监控 TOML 变更，原子替换内存配置
- `model-experience`: 模型运行经验记录，订阅 LLMUsageEvent，实时统计成功率/延迟/成本，支持 Thompson Sampling 探索
- `model-evaluation`: 影子调用评测，按采样率并行发送请求到对比模型，对比结果持久化到 relational_pool

### Modified Capabilities
- `llm-config`: 新增 routing 段和 eval 段配置 schema，保持现有 providers/defaults/call-points 段不变

## Impact

- `src/core/llm/` — 新增 5 个文件（smart_router.py, model_selector.py, experience.py, live_config.py, eval_runner.py），增强 circuit_breaker.py
- `src/core/llm/client.py` — 集成 SmartRouter，保持现有 API 兼容
- `src/core/llm/pool.py` — ProviderPool.execute() 接入 ModelSelector
- `src/core/event/bus.py` — 新增 LLMCompareEvent（评测用）
- `src/core/llm/types.py` — 新增 RoutingMode, CandidateScore, ExperienceData, EvalConfig
- `config/llm.toml` / `config/llm.example.toml` — 扩展配置 schema
- `config/settings.toml` — 新增 eval 开关
- 现有调用点（classifier, entity_extractor 等）无需修改
