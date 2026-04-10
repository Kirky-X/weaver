## ADDED Requirements

### Requirement: NewsNow API 基础 URL 可配置

NewsNowParser SHALL 支持通过构造参数配置 API 基础 URL。

#### Scenario: 使用默认 API URL
- **WHEN** NewsNowParser 未传递 `api_base_url` 参数
- **THEN** 系统使用默认值 `https://www.newsnow.world/api/s?id=`

#### Scenario: 使用自定义 API URL
- **WHEN** NewsNowParser 使用 `api_base_url="https://proxy.example.com/newsnow/api/s?id="` 实例化
- **THEN** 解析器构建请求时使用该 URL 前缀

### Requirement: SourceRegistry 传递配置给 NewsNowParser

SourceRegistry SHALL 支持将配置注入到 NewsNowParser 实例。

#### Scenario: 注册 NewsNow 解析器
- **WHEN** SourceRegistry 初始化内置解析器
- **THEN** NewsNowParser 接收来自 settings 的 `newsnow_api_base_url` 配置