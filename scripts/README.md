# Weaver Scripts

统一的开发和运维脚本目录。

## 脚本列表

| 脚本               | 描述                   |
| ------------------ | ---------------------- |
| `test_pipeline.py` | Pipeline 数据处理测试  |
| `test_api.py`      | API 端点测试           |
| `evaluate.py`      | 性能评估和搜索质量测试 |
| `manage.py`        | 环境验证和数据库种子   |

---

## test_pipeline.py

Pipeline 数据处理测试脚本，支持多种数据源模式。

### 用法

```bash
# NewsNow 模式
uv run scripts/test_pipeline.py --mode newsnow

# RSS 模式
uv run scripts/test_pipeline.py --mode rss

# 数据库故障转移测试模式
uv run scripts/test_pipeline.py --mode strategy

# 限制处理条目数
uv run scripts/test_pipeline.py --mode rss --max-items 50

# 跳过分类器直接作为新闻处理
uv run scripts/test_pipeline.py --mode rss --force-news

# 测试前清空数据库
uv run scripts/test_pipeline.py --mode rss --clear-db
```

### 参数

| 参数           | 默认值  | 描述                                 |
| -------------- | ------- | ------------------------------------ |
| `--mode`       | newsnow | 数据源模式：newsnow / rss / strategy |
| `--source`     | -       | RSS 源 URL（rss 模式）               |
| `--max-items`  | 10      | 最大处理条目数                       |
| `--force-news` | false   | 跳过分类器，强制作为新闻处理         |
| `--clear-db`   | false   | 测试前清空数据库                     |

---

## test_api.py

API 端点测试脚本，支持 E2E 流程测试和 API 审计。

### 用法

```bash
# E2E 测试 - 36kr 模式
uv run scripts/test_api.py e2e --mode 36kr

# E2E 测试 - RSS 模式
uv run scripts/test_api.py e2e --mode rss

# E2E 测试 - 全部模式
uv run scripts/test_api.py e2e --mode all

# E2E 测试 - 服务已启动，跳过启动
uv run scripts/test_api.py e2e --mode 36kr --no-start

# E2E 测试 - 限制条目数
uv run scripts/test_api.py e2e --mode 36kr --max-items 20

# API 审计 - 检查所有端点
uv run scripts/test_api.py audit

# API 审计 - 指定端口
uv run scripts/test_api.py audit --port 8080

# 使用 API Key
uv run scripts/test_api.py e2e --api-key your-api-key
```

### 子命令

#### e2e

端到端流程测试。

| 参数          | 默认值 | 描述                                      |
| ------------- | ------ | ----------------------------------------- |
| `--mode`      | 36kr   | 测试模式：36kr / rss / all                |
| `--max-items` | 10     | 最大处理条目数                            |
| `--no-start`  | false  | 服务已启动，跳过启动                      |
| `--api-key`   | -      | API Key（或设置 WEAVER_API_KEY 环境变量） |

#### audit

API 端点审计，遍历所有端点并记录响应。

| 参数        | 默认值 | 描述                                      |
| ----------- | ------ | ----------------------------------------- |
| `--port`    | 8000   | API 服务端口                              |
| `--api-key` | -      | API Key（或设置 WEAVER_API_KEY 环境变量） |

---

## evaluate.py

性能评估和搜索质量测试脚本。

### 用法

```bash
# HNSW 向量索引性能测试
uv run scripts/evaluate.py hnsw

# HNSW 测试 - 指定向量数量
uv run scripts/evaluate.py hnsw --num-vectors 2000

# HNSW 测试 - JSON 输出
uv run scripts/evaluate.py hnsw --output json

# BM25 搜索质量评估
uv run scripts/evaluate.py search

# 搜索评估 - 指定 K 值
uv run scripts/evaluate.py search --k-values 5,10,20

# 搜索评估 - JSON 输出
uv run scripts/evaluate.py search --output json

# 搜索评估 - 保存结果到文件
uv run scripts/evaluate.py search --output json --output-path ./results/
```

### 子命令

#### hnsw

HNSW 向量索引性能测试。

| 参数            | 默认值   | 描述                      |
| --------------- | -------- | ------------------------- |
| `--num-vectors` | 1000     | 批量插入测试的向量数量    |
| `--num-queries` | 20       | 查询性能测试的查询次数    |
| `--output`      | markdown | 输出格式：json / markdown |

#### search

BM25 搜索质量评估。

| 参数            | 默认值   | 描述                            |
| --------------- | -------- | ------------------------------- |
| `--k-values`    | 5,10,20  | Recall@K 和 Precision@K 的 K 值 |
| `--output`      | markdown | 输出格式：json / markdown       |
| `--output-path` | -        | 结果保存目录                    |

---

## manage.py

环境验证和数据库管理脚本。

### 用法

```bash
# 验证所有服务
uv run scripts/manage.py validate

# 验证特定服务
uv run scripts/manage.py validate --service postgres --service redis

# 种子数据库 - 插入缺失的关系类型
uv run scripts/manage.py seed

# 种子数据库 - 重置并重新插入所有数据
uv run scripts/manage.py seed --reset
```

### 子命令

#### validate

验证环境服务（PostgreSQL、Neo4j、Redis、LLM、Embedding）。

| 参数        | 描述                         |
| ----------- | ---------------------------- |
| `--service` | 指定验证的服务（可多次指定） |

可用服务：`postgres`、`neo4j`、`redis`、`llm`、`embedding`

#### seed

种子数据库关系类型和别名。

| 参数      | 描述                   |
| --------- | ---------------------- |
| `--reset` | 清空现有数据后重新插入 |

### 退出码

- `0` - 成功
- `1` - 失败
