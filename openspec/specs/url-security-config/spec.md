## ADDED Requirements

### Requirement: URLhaus API URL 可配置

URL 安全模块 SHALL 支持通过 `URLSecuritySettings.urlhaus_api_url` 配置 URLhaus API 端点。

#### Scenario: 使用默认 API URL
- **WHEN** `urlhaus_api_url` 未配置
- **THEN** 系统使用默认值 `https://urlhaus-api.abuse.ch/v1/url/`

#### Scenario: 使用自定义 API URL
- **WHEN** `urlhaus_api_url` 设置为 `https://proxy.example.com/urlhaus/v1/url/`
- **THEN** URLhausClient 向该地址发送请求

### Requirement: PhishTank 数据 URL 通过构造参数注入

PhishTankSync SHALL 通过构造参数接收数据 URL，而非使用类常量。

#### Scenario: 注入自定义数据 URL
- **WHEN** PhishTankSync 使用 `data_url` 参数实例化
- **THEN** sync() 方法使用注入的 URL 下载数据

#### Scenario: 使用默认数据 URL
- **WHEN** PhishTankSync 未传递 `data_url` 参数
- **THEN** sync() 方法使用 settings 中 `phishtank_data_url` 的值

### Requirement: 健康检查使用统一重试常量

EnvironmentValidator 中的所有验证方法 SHALL 使用 `Defaults.MAX_RETRIES` 而非硬编码的魔法数字。

#### Scenario: validate_postgres 重试次数
- **WHEN** PostgreSQL 连接验证失败
- **THEN** 系统重试 `Defaults.MAX_RETRIES` 次

#### Scenario: validate_neo4j 重试次数
- **WHEN** Neo4j 连接验证失败
- **THEN** 系统重试 `Defaults.MAX_RETRIES` 次

#### Scenario: validate_redis 重试次数
- **WHEN** Redis 连接验证失败
- **THEN** 系统重试 `Defaults.MAX_RETRIES` 次

#### Scenario: validate_llm 重试次数
- **WHEN** LLM 提供者验证失败
- **THEN** 系统重试 `Defaults.MAX_RETRIES` 次

#### Scenario: validate_embedding 重试次数
- **WHEN** Embedding 模型验证失败
- **THEN** 系统重试 `Defaults.MAX_RETRIES` 次