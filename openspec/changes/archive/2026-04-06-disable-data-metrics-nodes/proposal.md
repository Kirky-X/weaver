## Why

"数据指标"（Data Metrics）类型的实体由 spaCy 的 `CARDINAL`、`PERCENT`、`MONEY` 标签映射生成，通常表示新闻中的数字、百分比、金额等。在某些业务场景下，这类实体价值较低、数量庞大，会污染知识图谱。需要一个配置开关，让运维人员可以禁用此类型实体的提取和存储。

## What Changes

- 新增 `EntitySettings` 配置类，包含 `disable_data_metrics_nodes` 布尔字段
- 修改 spaCy 提取阶段，当配置启用时跳过生成"数据指标"实体
- 修改 LLM 提取阶段，当配置启用时过滤 LLM 返回的"数据指标"实体
- 修改 Entity Resolver，当配置启用时拒绝创建"数据指标"节点
- 更新相关依赖注入，确保配置传递到各组件

## Capabilities

### New Capabilities
- `entity-type-filtering`: 配置驱动的实体类型过滤能力，支持禁用特定类型实体的提取和存储

### Modified Capabilities
- `entity-resolver`: 新增配置驱动的实体类型过滤检查点

## Impact

**代码修改**：
- `src/config/settings.py` - 新增 `EntitySettings` 配置类
- `src/modules/processing/nlp/spacy_extractor.py` - 添加过滤参数
- `src/modules/processing/nodes/entity_extractor.py` - 添加过滤逻辑
- `src/modules/knowledge/graph/entity_resolver.py` - 添加配置驱动过滤
- `src/container.py` - 更新依赖注入

**配置文件**：
- `config/settings.toml.example` - 新增 `[entity]` 配置示例

**测试**：
- `tests/unit/config/test_settings.py`
- `tests/unit/modules/processing/nlp/test_spacy_extractor.py`
- `tests/unit/modules/processing/nodes/test_entity_extractor.py`
- `tests/unit/modules/knowledge/graph/test_entity_resolver.py`