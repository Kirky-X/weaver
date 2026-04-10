## Why

当前测试覆盖率为 83.16%，低于项目要求的 85% 阈值。关键模块如 `duckdb_handler.py` (46.67%)、`spacy_extractor.py` (67.01%) 和 `incremental_community_updater.py` (77.76%) 存在大量未测试分支，可能导致生产环境中的回归问题。

提升覆盖率可确保核心功能的正确性，减少调试时间，并增强代码重构的信心。

## What Changes

- 为低覆盖率模块补充单元测试
- 增加边缘情况和异常处理测试
- 补充 DuckDB 查询逻辑测试
- 完善 NLP 提取器分支覆盖
- 增强图度量计算测试

## Capabilities

### New Capabilities

- `duckdb-query-coverage`: DuckDB 查询处理和连接管理测试覆盖
- `nlp-extraction-coverage`: SpaCy NLP 提取器分支测试覆盖
- `graph-metrics-coverage`: 图度量计算完整测试覆盖
- `incremental-update-coverage`: 增量社区更新逻辑测试覆盖
- `batch-merge-coverage`: 批量合并边缘情况测试覆盖

### Modified Capabilities

无现有能力需求变更，仅为现有模块补充测试。

## Impact

**受影响文件**:
- `tests/unit/core/db/test_duckdb_handler.py` (新建)
- `tests/unit/modules/processing/nlp/test_spacy_extractor.py` (扩展)
- `tests/unit/modules/knowledge/graph/test_metrics.py` (扩展)
- `tests/unit/modules/knowledge/graph/test_incremental_community_updater.py` (扩展)
- `tests/unit/modules/processing/nodes/test_batch_merger.py` (扩展)

**预期覆盖率提升**: 83.16% → 85%+