# 数据库迁移工具

统一的数据库迁移工具，支持关系型数据库和图数据库的双向迁移。

## 功能特性

- **关系型数据库迁移**: PostgreSQL ↔ DuckDB 双向迁移
- **图数据库迁移**: Neo4j ↔ LadybugDB 双向迁移
- **全量迁移**: 一次性迁移所有数据
- **增量迁移**: 基于时间戳或 ID 的增量同步
- **大规模数据**: 支持百万级以上数据迁移
- **自定义映射**: 通过 YAML 配置节点和关系的转换规则
- **进度可视化**: Rich 进度条和迁移摘要

## 快速开始

### API 方式

启动关系型迁移:

```bash
curl -X POST http://localhost:8000/api/v1/migration/relational \
  -H "Content-Type: application/json" \
  -d '{
    "source_db": "postgres",
    "target_db": "duckdb",
    "tables": ["articles", "entities"],
    "batch_size": 5000
  }'
```

查询迁移进度:

```bash
curl http://localhost:8000/api/v1/migration/relational/{task_id}/progress
```

### CLI 方式

```bash
# 关系型迁移
python -m src.modules.migration relational \
  --source postgres \
  --target duckdb \
  --table articles \
  --batch 5000

# 图迁移
python -m src.modules.migration graph \
  --source neo4j \
  --target ladybug \
  --node Entity \
  --node Article

# 预览模式（不执行实际迁移）
python -m src.modules.migration relational \
  --source duckdb \
  --target postgres \
  --dry-run

# 查看映射规则
python -m src.modules.migration list-mappings
```

## 迁移类型

### 全量迁移

迁移源数据库中的所有数据到目标数据库。

```json
{
  "source_db": "postgres",
  "target_db": "duckdb",
  "tables": null // null 表示迁移所有表
}
```

### 增量迁移

基于增量键（如时间戳或自增 ID）迁移新增或更新的数据。

```json
{
  "source_db": "postgres",
  "target_db": "duckdb",
  "tables": ["articles"],
  "incremental_key": "updated_at",
  "incremental_since": "2024-01-01T00:00:00"
}
```

## 配置选项

| 参数              | 类型   | 默认值 | 说明                   |
| ----------------- | ------ | ------ | ---------------------- |
| source_db         | string | 必填   | 源数据库类型           |
| target_db         | string | 必填   | 目标数据库类型         |
| tables            | array  | null   | 要迁移的表/节点列表    |
| batch_size        | int    | 5000   | 每批处理行数           |
| incremental_key   | string | null   | 增量迁移键             |
| incremental_since | any    | null   | 增量起始值             |
| mapping_file      | string | null   | 映射规则文件路径       |
| strict_mode       | bool   | false  | 类型转换错误时是否失败 |

## 支持的数据库

### 关系型数据库

| 数据库     | 角色    | 说明                       |
| ---------- | ------- | -------------------------- |
| PostgreSQL | 源/目标 | 主生产数据库               |
| DuckDB     | 源/目标 | 分析型数据库，支持大数据量 |

### 图数据库

| 数据库    | 角色    | 说明                    |
| --------- | ------- | ----------------------- |
| Neo4j     | 源/目标 | 生产图数据库            |
| LadybugDB | 源/目标 | 本地图存储，SQLite 兼容 |

## 相关文档

- [API 参考](./api-reference.md)
- [CLI 参考](./cli-reference.md)
- [类型映射](./type-mapping.md)
- [自定义映射规则](./custom-mappings.md)
