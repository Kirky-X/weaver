## Why

`scripts/` 目录存在大量功能重复的脚本，14 个脚本中约 70% 的代码是重复的基础设施初始化、数据库连接和验证逻辑。这导致：
1. 维护成本高 — 相同逻辑分散在多个文件
2. 容易出现不一致 — 修复需同步多处
3. 已有模块未复用 — `src/core/health/env_validator.py` 等模块已实现核心功能，但脚本未使用

## What Changes

### 合并操作

| 新脚本 | 合并来源 | 代码量变化 |
|--------|----------|------------|
| `test_pipeline.py` | `test_pipeline_duckdb.py`, `test_pipeline_rss.py`, `test_pipeline_duckdb_ladybug.py` | 1234 → ~200 行 |
| `test_api.py` | `run_36kr_full_pipeline.py`, `http_audit.py` | 906 → ~300 行 |
| `evaluate.py` | `run_performance_tests.py`, `evaluate_search_quality.py` | 591 → ~250 行 |
| `manage.py` | `validate_environment.py`, `seed_relation_types.py` | 1136 → ~80 行 |

### 删除文件

- `test_pipeline_duckdb.py` (430 行)
- `test_pipeline_rss.py` (498 行)
- `test_pipeline_duckdb_ladybug.py` (306 行)
- `run_36kr_full_pipeline.py` (562 行)
- `http_audit.py` (344 行)
- `run_performance_tests.py` (295 行)
- `evaluate_search_quality.py` (296 行)
- `validate_environment.py` (868 行)
- `seed_relation_types.py` (268 行)

### 保留文件

- `db_query.py` — 功能独立，3 个子命令已完善
- `build_nuitka.py` — 构建专用
- `check_logging_usage.py` — 开发工具
- `reset_test_env.sh` — Shell 脚本
- `start.sh` — 启动脚本

### **BREAKING** 变更

- 旧脚本路径不再可用，需更新 CI/CD 和文档中的调用命令
- CLI 参数格式变化：统一使用子命令模式

## Capabilities

### New Capabilities

- `unified-pipeline-test`: 统一的 pipeline 测试脚本，支持 `--mode newsnow|rss|strategy`
- `unified-api-test`: 统一的 API 测试脚本，支持 `e2e` 和 `audit` 子命令
- `unified-evaluate`: 统一的评估脚本，支持 `hnsw` 和 `search` 子命令
- `unified-manage`: 统一的管理脚本，支持 `validate` 和 `seed` 子命令

### Modified Capabilities

无。此次变更为内部重构，不影响外部 API。

## Impact

### 代码影响

- **删除**: 9 个脚本文件，共 ~4200 行
- **新增**: 4 个合并脚本，共 ~830 行
- **净减少**: ~3370 行代码

### 依赖关系

- `test_pipeline.py` 依赖 `core.db.strategy`, `modules.processing.pipeline.graph`
- `evaluate.py` 依赖 `modules.knowledge.search.retrievers.BM25Retriever`
- `manage.py` 依赖 `core.health.env_validator.EnvironmentValidator`

### CI/CD 影响

需更新以下调用：
```bash
# 旧命令 → 新命令
scripts/run_36kr_full_pipeline.py → scripts/test_api.py e2e
scripts/validate_environment.py → scripts/manage.py validate
scripts/run_performance_tests.py → scripts/evaluate.py hnsw
```

### 文档影响

- README 中的脚本使用说明需更新
- 开发指南中的测试命令需更新