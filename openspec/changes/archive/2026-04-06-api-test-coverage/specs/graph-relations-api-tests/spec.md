## ADDED Requirements

### Requirement: Graph Relations API 单元测试覆盖

Graph 模块中关系相关端点（GET /graph/relations, GET /graph/relations/search, GET /graph/relation-types）必须有完整的单元测试覆盖。

#### Scenario: 获取实体关系类型
- **GIVEN** Neo4jEntityRepo.get_relation_types 返回关系类型列表
- **WHEN** 调用 `GET /graph/relations?entity=华为&entity_type=组织机构`
- **THEN** 返回 relation_type、target_count、primary_direction 列表

#### Scenario: 搜索关系 - 无过滤
- **GIVEN** Neo4jEntityRepo.find_by_relation_types 返回相关实体
- **WHEN** 调用 `GET /graph/relations/search?entity=华为`
- **THEN** 返回 relation_type、direction、target_name、weight 列表

#### Scenario: 搜索关系 - 按类型过滤
- **GIVEN** 指定 relation_types=合作,投资
- **WHEN** 调用 search 端点
- **THEN** find_by_relation_types 被调用时 types_list=["合作", "投资"]

#### Scenario: 搜索关系 - limit 生效
- **GIVEN** 指定 limit=10
- **WHEN** 调用 search 端点
- **THEN** find_by_relation_types 被调用时 limit=10

#### Scenario: 列出关系类型 - 成功
- **GIVEN** PostgreSQL 有活跃的 RelationType 记录
- **WHEN** 调用 `GET /graph/relation-types`
- **THEN** 返回 name、name_en、category、is_symmetric、alias_count

#### Scenario: 列出关系类型 - PostgreSQL 未初始化
- **GIVEN** _pg_pool 为 None
- **WHEN** 调用 relation-types 端点
- **THEN** 返回 HTTPException status_code=503

#### Scenario: 模型验证 - RelationTypeSummary
- **GIVEN** 构造 RelationTypeSummary
- **WHEN** 传入 relation_type、target_count、primary_direction
- **THEN** 模型字段正确赋值

#### Scenario: 模型验证 - RelatedEntityResult
- **GIVEN** 构造 RelatedEntityResult
- **WHEN** 传入 relation_type、direction、target_name、weight
- **THEN** weight 默认值为 1.0
