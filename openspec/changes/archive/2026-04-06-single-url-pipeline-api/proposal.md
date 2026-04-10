## Why

当前系统仅支持批量源爬取触发管道处理，缺乏单 URL 级别的处理入口。外部系统或用户需要针对特定资讯网页执行完整处理流程时，无法直接调用。新增单 URL 处理 API 可满足以下需求：外部内容注入、手动测试验证、即时处理热点资讯。

## What Changes

- 新增 `POST /pipeline/url` API 端点
- 支持单 URL 异步管道处理（抓取 → 清洗 → 分类 → 向量化 → 可信度分析 → 实体提取 → 持久化）
- SSRF 防护（复用现有 `URLValidator`）
- 可选白名单域名模式
- 复用现有任务状态存储和查询机制

## Capabilities

### New Capabilities

- `single-url-pipeline`: 单 URL 管道处理 API，支持异步任务执行、SSRF 防护和可选白名单域名验证

### Modified Capabilities

无。本变更仅新增功能，不修改现有能力的行为要求。

## Impact

| 影响范围 | 变更内容 |
|----------|----------|
| `src/api/endpoints/pipeline.py` | 新增 `/url` 端点和 `process_single_url` 后台处理函数 |
| `src/config/settings.py` | 新增 `PipelineUrlEndpointSettings` 配置类 |
| Redis | 复用现有 `pipeline:task_status` key |
| 外部 API | 新增端点，向后兼容 |