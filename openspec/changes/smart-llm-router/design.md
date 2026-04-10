## Context

项目已有完整的 LLM 调用基础设施：
- `LLMClient` 统一调用入口，支持 label 路由和 fallback 链
- `ProviderPool` 管理单个 provider 的熔断、限速、并发
- `EventBus` + `LLMUsageEvent` 发射每次调用的指标
- `LLMUsageBuffer` → Redis 缓冲 → `LLMUsageRepo` → relational_pool 持久化
- `LLMFailureEvent` + `LLMFailureRepo` 失败记录

当前路由逻辑是静态的：TOML 中配置固定的 `[call-points.X]` primary + fallbacks 列表，按顺序逐个尝试。无法根据实时性能数据做动态选择，也无法评估哪个模型在特定任务上表现更好。

## Goals / Non-Goals

**Goals:**
- 用多维权重评分替代固定 fallback 链，综合 editorial/reliability/cost/latency 选择最优模型
- 支持三种路由模式（auto/fast/best），动态调整评分权重
- 模型经验数据实时积累，支持 Thompson Sampling 探索
- 影子调用评测机制，量化对比不同模型表现
- 配置热更新，无需重启
- 100% 向后兼容，显式 label 调用和 call_at 行为不变

**Non-Goals:**
- 不做难度分类器（UncommonRoute 的 classifier）— 调用点本身已隐含任务难度
- 不做隐私路由（ClawXRouter 的 S1/S2/S3）— 不涉及 PII 检测
- 不做 Benchmark 质量先验 — Phase 1 以运行时经验为主
- 不修改现有 llm.toml 的 providers/defaults/call-points 段结构

## Decisions

### D1: ExperienceStore — 内存为主，relational_pool 为源

**决策**: ExperienceStore 以内存计数器记录实时经验，启动时从 `LLMUsageRepo.get_summary()` 加载最近 24 小时的历史数据。不引入新存储。

**替代方案**: 纯 Redis — 多实例场景下更好，但当前单实例，Redis 已由 LLMUsageBuffer 占用。内存方案零依赖。

**理由**: 项目已有 `CashewsRedisFallback` 作为 Redis 不可用时的兜底，ExperienceStore 同理设计为内存优先。多实例时通过 Redis 共享聚合数据。

### D2: 评分引擎嵌入 ProviderPool.execute()

**决策**: ModelSelector 不替代 ProviderPool.execute()，而是作为其前置步骤。ProviderPool.execute() 接收已排序的 label 列表后，仍按顺序尝试（保持现有 fallback 语义），但排序由 Selector 完成。

```
call_at("classifier")
  → SmartRouter.route()
    → ModelSelector.select(candidates) → [best, fb1, fb2]
  → ProviderPool.execute([best, fb1, fb2])
```

**理由**: ProviderPool 已完善的熔断/限速/重试逻辑不需要重写。Selector 只负责"谁排前面"。

### D3: 热更新用 watchfiles

**决策**: watchfiles 库监控 `config/llm.toml` 变更 → 原子加载 → 验证 → 热替换内存配置。无效配置拒绝并保留上次有效配置。

**理由**: 项目已有 watchfiles 依赖（或可零成本引入）。watchfiles 比 inotify 跨平台兼容更好。

### D4: 影子调用不阻塞主链路

**决策**: EvalRunner 在主调用完成后异步发送影子请求。主链路的响应时间和行为不受影响。

```
主调用 ──▶ 返回给用户
              │ (async, fire-and-forget)
影子调用 ──▶ 对比模型 ──▶ 记录结果
```

**理由**: 评测是 QA 行为，不能影响生产链路。

### D5: 熔断器增强 — 慢请求纳入

**决策**: 在现有 pybreaker 失败计数基础上，增加"慢请求"标记。连续 N 次 P95 延迟超过阈值的请求视为"降级"，降低 editorial 分数但不打开熔断器。

**理由**: 有些模型没失败但极慢，固定 fallback 链不会跳过它。慢请求降级让评分引擎自动降低其排名。

### D6: relational_pool 抽象，不绑定具体数据库

**决策**: 所有评测数据写入使用 `RelationalPool` 协议接口，不直接 import SQLAlchemy 或任何具体驱动。评测聚合表和 LLMUsageHourly 共享同一套 ORM 模式。

**理由**: 项目已有 PostgreSQL ↔ DuckDB 故障转移架构，新表必须遵守协议抽象。

## Risks / Trade-offs

| 风险 | 缓解措施 |
|------|---------|
| 冷启动：新部署时无经验数据 | editorial 分数（TOML 配置顺序）兜底，warmup_calls 强制探索 |
| 评分权重调参困难 | 提供 auto/fast/best 三套预设，用户无需手动调参 |
| 热更新竞态：TOML 写入中读取到半截数据 | 用户侧需原子写入（tmp + rename），LiveConfig 侧做 pydantic 验证 |
| 影子调用增加 LLM 负载 | sample_rate 默认 0.1（10%），可通过配置关闭 |
| 多实例部署时内存经验不一致 | Phase 1 容忍短暂不一致（熔断器本身就是 per-instance），Phase 2 通过 Redis 共享 |
| 新依赖 watchfiles | 项目已有类似库，或可在现有 asyncio 轮询基础上实现 |

## Migration Plan

1. **Phase 1**（新增文件，零风险）：types.py 扩展、experience.py、live_config.py
2. **Phase 2**（增强现有）：ProviderPool.execute() 接入 ModelSelector，向后兼容
3. **Phase 3**（集成）：LLMClient 接入 SmartRouter，保留显式 label 直通
4. **Phase 4**（评测）：EvalRunner 独立开关，默认关闭

**回滚**: 任何阶段失败时，SmartRouter 可降级到现有 LabelRouter 行为（通过 feature flag `routing.enabled = false`）。

## Open Questions

- **Q**: 是否需要为每个 call_point 单独配置 bandit 参数？
  **A**: Phase 1 用全局默认，Phase 2 再支持 per-call-point 覆盖。

- **Q**: EvalRunner 的对比模型从哪里来？
  **A**: 从 TOML `[eval]` 段配置，指定 `baseline_model` 和 `candidate_models`。
