# 自定义映射规则

通过 YAML 配置文件自定义迁移过程中的数据转换规则。

## 映射文件结构

```yaml
# 节点映射规则
nodes:
  - source_label: "Person"
    target_label: "Entity"
    property_mapping:
      name: canonical_name
      age: properties.age
    default_values:
      tier: 3
      type: "Person"

# 关系映射规则
relations:
  - source_type: "KNOWS"
    target_type: "RELATED_TO"
    property_mapping:
      since: properties.since
    default_values:
      edge_type: "social"
```

---

## 节点映射

### 基本结构

```yaml
nodes:
  - source_label: <源节点标签>
    target_label: <目标节点标签>
    key_mapping:
      source_key: <源键属性>
      target_key: <目标键属性>
    property_mapping:
      <源属性>: <目标属性>
    default_values:
      <属性>: <默认值>
```

### 示例

#### 简单标签转换

```yaml
nodes:
  - source_label: "User"
    target_label: "Person"
```

#### 属性重命名

```yaml
nodes:
  - source_label: "Person"
    target_label: "Entity"
    property_mapping:
      full_name: name
      email_address: email
      created_at: created_date
```

#### 嵌套属性映射

将源属性映射到目标属性的嵌套结构中：

```yaml
nodes:
  - source_label: "Person"
    target_label: "Entity"
    property_mapping:
      name: canonical_name
      bio: properties.bio
      avatar_url: properties.avatar
      social_links: properties.social
```

结果：

```json
{
  "canonical_name": "Alice",
  "properties": {
    "bio": "...",
    "avatar": "...",
    "social": {...}
  }
}
```

#### 添加默认值

```yaml
nodes:
  - source_label: "Person"
    target_label: "Entity"
    default_values:
      tier: 3
      type: "Person"
      source: "migration"
```

#### 键映射

指定用于匹配节点的键属性：

```yaml
nodes:
  - source_label: "Person"
    target_label: "Entity"
    key_mapping:
      source_key: "email"
      target_key: "canonical_email"
```

---

## 关系映射

### 基本结构

```yaml
relations:
  - source_type: <源关系类型>
    target_type: <目标关系类型>
    property_mapping:
      <源属性>: <目标属性>
    default_values:
      <属性>: <默认值>
```

### 示例

#### 类型转换

```yaml
relations:
  - source_type: "FRIEND_OF"
    target_type: "RELATED_TO"
```

#### 属性映射

```yaml
relations:
  - source_type: "WORKS_FOR"
    target_type: "RELATED_TO"
    property_mapping:
      role: properties.role
      start_date: properties.start_date
      department: properties.department
```

#### 添加元数据

```yaml
relations:
  - source_type: "KNOWS"
    target_type: "RELATED_TO"
    default_values:
      edge_type: "social"
      confidence: 1.0
      verified: true
```

---

## 完整示例

### 知识图谱迁移

```yaml
# config/mappings/knowledge_graph.yaml

nodes:
  # 人物 → 实体
  - source_label: "Person"
    target_label: "Entity"
    key_mapping:
      source_key: "name"
      target_key: "canonical_name"
    property_mapping:
      name: canonical_name
      bio: description
      birth_date: properties.birth_date
      nationality: properties.nationality
    default_values:
      type: "Person"
      tier: 3

  # 组织 → 实体
  - source_label: "Organization"
    target_label: "Entity"
    key_mapping:
      source_key: "org_name"
      target_key: "canonical_name"
    property_mapping:
      org_name: canonical_name
      description: description
      founded: properties.founded
      industry: properties.industry
    default_values:
      type: "Organization"
      tier: 2

  # 地点 → 实体
  - source_label: "Location"
    target_label: "Entity"
    property_mapping:
      location_name: canonical_name
      coordinates: properties.coordinates
      country: properties.country
    default_values:
      type: "Location"
      tier: 4

relations:
  # 雇佣关系
  - source_type: "WORKS_FOR"
    target_type: "RELATED_TO"
    property_mapping:
      role: properties.role
      since: properties.since
    default_values:
      edge_type: "employment"

  # 社交关系
  - source_type: "KNOWS"
    target_type: "RELATED_TO"
    property_mapping:
      since: properties.since
      how_met: properties.how_met
    default_values:
      edge_type: "social"

  # 位于
  - source_type: "LOCATED_AT"
    target_type: "RELATED_TO"
    default_values:
      edge_type: "location"
```

---

## 使用映射文件

### API 方式

```bash
curl -X POST http://localhost:8000/api/v1/migration/graph \
  -H "Content-Type: application/json" \
  -d '{
    "source_db": "neo4j",
    "target_db": "ladybug",
    "mapping_file": "config/mappings/knowledge_graph.yaml"
  }'
```

### CLI 方式

```bash
python -m src.modules.migration graph \
  -s neo4j \
  -t ladybug \
  --mapping config/mappings/knowledge_graph.yaml
```

---

## 上传映射文件

### 通过 API

```bash
curl -X POST http://localhost:8000/api/v1/migration/mappings \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my_custom_mapping",
    "content": "nodes:\n  - source_label: Person\n    target_label: Entity"
  }'
```

### 手动放置

将 YAML 文件放入 `config/mappings/` 目录：

```
config/
└── mappings/
    ├── example.yaml
    ├── knowledge_graph.yaml
    └── my_custom_mapping.yaml
```

---

## 映射规则优先级

1. **显式映射**: `property_mapping` 中定义的转换
2. **默认值**: `default_values` 中定义的值
3. **原始值**: 未映射的属性保持原样

---

## 验证映射文件

```bash
# 检查映射文件语法
python -c "
from modules.migration.mapping_registry import load_mapping_file
registry = load_mapping_file('config/mappings/my_mapping.yaml')
print(f'Nodes: {len(registry.node_mappings)}')
print(f'Relations: {len(registry.rel_mappings)}')
"
```
