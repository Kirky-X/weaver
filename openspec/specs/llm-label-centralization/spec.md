## ADDED Requirements

### Requirement: LLM embedding calls use configured defaults

所有 embedding 调用 SHALL 通过 `embed_default()` 方法执行，使用 `llm.toml` 中配置的 `[defaults.embedding]` 标签。

**约束**: 代码中不得出现硬编码的 embedding 标签字符串（如 `"embedding.aiping.Qwen3-Embedding-0.6B"`）。

#### Scenario: Search articles endpoint uses default embedding

- **WHEN** 调用 `GET /api/v1/search?mode=articles&q=test`
- **THEN** 系统使用 `embed_default()` 获取查询向量
- **AND** 不使用硬编码标签

#### Scenario: Global context uses default embedding

- **WHEN** global context 执行向量搜索
- **THEN** 系统使用 `embed_default()` 获取查询向量

#### Scenario: Entity extractor uses default embedding

- **WHEN** 实体提取器生成实体向量
- **THEN** 系统使用 `embed_default()` 获取向量

#### Scenario: Community report generator uses default embedding

- **WHEN** 社区报告生成器存储报告向量
- **THEN** 系统使用 `embed_default()` 获取向量

### Requirement: Fallback mechanism is preserved

当主 embedding provider 不可用时，系统 SHALL 自动使用 `llm.toml` 中配置的 fallback provider。

#### Scenario: Primary provider fails, fallback succeeds

- **WHEN** 主 provider (`aiping`) embedding 调用失败
- **THEN** 系统自动切换到 fallback provider (`ollama`)
- **AND** 返回有效的向量

### Requirement: Configuration is single source of truth

所有 LLM 模型选择 SHALL 通过 `config/llm.toml` 配置，代码中不包含模型选择逻辑。

#### Scenario: Model change via config only

- **WHEN** 需要更换 embedding 模型
- **THEN** 只需修改 `llm.toml` 中的 `[defaults.embedding]`
- **AND** 无需修改任何代码文件