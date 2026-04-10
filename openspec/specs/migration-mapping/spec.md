## ADDED Requirements

### Requirement: 映射规则文件格式

系统 SHALL 支持 YAML 格式的映射规则文件。

#### Scenario: 加载映射规则文件
- **WHEN** 用户指定 mapping_file="config/mappings/custom.yaml"
- **THEN** 系统解析 YAML 文件
- **AND** 注册节点映射和关系映射规则

#### Scenario: 映射规则文件不存在
- **WHEN** 指定的映射文件不存在
- **THEN** 系统返回错误 "Mapping file not found"
- **AND** 不执行迁移

### Requirement: 节点映射规则

系统 SHALL 支持自定义节点标签和属性的映射。

#### Scenario: 节点标签映射
- **WHEN** 映射规则定义 source_label: "Person", target_label: "Entity"
- **THEN** 源数据库中的 Person 节点迁移到目标数据库的 Entity 节点

#### Scenario: 属性映射
- **WHEN** 映射规则定义 property_mapping: {"name": "canonical_name"}
- **THEN** 源节点的 name 属性写入目标节点的 canonical_name 属性

#### Scenario: 默认值设置
- **WHEN** 映射规则定义 default_values: {"tier": 3}
- **THEN** 目标节点自动设置 tier=3
- **AND** 不影响源数据中已有的 tier 值

#### Scenario: 主键映射
- **WHEN** 映射规则定义 key_mapping: {"source_key": "name", "target_key": "canonical_name"}
- **THEN** 系统使用源节点的 name 属性值作为目标节点的主键

### Requirement: 关系映射规则

系统 SHALL 支持自定义关系类型和属性的映射。

#### Scenario: 关系类型映射
- **WHEN** 映射规则定义 source_type: "KNOWS", target_type: "RELATED_TO"
- **THEN** 源数据库中的 KNOWS 关系迁移为目标数据库的 RELATED_TO 关系

#### Scenario: 关系属性映射
- **WHEN** 映射规则定义 property_mapping: {"since": "properties"}
- **THEN** 源关系的 since 属性序列化到目标关系的 properties JSON 字段

### Requirement: 映射规则优先级

系统 SHALL 按优先级应用映射规则。

#### Scenario: 有映射规则时应用
- **WHEN** 节点标签存在映射规则
- **THEN** 系统应用映射转换
- **AND** 忽略同名属性的原样复制

#### Scenario: 无映射规则时原样迁移
- **WHEN** 节点标签不存在映射规则
- **THEN** 系统原样复制标签和属性
- **AND** 属性名保持不变

### Requirement: 映射规则验证

系统 SHALL 验证映射规则的正确性。

#### Scenario: 验证必需字段
- **WHEN** 映射规则缺少 source_label 或 target_label
- **THEN** 系统返回验证错误
- **AND** 列出缺失字段

#### Scenario: 验证目标 schema 兼容性
- **WHEN** 映射规则定义的目标属性在目标数据库 schema 中不存在
- **THEN** 系统发出警告
- **AND** 继续执行迁移（自动创建属性）

### Requirement: 映射规则 API

系统 SHALL 提供管理映射规则的 HTTP API。

#### Scenario: 上传映射规则
- **WHEN** 客户端 POST /migration/mappings 包含 YAML 内容
- **THEN** 系统验证并保存映射规则
- **AND** 返回映射规则 ID

#### Scenario: 列出映射规则
- **WHEN** 客户端 GET /migration/mappings
- **THEN** 系统返回已加载的所有映射规则列表
- **AND** 包含每个映射规则的元数据（名称、节点数、关系数）