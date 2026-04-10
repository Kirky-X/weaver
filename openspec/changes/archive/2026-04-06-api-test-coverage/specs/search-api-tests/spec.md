## ADDED Requirements

### Requirement: Search API 单元测试覆盖

Search 模块的 5 个端点（GET /search, POST /search/drift, POST /search/causal, POST /search/temporal）必须有完整的单元测试覆盖。

#### Scenario: 统一搜索 - WHY 意图路由
- **GIVEN** 用户发送 `GET /api/v1/search?q=为什么AI会影响就业`
- **WHEN** IntentRouter 识别为 WHY 意图
- **THEN** 路由到 LocalSearchEngine，返回因果关系答案

#### Scenario: 统一搜索 - 手动 mode 覆盖
- **GIVEN** 用户发送 `GET /api/v1/search?q=test&mode=local`
- **WHEN** 显式指定 mode 参数
- **THEN** 跳过意图路由，直接使用 LocalSearchEngine

#### Scenario: DRIFT 搜索成功
- **GIVEN** 用户发送 `POST /api/v1/search/drift` body=`{"query": "分析芯片供应链"}`
- **WHEN** DRIFTSearchEngine 返回层次化结果
- **THEN** 返回 200，response 包含 hierarchy、primer_communities、follow_up_iterations

#### Scenario: DRIFT 搜索 - LLM 不可用
- **GIVEN** DRIFTSearchEngine 抛出 LLM 相关异常
- **WHEN** 调用 drift 端点
- **THEN** 返回 HTTPException status_code=503

#### Scenario: 因果推理搜索成功
- **GIVEN** 用户发送 `POST /api/v1/search/causal` body=`{"query": "为什么会发生X"}`
- **WHEN** AdaptiveSearchEngine 返回结果
- **THEN** 返回 causal_chain 列表和 confidence

#### Scenario: 时间推理搜索成功
- **GIVEN** 用户发送 `POST /api/v1/search/temporal` body=`{"query": "什么时候发生了X"}`
- **WHEN** TemporalGraphRepo 返回事件
- **THEN** 返回 events 列表和 time_range

#### Scenario: 搜索端点 - 缺少 API Key
- **GIVEN** 请求未携带 X-API-Key 头
- **WHEN** 调用任意搜索端点
- **THEN** 返回 401 Unauthorized

### Requirement: 搜索模型验证测试

搜索端点的请求/响应模型必须验证边界条件。

#### Scenario: DriftSearchRequest 参数验证
- **GIVEN** primer_k=0 或 max_follow_ups=-1
- **WHEN** 构造 DriftSearchRequest
- **THEN** Pydantic 验证失败

#### Scenario: CausalSearchRequest 参数验证
- **GIVEN** max_depth=10 或 min_confidence=1.5
- **WHEN** 构造 CausalSearchRequest
- **THEN** Pydantic 验证失败

#### Scenario: TemporalSearchRequest 参数验证
- **GIVEN** time_window_days=0 或 limit=0
- **WHEN** 构造 TemporalSearchRequest
- **THEN** Pydantic 验证失败
