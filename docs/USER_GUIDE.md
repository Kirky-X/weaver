# Weaver 用户指南

本文档帮助您快速上手 Weaver，了解如何使用其功能来采集、处理和分析新闻数据。

## 目录

- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [基本概念](#基本概念)
- [管理新闻源](#管理新闻源)
- [运行 Pipeline](#运行-pipeline)
- [搜索文章](#搜索文章)
- [探索知识图谱](#探索知识图谱)
- [监控和运维](#监控和运维)
- [常见问题](#常见问题)

---

## 快速开始

### 1. 启动服务

Weaver 支持端口自动检测，当配置的端口被占用时会自动寻找可用端口：

```bash
# 开发模式（端口自动检测默认启用）
uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# 生产模式（使用 main.py 的 lifespan 管理）
uv run python -m src.main
```

**端口自动检测特性**：

- 启动时自动检查配置端口是否可用
- 端口被占用时自动寻找可用端口（双向搜索）
- 实际端口信息输出到日志
- 当 `WEAVER_WRITE_PORT_ENV=true` 时,端口信息会写入 `.env.weaver` 文件
- Docker 健康检查自动适配动态端口

**配置端口检测**：

```toml
# config/settings.toml
[api]
port = 8000              # 默认端口
port_auto_detect = true  # 启用自动检测(生产环境默认 false)
```

如果需要禁用自动检测（例如在固定端口环境）：

```toml
[api]
port = 8000
port_auto_detect = false
```

服务启动后，访问 `http://localhost:8000/health` 验证健康状态。

### 2. 添加第一个新闻源

```bash
curl -X POST "http://localhost:8000/api/v1/sources" \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "xinhua-news",
    "name": "新华社",
    "url": "http://www.xinhuanet.com/politics/news_politics.xml",
    "source_type": "rss",
    "enabled": true,
    "interval_minutes": 30,
    "credibility": 0.98,
    "tier": 1
  }'
```

### 3. 触发 Pipeline

```bash
curl -X POST "http://localhost:8000/api/v1/pipeline/trigger" \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "source_id": "xinhua-news",
    "force": false
  }'
```

### 4. 查询文章

```bash
curl -X GET "http://localhost:8000/api/v1/articles?page=1&page_size=10" \
  -H "X-API-Key: your-api-key"
```

---

## 配置说明

Weaver 使用统一的配置系统,支持 TOML 文件和环境变量。

### 配置文件结构

```bash
config/
├── settings.toml          # 主配置文件 (服务地址、功能开关)
├── settings.example.toml  # 配置模板
├── llm.toml              # LLM Provider 和路由配置
├── llm.example.toml      # LLM 配置模板
├── pipeline.toml         # Pipeline 阶段配置
└── prompts/              # LLM 提示词模板
```

### 环境变量格式

环境变量优先级最高,可以覆盖 TOML 配置。

**格式**: `WEAVER_<SECTION>__<FIELD>` (单下划线前缀 + 双下划线分隔嵌套)

```bash
# PostgreSQL 密码
WEAVER_POSTGRES__PASSWORD=your_password

# Neo4j 密码
WEAVER_NEO4J__PASSWORD=your_password

# Redis 密码(可选)
WEAVER_REDIS__PASSWORD=

# API Key (至少 32 字符)
WEAVER_API__API_KEY=your_api_key_at_least_32_characters_long

# LLM Provider API Keys
WEAVER_LLM__PROVIDERS__AIPING__API_KEY=your_aiping_api_key
WEAVER_LLM__PROVIDERS__DMX__API_KEY=your_dmx_api_key
```

### LLM 配置说明

LLM 配置使用两层嵌套结构: **Provider + Models**。

**示例** (`config/llm.toml`):

```toml
[providers.openai]
type = "openai"
base_url = "https://api.openai.com/v1"
api_key = "${OPENAI_API_KEY}"  # 引用环境变量
rpm_limit = 500
concurrency = 10

  [providers.openai.models.chat]
  model_id = "gpt-4o"
  temperature = 0.0
  max_tokens = 4096
  capabilities = ["chat", "vision"]

  [providers.openai.models.embedding]
  model_id = "text-embedding-3-large"
  capabilities = ["embedding"]
```

**调用点路由**:

```toml
[call-points.classifier]
primary = "chat.openai.gpt-4o"
fallbacks = ["chat.anthropic.claude-sonnet-4-20250514"]

[call-points.entity_extractor]
primary = "chat.openai.gpt-4o"
fallbacks = ["chat.anthropic.claude-sonnet-4-20250514"]
```

### 常用配置项

**API 服务**:

```toml
[api]
host = "0.0.0.0"
port = 8000
port_auto_detect = true  # 端口被占用时自动寻找可用端口
rate_limit = "100/minute"
```

**定时任务**:

```toml
[scheduler]
crawl_interval_minutes = 30        # RSS 抓取间隔
neo4j_retry_interval_minutes = 10  # Neo4j 写入重试间隔
retry_flush_interval_seconds = 30  # 爬虫重试队列刷新间隔
```

**搜索增强**:

```toml
[search]
hybrid_enabled = true              # 启用混合搜索 (向量 + 关键词)
rerank_enabled = true              # 启用重排序
rerank_model = "tiny"             # Flashrank 模型 (tiny/small/medium/multilingual)
mmr_enabled = false               # 启用 MMR 多样性
mmr_lambda = 0.7                  # MMR 平衡参数 (0-1)
bm25_rebuild_interval = 300       # BM25 索引重建间隔(秒)
temporal_decay_enabled = false    # 启用时间衰减
temporal_decay_half_life_days = 30.0  # 时间衰减半衰期(天)
```

---

## 基本概念

### 系统架构

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  数据源      │────▶│  采集层      │────▶│  处理流水线  │
│  (RSS/Web)  │     │  (Fetcher)  │     │  (Pipeline) │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                               │
                         ┌─────────────────────┼─────────────────────┐
                         │                     │                     │
                         ▼                     ▼                     ▼
                  ┌─────────────┐      ┌─────────────┐      ┌─────────────┐
                  │ PostgreSQL  │      │   Neo4j     │      │   Redis     │
                  │  (文章存储)  │      │ (知识图谱)   │      │ (缓存/队列)  │
                  └─────────────┘      └─────────────┘      └─────────────┘
```

### 核心概念

| 概念             | 说明                                   |
| ---------------- | -------------------------------------- |
| **Source**       | 新闻源，可以是 RSS/Atom 订阅或网页     |
| **Article**      | 文章，经过处理的新闻内容               |
| **Entity**       | 实体，从文章中提取的人、组织、地点等   |
| **Relationship** | 关系，实体之间的关联                   |
| **Pipeline**     | 处理流水线，将原始内容转换为结构化数据 |
| **Community**    | 社区，知识图谱中的实体群组             |

---

## 管理新闻源

### 添加 RSS 源

```bash
curl -X POST "http://localhost:8000/api/v1/sources" \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "bbc-news",
    "name": "BBC News",
    "url": "https://feeds.bbci.co.uk/news/rss.xml",
    "source_type": "rss",
    "enabled": true,
    "interval_minutes": 60,
    "credibility": 0.85,
    "tier": 2
  }'
```

### 查看所有源

```bash
curl -X GET "http://localhost:8000/api/v1/sources" \
  -H "X-API-Key: your-api-key"
```

### 更新源配置

```bash
# 禁用某个源
curl -X PUT "http://localhost:8000/api/v1/sources/bbc-news" \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": false
  }'

# 修改抓取间隔
curl -X PUT "http://localhost:8000/api/v1/sources/bbc-news" \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "interval_minutes": 120
  }'
```

### 删除源

```bash
curl -X DELETE "http://localhost:8000/api/v1/sources/bbc-news" \
  -H "X-API-Key: your-api-key"
```

### 源配置字段说明

| 字段                     | 类型      | 必填 | 说明                                     |
| ------------------------ | --------- | ---- | ---------------------------------------- |
| `id`                     | string    | 是   | 唯一标识符，建议使用小写和连字符         |
| `name`                   | string    | 是   | 显示名称                                 |
| `url`                    | string    | 是   | RSS/Atom 订阅地址                        |
| `source_type`            | string    | 否   | 源类型，默认 `rss`                       |
| `enabled`                | boolean   | 否   | 是否启用，默认 `true`                    |
| `interval_minutes`       | integer   | 否   | 抓取间隔（分钟），默认 30，范围 5-1440   |
| `per_host_concurrency`   | integer   | 否   | 每主机最大并发请求数，默认 2，范围 1-10  |
| `credibility`            | float     | 否   | 预设可信度（0.0-1.0）                    |
| `tier`                   | integer   | 否   | 层级：1=权威，2=可信，3=普通             |

---

## 运行 Pipeline

### 触发 Pipeline

Pipeline 会抓取并处理新闻文章。

```bash
# 触发所有源的 Pipeline
curl -X POST "http://localhost:8000/api/v1/pipeline/trigger" \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "source_id": null,
    "force": false,
    "max_items": null
  }'

# 触发特定源的 Pipeline
curl -X POST "http://localhost:8000/api/v1/pipeline/trigger" \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "source_id": "xinhua-news",
    "force": false
  }'

# 强制重新抓取（忽略最近已抓取的 URL）
curl -X POST "http://localhost:8000/api/v1/pipeline/trigger" \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "source_id": "xinhua-news",
    "force": true
  }'

# 限制处理数量
curl -X POST "http://localhost:8000/api/v1/pipeline/trigger" \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "source_id": "xinhua-news",
    "max_items": 50
  }'
```

### 查看任务状态

```bash
# 查询任务状态
curl -X GET "http://localhost:8000/api/v1/pipeline/tasks/{task_id}" \
  -H "X-API-Key: your-api-key"
```

**响应示例：**

```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "running",
  "source_id": "xinhua-news",
  "queued_at": "2024-01-15T10:30:00Z",
  "started_at": "2024-01-15T10:30:01Z",
  "completed_at": null,
  "progress": null,
  "total": null,
  "error": null,
  "total_processed": 15,
  "processing_count": 3,
  "completed_count": 10,
  "failed_count": 2,
  "pending_count": 5
}
```

### 查看队列统计

```bash
curl -X GET "http://localhost:8000/api/v1/pipeline/queue/stats" \
  -H "X-API-Key: your-api-key"
```

**响应示例：**

```json
{
  "queue_depth": 5,
  "status_counts": {
    "running": 2,
    "completed": 10,
    "failed": 3
  },
  "total_tasks": 15,
  "article_stats": {
    "total_articles": 1500,
    "processing_count": 25,
    "completed_count": 1200,
    "failed_count": 50,
    "pending_count": 275
  }
}
```

### 处理单个 URL

Weaver 还支持直接处理单个 URL，无需配置新闻源：

```bash
curl -X POST "http://localhost:8000/api/v1/pipeline/url" \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com/news/article",
    "whitelist_mode": false
  }'
```

**参数说明：**

| 字段             | 类型    | 默认  | 说明                           |
| ---------------- | ------- | ----- | ------------------------------ |
| `url`            | string  | 必填  | 要处理的资讯网页 URL           |
| `whitelist_mode` | boolean | false | 是否启用白名单模式             |

---

## 搜索文章

### 统一搜索端点

使用统一搜索端点，系统采用 **Intent-Aware Routing** 自动识别查询意图并选择最优搜索策略：

```bash
# 本地搜索（默认）- 实体聚焦的图谱问答
curl -X GET "http://localhost:8000/api/v1/search?q=雷军是谁" \
  -H "X-API-Key: your-api-key"

# 全局搜索 - 社区级聚合搜索
curl -X GET "http://localhost:8000/api/v1/search?q=中国经济&mode=global" \
  -H "X-API-Key: your-api-key"

# 文章搜索 - 混合向量+关键词检索
curl -X GET "http://localhost:8000/api/v1/search?q=人工智能&mode=articles&threshold=0.7" \
  -H "X-API-Key: your-api-key"
```

**mode 参数说明：**

| 模式       | 默认 | 说明                                                  |
| ---------- | ---- | ----------------------------------------------------- |
| `local`    |      | 直接向量搜索，适合实体邻里关系查询                    |
| `global`   |      | 社区级搜索，适合更广泛的上下文查询                    |
| `auto`     | ✅   | 基于意图的自动路由（默认）                            |

**其他查询参数：**

| 参数              | 类型    | 默认        | 说明                                       |
| ----------------- | ------- | ----------- | ------------------------------------------ |
| `q`               | string  | 必填        | 搜索查询                                   |
| `mode`            | string  | `auto`      | 搜索模式：local/global/auto                |
| `community_level` | int     | 0           | 社区层级（global 模式），范围 0-10         |
| `threshold`       | float   | 0.0         | 相似度阈值（articles 模式），范围 0.0-1.0  |
| `limit`           | int     | 20          | 最大结果数（articles 模式），范围 1-100    |
| `category`        | string  | null        | 类别过滤（articles 模式）                  |
| `use_hybrid`      | boolean | true        | 使用混合搜索（articles 模式）              |
| `global_mode`     | string  | `map_reduce`| Global 搜索模式：map_reduce 或 simple      |
| `output_mode`     | string  | `context`   | 输出格式：context（原始片段）或 narrative（LLM 综合答案） |
| `enrich_entities` | boolean | false       | 启用实体聚合以丰富结果                     |

### DRIFT 迭代式搜索（实验性）

适合复杂多面查询，结合全局社区洞察和局部实体细节：

```bash
curl -X POST "http://localhost:8000/api/v1/search/drift" \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "人工智能在医疗领域的应用和发展趋势",
    "primer_k": 3,
    "max_follow_ups": 2,
    "confidence_threshold": 0.7
  }'
```

**DRIFT 搜索参数：**

| 参数                 | 类型    | 默认  | 说明                           |
| -------------------- | ------- | ----- | ------------------------------ |
| `query`              | string  | 必填  | 搜索查询                       |
| `primer_k`           | int     | 3     | 初始社区报告数量               |
| `max_follow_ups`     | int     | 2     | 最大跟进迭代次数               |
| `confidence_threshold`| float  | 0.7   | 置信度阈值                     |

### 因果推理搜索

使用 MAGMA 多图架构遍历因果链，回答“为什么”问题：

```bash
curl -X POST "http://localhost:8000/api/v1/search/causal" \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "为什么某事件会发生",
    "max_depth": 3,
    "min_confidence": 0.7
  }'
```

### 时间推理搜索

按时间顺序检索事件，回答“何时”问题：

```bash
curl -X POST "http://localhost:8000/api/v1/search/temporal" \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "某事件何时发生",
    "time_window_days": 7,
    "limit": 10
  }'
```

### 查询文章列表

```bash
# 基本查询
curl -X GET "http://localhost:8000/api/v1/articles?page=1&page_size=20" \
  -H "X-API-Key: your-api-key"

# 按类别过滤
curl -X GET "http://localhost:8000/api/v1/articles?category=科技" \
  -H "X-API-Key: your-api-key"

# 按来源主机过滤
curl -X GET "http://localhost:8000/api/v1/articles?source_host=example.com" \
  -H "X-API-Key: your-api-key"

# 按可信度过滤
curl -X GET "http://localhost:8000/api/v1/articles?min_credibility=0.8" \
  -H "X-API-Key: your-api-key"

# 按分数过滤
curl -X GET "http://localhost:8000/api/v1/articles?min_score=0.7" \
  -H "X-API-Key: your-api-key"

# 组合过滤和排序
curl -X GET "http://localhost:8000/api/v1/articles?category=政治&min_credibility=0.7&sort_by=publish_time&sort_order=desc" \
  -H "X-API-Key: your-api-key"
```

**查询参数：**

| 参数            | 类型    | 默认           | 说明                                       |
| --------------- | ------- | -------------- | ------------------------------------------ |
| `page`          | int     | 1              | 页码（从 1 开始）                          |
| `page_size`     | int     | 20             | 每页条数，范围 1-100                         |
| `category`      | string  | null           | 按类别过滤                                 |
| `source_host`   | string  | null           | 按来源主机名过滤                           |
| `min_score`     | float   | null           | 最低分数过滤，范围 0-1                       |
| `min_credibility`| float  | null           | 最低可信度过滤，范围 0-1                     |
| `sort_by`       | string  | `publish_time` | 排序字段：publish_time/score/credibility_score/created_at |
| `sort_order`    | string  | `desc`         | 排序顺序：asc 或 desc                        |

### 获取文章详情

```bash
curl -X GET "http://localhost:8000/api/v1/articles/{article_id}" \
  -H "X-API-Key: your-api-key"
```

---

## 探索知识图谱

### 查询实体

```bash
# 查询实体及其关系
curl -X GET "http://localhost:8000/api/v1/graph/entities/%E9%9B%B7%E5%86%9B?limit=10" \
  -H "X-API-Key: your-api-key"
```

**注意**: 实体名称需要进行 URL 编码。

**响应示例：**

```json
{
  "entity": {
    "id": "entity-uuid",
    "canonical_name": "雷军",
    "type": "人物",
    "aliases": ["雷布斯"],
    "description": "小米科技创始人",
    "updated_at": "2024-01-15T10:30:00Z"
  },
  "relationships": [
    {
      "target": "小米",
      "relation_type": "创立",
      "source_article_id": "article-uuid",
      "created_at": "2024-01-15T10:30:00Z"
    }
  ],
  "related_entities": [
    {
      "id": "entity-uuid-2",
      "canonical_name": "小米",
      "type": "组织机构",
      "aliases": [],
      "description": "科技公司",
      "updated_at": "2024-01-15T10:30:00Z"
    }
  ],
  "mentioned_in_articles": [
    {
      "id": "article-uuid",
      "title": "相关新闻",
      "publish_time": "2024-01-15T10:30:00Z"
    }
  ]
}
```

### 关系搜索

Weaver 提供两层关系搜索：

**Layer 1: 发现实体关系类型**

```bash
curl -X GET "http://localhost:8000/api/v1/graph/relations?entity=%E5%B0%8F%E7%B1%B3&entity_type=%E7%BB%84%E7%BB%87%E6%9C%BA%E6%9E%84" \
  -H "X-API-Key: your-api-key"
```

**Layer 2: 搜索相关实体**

```bash
curl -X GET "http://localhost:8000/api/v1/graph/relations/search?entity=%E5%B0%8F%E7%B1%B3&relation_types=%E5%88%9B%E7%AB%8B,%E6%8A%95%E8%B5%84&limit=50" \
  -H "X-API-Key: your-api-key"
```

### 查看文章图谱

```bash
curl -X GET "http://localhost:8000/api/v1/graph/articles/{article_id}/graph" \
  -H "X-API-Key: your-api-key"
```

### 图谱健康度

```bash
curl -X GET "http://localhost:8000/api/v1/graph/metrics?view=health" \
  -H "X-API-Key: your-api-key"
```

### 完整图谱指标

```bash
curl -X GET "http://localhost:8000/api/v1/graph/metrics?view=full" \
  -H "X-API-Key: your-api-key"
```

### 社区列表

```bash
curl -X GET "http://localhost:8000/api/v1/admin/communities?level=0&limit=20&offset=0" \
  -H "X-API-Key: your-api-key"
```

**查询参数：**

| 参数    | 类型   | 默认 | 说明                          |
| ------- | ------ | ---- | ----------------------------- |
| `level` | int    | null | 按社区层级过滤                |
| `limit` | int    | 20   | 最大结果数，范围 1-100          |
| `offset`| int    | 0    | 结果偏移量                    |

### 社区详情

```bash
curl -X GET "http://localhost:8000/api/v1/admin/communities/{community_id}" \
  -H "X-API-Key: your-api-key"
```

### 重建社区

```bash
curl -X POST "http://localhost:8000/api/v1/admin/communities/rebuild" \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "max_cluster_size": 10,
    "seed": 42
  }'
```

**重建参数：**

| 参数               | 类型  | 默认 | 说明                          |
| ------------------ | ----- | ---- | ----------------------------- |
| `max_cluster_size` | int   | 10   | 最大簇大小，范围 1-100          |
| `seed`             | int   | 42   | 随机种子（用于可重复性）       |

### 生成社区报告

```bash
curl -X POST "http://localhost:8000/api/v1/admin/communities/reports/generate?level=0&regenerate_stale=true" \
  -H "X-API-Key: your-api-key"
```

### 社区健康检查

```bash
# 健康概览
curl -X GET "http://localhost:8000/api/v1/admin/communities/health" \
  -H "X-API-Key: your-api-key"

# 完整诊断
curl -X POST "http://localhost:8000/api/v1/admin/communities/health/diagnose" \
  -H "X-API-Key: your-api-key"

# 自动修复
curl -X POST "http://localhost:8000/api/v1/admin/communities/health/repair" \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "repair_types": ["empty_communities", "stale_reports"],
    "dry_run": false
  }'
```

---

## 监控和运维

### 健康检查

```bash
curl -X GET "http://localhost:8000/health"
```

### Prometheus 指标

```bash
curl -X GET "http://localhost:8000/metrics"
```

### 配置 Prometheus

```yaml
scrape_configs:
  - job_name: "weaver"
    scrape_interval: 15s
    static_configs:
      - targets: ["localhost:8000"]
    metrics_path: /metrics
```

### 常用监控查询

```promql
# HTTP 请求速率
rate(http_requests_total[5m])

# P95 请求延迟
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))

# 文章处理成功率
sum(rate(articles_processed_total{status="success"}[1h]))
/
sum(rate(articles_processed_total[1h]))

# 数据库连接池使用率
db_connection_pool_checked_out{database="postgres"}
/
db_connection_pool_size{database="postgres"}
```

---

## 常见问题

### Q: Pipeline 运行后没有看到文章？

**可能原因：**

1. 源配置错误（URL 不正确）
2. 网络连接问题
3. 文章被分类器过滤（非新闻内容）
4. spaCy 模型未正确安装

**排查步骤：**

```bash
# 1. 检查源配置
curl "http://localhost:8000/api/v1/sources/xinhua-news" \
  -H "X-API-Key: your-api-key"

# 2. 查看任务状态
curl "http://localhost:8000/api/v1/pipeline/tasks/{task_id}" \
  -H "X-API-Key: your-api-key"

# 3. 检查队列统计
curl "http://localhost:8000/api/v1/pipeline/queue/stats" \
  -H "X-API-Key: your-api-key"

# 4. 检查日志
# 查看应用日志中的错误信息，特别是 spaCy 模型加载和 LLM 调用错误
```

### Q: 搜索返回空结果？

**可能原因：**

1. 向量索引未创建
2. 查询与文章内容不匹配
3. 阈值设置过高
4. 知识图谱中没有相关实体

**解决方案：**

```bash
# 检查向量表
# 在 PostgreSQL 中运行：
SELECT COUNT(*) FROM article_embeddings;

# 降低阈值重试
curl "http://localhost:8000/api/v1/search?q=test&mode=local" \
  -H "X-API-Key: your-api-key"

# 尝试 auto 模式（基于意图路由）
curl "http://localhost:8000/api/v1/search?q=test" \
  -H "X-API-Key: your-api-key"
```

### Q: Neo4j 连接失败？

**排查步骤：**

1. 检查 Neo4j 服务是否运行
2. 验证配置中的连接信息（`config/settings.toml` 中的 `[neo4j]` 部分）
3. 检查防火墙设置
4. 确认环境变量 `WEAVER_NEO4J__PASSWORD` 已设置

```bash
# 测试 Neo4j 连接
curl "http://localhost:8000/health"
# 查看响应中的 neo4j 状态
```

### Q: 如何处理重复文章？

Weaver 自动处理重复文章：

1. **URL 去重**：相同 URL 的文章不会重复处理
2. **内容相似度合并**：相似度超过 0.80 的文章会被合并

如果需要手动触发重新处理：

```bash
curl -X POST "http://localhost:8000/api/v1/pipeline/trigger" \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "source_id": "xinhua-news",
    "force": true
  }'
```

### Q: 如何添加自定义实体类型？

Weaver 的实体类型由 LLM 提示词和 spaCy 模型决定。你可以通过以下方式影响实体提取：

1. **编辑提示词模板**: 修改 `config/prompts/` 中的相关文件
2. **配置 spaCy 模型**: 在 `config/settings.toml` 中配置

```toml
[entity]
disable_data_metrics_nodes = true  # 过滤数值类实体（CARDINAL/PERCENT/MONEY）
```

3. **调整 LLM 配置**: 在 `config/llm.toml` 中配置用于实体提取的模型

```toml
[call-points.entity_extractor]
primary = "chat.your_provider.your_model"
fallbacks = ["chat.another_provider.model"]
```

然后重启服务。

---

## 下一步

- 阅读 [API 文档](./API.md) 了解完整 API 接口
- 查看 [架构文档](./ARCHITECTURE.md) 了解系统设计
- 查看 [配置说明](../config/settings.example.toml) 了解所有配置项
- 参与 [贡献指南](../CONTRIBUTING.md) 帮助改进项目

### 管理员功能

Weaver 还提供了一些管理员功能：

- **源权威管理**: `/api/v1/admin/authorities` - 管理新闻源权威性评分
- **LLM 失败监控**: `/api/v1/admin/llm-failures` - 查看 LLM 调用失败记录
- **LLM 失败统计**: `/api/v1/admin/llm-failures/stats` - 查看 LLM 失败统计

### 去重配置

Weaver 自动处理重复文章：

1. **URL 去重**: 相同 URL 的文章不会重复处理
2. **SimHash 去重**: 标题相似度超过阈值的文章会被检测

```toml
# config/settings.toml
[dedup]
enable_simhash_dedup = true            # 启用 SimHash 标题去重
simhash_hamming_threshold = 3          # 最大汉明距离（0-64，越低越严格）
```

---

如有其他问题，请通过 [GitHub Issues](https://github.com/your-org/weaver/issues) 反馈。
