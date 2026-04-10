## Why

代码中存在 8 处硬编码的 LLM 标签（如 `embedding.aiping.Qwen3-Embedding-0.6B`），绕过了已配置的 `llm.toml` 路由系统。这导致：
1. **配置分散** — 模型选择分散在代码和配置文件中
2. **无法切换** — 无法通过配置切换模型或使用 fallback
3. **维护困难** — 更换模型需要修改多处代码

## What Changes

- 将所有硬编码的 `embed("embedding.aiping.Qwen3-Embedding-0.6B", ...)` 替换为 `embed_default(...)`
- 移除 8 处硬编码标签：
  - `src/api/endpoints/search.py:126`
  - `src/modules/knowledge/search/context/global_context.py:223`
  - `src/modules/knowledge/search/context/ladybug_global_context.py:195`
  - `src/modules/knowledge/graph/community_report_generator.py:416`
  - `src/modules/processing/nodes/entity_extractor.py:92, 181`
  - `src/modules/processing/nodes/re_vectorize.py:36`
  - `src/modules/processing/nodes/vectorize.py:32`

## Capabilities

### New Capabilities

- `llm-label-centralization`: 统一 LLM 标签管理，所有模型选择通过 `llm.toml` 配置

### Modified Capabilities

- 无需求变更，仅为实现层面的重构

## Impact

**Affected Files (8 files)**:
- `src/api/endpoints/search.py` — search_articles 端点
- `src/modules/knowledge/search/context/global_context.py` — Neo4j global context
- `src/modules/knowledge/search/context/ladybug_global_context.py` — LadybugDB global context
- `src/modules/knowledge/graph/community_report_generator.py` — 社区报告生成
- `src/modules/processing/nodes/entity_extractor.py` — 实体提取
- `src/modules/processing/nodes/re_vectorize.py` — 重新向量化
- `src/modules/processing/nodes/vectorize.py` — 向量化

**API 行为**: 无变化（使用相同的模型，只是通过配置路由）

**配置依赖**: `config/llm.toml` 中的 `[defaults.embedding]` 和 `[call-points.embedding]`