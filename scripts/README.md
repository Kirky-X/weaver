# Weaver Scripts

统一的开发和运维脚本目录。

## 脚本列表

| 脚本                | 描述                                 |
|-------------------|------------------------------------|
| `pipeline.py`     | 管道测试、待处理文章处理、重新处理                  |
| `db.py`           | 数据库查询、检查、数据质量检查、修复工具              |
| `tools.py`        | 性能评估、环境验证、数据库种子、代码检查              |
| `build_nuitka.py` | Nuitka 编译构建                        |
| `_common.py`      | 共享工具（init_script_container 等，非独立运行） |

---

## pipeline.py

统一的管道管理脚本,支持管道测试、待处理文章处理和重新处理不完整文章。

### 用法

```bash
# 管道测试 - NewsNow 模式
uv run scripts/pipeline.py test --mode newsnow --max-items 5

# 管道测试 - RSS 模式
uv run scripts/pipeline.py test --mode rss --source solidot

# 管道测试 - 全部源
uv run scripts/pipeline.py test --mode all --clear-db

# 管道测试 - 数据库故障转移模式
uv run scripts/pipeline.py test --mode strategy

# 处理待处理文章
uv run scripts/pipeline.py process-pending

# 重新处理不完整文章
uv run scripts/pipeline.py reprocess --incomplete

# 预览不完整文章（不实际处理）
uv run scripts/pipeline.py reprocess --incomplete --dry-run

# 批量重新处理（自定义批次大小和延迟）
uv run scripts/pipeline.py reprocess --incomplete --batch-size 5 --delay 30

# 重新处理指定文章
uv run scripts/pipeline.py reprocess --article-id <uuid>
```

### 子命令

#### test

管道测试。

| 参数            | 默认值     | 描述                                   |
|---------------|---------|--------------------------------------|
| `--mode`      | newsnow | 测试模式: newsnow / rss / strategy / all |
| `--source`    | solidot | RSS 源名称 (rss 模式)                     |
| `--source-id` | 36kr    | NewsNow 源 ID (newsnow 模式)            |
| `--max-items` | 5       | 最大处理条目数                              |
| `--clear-db`  | false   | 测试前清空数据库                             |
| `--timeout`   | 300     | 管道超时时间(秒)                            |
| `--port`      | 8000    | API 服务器端口                            |

#### process-pending

处理所有 persist_status='pending' 的文章。

#### reprocess

重新处理不完整的文章。

| 参数             | 默认值  | 描述                      |
|----------------|------|-------------------------|
| `--incomplete` | -    | 重新处理所有不完整文章             |
| `--article-id` | -    | 重新处理指定 ID 的文章           |
| `--dry-run`    | -    | 预览不完整文章列表，不实际处理         |
| `--batch-size` | 10   | 每批处理的文章数量               |
| `--delay`      | 60   | 批次间隔秒数（避免429限流）         |

---

## db.py

数据库查询和检查工具,支持 PostgreSQL、DuckDB、Neo4j、LadybugDB。

### 用法

```bash
# 查看所有数据库表统计
uv run scripts/db.py stats

# 查看特定数据库
uv run scripts/db.py stats --db duckdb
uv run scripts/db.py stats --db postgres --db duckdb

# 查询文章详情
uv run scripts/db.py article --id <article-uuid>

# 随机查询文章
uv run scripts/db.py random --limit 3

# 分页查询表数据
uv run scripts/db.py rows articles --limit 20 --page 1
uv run scripts/db.py rows Article --db neo4j --columns name,type

# LadybugDB 数据质量检查
uv run scripts/db.py dq-check
uv run scripts/db.py dq-check --db-path data/weaver.lbug

# 修复损坏的 model_id
uv run scripts/db.py fix-model-id --dry-run
uv run scripts/db.py fix-model-id --execute
```

### 子命令

#### stats

显示数据库表记录数。

| 参数     | 描述                                          |
|--------|---------------------------------------------|
| `--db` | 指定数据库(可多次指定): postgres/duckdb/neo4j/ladybug |

#### article

查询文章完整信息。

| 参数     | 描述                   |
|--------|----------------------|
| `--id` | 文章 UUID (必需)         |
| `--db` | 数据库: postgres/duckdb |

#### random

随机查询文章及实体关系。

| 参数        | 默认值   | 描述                 |
|-----------|-------|--------------------|
| `--limit` | 2     | 文章数量               |
| `--db`    | neo4j | 数据库: neo4j/ladybug |

#### rows

分页查询表数据。

| 参数           | 默认值      | 描述                           |
|--------------|----------|------------------------------|
| `table`      | -        | 表名(必需)                       |
| `--db`       | postgres | 数据库                          |
| `--columns`  | -        | 列名(逗号分隔)                     |
| `--limit`    | 20       | 每页行数                         |
| `--page`     | 1        | 页码                           |
| `--order-by` | -        | 排序: column:asc 或 column:desc |
| `--format`   | table    | 输出格式: table/json             |

#### null-fields

检查数据库表中的 NULL/空字段。

#### dq-check

LadybugDB 数据质量检查。

| 参数          | 默认值                | 描述                    |
|-------------|--------------------|-----------------------|
| `--db-path` | data/weaver.lbug   | LadybugDB 数据库路径       |

#### fix-model-id

修复 article_vectors 中损坏的 model_id 值。

| 参数          | 默认值                  | 描述             |
|-------------|----------------------|----------------|
| `--db-path` | data/weaver.duckdb   | DuckDB 数据库路径   |
| `--dry-run` | -                    | 预览变更，不实际执行     |
| `--execute` | -                    | 执行修复           |

---

## tools.py

统一的工具脚本,包含性能评估、环境验证、数据库种子和代码质量检查。

### 用法

```bash
# HNSW 向量索引性能测试
uv run scripts/tools.py evaluate hnsw

# HNSW 测试 - 指定向量数量
uv run scripts/tools.py evaluate hnsw --num-vectors 2000

# HNSW 测试 - JSON 输出
uv run scripts/tools.py evaluate hnsw --output json

# BM25 搜索质量评估
uv run scripts/tools.py evaluate search

# 搜索评估 - 指定 K 值
uv run scripts/tools.py evaluate search --k-values 5,10,20

# 搜索评估 - 保存结果
uv run scripts/tools.py evaluate search --output json --output-path ./results/

# 验证所有服务
uv run scripts/tools.py validate

# 验证特定服务
uv run scripts/tools.py validate --service postgres --service redis

# 种子数据库
uv run scripts/tools.py seed

# 种子数据库 - 重置
uv run scripts/tools.py seed --reset

# 检查日志规范
uv run scripts/tools.py check-logging

# 检查日志规范 - 显示修复提示
uv run scripts/tools.py check-logging --fix-hint
```

### 子命令

#### evaluate hnsw

HNSW 向量索引性能测试。

| 参数              | 默认值      | 描述                    |
|-----------------|----------|-----------------------|
| `--num-vectors` | 1000     | 批量插入测试的向量数量           |
| `--num-queries` | 20       | 查询性能测试的查询次数           |
| `--output`      | markdown | 输出格式: json / markdown |

#### evaluate search

BM25 搜索质量评估。

| 参数              | 默认值      | 描述                           |
|-----------------|----------|------------------------------|
| `--k-values`    | 5,10,20  | Recall@K 和 Precision@K 的 K 值 |
| `--output`      | markdown | 输出格式: json / markdown        |
| `--output-path` | -        | 结果保存目录                       |

#### validate

验证环境服务。

| 参数          | 描述             |
|-------------|----------------|
| `--service` | 指定验证的服务(可多次指定) |

可用服务: `postgres`、`neo4j`、`redis`、`llm`、`embedding`

#### seed

种子数据库关系类型和别名。

| 参数        | 描述          |
|-----------|-------------|
| `--reset` | 清空现有数据后重新插入 |

#### check-logging

检查禁止的 logging 模块使用。

| 参数           | 描述                                  |
|--------------|-------------------------------------|
| `files`      | 要检查的文件或目录(默认: src/ tests/ scripts/) |
| `--fix-hint` | 显示修复提示                              |

---

## build_nuitka.py

Nuitka 编译构建脚本,用于生成独立的二进制文件。

### 用法

```bash
uv run scripts/build_nuitka.py
```

### 输出

编译产物位于 `dist/` 目录。
