## ADDED Requirements

### Requirement: Admin LLM API 单元测试覆盖

Admin 模块的 LLM 使用统计（6 个端点）和失败记录（2 个端点）必须有完整的单元测试覆盖。

#### Scenario: LLM 使用统计 - 小时粒度
- **GIVEN** LLMUsageRepo.query_hourly 返回时间序列数据
- **WHEN** 调用 `GET /admin/llm-usage?from=...&to=...&granularity=hourly`
- **THEN** 返回 records 列表，每个 record 包含 time_bucket、call_count、latency_avg_ms

#### Scenario: LLM 使用统计 - 日/月粒度
- **GIVEN** granularity=daily 或 monthly
- **WHEN** 调用对应参数
- **THEN** repo.query_hourly 被调用时传入正确的 granularity 参数

#### Scenario: LLM 使用汇总
- **GIVEN** LLMUsageRepo.get_summary 返回聚合数据
- **WHEN** 调用 `GET /admin/llm-usage/summary?from=...&to=...`
- **THEN** 返回 total_calls、total_tokens、success_rate、error_types

#### Scenario: 按提供商统计
- **GIVEN** LLMUsageRepo.get_by_provider 返回分组数据
- **WHEN** 调用 `GET /admin/llm-usage/by-provider?from=...&to=...`
- **THEN** 返回每个 provider 的 call_count、total_tokens、avg_latency_ms

#### Scenario: 按模型统计
- **GIVEN** LLMUsageRepo.get_by_model 返回分组数据
- **WHEN** 调用 `GET /admin/llm-usage/by-model?from=...&to=...`
- **THEN** 返回每个 model 的统计，包含 provider 字段

#### Scenario: 按调用点统计
- **GIVEN** LLMUsageRepo.get_by_call_point 返回分组数据
- **WHEN** 调用 `GET /admin/llm-usage/by-call-point?from=...&to=...`
- **THEN** 返回每个 call_point 的 call_count、total_tokens

#### Scenario: LLM 使用统计 - 过滤器
- **GIVEN** 用户指定 provider、model 或 llm_type 过滤
- **WHEN** 调用对应端点并传入过滤参数
- **THEN** 过滤参数正确传递给 repo 方法

#### Scenario: LLM 失败记录列表
- **GIVEN** LLMFailureRepo.query 返回失败记录
- **WHEN** 调用 `GET /admin/llm-failures`
- **THEN** 返回失败记录列表，按 created_at 降序

#### Scenario: LLM 失败统计
- **GIVEN** LLMFailureRepo.get_stats 返回聚合数据
- **WHEN** 调用 `GET /admin/llm-failures/stats`
- **THEN** 返回 total_failures、by_call_point、by_status

#### Scenario: LLM 失败记录 - 过滤器
- **GIVEN** 用户指定 call_point、status、since 过滤
- **WHEN** 调用 llm-failures 端点并传入过滤参数
- **THEN** 过滤参数正确传递给 repo.query

#### Scenario: LLM 使用统计 - 缺少必填参数
- **GIVEN** 请求缺少 from 或 to 参数
- **WHEN** 调用 LLM 使用端点
- **THEN** FastAPI 返回 422 Validation Error

### Requirement: LLM 模型验证测试

LLM 端点的响应模型必须验证数据转换正确性。

#### Scenario: LLMUsageRecord 时间处理
- **GIVEN** repo 返回的 time_bucket 是 ISO 字符串
- **WHEN** 转换为 LLMUsageRecord
- **THEN** time_bucket 正确转换为 datetime 对象

#### Scenario: LLMFailureResponse 字段映射
- **GIVEN** repo 返回原始字段名（如 error_detail）
- **WHEN** 转换为 LLMFailureResponse
- **THEN** error_message 字段正确映射自 error_detail
