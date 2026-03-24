# 社区模块使用指南

本文档介绍如何使用 Weaver 的社区检测功能，包括社区重建、报告生成和搜索集成。

## 目录

- [快速开始](#快速开始)
- [社区检测](#社区检测)
- [社区报告](#社区报告)
- [搜索集成](#搜索集成)
- [API 参考](#api-参考)
- [最佳实践](#最佳实践)
- [故障排除](#故障排除)

---

## 快速开始

### 前置条件

1. Neo4j 数据库已运行
2. 图谱中已有实体和关系数据
3. LLM 服务已配置（用于报告生成）

### 初始化社区数据

```bash
# 手动触发社区重建
curl -X POST "http://localhost:8000/api/v1/admin/communities/rebuild" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"max_cluster_size": 10, "seed": 42}'
```

### 验证社区创建

```bash
# 查看社区列表
curl "http://localhost:8000/api/v1/graph/communities" \
  -H "Authorization: Bearer YOUR_API_KEY"
```

---

## 社区检测

### 算法说明

Weaver 使用 **Hierarchical Leiden 算法** 进行社区检测，该算法具有以下优点：

- **层次化结构**：生成多层次的社区划分
- **高模块度**：优化社区内连接密度
- **稳定性好**：相同输入产生相同结果（确定性）

### 触发方式

#### 1. 手动触发

```bash
POST /api/v1/admin/communities/rebuild
```

响应示例：

```json
{
  "success": true,
  "status": "completed",
  "communities_created": 25,
  "entities_processed": 350,
  "modularity": 0.42,
  "levels": 2,
  "orphan_count": 50,
  "execution_time_ms": 3500
}
```

#### 2. 自动触发

系统会自动在以下条件下触发社区检测：

| 条件 | 阈值 | 说明 |
|------|------|------|
| 无社区存在 | - | 首次运行时自动触发 |
| 实体变化 | 10% | 实体数量变化超过 10% |
| 时间间隔 | 7 天 | 距上次重建超过 7 天 |

### 检测参数

```python
from modules.graph_store.community_detector import CommunityDetector

detector = CommunityDetector(
    neo4j_pool=pool,
    max_cluster_size=10,  # 最大社区规模（实体数量上限）
    default_seed=42,      # 随机种子（确保可重复性）
)

result = await detector.rebuild_communities(
    max_cluster_size=10,  # 最大社区规模
    seed=42,             # 随机种子
)
```

**参数说明：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `max_cluster_size` | 10 | 社区最大规模，超过则拆分 |
| `seed` | 42 | 随机种子，用于算法随机化，保证结果可重复 |

### 结果解读

```python
result = await detector.detect_communities()

print(f"社区数量: {result.total_communities}")
print(f"模块度: {result.modularity}")  # 范围: [-0.5, 1.0]，越高越好
print(f"层次层数: {result.levels}")
print(f"孤立实体: {result.orphan_count}")
```

**模块度参考值**：

- `> 0.7`：优秀的社区结构
- `0.4 - 0.7`：良好的社区结构
- `< 0.4`：社区结构较弱

---

## 社区报告

### 报告生成

每个社区可生成语义摘要报告：

```python
from modules.graph_store.community_report_generator import CommunityReportGenerator

generator = CommunityReportGenerator(neo4j_pool, llm_client)

# 单个社区报告
result = await generator.generate_report(community_id="comm-123")

# 批量生成所有报告
batch_result = await generator.generate_all_reports()
```

### 报告内容

每个社区报告包含：

| 字段 | 说明 |
|------|------|
| `title` | 社区标题 |
| `summary` | 社区摘要（100-200字） |
| `full_content` | 完整报告内容 |
| `key_entities` | 关键实体列表 |
| `key_relationships` | 关键关系描述 |
| `rank` | 重要性评分 (1-10) |

### 报告嵌入

报告会自动生成向量嵌入，用于语义搜索：

```python
# 报告嵌入存储在 Neo4j
# 字段: full_content_embedding (1536维)
```

### 重新生成报告

```bash
# 重新生成单个社区报告
POST /api/v1/admin/communities/{community_id}/report/regenerate
```

---

## 搜索集成

### Global Search

全局搜索利用社区报告进行 Map-Reduce 问答：

```bash
# 全局搜索示例
GET /api/v1/search/global?query=人工智能最新进展
```

**工作流程**：

1. 向量相似度搜索相关社区报告
2. 并行生成每个社区的中间答案
3. 聚合生成最终答案

### DRIFT Search

DRIFT 搜索结合全局和局部搜索：

```bash
# DRIFT 搜索示例
POST /api/v1/search/drift
Content-Type: application/json

{
  "query": "OpenAI 和 Google 在 AI 领域的竞争格局"
}
```

**三阶段流程**：

1. **Primer 阶段**：向量搜索社区报告，生成初步答案
2. **Follow-up 阶段**：迭代局部搜索深化理解
3. **Aggregation 阶段**：聚合生成层次化回答

**响应示例**：

```json
{
  "query": "OpenAI 和 Google 在 AI 领域的竞争格局",
  "answer": "OpenAI 和 Google 是 AI 领域两大主要竞争者...",
  "confidence": 0.82,
  "hierarchy": {
    "primer": {
      "answer": "初步答案...",
      "community_count": 3
    },
    "follow_ups": [
      {"question": "OpenAI 的主要产品有哪些？", "answer": "..."}
    ]
  },
  "primer_communities": 3,
  "follow_up_iterations": 2
}
```

### 搜索配置

```python
from modules.search.engines.drift_search import DRIFTSearchEngine, DriftConfig

config = DriftConfig(
    primer_k=3,              # Primer 阶段使用的社区数量
    max_follow_ups=2,        # 最大 Follow-up 迭代次数
    confidence_threshold=0.7, # 提前终止阈值
)

engine = DRIFTSearchEngine(neo4j_pool, llm_client, config=config)
```

---

## API 参考

### 社区管理

#### 重建社区

```http
POST /api/v1/admin/communities/rebuild
Authorization: Bearer {api_key}
Content-Type: application/json

{
  "max_cluster_size": 10,
  "seed": 42
}
```

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `max_cluster_size` | int | 10 | 最大社区规模 |
| `seed` | int | 42 | 随机种子 |

**响应**：

```json
{
  "success": true,
  "status": "completed",
  "communities_created": 25,
  "entities_processed": 350,
  "modularity": 0.42,
  "levels": 2,
  "orphan_count": 50,
  "execution_time_ms": 3500
}
```

#### 获取社区列表

```http
GET /api/v1/graph/communities?level=0&limit=20&offset=0
Authorization: Bearer {api_key}
```

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `level` | int | - | 社区层级（不指定返回所有） |
| `limit` | int | 20 | 返回数量 |
| `offset` | int | 0 | 偏移量 |

**响应**：

```json
[
  {
    "id": "comm-1",
    "title": "人工智能研究",
    "summary": "AI 领域的研究进展...",
    "level": 0,
    "entity_count": 15,
    "rank": 8.5
  }
]
```

#### 获取社区详情

```http
GET /api/v1/graph/communities/{community_id}
Authorization: Bearer {api_key}
```

**响应**：

```json
{
  "id": "comm-1",
  "title": "人工智能研究",
  "summary": "AI 领域的研究进展...",
  "full_content": "完整报告内容...",
  "level": 0,
  "entity_count": 15,
  "rank": 8.5,
  "key_entities": ["OpenAI", "GPT-4", "DeepMind"],
  "parent_id": null
}
```

### 社区指标

```http
GET /api/v1/graph/metrics/community
Authorization: Bearer {api_key}
```

**响应**：

```json
{
  "total_communities": 25,
  "total_entities_in_communities": 350,
  "avg_community_size": 14.0,
  "modularity": 0.42,
  "hierarchy_levels": 2,
  "top_communities": [
    {"id": "comm-1", "title": "AI研究", "entity_count": 25}
  ]
}
```

### 搜索端点

#### 全局搜索

```http
GET /api/v1/search/global?query={query}&level=0
Authorization: Bearer {api_key}
```

#### DRIFT 搜索

```http
POST /api/v1/search/drift
Authorization: Bearer {api_key}
Content-Type: application/json

{
  "query": "搜索问题"
}
```

---

## 最佳实践

### 社区重建时机

1. **初始部署**：首次部署后立即触发社区重建
2. **数据更新**：大规模数据导入后触发
3. **定期维护**：每周执行一次自动重建

### 性能优化

1. **调整 max_cluster_size**：
   - 小型图谱（<1K 实体）：5-10
   - 中型图谱（1K-10K）：10-20
   - 大型图谱（>10K）：20-50

2. **报告生成并发**：
   ```python
   generator = CommunityReportGenerator(
       neo4j_pool,
       llm_client,
       max_concurrent=10,  # 并发生成报告数
   )
   ```

3. **搜索缓存**：
   - 启用社区报告缓存
   - 使用 Redis 缓存搜索结果

### 监控指标

关注以下 Prometheus 指标：

```promql
# 社区数量
community_count_total

# 社区检测执行时间
community_detection_duration_seconds

# 报告生成成功率
community_report_generation_success_rate

# 搜索延迟
search_duration_seconds{type="global|drift"}
```

---

## 故障排除

### 常见问题

#### 1. 社区检测返回空结果

**原因**：图谱中没有足够的实体关系

**解决**：
- 检查实体和关系数量
- 确保 RELATED_TO 关系存在

#### 2. 模块度值很低

**原因**：图谱结构不适合社区划分

**解决**：
- 增加实体关系密度
- 检查孤立实体比例

#### 3. 报告生成失败

**原因**：LLM 服务不可用或超时

**解决**：
- 检查 LLM 服务状态
- 增加超时时间
- 查看错误日志

#### 4. 搜索结果不相关

**原因**：社区报告嵌入缺失或质量问题

**解决**：
- 重新生成报告
- 检查嵌入向量是否正确存储
- 验证相似度阈值设置

### 日志查看

```bash
# 社区检测日志
grep "community_detection" /var/log/weaver/app.log

# 报告生成日志
grep "community_report" /var/log/weaver/app.log

# 搜索日志
grep "search\|drift" /var/log/weaver/app.log
```

### 回滚操作

如果社区数据出现问题，可以重新构建：

```bash
# 强制重建（清除现有社区）
POST /api/v1/admin/communities/rebuild
{"force": true}
```

---

## 相关文档

- [系统架构文档](./architecture.md)
- [API 文档](./api.md)
- [部署指南](./deployment.md)