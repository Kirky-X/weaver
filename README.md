# Weaver

智能新闻采集、分析与知识图谱构建平台

## 核心特性

- **RSS 源管理** - 订阅、调度、解析 RSS/Atom 源，支持增量抓取
- **智能爬取** - 自动选择 HTTPX 或 Playwright，支持动态页面渲染
- **LLM 处理流水线** - 分类、清洗、摘要、情感分析、实体提取
- **知识图谱** - Neo4j 存储实体关系，支持图谱查询
- **向量检索** - pgvector 支持语义相似度搜索
- **可信度评估** - 多维度信号聚合计算新闻可信度
- **REST API** - FastAPI 提供完整 API 接口

## 技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.12+ |
| Web 框架 | FastAPI + Uvicorn |
| 关系数据库 | PostgreSQL + pgvector |
| 图数据库 | Neo4j |
| 缓存 | Redis |
| 浏览器自动化 | Playwright |
| LLM 框架 | LangChain / LangGraph |
| NLP | spaCy |
| 任务调度 | APScheduler |
| 可观测性 | Prometheus + OpenTelemetry |

## 架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              RSS Sources                                     │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│  SourceScheduler → Deduplicator → Interleaver → Crawler (SmartFetcher)      │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Processing Pipeline                                │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ Phase 1 (Per-Article Concurrent)                                      │  │
│  │   Classifier → Cleaner → Categorizer → Vectorize                      │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                    ↓                                         │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ Phase 2 (Batch Serial)                                                 │  │
│  │   BatchMerger (Union-Find similarity clustering)                       │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                    ↓                                         │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ Phase 3 (Per-Article Concurrent)                                      │  │
│  │   ReVectorize → Analyze → Credibility → EntityExtractor               │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Storage Layer                                      │
│         PostgreSQL (Articles + Vectors)    Neo4j (Knowledge Graph)          │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 目录结构

```
src/
├── api/                     # FastAPI 层
│   ├── endpoints/           # 业务端点
│   │   ├── articles.py      # 文章查询
│   │   ├── graph.py         # 知识图谱
│   │   ├── admin.py         # 管理接口
│   │   ├── metrics.py       # Prometheus 指标
│   │   ├── pipeline.py      # Pipeline 触发
│   │   └── sources.py       # 源管理
│   ├── middleware/          # 中间件
│   │   └── auth.py          # API Key 认证
│   └── router.py            # 路由聚合
├── config/                  # 配置
│   ├── prompts/             # LLM Prompt 模板 (TOML)
│   │   ├── classifier.toml
│   │   ├── cleaner.toml
│   │   ├── categorizer.toml
│   │   ├── merger.toml
│   │   ├── analyze.toml
│   │   ├── credibility.toml
│   │   ├── entity_extractor.toml
│   │   └── entity_resolver.toml
│   ├── settings.py          # 配置类定义
│   └── settings.toml        # 主配置文件
├── core/                    # 核心基础设施
│   ├── cache/               # Redis 客户端
│   ├── db/                  # 数据库连接池
│   │   ├── postgres.py      # PostgreSQL
│   │   ├── neo4j.py         # Neo4j
│   │   └── models.py        # SQLAlchemy 模型
│   ├── event/               # 事件总线
│   ├── fetcher/             # Playwright 浏览器池
│   ├── llm/                 # LLM 客户端
│   │   ├── client.py        # 统一客户端
│   │   ├── config_manager.py
│   │   ├── queue_manager.py # 优先级队列
│   │   ├── rate_limiter.py  # Redis 令牌桶
│   │   ├── token_budget.py  # Token 截断
│   │   ├── output_validator.py
│   │   ├── types.py         # 枚举定义
│   │   └── providers/       # Provider 实现
│   ├── observability/       # 可观测性
│   │   ├── logging.py       # structlog
│   │   ├── metrics.py       # Prometheus
│   │   └── tracing.py       # OpenTelemetry
│   ├── prompt/              # Prompt 加载器
│   └── resilience/          # 断路器
├── modules/                 # 业务模块
│   ├── collector/           # 采集层
│   │   ├── crawler.py       # 智能爬虫
│   │   ├── deduplicator.py  # 两级去重
│   │   ├── interleaver.py   # 交错调度
│   │   ├── retry.py         # 重试队列
│   │   └── models.py        # ArticleRaw
│   ├── fetcher/             # 抓取器
│   │   ├── base.py          # 抽象基类
│   │   ├── httpx_fetcher.py # HTTP 抓取
│   │   ├── playwright_fetcher.py
│   │   └── smart_fetcher.py # 自动选择
│   ├── graph_store/         # 图存储
│   │   ├── entity_resolver.py
│   │   └── neo4j_writer.py
│   ├── nlp/                 # NLP
│   │   └── spacy_extractor.py
│   ├── pipeline/            # 处理流水线
│   │   ├── graph.py         # Pipeline 编排
│   │   ├── state.py         # PipelineState
│   │   └── nodes/           # 处理节点
│   │       ├── classifier.py
│   │       ├── cleaner.py
│   │       ├── categorizer.py
│   │       ├── vectorize.py
│   │       ├── batch_merger.py
│   │       ├── re_vectorize.py
│   │       ├── analyze.py
│   │       ├── credibility_checker.py
│   │       └── entity_extractor.py
│   ├── scheduler/           # 定时任务
│   │   └── jobs.py
│   ├── source/              # 源管理
│   │   ├── registry.py
│   │   ├── scheduler.py
│   │   ├── rss_parser.py
│   │   └── models.py
│   └── storage/             # 数据仓库
│       ├── article_repo.py
│       ├── vector_repo.py
│       ├── source_authority_repo.py
│       └── neo4j/
│           ├── article_repo.py
│           └── entity_repo.py
├── alembic/                 # 数据库迁移
│   ├── env.py
│   └── versions/
├── scripts/                 # 脚本
│   └── process_pending.py
├── container.py             # 依赖注入容器
└── main.py                  # 应用入口
```

## 快速开始

### 环境要求

- Python 3.12+
- PostgreSQL 15+ (with pgvector)
- Neo4j 5+
- Redis 7+

### 安装

```bash
# 克隆项目
git clone <repository-url>
cd weaver

# 安装依赖 (使用 uv)
uv sync

# 安装 Playwright 浏览器
uv run playwright install chromium

# 安装 spaCy 模型
uv run python -m spacy download zh_core_web_sm
```

### 配置

1. 复制配置模板：

```bash
cp src/config/settings.example.toml src/config/settings.toml
```

2. 编辑 `settings.toml`：

```toml
[postgres]
dsn = "postgresql+asyncpg://user:pass@localhost:5432/news_discovery"

[neo4j]
uri = "bolt://localhost:7687"
user = "neo4j"
password = "your_password"

[redis]
url = "redis://localhost:6379/0"

[llm]
embedding_provider = "openai"
embedding_model = "text-embedding-3-large"

[llm.providers.openai]
provider = "openai"
model = "gpt-4o"
api_key = "your_api_key"
base_url = "https://api.openai.com/v1"

[llm.providers.ollama]
provider = "ollama"
model = "qwen3.5:9b"
base_url = "http://localhost:11434"

[api]
api_key = "your-api-key"
rate_limit = "100/minute"
host = "0.0.0.0"
port = 8000
```

### 数据库迁移

```bash
# 运行迁移
uv run alembic upgrade head
```

### 启动服务

```bash
# 开发模式
uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# 生产模式
uv run python -m src.main
```

## API 端点

| 端点 | 方法 | 描述 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/api/v1/sources` | GET | 获取源列表 |
| `/api/v1/sources` | POST | 添加新源 |
| `/api/v1/sources/{id}/trigger` | POST | 触发源抓取 |
| `/api/v1/pipeline/process` | POST | 处理待处理文章 |
| `/api/v1/articles` | GET | 查询文章列表 |
| `/api/v1/articles/{id}` | GET | 获取文章详情 |
| `/api/v1/graph/entities` | GET | 查询实体 |
| `/api/v1/graph/relations` | GET | 查询关系 |
| `/api/v1/admin/sources/authority` | GET | 获取源权威度 |
| `/api/v1/metrics` | GET | Prometheus 指标 |

### 认证

所有 API 请求需要在 Header 中携带 API Key：

```
Authorization: Bearer your-api-key
```

## Pipeline 流程

### Phase 1: 单文章并发处理

```
Classifier → Cleaner → Categorizer → Vectorize
```

- **Classifier**: 判断是否为新闻，非新闻直接终止
- **Cleaner**: 清洗 HTML、提取正文
- **Categorizer**: 分类（政治/军事/经济/科技等）、语言、地区
- **Vectorize**: 生成内容向量 (1024维)

### Phase 2: 批量合并

```
BatchMerger (Union-Find 相似度聚类)
```

- 相似度阈值: 0.80
- 合并相似文章，保留最完整版本

### Phase 3: 单文章后处理

```
ReVectorize → Analyze → Credibility → EntityExtractor
```

- **ReVectorize**: 合并后重新生成向量
- **Analyze**: 摘要、情感分析、关键数据提取
- **Credibility**: 可信度评分 (来源权威性 + 交叉核实 + 内容核查 + 时效性)
- **EntityExtractor**: spaCy + LLM 实体提取

## 可信度评分

| 信号 | 权重 | 说明 |
|------|------|------|
| 来源权威性 | 0.30 | 基于历史准确率、域名信任度 |
| 交叉核实 | 0.25 | 多源报道数量 |
| 内容核查 | 0.30 | LLM 事实一致性检查 |
| 时效性 | 0.15 | 发布时间新鲜度 |

时效性评分规则：
- ≤6小时: 1.00
- ≤24小时: 0.85
- ≤72小时: 0.65
- ≤168小时: 0.45
- >168小时: 0.30

## LLM 调用点

| 调用点 | 类型 | 说明 |
|--------|------|------|
| classifier | CHAT | 新闻分类 |
| cleaner | CHAT | 内容清洗 |
| categorizer | CHAT | 分类识别 |
| merger | CHAT | 文章合并 |
| analyze | CHAT | 摘要分析 |
| credibility_checker | CHAT | 可信度检查 |
| entity_extractor | CHAT | 实体提取 |
| entity_resolver | CHAT | 实体消歧 |
| embedding | EMBEDDING | 向量生成 |
| rerank | RERANK | 重排序 |

## 定时任务

| 任务 | 间隔 | 说明 |
|------|------|------|
| retry_neo4j_writes | 10分钟 | 重试失败的 Neo4j 写入 |
| flush_retry_queue | 30秒 | 刷新爬虫重试队列 |
| update_source_auto_scores | 每天3点 | 更新源权威度 |
| archive_old_neo4j_nodes | 每周六2点 | 归档旧文章 |
| cleanup_orphan_entity_vectors | 每周六3点 | 清理孤立向量 |
| retry_pipeline_processing | 15分钟 | 重试失败的 Pipeline 处理 |

## 开发指南

### 运行测试

```bash
# 运行所有测试
uv run pytest

# 运行单元测试
uv run pytest tests/unit/

# 运行集成测试
uv run pytest tests/integration/

# 运行 E2E 测试
uv run pytest tests/e2e/

# 带覆盖率
uv run pytest --cov=src tests/
```

### 数据库迁移

```bash
# 创建新迁移
uv run alembic revision --autogenerate -m "description"

# 应用迁移
uv run alembic upgrade head

# 回滚
uv run alembic downgrade -1
```

### 代码风格

- 使用 `ruff` 进行代码格式化和 lint
- 类型注解必须完整
- 文档字符串使用 Google 风格

## License

MIT
