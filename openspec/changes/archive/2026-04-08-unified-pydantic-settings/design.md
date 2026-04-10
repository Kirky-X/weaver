## Context

当前 Weaver 项目配置系统基于 pydantic-settings 构建，但存在以下问题：

1. **自定义 TOML 加载**：`src/config/settings.py` 实现了 `TomlSettingsSource` 自定义类，手动解析 `config/settings.toml`，而 pydantic-settings 2.x 原生支持 `TomlConfigSettingsSource`
2. **复杂的环境变量优先级**：`Settings.__init__` 中有 60+ 行字段剥离逻辑，确保 `POSTGRES_*` 等环境变量覆盖 TOML 值，这些在原生 `settings_customise_sources` API 中可自动处理
3. **LLM 配置独立**：`src/core/llm/config.py` 的 `LLMConfigLoader` 使用自定义 `${ENV_VAR}` 语法引用环境变量，与 pydantic-settings 不一致
4. **Pipeline 配置分离**：`src/modules/processing/pipeline/config.py` 使用 dataclass + YAML，无类型验证和环境变量支持

**约束：**
- pydantic-settings 2.13.1+ 已在项目中
- 无需向后兼容
- LLM 配置保持独立 `llm.toml` 文件

## Goals / Non-Goals

**Goals:**

1. 使用 pydantic-settings 原生 `TomlConfigSettingsSource` 替代自定义实现
2. 统一环境变量命名格式为 `WEAVER__<SECTION>__<FIELD>`
3. 将 LLM 和 Pipeline 配置迁移到 pydantic BaseModel，享受类型验证和环境变量覆盖能力
4. 移除重复的配置加载代码

**Non-Goals:**

1. 不改变配置项本身（只改变加载和管理方式）
2. 不引入新的配置文件格式（保持 TOML）
3. 不重构业务逻辑代码

## Decisions

### 1. 环境变量命名格式

**决定：** 统一使用 `WEAVER__<SECTION>__<FIELD>` 嵌套格式

**理由：**
- 与 pydantic-settings 的 `env_nested_delimiter="__"` 完美匹配
- 所有配置都有 `WEAVER__` 前缀，明确标识来源
- LLM 配置的环境变量 `WEAVER__LLM__PROVIDERS__AIPING__API_KEY` 与主配置格式一致

**替代方案：**
- 子模块扁平前缀（`POSTGRES_HOST`）：需要子配置类单独设置 `env_prefix`，与嵌套配置不一致

### 2. LLM 配置处理

**决定：** 将 LLM dataclass 转换为 pydantic BaseModel，移除 `${ENV_VAR}` 语法

**理由：**
- pydantic-settings 原生支持环境变量覆盖，无需 `${ENV_VAR}` 语法
- 转换后支持完整的类型验证
- 环境变量可覆盖 TOML 中的任何值

**替代方案：**
- 保留 `${ENV_VAR}` 语法解析：需要自定义代码，与 pydantic-settings 不兼容

### 3. 配置文件组织

**决定：** 分层组合架构，每个模块有独立 Settings 类和 toml_file

```python
class Settings(BaseSettings):
    postgres: PostgresSettings
    neo4j: Neo4jSettings
    llm: LLMSettings       # 独立 llm.toml
    pipeline: PipelineSettings  # 独立 pipeline.toml
```

**理由：**
- 模块化，职责清晰
- 每个子配置可独立测试
- 符合用户需求的层级架构

### 4. Pipeline 配置迁移

**决定：** 从 YAML + dataclass 迁移到 TOML + pydantic BaseModel

**理由：**
- 与主配置系统格式统一（TOML）
- 支持环境变量覆盖（如 `WEAVER__PIPELINE__PHASE1__CONCURRENCY=10`）
- 类型验证和 IDE 支持

## Risks / Trade-offs

| 风险 | 缓解措施 |
|------|----------|
| 环境变量命名变更导致部署脚本失效 | 更新 `.env.example` 和 `docker-compose.yml`，提供迁移指南 |
| LLM toml 格式变更 | 提供配置文件迁移脚本 |
| pydantic-settings 版本兼容性 | 锁定 `pydantic-settings>=2.13.1` |
| 动态 provider 键名（`[providers.aiping]`）的环境变量覆盖 | 使用 `dict[str, ProviderConfig]` 类型，pydantic-settings 支持嵌套字典的环境变量覆盖 |

## Migration Plan

### 阶段一：创建子配置模型（无破坏性）

1. 创建 `src/config/subconfigs.py`，定义所有子配置 BaseModel
2. 将 LLM types.py 中的 dataclass 转换为 pydantic BaseModel
3. 将 Pipeline config.py 中的 dataclass 转换为 pydantic BaseModel

### 阶段二：重构 Settings 主类

1. 移除 `TomlSettingsSource` 自定义类
2. 重构 Settings 类使用原生 `TomlConfigSettingsSource`
3. 更新 `settings_customise_sources` 方法

### 阶段三：更新配置文件和环境变量

1. 创建 `config/pipeline.toml`（从 YAML 转换）
2. 更新 `config/llm.toml`（移除 `${ENV_VAR}` 语法）
3. 更新 `.env.example` 和 `docker-compose.yml`

### 阶段四：集成和测试

1. 更新 Container 配置注入
2. 更新测试用例
3. 验证所有配置路径

**回滚策略：** 保留原配置文件备份，Git 分支隔离开发