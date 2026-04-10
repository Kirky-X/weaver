## Context

测试脚本 `scripts/test_pipeline.py` 用于验证完整的数据处理 pipeline。当前 NewsNow API 的基础 URL（`https://www.newsnow.net.cn/api/s`）已不可用，需要更新为 `https://www.newsnow.world/api/s?id=`。同时，资讯源ID硬编码为 `hupu`，缺乏灵活性。

## Goals / Non-Goals

**Goals:**
- 更新 NewsNow API URL 为当前可用端点
- 支持通过命令行参数指定资讯源ID
- 保持向后兼容（默认值行为明确）

**Non-Goals:**
- 不修改 NewsNow API 响应解析逻辑
- 不添加新的测试模式
- 不修改 pipeline 核心处理逻辑

## Decisions

### 1. API URL 更新

**决策**: 将 `API_BASE_URL` 从 `https://www.newsnow.net.cn/api/s` 改为 `https://www.newsnow.world/api/s?id=`

**理由**:
- 新域名是当前可用的服务端点
- URL 结构从 `?id=` 查询参数形式更改为直接拼接源ID

### 2. 源ID 参数化

**决策**: 添加 `--source-id` 命令行参数，默认值 `36kr`

**理由**:
- 命令行参数是最直接的配置方式
- 默认值选择 `36kr` 是常用科技资讯源
- 与现有 `--source` 参数（RSS模式）保持一致风格

### 3. URL 构建方式

**决策**: 在 `NewsNowParser` 中，URL 从 `SourceConfig.url` 直接获取，不使用 `API_BASE_URL` 拼接

**理由**:
- 当前实现 `parse(config: SourceConfig)` 直接使用 `config.url`
- 测试脚本负责构建完整 URL，Parser 保持通用性
- 避免修改 Parser 的 API 契约

## Risks / Trade-offs

| 风险 | 缓解措施 |
|------|----------|
| 新 API 域名响应格式可能不同 | 测试验证响应解析兼容性 |
| 其他代码可能依赖旧 URL | 全局搜索 `newsnow.net.cn` 确认无其他引用 |