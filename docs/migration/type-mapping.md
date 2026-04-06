# 类型映射

迁移工具自动处理不同数据库之间的类型转换。

## 关系型数据库类型映射

### PostgreSQL → DuckDB

| PostgreSQL 类型  | DuckDB 类型              | 说明         |
| ---------------- | ------------------------ | ------------ |
| INTEGER          | INTEGER                  | 整数         |
| BIGINT           | BIGINT                   | 大整数       |
| SMALLINT         | SMALLINT                 | 小整数       |
| REAL             | FLOAT                    | 单精度浮点   |
| DOUBLE PRECISION | DOUBLE                   | 双精度浮点   |
| DECIMAL(p,s)     | DECIMAL(p,s)             | 精确数值     |
| VARCHAR(n)       | VARCHAR                  | 变长字符串   |
| TEXT             | VARCHAR                  | 文本         |
| CHAR(n)          | VARCHAR                  | 定长字符串   |
| BOOLEAN          | BOOLEAN                  | 布尔值       |
| DATE             | DATE                     | 日期         |
| TIME             | TIME                     | 时间         |
| TIMESTAMP        | TIMESTAMP                | 时间戳       |
| TIMESTAMPTZ      | TIMESTAMP WITH TIME ZONE | 带时区时间戳 |
| BYTEA            | BLOB                     | 二进制数据   |
| JSON             | JSON                     | JSON 数据    |
| JSONB            | JSON                     | JSON 二进制  |
| UUID             | UUID                     | UUID         |
| ARRAY            | LIST                     | 数组         |

### DuckDB → PostgreSQL

| DuckDB 类型  | PostgreSQL 类型  | 说明                            |
| ------------ | ---------------- | ------------------------------- |
| INTEGER      | INTEGER          | 整数                            |
| BIGINT       | BIGINT           | 大整数                          |
| SMALLINT     | SMALLINT         | 小整数                          |
| TINYINT      | SMALLINT         | 微整数（PostgreSQL 无 TINYINT） |
| FLOAT        | REAL             | 单精度浮点                      |
| DOUBLE       | DOUBLE PRECISION | 双精度浮点                      |
| DECIMAL(p,s) | DECIMAL(p,s)     | 精确数值                        |
| VARCHAR      | TEXT             | 字符串                          |
| BOOLEAN      | BOOLEAN          | 布尔值                          |
| DATE         | DATE             | 日期                            |
| TIME         | TIME             | 时间                            |
| TIMESTAMP    | TIMESTAMP        | 时间戳                          |
| BLOB         | BYTEA            | 二进制数据                      |
| JSON         | JSONB            | JSON 数据                       |
| UUID         | UUID             | UUID                            |
| LIST         | ARRAY            | 数组                            |
| STRUCT       | JSONB            | 结构体（转为 JSON）             |

---

## 图数据库类型映射

### Neo4j → LadybugDB

Neo4j 属性类型映射到 LadybugDB 存储格式：

| Neo4j 类型 | LadybugDB 存储  | 说明     |
| ---------- | --------------- | -------- |
| String     | TEXT            | 字符串   |
| Integer    | INTEGER         | 整数     |
| Float      | REAL            | 浮点数   |
| Boolean    | INTEGER (0/1)   | 布尔值   |
| DateTime   | TEXT (ISO 8601) | 日期时间 |
| Date       | TEXT (ISO 8601) | 日期     |
| Point      | JSON            | 地理坐标 |
| Duration   | TEXT            | 时间间隔 |
| List       | JSON            | 数组     |
| Map        | JSON            | 对象     |

### LadybugDB → Neo4j

| LadybugDB 类型 | Neo4j 类型 | 说明      |
| -------------- | ---------- | --------- |
| TEXT           | String     | 字符串    |
| INTEGER        | Integer    | 整数      |
| REAL           | Float      | 浮点数    |
| INTEGER (0/1)  | Boolean    | 布尔值    |
| JSON           | Map/List   | JSON 数据 |

---

## 值转换规则

### 空值处理

- `NULL` 在所有数据库间保持为 `NULL`
- 空字符串 `""` 保持为空字符串（不转为 NULL）

### 布尔值转换

```python
# PostgreSQL/DuckDB
True  → True
False → False
NULL  → NULL

# Neo4j → LadybugDB
True  → 1
False → 0

# LadybugDB → Neo4j
0 → False
1 → True
NULL → NULL
```

### 日期时间格式

```python
# ISO 8601 格式
"2024-01-15T10:30:00Z"
"2024-01-15T10:30:00+08:00"
"2024-01-15"  # 仅日期
```

### JSON 处理

```python
# 嵌套对象保持原结构
{"name": "Alice", "meta": {"age": 30}}

# 数组保持原结构
["a", "b", "c"]
```

---

## 类型转换错误处理

### 严格模式 (`strict_mode: true`)

类型转换失败时立即终止迁移并报告错误。

```json
{
  "source_db": "postgres",
  "target_db": "duckdb",
  "strict_mode": true
}
```

### 宽松模式 (`strict_mode: false`，默认)

类型转换失败时记录警告并跳过该值（设为 NULL）。

---

## 自定义类型映射

如需自定义类型映射，可通过映射规则文件配置：

```yaml
types:
  - source: "custom_type"
    target: "VARCHAR"
    converter: "string"
```

参见 [自定义映射规则](./custom-mappings.md) 了解更多。
