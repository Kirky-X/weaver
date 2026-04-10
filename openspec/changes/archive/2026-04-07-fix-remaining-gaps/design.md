## Context

验证报告确认 18 项归档方案中仅 3 项存在真实缺失：

1. `ExplicitInterfaceMixin` — `src/core/protocols/validation.py` 已有 `assert_implements()` 函数，但缺少面向类的 mixin 验证方式
2. `token_budget.py` 硬编码 — `TokenBudgetManager.__init__` 使用 `model: str = "gpt-4o"` 作为 tiktoken 编码查询的默认值，无配置化路径
3. `test_duckdb_handler.py` — DuckDB 查询处理器无任何单元测试

当前 `src/core/protocols/` 目录下已有 `pools.py`、`repositories.py`、`services.py`、`validation.py` 等协议文件。

## Goals / Non-Goals

**Goals:**

- 补齐 ExplicitInterfaceMixin，提供类级别的 Protocol 验证能力
- 将 token_budget 的 model 默认值配置化，消除硬编码
- 为 DuckDB handler 创建完整单元测试

**Non-Goals:**

- 不重构现有协议架构
- 不修改 tiktoken 的编码策略（保持 cl100k_base 降级）
- 不修改 DuckDB handler 本身的实现

## Decisions

### 1. ExplicitInterfaceMixin 实现

**决策**: 在 `src/core/protocols/validation.py` 中新增 `ExplicitInterfaceMixin` 类。

**理由**: `validation.py` 已有 `assert_implements()` 函数，mixin 放在同一模块保持内聚。mixin 提供 `__init_subclass__` 钩子，在类定义时自动验证是否正确实现了声明的 Protocol。

**替代方案**: 独立文件 — 增加模块碎片化，不必要。

### 2. token_budget.py 配置化

**决策**: 新增 `settings.llm.tokenizer_model` 配置项（可选），`TokenBudgetManager` 优先从 settings 读取，保留 "gpt-4o" 作为最终 fallback。

**理由**: tiktoken 编码模型名与 LLM 调用模型名是不同概念，需要独立配置。保留 fallback 确保无配置时仍可工作。

**替代方案**: 直接使用 LLM 配置中的模型名 — 不合适，tiktoken 模型名和 API 模型名不一定一致。

### 3. DuckDB handler 测试

**决策**: 创建 `tests/unit/core/db/test_duckdb_handler.py`，使用内存 DuckDB 实例进行测试。

**理由**: DuckDB 支持内存模式，无需外部服务，测试速度快且隔离。

## Risks / Trade-offs

- [Mixin 增加隐式行为] → `__init_subclass__` 是标准 Python 机制，且仅验证不修改行为
- [新增配置项增加复杂度] → tokenizer_model 为可选配置，无配置时行为与当前完全一致
- [DuckDB 内存测试可能遗漏磁盘模式问题] → 核心查询逻辑一致，磁盘 I/O 属于集成测试范畴
