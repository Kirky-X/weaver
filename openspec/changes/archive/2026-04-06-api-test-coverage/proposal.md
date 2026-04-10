## Why

Weaver 的 36 个 HTTP API 端点中，仅 34% 有单元测试覆盖。Search API（5 个端点）、Graph Metrics、Admin LLM（6 个端点）、Communities（5 个端点）和 Graph Relations（2 个端点）完全缺失测试。需要按用户使用场景设计并实现全面的 HTTP API 测试，确保所有端点行为正确。

## What Changes

- 新增 5 个单元测试文件，覆盖 Search API、Graph Metrics API、Admin LLM API、Communities API、Graph Relations API
- 新增 1 个集成测试文件，验证 API 端点与真实服务的 HTTP 级交互
- 新增 1 个 E2E 用户流程测试文件，覆盖 4 条核心用户操作路径
- 总计约 51 个新增测试用例

## Capabilities

### New Capabilities

- `search-api-tests`: Search API 单元测试（统一搜索、DRIFT、因果推理、时间推理、速率限制）
- `graph-metrics-api-tests`: Graph Metrics API 单元测试（health/full/community 视图、缓存、过滤）
- `admin-llm-api-tests`: Admin LLM API 单元测试（使用统计、失败记录、按维度分组）
- `communities-api-tests`: Communities API 单元测试（重建、报告生成、社区列表/详情）
- `graph-relations-api-tests`: Graph Relations API 单元测试（关系发现、关系搜索、关系类型列表）
- `api-user-flow-tests`: E2E 用户流程测试（资讯处理、知识搜索、运维监控、社区管理）

### Modified Capabilities

## Impact

- 新增文件：`tests/unit/api/` 下 5 个测试文件，`tests/integration/` 下 1 个文件，`tests/e2e/` 下 1 个文件
- 不修改任何生产代码
- 依赖现有 `tests/conftest.py` 中的 mock fixtures
- 测试框架：pytest + pytest-asyncio + FastAPI TestClient
