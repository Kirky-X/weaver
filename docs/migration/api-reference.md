# API 参考

迁移模块提供 RESTful API 端点用于管理和监控数据库迁移。

## 基础路径

```
/api/v1/migration
```

## 关系型迁移端点

### 启动关系型迁移

```http
POST /api/v1/migration/relational
```

启动 PostgreSQL ↔ DuckDB 迁移任务。

**请求体**

```json
{
  "source_db": "string",           // 必填: postgres | duckdb
  "target_db": "string",           // 必填: postgres | duckdb
  "tables": ["string"] | null,     // 可选: 要迁移的表列表
  "batch_size": 5000,              // 可选: 批次大小 (100-50000)
  "incremental_key": "string",     // 可选: 增量键列名
  "incremental_since": "any",      // 可选: 增量起始值
  "mapping_file": "string",        // 可选: 映射规则文件
  "strict_mode": false             // 可选: 严格模式
}
```

**响应**

```json
{
  "task_id": "abc12345",
  "status": "pending",
  "message": "迁移 postgres → duckdb 已启动"
}
```

**示例**

```bash
# 全量迁移
curl -X POST http://localhost:8000/api/v1/migration/relational \
  -H "Content-Type: application/json" \
  -d '{"source_db": "postgres", "target_db": "duckdb"}'

# 增量迁移
curl -X POST http://localhost:8000/api/v1/migration/relational \
  -H "Content-Type: application/json" \
  -d '{
    "source_db": "postgres",
    "target_db": "duckdb",
    "tables": ["articles"],
    "incremental_key": "updated_at",
    "incremental_since": "2024-01-01T00:00:00"
  }'
```

---

### 查询迁移进度

```http
GET /api/v1/migration/relational/{task_id}/progress
```

获取关系型迁移任务的进度信息。

**路径参数**

| 参数    | 类型   | 说明    |
| ------- | ------ | ------- |
| task_id | string | 任务 ID |

**响应**

```json
{
  "task_id": "abc12345",
  "source_db": "postgres",
  "target_db": "duckdb",
  "items": [
    {
      "name": "articles",
      "total": 10000,
      "migrated": 5000,
      "status": "running",
      "error": null
    }
  ],
  "total_migrated": 5000,
  "total_expected": 10000,
  "started_at": "2024-01-01T00:00:00",
  "elapsed_seconds": 30.5,
  "status": "running",
  "error": null
}
```

**状态值**

| 值        | 说明     |
| --------- | -------- |
| pending   | 等待执行 |
| running   | 正在执行 |
| completed | 已完成   |
| failed    | 失败     |
| cancelled | 已取消   |

---

### 取消迁移

```http
POST /api/v1/migration/relational/{task_id}/cancel
```

取消正在运行的迁移任务。

**响应**

```json
{
  "task_id": "abc12345",
  "status": "cancelled"
}
```

---

## 图迁移端点

### 启动图迁移

```http
POST /api/v1/migration/graph
```

启动 Neo4j ↔ LadybugDB 迁移任务。

**请求体**

```json
{
  "source_db": "string", // 必填: neo4j | ladybug
  "target_db": "string", // 必填: neo4j | ladybug
  "node_labels": ["string"], // 可选: 节点标签列表
  "rel_types": ["string"], // 可选: 关系类型列表
  "batch_size": 5000, // 可选: 批次大小
  "mapping_file": "string" // 可选: 映射规则文件
}
```

**响应**

```json
{
  "task_id": "xyz78901",
  "status": "pending",
  "message": "图迁移 neo4j → ladybug 已启动"
}
```

---

### 查询图迁移进度

```http
GET /api/v1/migration/graph/{task_id}/progress
```

获取图迁移任务的进度信息。

---

### 取消图迁移

```http
POST /api/v1/migration/graph/{task_id}/cancel
```

取消正在运行的图迁移任务。

---

## 映射规则端点

### 上传映射规则

```http
POST /api/v1/migration/mappings
```

上传自定义映射规则文件。

**请求体**

```json
{
  "name": "my_mapping",
  "content": "nodes:\n  - source_label: Person\n    target_label: Entity"
}
```

**响应**

```json
{
  "name": "my_mapping",
  "status": "saved",
  "message": "映射规则已保存到 config/mappings/my_mapping.yaml"
}
```

---

### 列出映射规则

```http
GET /api/v1/migration/mappings
```

获取所有可用的映射规则文件。

**响应**

```json
[
  {
    "name": "example",
    "node_mappings": 3,
    "rel_mappings": 3,
    "file_path": "config/mappings/example.yaml"
  }
]
```

---

### 获取映射规则详情

```http
GET /api/v1/migration/mappings/{name}
```

获取指定映射规则的详细信息。

**响应**

```json
{
  "name": "example",
  "node_mappings": [...],
  "rel_mappings": [...],
  "content": "..."
}
```

---

## 文件端点

### 上传源数据文件

```http
POST /api/v1/migration/upload
```

上传源数据库文件（DuckDB 或 LadybugDB）。

**请求**

`multipart/form-data` 格式：

- `file`: 数据库文件 (.duckdb 或 .ladybug)

**响应**

```json
{
  "filename": "my_data.duckdb",
  "path": "data/uploads/my_data.duckdb",
  "size": 1024000
}
```

---

### 下载迁移结果

```http
GET /api/v1/migration/download/{task_id}
```

下载迁移结果文件。

**响应**

```json
{
  "task_id": "abc12345",
  "filename": "migration_result.duckdb",
  "path": "data/migration_result.duckdb",
  "size": 2048000
}
```

---

## 错误响应

所有端点在出错时返回统一格式：

```json
{
  "detail": "错误描述信息"
}
```

**常见错误码**

| 状态码 | 说明           |
| ------ | -------------- |
| 400    | 请求参数无效   |
| 404    | 资源不存在     |
| 500    | 服务器内部错误 |
