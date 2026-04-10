## 1. 子配置模型定义

- [x] 1.1 创建 `src/config/subconfigs.py`，定义所有子配置 BaseModel 类
- [x] 1.2 定义 `PostgresSettings`、`Neo4jSettings`、`RedisSettings`、`DuckDBSettings`、`LadybugSettings`
- [x] 1.3 定义 `APISettings`、`SchedulerSettings`、`FetcherSettings`、`SearchSettings`
- [x] 1.4 定义 `DedupSettings`、`ObservabilitySettings`、`MemorySettings`、`SpacySettings`
- [x] 1.5 定义 `URLSecuritySettings`、`EntitySettings`、`HealthCheckSettings`、`PromptSettings`
- [x] 1.6 定义 `IntentRoutingSettings`、`TemporalInferenceSettings`、`PipelineUrlEndpointSettings`

## 2. LLM 配置类型迁移

- [x] 2.1 将 `src/core/llm/types.py` 中的 `ModelConfig` dataclass 转换为 pydantic BaseModel
- [x] 2.2 将 `ProviderConfig` dataclass 转换为 pydantic BaseModel
- [x] 2.3 将 `RoutingConfig` dataclass 转换为 pydantic BaseModel
- [x] 2.4 将 `GlobalConfig` dataclass 转换为 pydantic BaseModel
- [x] 2.5 创建 `LLMSettings` 类，使用 pydantic-settings 加载 `llm.toml`
- [x] 2.6 移除 `LLMConfigLoader` 类及其自定义 `${ENV_VAR}` 解析逻辑

## 3. Pipeline 配置类型迁移

- [x] 3.1 将 `StageConfig` dataclass 转换为 pydantic BaseModel
- [x] 3.2 将 `PhaseConfig` dataclass 转换为 pydantic BaseModel
- [x] 3.3 将 `BatchConfig` dataclass 转换为 pydantic BaseModel
- [x] 3.4 创建 `PipelineSettings` 类，使用 pydantic-settings 加载 `pipeline.toml`
- [x] 3.5 移除 `PipelineConfigLoader` 类
- [x] 3.6 移除 YAML 相关依赖（`save_default_config` 函数）

## 4. Settings 主类重构

- [x] 4.1 移除自定义 `TomlSettingsSource` 类
- [x] 4.2 移除 `Settings.__init__` 中的字段剥离逻辑
- [x] 4.3 重构 Settings 类，使用原生 `TomlConfigSettingsSource`
- [x] 4.4 更新 `settings_customise_sources` 方法配置优先级
- [x] 4.5 将所有子配置（包括 LLMSettings、PipelineSettings）聚合到 Settings

## 5. 配置文件迁移

- [x] 5.1 创建 `config/pipeline.toml`，从现有 YAML 格式转换
- [x] 5.2 更新 `config/llm.toml`，移除所有 `${ENV_VAR}` 语法
- [x] 5.3 更新 `config/settings.toml`，确保格式与新的子配置类匹配

## 6. 环境变量更新

- [x] 6.1 更新 `.env.example`，使用新的 `WEAVER_<SECTION>__<FIELD>` 格式
- [x] 6.2 更新 `docker/docker-compose.yml` 中的环境变量名称
- [x] 6.3 更新 `tests/e2e/test_env.env` 和 `tests/e2e/conftest.py`

## 7. Container 集成更新

- [x] 7.1 更新 `src/container.py` 的 `configure` 方法适配新 Settings
- [x] 7.2 更新 `llm_client` 方法从 Settings 获取 LLM 配置
- [x] 7.3 移除独立的 Pipeline 配置加载逻辑
- [x] 7.4 更新 `get_settings()` 便捷函数

## 8. 测试更新

- [x] 8.1 更新 `tests/unit/config/` 中的单元测试
- [x] 8.2 更新 `tests/e2e/conftest.py` 中的环境变量使用
- [x] 8.3 添加新配置类型的验证测试
- [x] 8.4 验证环境变量覆盖功能正常工作

## 9. 清理与验证

- [x] 9.1 删除不再使用的自定义配置加载代码
- [x] 9.2 运行完整测试套件确保无回归
- [x] 9.3 验证所有配置路径可正常工作
- [x] 9.4 更新相关文档
