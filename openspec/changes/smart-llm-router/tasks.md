## 1. Types & Configuration

- [x] 1.1 Extend `src/core/llm/types.py` with RoutingMode, CandidateScore, ExperienceData, EvalConfig, RoutingInfeasibleError
- [x] 1.2 Add `LLMCompareEvent` to `src/core/event/bus.py`
- [x] 1.3 Extend `src/core/llm/config.py` (LLMSettings) to parse `[routing.<call_point>]` and `[eval]` sections
- [x] 1.4 Update `config/llm.example.toml` with routing and eval section examples
- [x] 1.5 Add `watchfiles` to pyproject.toml dependencies

## 2. ExperienceStore

- [x] 2.1 Create `src/core/llm/experience.py` with ExperienceStore class
- [x] 2.2 Implement in-memory counter tracking for (call_point, provider, model) triplet
- [x] 2.3 Subscribe ExperienceStore to LLMUsageEvent via EventBus
- [x] 2.4 Implement startup warmup: load last 24h from LLMUsageRepo via relational_pool
- [x] 2.5 Implement Thompson Sampling Beta distribution (alpha/beta params, sample method)
- [x] 2.6 Implement experience data decay (24h = 50% weight, 7d = excluded)
- [x] 2.7 Write unit tests for ExperienceStore scoring and Thompson Sampling

## 3. LiveConfig

- [x] 3.1 Create `src/core/llm/live_config.py` with LiveConfig class
- [x] 3.2 Implement watchfiles-based TOML monitoring
- [x] 3.3 Implement atomic two-phase config swap (validate then replace)
- [x] 3.4 Implement config validation error reporting with previous config fallback
- [x] 3.5 Wire LiveConfig into LLMSettings initialization
- [x] 3.6 Write unit tests for hot reload (valid/invalid TOML, atomic swap)

## 4. ModelSelector

- [x] 4.1 Create `src/core/llm/model_selector.py` with ModelSelector class
- [x] 4.2 Implement four-dimension scoring: editorial, reliability, cost, latency
- [x] 4.3 Implement dimension normalization (min-max scaling to [0, 1])
- [x] 4.4 Implement mode-based weight configuration (auto/fast/best)
- [x] 4.5 Implement capability filtering (chat/embedding/rerank)
- [x] 4.6 Implement circuit breaker state filtering (exclude OPEN providers)
- [x] 4.7 Implement Thompson Sampling exploration bonus integration
- [x] 4.8 Implement RoutingInfeasibleError for empty candidate sets
- [x] 4.9 Wire ModelSelector into ProviderPool.execute() as pre-sort step (via SmartRouter)
- [x] 4.10 Write unit tests for scoring, normalization, mode weights, filtering

## 5. SmartRouter

- [x] 5.1 Create `src/core/llm/smart_router.py` with SmartRouter facade class
- [x] 5.2 Implement route(call_point) → sorted label list
- [x] 5.3 Implement per-call-point routing mode resolution
- [x] 5.4 Implement fallback to existing LabelRouter when routing is disabled
- [x] 5.5 Integrate SmartRouter into LLMClient.call_at()
- [x] 5.6 Verify backward compatibility: explicit label calls bypass SmartRouter
- [x] 5.7 Write integration tests for SmartRouter end-to-end

## 6. Circuit Breaker Enhancement

- [x] 6.1 Add slow_request tracking to ProviderCircuitBreaker
- [x] 6.2 Add configurable slow_threshold (default: 0.5 × timeout)
- [x] 6.3 Implement editorial score reduction after consecutive slow requests
- [x] 6.4 Ensure CircuitOpenError is raised immediately when circuit is OPEN
- [x] 6.5 Update ProviderPool to handle slow request degradation
- [x] 6.6 Write unit tests for slow request tracking and degradation

## 7. EvalRunner

- [x] 7.1 Create `src/core/llm/eval_runner.py` with EvalRunner class
- [x] 7.2 Implement shadow call triggering with configurable sample_rate
- [x] 7.3 Ensure shadow calls are fire-and-forget (async, non-blocking)
- [x] 7.4 Implement LLMCompareEvent publishing on shadow call completion
- [x] 7.5 Create Redis buffer for comparison results (follow LLMUsageBuffer pattern)
- [x] 7.6 Implement aggregation to relational_pool (follow LLMUsageRepo pattern)
- [x] 7.7 Implement comparison query API (win rate, latency delta)
- [x] 7.8 Wire EvalRunner into LLMClient.call_at() when eval is enabled
- [x] 7.9 Write unit tests for EvalRunner isolation and event publishing

## 8. Integration & Verification

- [x] 8.1 Update Container.init_llm() to wire ExperienceStore, LiveConfig, SmartRouter, EvalRunner
- [x] 8.2 Add LiveConfig watcher start to Container.startup()
- [x] 8.3 Add ExperienceStore EventBus subscription to Container.startup()
- [x] 8.4 Update Container.shutdown() to stop LiveConfig watcher
- [x] 8.5 Run full test suite: `uv run pytest tests/ -v` (54 LLM tests passed, 4141 total passed)
- [x] 8.6 Run linting: `uv run ruff check src/core/llm/`
- [x] 8.7 Run formatting: `uv run ruff format src/core/llm/`
- [x] 8.8 Verify backward compatibility: all existing call_at() calls work unchanged
