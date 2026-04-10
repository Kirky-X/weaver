## 1. Search API 单元测试

- [x] 1.1 创建 `tests/unit/api/test_search_api.py`，编写 SearchResponse/DriftSearchRequest/CausalSearchRequest/TemporalSearchRequest 模型验证测试
- [x] 1.2 编写 `test_search_unified_why_intent` — 验证 WHY 意图路由到 LocalSearchEngine
- [x] 1.3 编写 `test_search_unified_open_intent` — 验证 OPEN 意图路由到 GlobalSearchEngine
- [x] 1.4 编写 `test_search_unified_mode_override` — 验证 mode 参数跳过意图路由（local/global/articles 三种覆盖）
- [x] 1.5 编写 `test_search_unified_output_mode_validation` — 验证 output_mode 参数验证
- [x] 1.6 编写 `test_search_drift_success` — mock DRIFTSearchEngine，验证层次化响应结构
- [x] 1.7 编写 `test_search_drift_graph_unavailable` — Neo4j 错误时返回 503
- [x] 1.8 编写 `test_search_drift_llm_unavailable` — LLM 错误时返回 503
- [x] 1.9 编写 `test_search_causal_success` — mock AdaptiveSearchEngine，验证 causal_chain 响应
- [x] 1.10 编写 `test_search_causal_graph_unavailable` — Neo4j 错误时返回 503
- [x] 1.11 编写 `test_search_temporal_success` — mock TemporalGraphRepo，验证 events 和 time_range
- [x] 1.12 编写 `test_search_temporal_graph_unavailable` — Neo4j 错误时返回 503

## 2. Graph Metrics API 单元测试

- [x] 2.1 创建 `tests/unit/api/test_graph_metrics_api.py`，编写 HealthSummaryResponse/GraphMetricsResponse/CommunityMetricsResponse 模型验证测试
- [x] 2.2 编写 `test_graph_metrics_health_view` — mock GraphQualityMetrics.get_health_summary，验证 health_score 和 status
- [x] 2.3 编写 `test_graph_metrics_full_view` — mock GraphQualityMetrics.calculate_all_metrics，验证完整指标字段
- [x] 2.4 编写 `test_graph_metrics_full_include_filter` — 验证 include 参数只返回请求的子集
- [x] 2.5 编写 `test_graph_metrics_community_view` — mock Neo4jCommunityRepo，验证社区指标
- [x] 2.6 编写 `test_graph_metrics_community_no_data` — 无社区时返回空结构
- [x] 2.7 编写 `test_graph_metrics_invalid_view` — 无效 view 参数返回 400
- [x] 2.8 编写 `test_parse_include_param` — 验证 _parse_include_param 解析逻辑

## 3. Admin LLM API 单元测试

- [x] 3.1 创建 `tests/unit/api/test_admin_llm_api.py`，编写 LLMUsageRecord/LLMUsageSummary/LLMFailureResponse 模型验证测试
- [x] 3.2 编写 `test_get_llm_usage_hourly` — mock LLMUsageRepo.query_hourly，验证时间粒度
- [x] 3.3 编写 `test_get_llm_usage_daily_monthly` — 验证 granularity 参数传递
- [x] 3.4 编写 `test_get_llm_usage_summary` — mock repo.get_summary，验证汇总字段
- [x] 3.5 编写 `test_get_llm_usage_by_provider` — mock repo.get_by_provider，验证分组
- [x] 3.6 编写 `test_get_llm_usage_by_model` — mock repo.get_by_model，验证分组
- [x] 3.7 编写 `test_get_llm_usage_by_call_point` — mock repo.get_by_call_point，验证分组
- [x] 3.8 编写 `test_get_llm_usage_with_filters` — 验证 provider/model/llm_type/call_point 过滤参数
- [x] 3.9 编写 `test_list_llm_failures` — mock LLMFailureRepo.query，验证列表返回
- [x] 3.10 编写 `test_list_llm_failures_with_filters` — 验证 call_point/status/since 过滤
- [x] 3.11 编写 `test_get_llm_failure_stats` — mock repo.get_stats，验证统计结构
- [x] 3.12 编写 `test_update_authority_validation` — 验证 UpdateAuthorityRequest 边界值

## 4. Communities API 单元测试

- [x] 4.1 创建 `tests/unit/api/test_communities_api.py`，编写 RebuildRequest/CommunityResponse/CommunityDetailResponse 模型验证测试
- [x] 4.2 编写 `test_rebuild_communities_success` — mock CommunityDetector，验证重建统计
- [x] 4.3 编写 `test_rebuild_communities_with_params` — 验证 max_cluster_size 和 seed 参数
- [x] 4.4 编写 `test_rebuild_communities_error` — 异常时返回 500
- [x] 4.5 编写 `test_generate_all_reports_success` — mock CommunityReportGenerator，验证成功/失败计数
- [x] 4.6 编写 `test_generate_reports_level_filter` — 验证 level 过滤
- [x] 4.7 编写 `test_regenerate_report_success` — 验证报告重新生成返回 report_id
- [x] 4.8 编写 `test_regenerate_report_not_found` — 社区不存在返回 404
- [x] 4.9 编写 `test_list_communities` — mock Neo4jCommunityRepo，验证分页和过滤
- [x] 4.10 编写 `test_get_community_detail` — 验证社区详情包含 entities、children、report
- [x] 4.11 编写 `test_get_community_not_found` — 返回 404

## 5. Graph Relations API 单元测试

- [x] 5.1 创建 `tests/unit/api/test_graph_relations_api.py`，编写 RelationTypeSummary/RelatedEntityResult/RelationTypeInfo 模型验证测试
- [x] 5.2 编写 `test_get_entity_relations` — mock Neo4jEntityRepo.get_relation_types，验证返回结构
- [x] 5.3 编写 `test_search_relations_no_filter` — mock find_by_relation_types，验证无过滤搜索
- [x] 5.4 编写 `test_search_relations_with_type_filter` — 验证 relation_types 逗号分隔解析
- [x] 5.5 编写 `test_search_relations_limit` — 验证 limit 参数传递
- [x] 5.6 编写 `test_list_relation_types_success` — mock PostgreSQL session，验证查询结果
- [x] 5.7 编写 `test_list_relation_types_postgres_unavailable` — _pg_pool 为 None 时返回 503

## 6. E2E 用户流程测试

- [x] 6.1 创建 `tests/e2e/test_api_user_flows.py`，设置 FastAPI TestClient 和 conftest fixtures
- [x] 6.2 编写 `test_flow_news_processing` — 资讯处理完整流程（创建源→触发爬取→查询状态→查看文章→查看实体）
- [x] 6.3 编写 `test_flow_knowledge_search` — 知识搜索流程（统一搜索→图谱可视化→图谱健康）
- [x] 6.4 编写 `test_flow_ops_monitoring` — 运维监控流程（health→metrics→LLM 使用→失败统计）
- [x] 6.5 编写 `test_flow_community_management` — 社区管理流程（重建→生成报告→列表→详情）
- [x] 6.6 编写 `test_auth_missing_key` — 验证无 API Key 返回 401
- [x] 6.7 编写 `test_auth_invalid_key` — 验证无效 API Key 返回 403
