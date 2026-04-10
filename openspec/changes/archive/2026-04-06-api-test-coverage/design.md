## Context

Weaver 项目使用 FastAPI 框架，提供 36 个 HTTP API 端点覆盖 10 个模块。现有测试集中在 `tests/unit/api/test_api.py`，覆盖 Sources、Pipeline、Articles、Graph（部分）端点的单元测试。测试使用 pytest + pytest-asyncio，通过 AsyncMock 模拟外部依赖（Neo4j、PostgreSQL、Redis、LLM）。

## Goals / Non-Goals

**Goals:**
- 为缺失测试的 5 个 API 模块（Search、Graph Metrics、Admin LLM、Communities、Graph Relations）编写单元测试
- 按用户使用场景设计 4 条端到端用户流程 E2E 测试
- 测试覆盖率达到端点级别的 90%+
- 每个测试可独立运行，不依赖外部服务

**Non-Goals:**
- 不修改生产代码
- 不重构现有测试
- 不添加性能测试或压力测试
- 不测试第三方库的内部行为

## Decisions

### 1. 测试分层：单元 → 用户流程

**决定**: 采用两层测试策略，单元测试验证端点逻辑，E2E 用户流程测试验证端到端交互。

**理由**: 项目已有 `tests/conftest.py` 提供完善的 mock fixtures，单元测试可以快速验证每个端点的正确性。E2E 用户流程测试模拟真实用户操作路径，确保端点间协作正确。

### 2. Mock 策略：函数级直接调用

**决定**: 单元测试直接调用端点函数（非 HTTP 层），通过参数注入 mock 依赖。

**理由**: 现有测试 (`test_api.py`) 已采用此模式，直接调用 `async def endpoint(...)` 并注入 mock 参数。这避免了 FastAPI TestClient 的复杂性（如 lifespan、middleware），同时能验证核心业务逻辑。

### 3. 用户流程测试：FastAPI TestClient

**决定**: E2E 用户流程测试使用 `httpx.AsyncClient` 或 `fastapi.testclient.TestClient` 发起真实 HTTP 请求。

**理由**: 用户流程测试需要验证 HTTP 层面的请求/响应（状态码、头信息、JSON 格式），TestClient 提供了最接近真实行为的测试方式。

### 4. 文件组织：按 API 模块分文件

**决定**: 每个端点模块一个测试文件，E2E 测试单独一个文件。

**文件映射**:
```
tests/unit/api/test_search_api.py          # Search API
tests/unit/api/test_graph_metrics_api.py   # Graph Metrics API
tests/unit/api/test_admin_llm_api.py       # Admin LLM API
tests/unit/api/test_communities_api.py     # Communities API
tests/unit/api/test_graph_relations_api.py # Graph Relations API
tests/e2e/test_api_user_flows.py           # 用户流程
```

### 5. 测试模式：Arrange-Act-Assert

**决定**: 每个测试用例遵循 AAA 模式。

```python
@pytest.mark.asyncio
async def test_endpoint_name():
    # Arrange - 准备 mock 和测试数据
    mock_repo = MagicMock()
    mock_repo.method = AsyncMock(return_value=data)

    # Act - 调用端点函数
    result = await endpoint_function(param=..., _="test-key", repo=mock_repo)

    # Assert - 验证返回值和 mock 调用
    assert result.data.field == expected
    mock_repo.method.assert_called_once_with(...)
```

## Risks / Trade-offs

- **Mock 过度**: mock 可能隐藏真实集成问题 → E2E 用户流程测试补充覆盖
- **测试维护成本**: 51 个新测试用例增加维护负担 → 但每个测试聚焦单一行为，变更影响面小
- **Lifespan 依赖**: E2E 测试需要处理 FastAPI lifespan 上下文 → 使用 fixture 预配置服务注册表
