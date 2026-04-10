# 代码审查修复方案

## Why

基于多维度代码审查（安全性、架构、性能、代码质量、业务逻辑），发现若干需要修复的问题。其中部分原报告的CRITICAL问题经验证后实际风险较低，但仍存在MEDIUM级别问题需要解决，以确保代码质量和类型安全。

## What Changes

### 类型安全修复
- 修复 `src/core/llm/types.py` 中 dataclass 字段类型注解错误（`list[str] = None` → `list[str] | None = None`）
- 修复 `src/core/utils/sanitize.py` 中 `sanitize_dict` 返回类型注解（`dict[str, str]` → `dict[str, Any]`）

### 安全加固
- 移除 `src/config/settings.py` 中 Neo4j 硬编码默认密码，强制通过环境变量配置

### 代码质量改进
- 审查并改进 87 处 `except Exception` 异常捕获，添加适当的日志记录
- Container 类拆分建议（1242行，作为后续架构优化任务）

### 性能优化
- 添加缺失的数据库索引（根据实际查询模式评估）
- LLM Usage Buffer 批量合并优化建议

### 架构改进
- Fast Path 失败补偿机制（设计层面，Slow Path 可修复不一致）

## Capabilities

### New Capabilities

- `type-annotation-fixes`: 修复类型注解错误，确保 mypy 类型检查通过
- `exception-handling-improvements`: 改进异常处理，添加日志记录
- `security-default-removal`: 移除硬编码默认密码，强化安全配置

### Modified Capabilities

- `code-quality-improvements`: 扩展现有代码质量改进规范，新增异常处理最佳实践
- `security-hardening`: 扩展现有安全加固规范，新增默认密码移除要求

## Impact

### 直接影响
- `src/core/llm/types.py` - 类型注解修复
- `src/core/utils/sanitize.py` - 返回类型注解修复
- `src/config/settings.py` - 移除硬编码默认密码
- 多个模块的异常处理代码

### 验证影响
- 需运行 `mypy src --ignore-missing-imports` 验证类型检查
- 需运行 `uv run pytest tests/` 确保无回归

### 后续优化（P2/P3）
- Container 类拆分架构改进
- LLM Usage Buffer 批量合并
- 数据库索引优化

## Risk Assessment

| 风险 | 等级 | 缓解措施 |
|------|------|---------|
| 类型注解修改影响运行时 | LOW | 仅影响类型检查，不改变运行行为 |
| 移除默认密码影响开发环境 | MEDIUM | 提供 .env.example 指导，启动时检查 |
| 异常处理修改引入回归 | LOW | 保持原有异常处理逻辑，仅添加日志 |