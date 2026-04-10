## Why

归档方案实施状态验证发现 18 项方案中仅 3 项存在真实缺失，需修复以完成闭环。这三项分别是：`ExplicitInterfaceMixin` 工具类未创建（架构协议验证工具）、`token_budget.py` 中硬编码 "gpt-4o" 默认参数（缺乏配置化）、`test_duckdb_handler.py` 测试文件缺失（DuckDB 查询无测试覆盖）。

## What Changes

- 创建 `ExplicitInterfaceMixin` 工具类，提供运行时 Protocol 实现验证的便捷 mixin 方式
- 将 `token_budget.py` 中 `TokenBudgetManager.__init__` 的 `model: str = "gpt-4o"` 默认参数改为从配置读取，保留 tiktoken 编码查询的降级能力
- 创建 `tests/unit/core/db/test_duckdb_handler.py`，覆盖 DuckDB 处理器的查询、连接、错误处理等核心功能

## Capabilities

### New Capabilities

- `duckdb-handler-coverage`: DuckDB 处理器单元测试覆盖

### Modified Capabilities

- `explicit-interface-contract`: 新增 ExplicitInterfaceMixin 便捷工具类
- `llm-label-centralization`: token_budget.py 的 model 参数配置化

## Impact

- `src/core/protocols/` — 新增 mixin 类文件
- `src/core/llm/token_budget.py` — 修改默认参数为配置驱动
- `src/config/settings.py` — 可能新增 tokenizer_model 配置项
- `tests/unit/core/db/` — 新增测试文件
- 无破坏性变更，所有修改向后兼容
