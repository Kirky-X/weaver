# CLI 参考

迁移模块提供命令行接口用于执行和管理数据库迁移。

## 基本用法

```bash
python -m src.modules.migration <command> [options]
```

## 命令

### `relational`

执行关系型数据库迁移（PostgreSQL ↔ DuckDB）。

```bash
python -m src.modules.migration relational [OPTIONS]
```

**选项**

| 选项                | 简写 | 类型   | 必填 | 说明                           |
| ------------------- | ---- | ------ | ---- | ------------------------------ |
| `--source`          | `-s` | string | 是   | 源数据库: postgres \| duckdb   |
| `--target`          | `-t` | string | 是   | 目标数据库: postgres \| duckdb |
| `--table`           |      | string | 否   | 要迁移的表（可多次指定）       |
| `--batch`           | `-b` | int    | 否   | 每批行数（默认: 5000）         |
| `--incremental-key` | `-k` | string | 否   | 增量迁移的键列                 |
| `--since`           |      | string | 否   | 增量迁移起始值                 |
| `--mapping`         | `-m` | path   | 否   | 自定义映射规则文件             |
| `--strict`          |      | flag   | 否   | 类型转换错误时失败             |
| `--dry-run`         |      | flag   | 否   | 预览模式，不实际执行           |

**示例**

```bash
# 全量迁移所有表
python -m src.modules.migration relational -s postgres -t duckdb

# 迁移指定表
python -m src.modules.migration relational \
  -s postgres \
  -t duckdb \
  --table articles \
  --table entities

# 增量迁移
python -m src.modules.migration relational \
  -s postgres \
  -t duckdb \
  --table articles \
  --incremental-key updated_at \
  --since "2024-01-01"

# 预览模式
python -m src.modules.migration relational \
  -s duckdb \
  -t postgres \
  --dry-run
```

---

### `graph`

执行图数据库迁移（Neo4j ↔ LadybugDB）。

```bash
python -m src.modules.migration graph [OPTIONS]
```

**选项**

| 选项        | 简写 | 类型   | 必填 | 说明                         |
| ----------- | ---- | ------ | ---- | ---------------------------- |
| `--source`  | `-s` | string | 是   | 源数据库: neo4j \| ladybug   |
| `--target`  | `-t` | string | 是   | 目标数据库: neo4j \| ladybug |
| `--node`    |      | string | 否   | 节点标签（可多次指定）       |
| `--rel`     |      | string | 否   | 关系类型（可多次指定）       |
| `--batch`   | `-b` | int    | 否   | 每批项目数（默认: 5000）     |
| `--mapping` | `-m` | path   | 否   | 自定义映射规则文件           |
| `--dry-run` |      | flag   | 否   | 预览模式                     |

**示例**

```bash
# 迁移所有节点和关系
python -m src.modules.migration graph -s neo4j -t ladybug

# 迁移指定节点标签
python -m src.modules.migration graph \
  -s neo4j \
  -t ladybug \
  --node Entity \
  --node Article

# 使用自定义映射
python -m src.modules.migration graph \
  -s neo4j \
  -t ladybug \
  --mapping config/mappings/custom.yaml
```

---

### `status`

查询迁移任务状态。

```bash
python -m src.modules.migration status <task_id>
```

**参数**

| 参数    | 类型   | 说明    |
| ------- | ------ | ------- |
| task_id | string | 任务 ID |

**示例**

```bash
python -m src.modules.migration status abc12345
```

**输出**

```
任务状态: abc12345

┌─────────────┬─────────────────────┐
│ 项目        │ 状态                │
├─────────────┼─────────────────────┤
│ 源数据库    │ postgres            │
│ 目标数据库  │ duckdb              │
│ 状态        │ completed           │
│ 已迁移      │ 10000               │
│ 预期总数    │ 10000               │
└─────────────┴─────────────────────┘
```

---

### `list-mappings`

列出可用的映射规则文件。

```bash
python -m src.modules.migration list-mappings [OPTIONS]
```

**选项**

| 选项    | 简写 | 类型 | 说明                                  |
| ------- | ---- | ---- | ------------------------------------- |
| `--dir` | `-d` | path | 映射规则目录（默认: config/mappings） |

**示例**

```bash
python -m src.modules.migration list-mappings

# 指定自定义目录
python -m src.modules.migration list-mappings --dir custom/mappings
```

**输出**

```
                映射规则文件
┏━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ 名称     ┃ 节点映射 ┃ 关系映射 ┃ 路径                      ┃
┡━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ example  │        3 │        3 │ config/mappings/example… │
│ custom   │        5 │        2 │ config/mappings/custom.… │
└──────────┴──────────┴──────────┴───────────────────────────┘
```

---

### `cancel`

取消正在运行的迁移任务。

```bash
python -m src.modules.migration cancel <task_id>
```

**示例**

```bash
python -m src.modules.migration cancel abc12345
```

---

## 环境变量

| 变量             | 说明                  |
| ---------------- | --------------------- |
| `POSTGRES_DSN`   | PostgreSQL 连接字符串 |
| `DUCKDB_PATH`    | DuckDB 数据库路径     |
| `NEO4J_URI`      | Neo4j 连接 URI        |
| `NEO4J_USER`     | Neo4j 用户名          |
| `NEO4J_PASSWORD` | Neo4j 密码            |
| `LADYBUG_PATH`   | LadybugDB 数据库路径  |

## 退出码

| 码  | 说明                           |
| --- | ------------------------------ |
| 0   | 成功                           |
| 1   | 错误（任务不存在、取消失败等） |
