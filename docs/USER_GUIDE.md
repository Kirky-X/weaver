# Weaver 用户指南

本文档帮助您快速上手 Weaver，了解如何使用其功能来采集、处理和分析新闻数据。

## 目录

- [快速开始](#快速开始)
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

```bash
# 开发模式
uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# 生产模式
uv run python -m src.main
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

| 概念 | 说明 |
|------|------|
| **Source** | 新闻源，可以是 RSS/Atom 订阅或网页 |
| **Article** | 文章，经过处理的新闻内容 |
| **Entity** | 实体，从文章中提取的人、组织、地点等 |
| **Relationship** | 关系，实体之间的关联 |
| **Pipeline** | 处理流水线，将原始内容转换为结构化数据 |
| **Community** | 社区，知识图谱中的实体群组 |

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

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | 是 | 唯一标识符，建议使用小写和连字符 |
| `name` | string | 是 | 显示名称 |
| `url` | string | 是 | RSS/Atom 订阅地址 |
| `source_type` | string | 否 | 源类型，默认 `rss` |
| `enabled` | boolean | 否 | 是否启用，默认 `true` |
| `interval_minutes` | integer | 否 | 抓取间隔（分钟），默认 30 |
| `credibility` | float | 否 | 预设可信度（0.0-1.0） |
| `tier` | integer | 否 | 层级：1=权威，2=可信，3=普通 |

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

---

## 搜索文章

### 统一搜索端点

使用统一搜索端点，通过 `mode` 参数路由到不同的搜索引擎：

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

| 模式 | 默认 | 说明 |
|------|------|------|
| `local` | ✅ | 实体聚焦的图谱问答，适合"X 是谁？"、"X 和 Y 的关系？" |
| `global` | | 社区级聚合搜索，适合跨多个话题的探索性查询 |
| `articles` | | 混合向量+关键词相似文章搜索 |

### DRIFT 迭代式搜索（实验性）

适合复杂多面查询，结合全局社区洞察和局部实体细节：

```bash
curl -X POST "http://localhost:8000/api/v1/search/drift" \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "人工智能在医疗领域的应用和发展趋势",
    "primer_k": 3,
    "max_follow_ups": 2
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

# 按可信度过滤
curl -X GET "http://localhost:8000/api/v1/articles?min_credibility=0.8" \
  -H "X-API-Key: your-api-key"

# 组合过滤和排序
curl -X GET "http://localhost:8000/api/v1/articles?category=政治&min_credibility=0.7&sort_by=publish_time&sort_order=desc" \
  -H "X-API-Key: your-api-key"
```

### 获取文章详情

```bash
curl -X GET "http://localhost:8000/api/v1/articles/{article_id}" \
  -H "X-API-Key: your-api-key"
```

---

## 探索知识图谱

### 查询实体

```bash
curl -X GET "http://localhost:8000/api/v1/graph/entities/雷军?limit=10" \
  -H "X-API-Key: your-api-key"
```

**响应示例：**

```json
{
  "entity": {
    "id": "entity-uuid",
    "canonical_name": "雷军",
    "type": "人物",
    "aliases": ["雷布斯"],
    "description": "小米科技创始人"
  },
  "relationships": [
    {
      "target": "小米",
      "relation_type": "创立",
      "source_article_id": "article-uuid"
    }
  ],
  "related_entities": [
    {
      "canonical_name": "小米",
      "type": "组织机构"
    }
  ]
}
```

### 查看文章图谱

```bash
curl -X GET "http://localhost:8000/api/v1/graph/articles/{article_id}/graph" \
  -H "X-API-Key: your-api-key"
```

### 图谱健康度

```bash
curl -X GET "http://localhost:8000/api/v1/graph/metrics/health" \
  -H "X-API-Key: your-api-key"
```

### 完整图谱指标

```bash
curl -X GET "http://localhost:8000/api/v1/graph/metrics/full" \
  -H "X-API-Key: your-api-key"
```

### 社区列表

```bash
curl -X GET "http://localhost:8000/api/v1/graph/communities?limit=20" \
  -H "X-API-Key: your-api-key"
```

### 社区详情

```bash
curl -X GET "http://localhost:8000/api/v1/graph/communities/{community_id}" \
  -H "X-API-Key: your-api-key"
```

### 重建社区

```bash
curl -X POST "http://localhost:8000/api/v1/admin/communities/rebuild" \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "force": false
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
  - job_name: 'weaver'
    scrape_interval: 15s
    static_configs:
      - targets: ['localhost:8000']
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

**排查步骤：**
```bash
# 1. 检查源配置
curl "http://localhost:8000/api/v1/sources/xinhua-news" \
  -H "X-API-Key: your-api-key"

# 2. 查看任务状态
curl "http://localhost:8000/api/v1/pipeline/tasks/{task_id}" \
  -H "X-API-Key: your-api-key"

# 3. 检查日志
# 查看应用日志中的错误信息
```

### Q: 搜索返回空结果？

**可能原因：**
1. 向量索引未创建
2. 查询与文章内容不匹配
3. 阈值设置过高

**解决方案：**
```bash
# 检查向量表
# 在 PostgreSQL 中运行：
SELECT COUNT(*) FROM article_vectors;

# 降低阈值重试
curl "http://localhost:8000/api/v1/search/articles?q=test&threshold=0.5" \
  -H "X-API-Key: your-api-key"
```

### Q: Neo4j 连接失败？

**排查步骤：**
1. 检查 Neo4j 服务是否运行
2. 验证配置中的连接信息
3. 检查防火墙设置

```bash
# 测试 Neo4j 连接
curl "http://localhost:8000/health"
# 查看 neo4j 状态
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

编辑 `config/settings.toml` 中的实体配置：

```toml
[entity_types]
custom_types = ["产品", "技术", "专利"]
```

然后重启服务。

---

## 下一步

- 阅读 [API 文档](./API.md) 了解完整 API 接口
- 查看 [架构文档](./ARCHITECTURE.md) 了解系统设计
- 参与 [贡献指南](../CONTRIBUTING.md) 帮助改进项目

---

如有其他问题，请通过 [GitHub Issues](https://github.com/your-org/weaver/issues) 反馈。
