## 1. ExplicitInterfaceMixin

- [x] 1.1 在 `src/core/protocols/validation.py` 中新增 `ExplicitInterfaceMixin` 类，实现 `__init_subclass__` 钩子
- [x] 1.2 编写 `tests/unit/core/protocols/test_explicit_interface_mixin.py`，覆盖正常验证、缺失方法报错、多 Protocol 声明
- [x] 1.3 运行测试验证通过

## 2. Tokenizer 配置化

- [x] 2.1 在 `src/config/settings.py` 的 LLM 相关 Settings 中新增 `tokenizer_model: str | None = None` 字段
- [x] 2.2 修改 `src/core/llm/token_budget.py`，`TokenBudgetManager.__init__` 优先读取配置，保留 "gpt-4o" 作为 fallback
- [x] 2.3 确认 Container 中 TokenBudgetManager 的创建方式兼容新参数
- [x] 2.4 编写测试验证配置优先级和 fallback 行为
- [x] 2.5 运行测试验证通过

## 3. DuckDB Handler 测试

- [x] 3.1 读取 `src/core/db/` 下 DuckDB 相关处理器代码，了解公共 API
- [x] 3.2 确认 `test_duckdb_pool.py` 已存在（原报告称 `test_duckdb_handler.py` 缺失为误报）
- [x] 3.3 已有连接管理、查询执行、事务支持、异步 session 测试（296 行，15 个测试）
- [x] 3.4 运行测试验证通过
