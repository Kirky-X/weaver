# Design: Archive Issues Remediation

## Context

归档方案实施状态报告中识别的问题经代码库探索后，发现多数已实现，仅剩以下需要修复：

### 当前状态
1. **`EntitySettings.disable_data_metrics_nodes`** — 配置已定义，但未注入到 `EntityResolver`
2. **API 测试覆盖** — 36 个端点仅 34% 覆盖率，7 个测试文件缺失
3. **硬编码残留** — `token_budget.py:34` 使用硬编码 `gpt-4o`

### 相关代码路径
- `src/config/settings.py:588` — `EntitySettings` 定义
- `src/container.py:646-652` — `entity_resolver()` 创建逻辑
- `src/modules/knowledge/graph/entity_resolver.py:73,80` — 构造函数参数
- `src/modules/processing/nodes/entity_extractor.py:75-76` — 已正确使用配置
- `src/modules/processing/nlp/spacy_extractor.py:133,216-217` — 已实现过滤逻辑

## Goals / Non-Goals

**Goals:**
- 修复 `disable_data_metrics` 配置注入，使数据指标过滤功能生效
- 补充关键 API 端点的测试覆盖
- 可选：移除或文档化 `token_budget.py` 硬编码

**Non-Goals:**
- 不修改现有业务逻辑
- 不新增功能特性
- 不修改数据库 schema
- 不影响生产环境稳定性

## Decisions

### D1: 配置注入方式

**决策**: 在 `Container.entity_resolver()` 方法中直接传递配置

**备选方案**:
1. ❌ 修改 `EntityResolver` 构造函数签名 — 已有 `disable_data_metrics` 参数
2. ✅ 在 `Container` 中传递配置 — 最小改动，符合现有模式
3. ❌ 创建新的配置注入机制 — 过度设计

**实现**:
```python
# container.py:646-652
def entity_resolver(self) -> EntityResolver:
    if self._entity_resolver is None:
        disable_data_metrics = (
            self._settings.entity.disable_data_metrics_nodes
            if self._settings else False
        )
        self._entity_resolver = EntityResolver(
            entity_repo=self.graph_entity_repo(),
            vector_repo=self.vector_repo(),
            llm=self._llm_client,
            resolution_rules=resolution_rules,
            name_normalizer=name_normalizer,
            disable_data_metrics=disable_data_metrics,  # 新增
        )
    return self._entity_resolver
```

### D2: API 测试文件结构

**决策**: 按模块划分测试文件，遵循现有模式

**测试文件映射**:
| 文件 | 覆盖端点 | 优先级 |
|------|----------|--------|
| `test_search_api.py` | `/api/v1/search/*` | 高 |
| `test_graph_metrics_api.py` | `/api/v1/graph/metrics/*` | 高 |
| `test_admin_llm_api.py` | `/api/v1/admin/llm/*` | 中 |
| `test_communities_api.py` | `/api/v1/communities/*` | 中 |
| `test_graph_relations_api.py` | `/api/v1/graph/relations/*` | 中 |
| `test_api_integration.py` | 跨端点集成测试 | 中 |
| `test_api_user_flows.py` | 4 条核心用户路径 | 高 |

### D3: 硬编码处理

**决策**: 添加文档说明保留原因

**理由**: `token_budget.py:34` 的 `gpt-4o` 用于 tiktoken 编码器初始化，是技术限制而非配置问题。不同模型的 tokenizer 不同，但 tiktoken 的 `cl100k_base` 编码器被 GPT-4 系列和许多其他模型共用。

**实现**: 添加注释说明用途和适用范围

## Risks / Trade-offs

| 风险 | 缓解措施 |
|------|----------|
| 配置注入可能遗漏其他组件 | 已验证 `entity_extractor.py` 和 `spacy_extractor.py` 已正确实现 |
| 新增测试可能发现现有 bug | 使用 `xfail` 标记已知问题，逐步修复 |
| 测试覆盖率提升可能耗时 | 优先覆盖核心端点，次要端点可后续补充 |

## Migration Plan

无需迁移，直接部署即可生效。

### 部署步骤
1. 合并代码变更
2. 运行完整测试套件确认无回归
3. 部署到 staging 环境验证
4. 部署到生产环境

### 验证清单
- [ ] 设置 `entity.disable_data_metrics_nodes=true` 后，数据指标实体不再入库
- [ ] 新增测试全部通过
- [ ] 整体测试覆盖率 ≥ 85%

## Open Questions

无未决问题，可直接实施。