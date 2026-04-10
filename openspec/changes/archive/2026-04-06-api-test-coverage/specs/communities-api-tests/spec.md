## ADDED Requirements

### Requirement: Communities API 单元测试覆盖

Communities 模块的 5 个端点（重建、报告生成、报告重新生成、列表、详情）必须有完整的单元测试覆盖。

#### Scenario: 重建社区成功
- **GIVEN** CommunityDetector.rebuild_communities 返回 CommunityDetectionResult
- **WHEN** 调用 `POST /admin/communities/rebuild`
- **THEN** 返回 communities_created、entities_processed、modularity、orphan_count

#### Scenario: 重建社区 - 自定义参数
- **GIVEN** 请求 body 包含 max_cluster_size=20, seed=123
- **WHEN** 调用 rebuild 端点
- **THEN** CommunityDetector 使用指定参数

#### Scenario: 重建社区 - Neo4j 错误
- **GIVEN** CommunityDetector.rebuild_communities 抛出异常
- **WHEN** 调用 rebuild 端点
- **THEN** 返回 HTTPException status_code=500

#### Scenario: 生成所有报告成功
- **GIVEN** CommunityReportGenerator.generate_all_reports 返回统计
- **WHEN** 调用 `POST /admin/communities/reports/generate`
- **THEN** 返回 total、success、failed 计数

#### Scenario: 生成报告 - 按层级过滤
- **GIVEN** 指定 level=1 参数
- **WHEN** 调用 reports/generate 端点
- **THEN** generate_all_reports 被调用时传入 level=1

#### Scenario: 重新生成报告成功
- **GIVEN** CommunityReportGenerator.regenerate_report 返回成功
- **WHEN** 调用 `POST /admin/communities/{id}/report/regenerate`
- **THEN** 返回 status 和 report_id

#### Scenario: 重新生成报告 - 社区不存在
- **GIVEN** regenerate_report 返回 success=False 且错误包含 "not found"
- **WHEN** 调用 regenerate 端点
- **THEN** 返回 HTTPException status_code=404

#### Scenario: 列出社区成功
- **GIVEN** Neo4jCommunityRepo.list_communities 返回社区列表
- **WHEN** 调用 `GET /graph/communities`
- **THEN** 返回 communities 列表、total、level

#### Scenario: 列出社区 - 分页
- **GIVEN** 指定 limit=10, offset=20
- **WHEN** 调用 communities 端点
- **THEN** repo 使用正确的分页参数

#### Scenario: 社区详情成功
- **GIVEN** Neo4jCommunityRepo.get_community 返回社区信息
- **WHEN** 调用 `GET /graph/communities/{id}`
- **THEN** 返回 id、title、level、entities、children_ids、report

#### Scenario: 社区详情 - 不存在
- **GIVEN** Neo4jCommunityRepo.get_community 返回 None
- **WHEN** 调用 community detail 端点
- **THEN** 返回 HTTPException status_code=404
