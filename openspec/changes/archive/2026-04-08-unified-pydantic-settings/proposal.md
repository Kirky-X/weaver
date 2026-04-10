## Why

当前配置系统存在以下问题：

1. **自定义 TOML 加载逻辑**：`settings.py` 实现了自定义 `TomlSettingsSource`，而 pydantic-settings 2.x 原生支持 `TomlConfigSettingsSource`
2. **复杂的环境变量优先级处理**：`Settings.__init__` 中有大量字段剥离逻辑以确保 `env > toml` 优先级，这些在原生 API 中可自动处理
3. **LLM 配置系统独立**：`LLMConfigLoader` 重复实现 TOML 解析和环境变量引用（`${ENV_VAR}`），与主配置系统不统一
4. **Pipeline 配置使用 dataclass**：无类型验证、无环境变量支持、与主配置系统分离

重构后可实现：统一配置架构、减少维护成本、支持完整的 pydantic 验证能力。

## What Changes

- **移除自定义 TomlSettingsSource**：使用原生 `TomlConfigSettingsSource`
- **移除 Settings.__init__ 中的字段剥离逻辑**：利用 `settings_customise_sources` 自动处理优先级
- **LLM 配置迁移到 pydantic BaseModel**：移除 `LLMConfigLoader`，移除 `${ENV_VAR}` 语法
- **Pipeline 配置迁移到 pydantic BaseModel**：替换 dataclass，支持环境变量覆盖
- **统一环境变量命名**：全部使用 `WEAVER__<SECTION>__<FIELD>` 格式
- **BREAKING**：环境变量命名从 `POSTGRES_HOST` 变为 `WEAVER__POSTGRES__HOST`

## Capabilities

### New Capabilities

- `unified-config-system`: 统一配置管理架构，使用 pydantic-settings 原生能力管理所有配置模块

### Modified Capabilities

- `llm-config`: 从自定义 LLMConfigLoader 迁移到 pydantic-settings，移除 `${ENV_VAR}` 语法
- `pipeline-config`: 从 dataclass 迁移到 pydantic BaseModel，支持环境变量覆盖

## Impact

**代码变更：**

| 文件 | 变更类型 |
|------|----------|
| `src/config/settings.py` | 重构：移除自定义 TOML source，简化 Settings 类 |
| `src/config/subconfigs.py` | 新增：所有子配置 BaseModel 类 |
| `src/core/llm/types.py` | 重构：dataclass → pydantic BaseModel |
| `src/core/llm/config.py` | 重构：移除 LLMConfigLoader，创建 LLMSettings |
| `src/modules/processing/pipeline/config.py` | 重构：dataclass → pydantic BaseModel |
| `src/container.py` | 更新：配置注入方式适配 |

**配置文件变更：**

| 文件 | 变更类型 |
|------|----------|
| `config/settings.toml` | 更新：格式适配 |
| `config/llm.toml` | 更新：移除 `${ENV_VAR}` 语法 |
| `config/pipeline.toml` | 新增：从 YAML 转换为 TOML |

**环境变量变更：**

| 变更前 | 变更后 |
|--------|--------|
| `POSTGRES_HOST` | `WEAVER__POSTGRES__HOST` |
| `NEO4J_PASSWORD` | `WEAVER__NEO4J__PASSWORD` |
| `REDIS_URL` | `WEAVER__REDIS__URL` |
| `WEAVER_API__API_KEY` | `WEAVER__API__API_KEY` |

**依赖项：**

- 无新增依赖，pydantic-settings 已在项目中使用