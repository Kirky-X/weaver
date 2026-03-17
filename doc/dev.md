# 资讯发掘后端 — 综合开发文档 

---

## 目录

1. [技术栈](#一技术栈)
2. [项目目录结构](#二项目目录结构)
3. [依赖管理（uv）](#三依赖管理uv)
4. [数据库 Schema](#四数据库-schema)
5. [核心模块设计](#五核心模块设计)
   - 5.1 依赖注入容器
   - 5.2 LLM 模块（队列 + Fallback + 限速）
   - 5.3 Prompt 管理
   - 5.4 可观测性基础设施
   - 5.5 Playwright 浏览器池
   - 5.6 采集模块
   - 5.7 NLP 模块（spaCy）
6. [Pipeline 流程](#六pipeline-流程)
   - 6.1 总体流程图
   - 6.2 各节点详细说明
   - 6.3 批量 Merger 算法（Union-Find）
   - 6.4 可信度检测算法
   - 6.5 实体解析算法
7. [数据流总览](#七数据流总览)
8. [HTTP API](#八http-api)
9. [Redis Key 设计](#九redis-key-设计)
10. [Neo4j 图模型](#十neo4j-图模型)
11. [运维](#十一运维)

---

## 一、技术栈

| 层次 | 技术 | 版本 |
|------|------|------|
| Web 框架 | FastAPI | ^0.115 |
| ASGI 服务器 | Uvicorn | ^0.32 |
| LLM 框架 | LangChain + LangGraph | ^0.3 / ^0.2 |
| 请求模块 | httpx | ^0.28 |
| 反爬模块 | Playwright + playwright-stealth | ^1.49 |
| 内容解析 | trafilatura | ^2.0 |
| 关系数据库 | PostgreSQL 17 + pgvector | — |
| ORM / 迁移 | SQLAlchemy 2.0 (async) + Alembic | ^2.0 / ^1.14 |
| 图数据库 | Neo4j 5 (官方 async driver) | ^5.27 |
| 缓存 | Redis 7 (redis-py) | ^5.2 |
| 依赖注入 | python-dependency-injector | ^4.43 |
| 任务调度 | APScheduler | ^4.0 |
| 配置管理 | pydantic-settings + tomllib(内置) | ^2.7 |
| NLP | spaCy | ^3.8 |
| 结构化日志 | structlog | ^24.4 |
| Metrics | prometheus-client | ^0.21 |
| 分布式追踪 | opentelemetry-sdk | ^1.29 |
| 限流 | slowapi | ^0.1 |
| 数据校验 | pydantic | ^2.10 |
| 异步运行时 | asyncio + anyio | — |
| 包管理器 | uv | latest |

---

## 二、项目目录结构

```
weaver/
├── pyproject.toml                   # uv 项目配置
├── uv.lock
├── .python-version                  # 固定 Python 版本，如 3.12
├── main.py                          # 应用入口
├── container.py                     # DI 容器
│
├── config/
│   ├── settings.py                  # pydantic-settings 全局配置
│   ├── settings.toml                # 默认配置（不含密钥）
│   ├── settings.example.toml        # 模板（提交到 Git）
│   └── prompts/                     # Prompt TOML（含版本号）
│       ├── classifier.toml
│       ├── cleaner.toml
│       ├── categorizer.toml
│       ├── analyze.toml             # summarizer + scorer + sentiment 合并
│       ├── credibility_checker.toml
│       ├── entity_extractor.toml
│       ├── entity_resolver.toml
│       ├── merger.toml
│       └── quality_scorer.toml      # 文章质量评分
│
├── core/
│   ├── llm/
│   │   ├── types.py                 # LLMTask, CallPoint, LLMType
│   │   ├── config_manager.py        # 多厂商配置解析
│   │   ├── queue_manager.py         # 队列 + Fallback Chain
│   │   ├── rate_limiter.py          # Redis 令牌桶（多进程安全）
│   │   ├── token_budget.py          # Token 截断管理
│   │   ├── output_validator.py      # Pydantic 输出校验 + 自重试
│   │   ├── providers/
│   │   │   ├── base.py
│   │   │   ├── chat.py
│   │   │   ├── embedding.py
│   │   │   └── rerank.py
│   │   └── client.py                # 对外统一入口 LLMClient
│   │
│   ├── db/
│   │   ├── postgres.py              # asyncpg 连接池 + Session 工厂
│   │   ├── neo4j.py                 # Neo4j AsyncDriver 封装
│   │   └── models.py                # SQLAlchemy ORM 模型
│   │
│   ├── cache/
│   │   └── redis.py                 # redis-py async 封装
│   │
│   ├── prompt/
│   │   └── loader.py                # TOML Prompt 加载（含版本）
│   │
│   ├── resilience/
│   │   └── circuit_breaker.py       # 通用断路器
│   │
│   ├── event/
│   │   └── bus.py                   # 内部事件总线
│   │
│   └── observability/
│       ├── logging.py               # structlog 配置
│       ├── metrics.py               # Prometheus 指标定义
│       └── tracing.py               # OpenTelemetry 追踪
│
├── modules/
│   ├── fetcher/
│   │   ├── base.py
│   │   ├── httpx_fetcher.py
│   │   ├── playwright_fetcher.py
│   │   ├── playwright_pool.py        # 浏览器上下文池
│   │   ├── rate_limiter.py           # HTTP请求限流
│   │   └── smart_fetcher.py
│   │
│   ├── source/
│   │   ├── models.py                # NewsItem
│   │   ├── base.py
│   │   ├── rss_parser.py
│   │   ├── registry.py
│   │   └── scheduler.py
│   │
│   ├── collector/
│   │   ├── models.py                # ArticleRaw
│   │   ├── deduplicator.py          # Redis + DB 两级去重
│   │   ├── interleaver.py
│   │   ├── crawler.py               # per-host 限速 + 全局上限
│   │   └── retry.py                 # Dead-Letter 重试
│   │
│   ├── pipeline/
│   │   ├── graph.py                 # LangGraph 主流程
│   │   ├── state.py                 # PipelineState TypedDict
│   │   └── nodes/
│   │       ├── classifier.py
│   │       ├── cleaner.py
│   │       ├── categorizer.py
│   │       ├── vectorize.py
│   │       ├── batch_merger.py      # 批次级 Union-Find + Merger
│   │       ├── re_vectorize.py
│   │       ├── analyze.py           # summarizer + scorer + sentiment
│   │       ├── credibility_checker.py
│   │       ├── entity_extractor.py  # spaCy + LLM
│   │       └── quality_scorer.py    # 文章质量评分
│   │
│   ├── nlp/
│   │   └── spacy_extractor.py       # 多语言 spaCy 封装
│   │
│   ├── graph_store/
│   │   ├── entity_resolver.py
│   │   └── neo4j_writer.py
│   │
│   └── storage/
│       ├── base.py
│       ├── article_repo.py
│       ├── vector_repo.py
│       ├── source_authority_repo.py
│       └── neo4j/
│           ├── entity_repo.py
│           └── article_repo.py
│
├── api/
│   ├── router.py
│   ├── middleware/
│   │   ├── auth.py                  # API Key 认证
│   │   └── rate_limit.py            # slowapi 限流
│   └── endpoints/
│       ├── sources.py
│       ├── articles.py
│       ├── pipeline.py              # 异步触发 + 状态查询
│       ├── graph.py
│       └── admin.py                 # source_authority 管理
│
├── alembic/
│   ├── env.py
│   └── versions/
│       ├── 001_initial_schema.py
│       ├── 002_add_merge_fields.py
│       ├── 003_add_persist_status.py
│       ├── 004_add_credibility_fields.py
│       └── 005_add_emotion_fields.py
│
├── tests/
│   ├── unit/
│   │   ├── test_deduplicator.py
│   │   ├── test_union_find.py
│   │   ├── test_token_budget.py
│   │   ├── test_circuit_breaker.py
│   │   ├── test_rate_limiter.py
│   │   └── test_credibility_calc.py
│   ├── integration/
│   │   ├── test_pipeline_nodes.py
│   │   ├── test_article_repo.py
│   │   └── test_neo4j_repo.py
│   └── e2e/
│       └── test_full_pipeline.py
│
└── plugins/                         # 自定义 Source 插件目录
```

---

## 三、依赖管理（uv）

```bash
# 初始化项目
uv init weaver
cd weaver
uv python pin 3.12

# 核心框架
uv add fastapi uvicorn[standard]
uv add langchain langchain-openai langgraph
uv add "langgraph[checkpoint-redis]"

# 数据库
uv add sqlalchemy[asyncio] asyncpg alembic
uv add pgvector
uv add neo4j

# 缓存 & 调度
uv add "redis[hiredis]"
uv add apscheduler

# 配置 & 注入
uv add pydantic-settings python-dependency-injector

# 采集 & 解析
uv add httpx playwright trafilatura feedparser

# NLP
uv add "spacy>=3.8"
# 安装模型（在 Dockerfile 或脚本中执行）
# uv run python -m spacy download zh_core_web_trf
# uv run python -m spacy download en_core_web_trf
# uv run python -m spacy download xx_ent_wiki_sm

# 可观测性
uv add structlog prometheus-client
uv add opentelemetry-sdk opentelemetry-instrumentation-fastapi

# 限流 & 安全
uv add slowapi

# 开发依赖
uv add --dev pytest pytest-asyncio pytest-mock anyio
uv add --dev testcontainers
```

**`pyproject.toml` 关键配置：**

```toml
[project]
name = "weaver"
version = "0.1.0"
requires-python = ">=3.12"

[tool.uv]
dev-dependencies = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "pytest-mock>=3.14",
    "testcontainers>=4.8",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

---

## 四、数据库 Schema

### 4.1 PostgreSQL

```sql
-- ============================================================
-- 枚举类型
-- ============================================================
CREATE TYPE category_type AS ENUM (
    '政治', '军事', '经济', '科技', '社会', '文化', '体育', '国际'
);

CREATE TYPE persist_status AS ENUM (
    'pending', 'processing', 'pg_done', 'neo4j_done', 'failed'
);

CREATE TYPE emotion_type AS ENUM (
    '乐观', '振奋', '期待',
    '平静', '客观',
    '担忧', '悲观', '愤怒', '恐慌'
);

CREATE TYPE vector_type AS ENUM ('title', 'content');

-- ============================================================
-- 主表：articles
-- ============================================================
CREATE TABLE articles (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_url          TEXT UNIQUE NOT NULL,
    source_host         VARCHAR(200),
    is_news             BOOLEAN NOT NULL DEFAULT FALSE,
    title               TEXT NOT NULL,
    body                TEXT NOT NULL,
    category            category_type,
    language            VARCHAR(10),
    region              VARCHAR(50),

    -- 合并相关
    merged_into         UUID REFERENCES articles(id),
    is_merged           BOOLEAN NOT NULL DEFAULT FALSE,
    merged_source_ids   UUID[],

    -- 摘要 & 分析
    summary             TEXT,
    event_time          TIMESTAMPTZ,
    subjects            TEXT[],
    key_data            TEXT[],
    impact              TEXT,
    has_data            BOOLEAN,

    -- 评分（0.00~1.00）
    score               NUMERIC(3,2) CHECK (score >= 0 AND score <= 1),

    -- 情绪
    sentiment           VARCHAR(10),
    sentiment_score     NUMERIC(3,2) CHECK (sentiment_score >= 0 AND sentiment_score <= 1),
    primary_emotion     emotion_type,
    emotion_targets     TEXT[],

    -- 可信度
    credibility_score   NUMERIC(3,2) CHECK (credibility_score >= 0 AND credibility_score <= 1),
    source_credibility  NUMERIC(3,2),
    cross_verification  NUMERIC(3,2),
    content_check_score NUMERIC(3,2),
    credibility_flags   TEXT[],
    verified_by_sources INT NOT NULL DEFAULT 0,

    -- 持久化状态
    persist_status      persist_status NOT NULL DEFAULT 'pending',
    
    -- 质量评分
    quality_score       NUMERIC(3,2) CHECK (quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 1)),
    
    -- 处理追踪
    processing_stage    VARCHAR(50),
    processing_error    TEXT,
    retry_count         INT NOT NULL DEFAULT 0,

    -- Prompt 版本溯源
    prompt_versions     JSONB,

    -- 约束
    CONSTRAINT chk_no_self_merge CHECK (merged_into IS DISTINCT FROM id),

    publish_time        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- 索引
CREATE INDEX idx_articles_category       ON articles (category);
CREATE INDEX idx_articles_publish_time   ON articles (publish_time DESC);
CREATE INDEX idx_articles_score          ON articles (score DESC);
CREATE INDEX idx_articles_credibility    ON articles (credibility_score DESC);
CREATE INDEX idx_articles_sentiment_score ON articles (sentiment_score DESC);
CREATE INDEX idx_articles_primary_emotion ON articles (primary_emotion);
CREATE INDEX idx_articles_merged_into    ON articles (merged_into);
CREATE INDEX idx_articles_persist_status ON articles (persist_status)
    WHERE persist_status IN ('pending', 'pg_done');

-- ============================================================
-- 向量表：article_vectors
-- ============================================================
CREATE TABLE article_vectors (
    id           BIGSERIAL PRIMARY KEY,
    article_id   UUID NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    vector_type  vector_type NOT NULL,
    embedding    VECTOR(1024) NOT NULL,
    model_id     VARCHAR(64) NOT NULL DEFAULT 'text-embedding-3-large',
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (article_id, vector_type)
);

-- HNSW 索引（m=32, ef_construction=256，高召回率）
CREATE INDEX idx_av_hnsw ON article_vectors
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 32, ef_construction = 256);

-- Merger 查询复合索引（加速标量过滤）
CREATE INDEX idx_av_merger ON articles (category, is_merged, publish_time DESC)
    WHERE is_merged = FALSE;

-- ============================================================
-- 实体向量表：entity_vectors
-- ============================================================
CREATE TABLE entity_vectors (
    id          BIGSERIAL PRIMARY KEY,
    neo4j_id    VARCHAR(100) NOT NULL UNIQUE,
    embedding   VECTOR(1024) NOT NULL,
    model_id    VARCHAR(64) NOT NULL DEFAULT 'text-embedding-3-large',
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_ev_hnsw ON entity_vectors
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 32, ef_construction = 256);

-- ============================================================
-- 资讯源权威性表：source_authorities
-- ============================================================
CREATE TABLE source_authorities (
    id           BIGSERIAL PRIMARY KEY,
    host         VARCHAR(200) UNIQUE NOT NULL,
    authority    NUMERIC(3,2) NOT NULL DEFAULT 0.50,
    tier         SMALLINT NOT NULL DEFAULT 3,  -- 1=官方 2=主流 3=自媒体
    description  TEXT,
    needs_review BOOLEAN NOT NULL DEFAULT TRUE,
    auto_score   NUMERIC(3,2),  -- 基于历史文章自动推算的参考值
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO source_authorities (host, authority, tier, needs_review) VALUES
    ('xinhuanet.com',  0.95, 1, FALSE),
    ('people.com.cn',  0.95, 1, FALSE),
    ('cctv.com',       0.93, 1, FALSE),
    ('reuters.com',    0.90, 2, FALSE),
    ('bloomberg.com',  0.88, 2, FALSE),
    ('36kr.com',       0.65, 2, FALSE),
    ('weibo.com',      0.35, 3, FALSE);

-- ============================================================
-- 文章实体关联表：article_entities
-- ============================================================
CREATE TABLE article_entities (
    id          BIGSERIAL PRIMARY KEY,
    article_id  UUID NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    neo4j_id    VARCHAR(100) NOT NULL,
    entity_name VARCHAR(500) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    role        VARCHAR(100)
);

CREATE INDEX idx_ae_article ON article_entities (article_id);
CREATE INDEX idx_ae_neo4j   ON article_entities (neo4j_id);
```

### 4.2 Alembic 迁移注意事项

```python
# alembic/versions/001_initial_schema.py
# pgvector 相关操作需手写 op.execute()，不能依赖 autogenerate

def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # ... 建表 DDL
    # HNSW 索引必须在事务外，使用 CONCURRENTLY
    op.execute("""
        CREATE INDEX CONCURRENTLY idx_av_hnsw ON article_vectors
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 32, ef_construction = 256)
    """)
```

---

## 五、核心模块设计

### 5.1 依赖注入容器

```python
# container.py
"""依赖注入容器 - 手动管理的轻量级实现。

设计决策：
- 使用自定义Container类而非dependency_injector库，更轻量且无第三方依赖
- 采用懒加载模式，按需初始化各组件
- 支持优雅停机，确保资源正确释放
"""
from __future__ import annotations
from typing import Any

from config.settings import Settings
from core.db import PostgresPool, Neo4jPool
from core.cache import RedisClient
from core.observability import get_logger
from core.llm.client import LLMClient
from core.llm.config_manager import LLMConfigManager
from core.llm.token_budget import TokenBudgetManager
from core.llm.rate_limiter import RedisTokenBucket
from core.llm.queue_manager import LLMQueueManager
from core.event import EventBus
from core.prompt import PromptLoader
from modules.source import SourceRegistry, SourceScheduler
from modules.storage import ArticleRepo, VectorRepo, SourceAuthorityRepo
from modules.storage.neo4j import Neo4jEntityRepo, Neo4jArticleRepo
from modules.graph_store import Neo4jWriter, EntityResolver
from modules.fetcher import SmartFetcher, PlaywrightContextPool
from modules.collector import Deduplicator
from modules.collector.crawler import Crawler
from modules.pipeline.graph import Pipeline

log = get_logger("container")


class Container:
    """依赖注入容器，管理所有核心服务的生命周期。"""

    def __init__(self) -> None:
        self._settings: Settings | None = None
        self._postgres_pool: PostgresPool | None = None
        self._neo4j_pool: Neo4jPool | None = None
        self._redis_client: RedisClient | None = None
        self._llm_client: LLMClient | None = None
        self._prompt_loader: PromptLoader | None = None
        # ... 其他组件

    def configure(self, settings: Settings) -> "Container":
        """配置容器。"""
        self._settings = settings
        return self

    # ── 数据库连接池 ──────────────────────────────────────────

    async def init_postgres(self) -> PostgresPool:
        """初始化 PostgreSQL 连接池。"""
        if self._postgres_pool is None:
            self._postgres_pool = PostgresPool(self._settings.postgres.dsn)
            await self._postgres_pool.startup()
        return self._postgres_pool

    async def init_neo4j(self) -> Neo4jPool:
        """初始化 Neo4j 连接池。"""
        if self._neo4j_pool is None:
            self._neo4j_pool = Neo4jPool(
                self._settings.neo4j.uri,
                ("neo4j", self._settings.neo4j.password),
            )
            await self._neo4j_pool.startup()
        return self._neo4j_pool

    # ── LLM & Prompt ─────────────────────────────────────────────

    async def init_llm(self) -> LLMClient:
        """初始化 LLM 客户端。"""
        if self._llm_client is None:
            config_manager = LLMConfigManager(self._settings.llm)
            rate_limiter = RedisTokenBucket(self._redis_client.client)
            event_bus = EventBus()
            queue_manager = LLMQueueManager(
                config_manager=config_manager,
                rate_limiter=rate_limiter,
                event_bus=event_bus,
            )
            await queue_manager.startup()
            prompt_loader = self.prompt_loader()
            token_budget = TokenBudgetManager()
            self._llm_client = LLMClient(
                queue_manager=queue_manager,
                prompt_loader=prompt_loader,
                token_budget=token_budget,
            )
        return self._llm_client

    # ── Fetcher & Crawler ────────────────────────────────────────

    async def init_playwright_pool(self) -> PlaywrightContextPool:
        """初始化 Playwright 浏览器池。"""
        if self._playwright_pool is None:
            settings = self._settings.fetcher
            self._playwright_pool = PlaywrightContextPool(
                pool_size=settings.playwright_pool_size,
                stealth_enabled=settings.stealth_enabled,
                user_agent=settings.stealth_user_agent,
            )
            await self._playwright_pool.startup()
        return self._playwright_pool

    # ── 生命周期 ─────────────────────────────────────────────────

    async def startup(self) -> None:
        """初始化所有服务。"""
        await self.init_postgres()
        await self.init_redis()
        await self.init_neo4j()
        await self.init_llm()
        await self.init_playwright_pool()
        await self.init_smart_fetcher()
        await self.init_pipeline()

    async def shutdown(self) -> None:
        """关闭所有服务（逆序）。"""
        if self._playwright_pool:
            await self._playwright_pool.shutdown()
        if self._redis_client:
            await self._redis_client.shutdown()
        if self._postgres_pool:
            await self._postgres_pool.shutdown()
        if self._neo4j_pool:
            await self._neo4j_pool.shutdown()
```

---

### 5.2 LLM 模块

#### 5.2.1 CallPoint & LLMTask

```python
# core/llm/types.py
from enum import Enum
from dataclasses import dataclass, field
from typing import Any
import asyncio

class LLMType(str, Enum):
    CHAT      = "chat"
    EMBEDDING = "embedding"
    RERANK    = "rerank"

class CallPoint(str, Enum):
    CLASSIFIER          = "classifier"
    CLEANER             = "cleaner"
    CATEGORIZER         = "categorizer"
    MERGER              = "merger"
    ANALYZE             = "analyze"            # summarizer + scorer + sentiment 合并
    CREDIBILITY_CHECKER = "credibility_checker"
    ENTITY_EXTRACTOR    = "entity_extractor"
    ENTITY_RESOLVER     = "entity_resolver"
    EMBEDDING           = "embedding"
    RERANK              = "rerank"

@dataclass
class LLMTask:
    call_point:   CallPoint
    llm_type:     LLMType
    payload:      Any
    priority:     int = 5
    attempt:      int = 0             # 当前重试次数（自重试计数）
    future:       asyncio.Future | None = field(default=None, init=False)
```

#### 5.2.2 Redis 令牌桶（多进程安全）

```python
# core/llm/rate_limiter.py
import time
from redis.asyncio import Redis

# Lua 脚本：原子性令牌扣减
_LUA_CONSUME = """
local key      = KEYS[1]
local capacity = tonumber(ARGV[1])
local rate     = tonumber(ARGV[2])   -- 每秒补充令牌数
local now      = tonumber(ARGV[3])   -- 当前时间戳（秒，浮点）
local cost     = tonumber(ARGV[4])   -- 本次消耗令牌数，通常为 1

local info     = redis.call('HMGET', key, 'tokens', 'last_time')
local tokens   = tonumber(info[1]) or capacity
local last     = tonumber(info[2]) or now

-- 按时间差补充令牌
tokens = math.min(capacity, tokens + (now - last) * rate)

if tokens < cost then
    -- 令牌不足，返回需等待的秒数
    local wait = (cost - tokens) / rate
    return {0, wait}
end

tokens = tokens - cost
redis.call('HMSET', key, 'tokens', tokens, 'last_time', now)
redis.call('EXPIRE', key, 3600)
return {1, 0}
"""

class RedisTokenBucket:
    def __init__(self, redis: Redis):
        self._redis  = redis
        self._script = redis.register_script(_LUA_CONSUME)

    async def consume(self, provider: str, rpm_limit: int) -> float:
        """
        尝试消耗一个令牌。
        返回 0.0 表示立即可用；返回 >0 表示需等待的秒数。
        """
        key      = f"llm:rpm:{provider}"
        capacity = rpm_limit
        rate     = rpm_limit / 60.0
        now      = time.time()

        result = await self._script(keys=[key], args=[capacity, rate, now, 1])
        allowed, wait = result
        return 0.0 if allowed else float(wait)
```

#### 5.2.3 断路器

```python
# core/resilience/circuit_breaker.py
import asyncio, time
from enum import Enum

class CBState(Enum):
    CLOSED   = "closed"
    OPEN     = "open"
    HALF_OPEN = "half_open"

class CircuitBreaker:
    """
    状态机：
      CLOSED  →（连续失败 >= threshold）→ OPEN
      OPEN    →（冷却期 timeout_secs 后）→ HALF_OPEN
      HALF_OPEN →（探测成功）→ CLOSED
      HALF_OPEN →（探测失败）→ OPEN
    """
    def __init__(self, threshold: int = 5, timeout_secs: float = 60.0):
        self._threshold    = threshold
        self._timeout      = timeout_secs
        self._state        = CBState.CLOSED
        self._fail_count   = 0
        self._opened_at    = 0.0

    def is_open(self) -> bool:
        if self._state == CBState.OPEN:
            if time.monotonic() - self._opened_at >= self._timeout:
                self._state = CBState.HALF_OPEN
                return False
            return True
        return False

    def record_success(self):
        self._fail_count = 0
        self._state      = CBState.CLOSED

    def record_failure(self):
        self._fail_count += 1
        if self._fail_count >= self._threshold:
            self._state     = CBState.OPEN
            self._opened_at = time.monotonic()
```

#### 5.2.4 Fallback Chain 队列管理器

```python
# core/llm/queue_manager.py
import asyncio
from typing import Any
from core.llm.types import LLMTask, CallPoint
from core.llm.circuit_breaker import CircuitBreaker
from core.llm.rate_limiter import RedisTokenBucket
from core.event.bus import EventBus, FallbackEvent

# 触发 Fallback 的异常类型
FALLBACK_ERRORS = (TimeoutError, ConnectionError)
# OutputParserException 先自重试，再 Fallback
SELF_RETRY_ERRORS = ("OutputParserException",)
# 不触发 Fallback 的客户端错误（4xx）
NON_RETRYABLE_STATUS = {400, 401, 403, 413}

class ProviderQueue:
    def __init__(self, provider_name: str, concurrency: int):
        self.name            = provider_name
        self._queue          = asyncio.PriorityQueue()
        self._semaphore      = asyncio.Semaphore(concurrency)
        self.circuit_breaker = CircuitBreaker()

    async def enqueue(self, task: LLMTask) -> asyncio.Future:
        task.future = asyncio.get_running_loop().create_future()
        await self._queue.put((task.priority, id(task), task))
        return task.future

    async def start_workers(self, n: int):
        for _ in range(n):
            asyncio.create_task(self._worker())

    async def _worker(self):
        while True:
            _, _, task = await self._queue.get()
            async with self._semaphore:
                try:
                    result = await self._dispatch(task)
                    self.circuit_breaker.record_success()
                    task.future.set_result(result)
                except Exception as exc:
                    self.circuit_breaker.record_failure()
                    task.future.set_exception(exc)
            self._queue.task_done()

    async def _dispatch(self, task: LLMTask):
        """实际调用 LLM Provider，子类或注入实现"""
        raise NotImplementedError


class LLMQueueManager:
    def __init__(self, config_manager, rate_limiter: RedisTokenBucket, event_bus: EventBus):
        self._config       = config_manager
        self._rate_limiter = rate_limiter
        self._event_bus    = event_bus
        self._queues: dict[str, ProviderQueue] = {}

    async def startup(self):
        for name, cfg in self._config.list_providers():
            q = ProviderQueue(name, cfg.concurrency)
            await q.start_workers(cfg.concurrency)
            self._queues[name] = q

    async def enqueue(self, task: LLMTask) -> Any:
        call_cfg       = self._config.get_call_point_config(task.call_point)
        provider_chain = [call_cfg.primary] + call_cfg.fallbacks
        last_exc       = None

        for idx, pcfg in enumerate(provider_chain):
            queue = self._queues[pcfg.provider]

            # 断路器检查
            if queue.circuit_breaker.is_open():
                await self._event_bus.publish(FallbackEvent(
                    call_point=task.call_point,
                    from_provider=pcfg.provider,
                    reason="circuit_open", attempt=idx,
                ))
                continue

            # 令牌桶限速（多进程安全）
            wait = await self._rate_limiter.consume(pcfg.provider, pcfg.rpm_limit)
            if wait > 0:
                await asyncio.sleep(wait)

            try:
                task.provider_cfg = pcfg
                future = await queue.enqueue(task)
                result = await future

                if idx > 0:
                    await self._event_bus.publish(FallbackEvent(
                        call_point=task.call_point,
                        from_provider=provider_chain[0].provider,
                        to_provider=pcfg.provider,
                        reason="fallback_success", attempt=idx,
                    ))
                return result

            except Exception as exc:
                exc_name = type(exc).__name__

                # OutputParserException 先自重试一次
                if exc_name in SELF_RETRY_ERRORS and task.attempt == 0:
                    task.attempt += 1
                    task.payload["_retry_hint"] = "请严格按 JSON 格式输出，不要有任何额外文字。"
                    future = await queue.enqueue(task)
                    try:
                        return await future
                    except Exception as retry_exc:
                        exc = retry_exc

                # 4xx 等不触发 Fallback
                if getattr(exc, "status_code", None) in NON_RETRYABLE_STATUS:
                    raise

                last_exc = exc
                await self._event_bus.publish(FallbackEvent(
                    call_point=task.call_point,
                    from_provider=pcfg.provider,
                    reason=exc_name, attempt=idx,
                ))
                continue

        raise AllProvidersFailedError(task.call_point, provider_chain) from last_exc
```

#### 5.2.5 Token 截断管理

```python
# core/llm/token_budget.py
import tiktoken
from core.llm.types import CallPoint

LIMITS: dict[CallPoint, int] = {
    CallPoint.CLEANER:          6000,
    CallPoint.ANALYZE:          4000,
    CallPoint.ENTITY_EXTRACTOR: 4000,
    CallPoint.CREDIBILITY_CHECKER: 3000,
    CallPoint.CLASSIFIER:       1000,
    CallPoint.MERGER:           8000,   # Merger 输入更多
}

class TokenBudgetManager:
    def __init__(self, model: str = "gpt-4o"):
        self._enc = tiktoken.encoding_for_model(model)

    def truncate(self, text: str, call_point: CallPoint) -> str:
        limit  = LIMITS.get(call_point, 4000)
        tokens = self._enc.encode(text)
        if len(tokens) <= limit:
            return text
        # 保留前 70% + 后 30%（新闻导语 + 结论）
        head_n = int(limit * 0.7)
        tail_n = limit - head_n
        head   = self._enc.decode(tokens[:head_n])
        tail   = self._enc.decode(tokens[-tail_n:])
        return head + "\n...[内容截断]...\n" + tail
```

#### 5.2.6 结构化输出校验

```python
# core/llm/output_validator.py
from pydantic import BaseModel, Field
from typing import TypeVar, Type
import json

T = TypeVar("T", bound=BaseModel)

def parse_llm_json(raw: str, model_cls: Type[T]) -> T:
    """
    去除 Markdown 代码块包装，解析 JSON，Pydantic 校验。
    失败时抛 OutputParserException。
    """
    clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = json.loads(clean)
        return model_cls.model_validate(data)
    except Exception as exc:
        raise OutputParserException(f"解析失败: {exc}\n原始内容: {raw[:200]}") from exc

# 各节点输出模型示例
class ClassifierOutput(BaseModel):
    is_news:    bool
    confidence: float = Field(ge=0, le=1)

class AnalyzeOutput(BaseModel):
    summary:         str
    event_time:      str | None
    subjects:        list[str]
    key_data:        list[str]
    impact:          str
    has_data:        bool
    sentiment:       str
    sentiment_score: float = Field(ge=0, le=1)
    primary_emotion: str
    emotion_targets: list[str]
    score:           float = Field(ge=0, le=1)

class CredibilityOutput(BaseModel):
    score: float = Field(ge=0, le=1)
    flags: list[str] = []

class EntityExtractorOutput(BaseModel):
    entities:  list[dict]
    relations: list[dict]
```

---

### 5.3 Prompt 管理

```python
# core/prompt/loader.py
import tomllib
from pathlib import Path

class PromptLoader:
    def __init__(self, path: str):
        self._path  = Path(path)
        self._cache: dict[str, dict] = {}

    def get(self, name: str, key: str = "system") -> str:
        if name not in self._cache:
            with open(self._path / f"{name}.toml", "rb") as f:
                self._cache[name] = tomllib.load(f)
        return self._cache[name][key]

    def get_version(self, name: str) -> str:
        if name not in self._cache:
            self.get(name)
        return self._cache[name].get("version", "unknown")
```

```toml
# config/prompts/analyze.toml
version = "2.1.0"

system = """
你是一个专业新闻分析师。对以下资讯进行全面分析，输出 JSON。
{
  "summary":         "150字以内的客观摘要",
  "event_time":      "事件发生时间 ISO8601 或 null",
  "subjects":        ["主体人物/组织"],
  "key_data":        ["关键数据，如有"],
  "impact":          "结果或影响描述",
  "has_data":        true/false,
  "sentiment":       "positive/neutral/negative",
  "sentiment_score": 0.00~1.00,
  "primary_emotion": "乐观|振奋|期待|平静|客观|担忧|悲观|愤怒|恐慌",
  "emotion_targets": ["情绪指向对象"],
  "score":           0.00~1.00
}
仅输出 JSON，不要有任何额外内容。
"""
```

---

### 5.4 可观测性

```python
# core/observability/logging.py
import structlog

def configure_logging():
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(20),
    )

# 使用示例：每条日志自动携带 trace_id, article_url, call_point
log = structlog.get_logger()
log.info("llm_call_success", call_point="analyze", latency_ms=320, provider="openai")
```

```python
# core/observability/metrics.py
from prometheus_client import Counter, Histogram, Gauge

class MetricsCollector:
    llm_call_total = Counter(
        "llm_call_total", "LLM 调用次数",
        ["call_point", "provider", "status"]
    )
    llm_call_latency = Histogram(
        "llm_call_latency_seconds", "LLM 调用延迟",
        ["call_point", "provider"],
        buckets=[0.1, 0.5, 1, 2, 5, 10, 30]
    )
    fallback_total = Counter(
        "llm_fallback_total", "Fallback 发生次数",
        ["call_point", "from_provider", "reason"]
    )
    pipeline_stage_latency = Histogram(
        "pipeline_stage_latency_seconds", "Pipeline 节点延迟",
        ["stage"]
    )
    credibility_score_dist = Histogram(
        "credibility_score_distribution", "可信度分布",
        buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    )
    pipeline_queue_depth = Gauge(
        "pipeline_queue_depth", "Pipeline 任务队列深度"
    )
```

---

### 5.5 Playwright 浏览器上下文池

```python
# core/fetcher/playwright_pool.py
import asyncio
from contextlib import asynccontextmanager
from playwright.async_api import async_playwright, Browser, BrowserContext

class PlaywrightContextPool:
    """
    单 Browser 实例 + N 个 BrowserContext 的池化方案。
    每个 Context 隔离 Cookie / Storage，使用后清理归还。
    """
    def __init__(self, pool_size: int = 5):
        self._pool_size = pool_size
        self._browser:  Browser | None = None
        self._pool:     asyncio.Queue[BrowserContext] = asyncio.Queue()

    async def startup(self):
        self._pw      = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=True)
        for _ in range(self._pool_size):
            ctx = await self._browser.new_context(
                user_agent="Mozilla/5.0 (compatible; NewsBot/1.0)",
            )
            await self._pool.put(ctx)

    async def shutdown(self):
        while not self._pool.empty():
            ctx = await self._pool.get()
            await ctx.close()
        if self._browser:
            await self._browser.close()
        await self._pw.stop()

    @asynccontextmanager
    async def acquire(self):
        ctx = await self._pool.get()
        try:
            yield ctx
        finally:
            # 清理 Cookie，防止 session 污染
            await ctx.clear_cookies()
            await self._pool.put(ctx)
```

---

### 5.6 采集模块

#### 两级去重

```python
# modules/collector/deduplicator.py
import hashlib, time
from core.cache.redis import RedisClient
from modules.storage.article_repo import ArticleRepo

class Deduplicator:
    DEDUP_KEY = "crawl:dedup"   # Hash，无 TTL，依赖 DB UNIQUE 兜底

    def __init__(self, redis: RedisClient, article_repo: ArticleRepo):
        self._redis = redis
        self._repo  = article_repo

    async def dedup(self, items: list) -> list:
        # 第一级：Redis Hash 快速过滤
        pipe      = self._redis.pipeline()
        url_hashes = [self._hash(i.url) for i in items]
        for h in url_hashes:
            pipe.hexists(self.DEDUP_KEY, h)
        exists = await pipe.execute()

        candidates = [item for item, ex in zip(items, exists) if not ex]

        # 第二级：DB 精确兜底（批量查询走 UNIQUE 索引）
        urls         = [i.url for i in candidates]
        db_existing  = await self._repo.get_existing_urls(urls)
        new_items    = [i for i in candidates if i.url not in db_existing]

        # 将新 URL 写入 Redis Hash
        if new_items:
            pipe = self._redis.pipeline()
            for i in new_items:
                pipe.hset(self.DEDUP_KEY, self._hash(i.url), int(time.time()))
            await pipe.execute()

        return new_items

    @staticmethod
    def _hash(url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()[:16]
```

#### Crawler per-host 限速

```python
# modules/collector/crawler.py
import asyncio, os
from modules.source.models import NewsItem
from modules.collector.models import ArticleRaw

GLOBAL_MAX_CONCURRENCY = 32   # 绝对上限

def get_host(url: str) -> str:
    from urllib.parse import urlparse
    return urlparse(url).netloc

class Crawler:
    def __init__(self, smart_fetcher, default_per_host: int = 2):
        self._fetcher         = smart_fetcher
        self._default_per_host = default_per_host

    async def crawl_batch(
        self,
        items: list[NewsItem],
        per_host_config: dict[str, int] | None = None,
    ) -> list[ArticleRaw | Exception]:
        per_host_config = per_host_config or {}

        # 全局并发 = min(cpu, host_count, GLOBAL_MAX)
        host_count   = len({get_host(i.url) for i in items})
        global_limit = min(os.cpu_count() or 1, host_count, GLOBAL_MAX_CONCURRENCY)
        global_sem   = asyncio.Semaphore(global_limit)

        # per-host Semaphore
        host_sems: dict[str, asyncio.Semaphore] = {}
        for item in items:
            host = get_host(item.url)
            if host not in host_sems:
                limit = per_host_config.get(host, self._default_per_host)
                host_sems[host] = asyncio.Semaphore(limit)

        async def crawl_one(item: NewsItem) -> ArticleRaw:
            host = get_host(item.url)
            async with global_sem, host_sems[host]:
                status, html = await self._fetcher.fetch(item.url)
                body = trafilatura.extract(html, include_comments=False) or ""
                return ArticleRaw(
                    url=item.url, title=item.title,
                    body=body, source=item.source,
                    publish_time=item.pubDate,
                )

        return await asyncio.gather(
            *[crawl_one(i) for i in items],
            return_exceptions=True,
        )
```

---

### 5.7 NLP 模块（多语言 spaCy）

```python
# modules/nlp/spacy_extractor.py
import spacy
from dataclasses import dataclass
from functools import lru_cache

MODEL_MAP = {
    "zh": "zh_core_web_trf",
    "en": "en_core_web_trf",
    "default": "xx_ent_wiki_sm",
}

SPACY_TO_ENTITY_TYPE = {
    "PER":      "人物", "PERSON":  "人物",
    "ORG":      "组织机构",
    "GPE":      "地点", "LOC":     "地点",
    "TIME":     "事件", "DATE":    "事件", "EVENT": "事件",
    "CARDINAL": "数据指标", "PERCENT": "数据指标",
    "MONEY":    "数据指标",
    "LAW":      "法规与政策",
}

@dataclass
class SpacyEntity:
    name:  str
    type:  str
    start: int
    end:   int
    label: str

class SpacyExtractor:
    def __init__(self):
        self._models: dict[str, spacy.Language] = {}

    @lru_cache(maxsize=3)
    def _load(self, model_name: str) -> spacy.Language:
        return spacy.load(model_name, exclude=["parser", "tagger", "lemmatizer"])

    def _get_nlp(self, language: str) -> spacy.Language:
        model = MODEL_MAP.get(language, MODEL_MAP["default"])
        return self._load(model)

    def extract(self, text: str, language: str = "zh") -> list[SpacyEntity]:
        nlp = self._get_nlp(language)
        doc = nlp(text)
        seen, results = set(), []
        for ent in doc.ents:
            if ent.text in seen:
                continue
            seen.add(ent.text)
            entity_type = SPACY_TO_ENTITY_TYPE.get(ent.label_)
            if not entity_type:
                continue
            results.append(SpacyEntity(
                name=ent.text, type=entity_type,
                start=ent.start_char, end=ent.end_char,
                label=ent.label_,
            ))
        return results
```

---

## 六、Pipeline 流程

### 6.1 总体流程图

```
[START]
   │
   ▼
[classifier]            is_news=False ──► [END（跳过）]
   │
   ▼
[cleaner]               LLM 清洗正文
   │
   ▼
[categorizer]           LLM：category / language / region
   │
   ▼                    ◄─── 批次内所有文章并发执行上面 3 个节点
[vectorize]             生成 content embedding，仅用于 Merger 查询，不落库
   │
   ▼
[batch_merger]          ★ 批次级串行节点（Union-Find + pgvector + LLM）
   │
   ▼
[re_vectorize]          对合并后正文重新生成向量，写入 article_vectors（含 model_id）
   │
   ▼
[analyze]               一次 LLM：summary + scorer + sentiment（节省调用次数）
   │
   ▼
[credibility_checker]   多信号聚合：来源权威 + 交叉核实 + LLM核查 + 时效
   │
   ▼
[entity_extractor]      spaCy（按 language 路由）→ batch embed → LLM 精化+消歧
   │
   ▼
[entity_resolver]       pgvector 向量召回 → LLM 去重合并 → Neo4j MERGE
   │
   ▼
[persist]               UoW 写 Postgres（pg_done）→ Neo4j MERGE（neo4j_done）
   │
   ▼
[checkpoint_cleanup]    删除 LangGraph Checkpoint，释放 Redis
   │
   ▼
[END]
```

### 6.2 各节点详细说明

#### classifier 节点

```python
# modules/pipeline/nodes/classifier.py
class ClassifierNode(BasePipelineNode):
    async def _execute(self, state: PipelineState) -> PipelineState:
        raw     = state["raw"]
        payload = {
            "title":        raw.title,
            "body_snippet": self._budget.truncate(raw.body, CallPoint.CLASSIFIER),
        }
        result: ClassifierOutput = await self._llm.call(
            CallPoint.CLASSIFIER, payload, output_model=ClassifierOutput
        )
        state["is_news"] = result.is_news
        # 记录 Prompt 版本
        state.setdefault("prompt_versions", {})["classifier"] = \
            self._prompt_loader.get_version("classifier")
        return state
```

#### analyze 节点（summarizer + scorer + sentiment 合并）

```python
class AnalyzeNode(BasePipelineNode):
    async def _execute(self, state: PipelineState) -> PipelineState:
        body    = self._budget.truncate(state["cleaned"]["body"], CallPoint.ANALYZE)
        result: AnalyzeOutput = await self._llm.call(
            CallPoint.ANALYZE,
            {"title": state["cleaned"]["title"], "body": body},
            output_model=AnalyzeOutput,
        )
        state["summary_info"] = {
            "summary":    result.summary,
            "event_time": result.event_time,
            "subjects":   result.subjects,
            "key_data":   result.key_data,
            "impact":     result.impact,
            "has_data":   result.has_data,
        }
        state["sentiment"] = {
            "sentiment":       result.sentiment,
            "sentiment_score": result.sentiment_score,
            "primary_emotion": result.primary_emotion,
            "emotion_targets": result.emotion_targets,
        }
        state["score"] = result.score
        state.setdefault("prompt_versions", {})["analyze"] = \
            self._prompt_loader.get_version("analyze")
        return state
```

#### entity_extractor 节点

```python
class EntityExtractorNode(BasePipelineNode):
    async def _execute(self, state: PipelineState) -> PipelineState:
        body     = state["cleaned"]["body"]
        language = state.get("language", "zh")

        # 阶段 1：spaCy（同步，run_in_executor 避免阻塞事件循环）
        loop          = asyncio.get_running_loop()
        spacy_entities = await loop.run_in_executor(
            None, self._spacy.extract, body, language
        )

        # 阶段 2：batch embed 实体，写入 entity_vectors
        entity_texts  = [f"{e.name}（{e.type}）" for e in spacy_entities]
        entity_embeds = await self._llm.batch_embed(entity_texts)
        await self._vector_repo.upsert_entity_vectors(
            list(zip([e.name for e in spacy_entities], entity_embeds))
        )

        # 阶段 3：LLM 精化
        body_trunc = self._budget.truncate(body, CallPoint.ENTITY_EXTRACTOR)
        result: EntityExtractorOutput = await self._llm.call(
            CallPoint.ENTITY_EXTRACTOR,
            {
                "body":           body_trunc,
                "spacy_entities": [vars(e) for e in spacy_entities],
            },
            output_model=EntityExtractorOutput,
        )
        state["entities"]  = result.entities
        state["relations"] = result.relations
        state.setdefault("prompt_versions", {})["entity_extractor"] = \
            self._prompt_loader.get_version("entity_extractor")
        return state
```

#### persist 节点（含优雅停机支持）

```python
class PersistNode(BasePipelineNode):
    async def _execute(self, state: PipelineState) -> PipelineState:
        if state.get("terminal"):
            return state   # classifier 短路，跳过

        # 步骤 1：写 Postgres
        async with self._uow as uow:
            article_id = await uow.articles.upsert(state)
            await uow.commit()
        await self._article_repo.update_persist_status(article_id, "pg_done")
        state["article_id"] = str(article_id)

        # 步骤 2：写 Neo4j
        try:
            neo4j_ids = await self._neo4j_writer.write(state)
            state["neo4j_ids"] = neo4j_ids
            await self._article_repo.update_persist_status(article_id, "neo4j_done")
        except Exception as exc:
            # pg_done 状态留存，补偿任务定期扫描重试
            log.error("neo4j_write_failed", article_id=str(article_id), error=str(exc))

        return state
```

---

### 6.3 批量 Merger 算法（Union-Find）

```python
# modules/pipeline/nodes/batch_merger.py
import asyncio
from dataclasses import dataclass

class UnionFind:
    """路径压缩 + 按秩合并，O(α(n)) 均摊复杂度"""
    def __init__(self, elements: list[str]):
        self._parent = {e: e for e in elements}
        self._rank   = {e: 0 for e in elements}

    def find(self, x: str) -> str:
        if self._parent[x] != x:
            self._parent[x] = self.find(self._parent[x])   # 路径压缩
        return self._parent[x]

    def union(self, x: str, y: str):
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        # 按秩合并
        if self._rank[rx] < self._rank[ry]:
            rx, ry = ry, rx
        self._parent[ry] = rx
        if self._rank[rx] == self._rank[ry]:
            self._rank[rx] += 1

    def get_groups(self) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {}
        for e in self._parent:
            root = self.find(e)
            groups.setdefault(root, []).append(e)
        return groups


class BatchMergerNode(BasePipelineNode):
    """
    批次级 Merger：
    1. 批次内两两 cosine > 0.80 → Union-Find 归组
    2. 跨库 pgvector 查询历史相似文章 → 扩展 Union-Find
    3. 二次合并确保每篇 article 只属于一个最终组
    4. 每组 → 一次 LLM Merger 调用
    """
    SIMILARITY_THRESHOLD = 0.80

    async def execute_batch(self, states: list[PipelineState]) -> list[PipelineState]:
        # 提取所有向量
        ids      = [s["raw"].url for s in states]
        vectors  = [s["vectors"]["content"] for s in states]
        uf       = UnionFind(ids)

        # ① 批次内相似度矩阵（numpy 矩阵运算）
        import numpy as np
        mat = np.array(vectors, dtype=np.float32)
        # 归一化（cosine = dot product after L2 norm）
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        normed = mat / (norms + 1e-8)
        sim_matrix = normed @ normed.T

        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                if sim_matrix[i, j] > self.SIMILARITY_THRESHOLD:
                    # 同 category 才合并
                    if states[i].get("category") == states[j].get("category"):
                        uf.union(ids[i], ids[j])

        # ② 跨库查询（每篇查一次，然后二次合并到同一 UF）
        cross_tasks = [
            self._cross_query(s, uf, ids)
            for s in states
        ]
        await asyncio.gather(*cross_tasks)

        # ③ 按组并发 LLM Merger
        groups = uf.get_groups()
        merge_tasks = []
        for root, members in groups.items():
            if len(members) == 1:
                continue   # 无需合并
            group_states = [s for s in states if s["raw"].url in members]
            merge_tasks.append(self._llm_merge(group_states))

        await asyncio.gather(*merge_tasks)
        return states

    async def _cross_query(self, state: PipelineState, uf: UnionFind, ids: list[str]):
        """向库中查历史相似文章，扩展 UF"""
        hits = await self._vector_repo.find_similar(
            embedding  = state["vectors"]["content"],
            category   = state.get("category"),
            threshold  = self.SIMILARITY_THRESHOLD,
            limit      = 20,
        )
        for hit in hits:
            # 将历史 article_id 也加入 UF（动态扩充）
            if hit.article_id not in uf._parent:
                uf._parent[hit.article_id] = hit.article_id
                uf._rank[hit.article_id]   = 0
            if state.get("category") == hit.category:
                uf.union(state["raw"].url, hit.article_id)

    async def _llm_merge(self, group_states: list[PipelineState]):
        """将一组相似文章 LLM 合并为单篇"""
        articles_payload = [
            {
                "title":        s["cleaned"]["title"],
                "body":         s["cleaned"]["body"][:1000],  # 截取摘要
                "publish_time": s["raw"].publish_time,
                "source":       s["raw"].source,
            }
            for s in group_states
        ]
        result = await self._llm.call(
            CallPoint.MERGER,
            {"articles": articles_payload},
        )
        # 将合并结果写回"主"文章（最新发布的那篇），其余标记 is_merged
        primary = max(group_states, key=lambda s: s["raw"].publish_time or 0)
        primary["cleaned"]["body"]    = result["merged_body"]
        primary["cleaned"]["title"]   = result["merged_title"]
        primary["merged_source_ids"]  = [
            s["raw"].url for s in group_states if s is not primary
        ]
        for s in group_states:
            if s is not primary:
                s["is_merged"] = True
```

---

### 6.4 可信度检测算法

```python
# modules/pipeline/nodes/credibility_checker.py
from datetime import datetime, timezone

class CredibilityCheckerNode(BasePipelineNode):

    WEIGHTS = {
        "source":      0.30,
        "cross":       0.25,
        "content":     0.30,
        "timeliness":  0.15,
    }

    async def _execute(self, state: PipelineState) -> PipelineState:
        # 信号 1：来源权威性
        source_auth  = await self._source_auth_repo.get_or_create(
            host=state["raw"].source_host,
            auto_score=None,   # 首次入库用默认 0.5
        )
        s1 = source_auth.authority

        # 信号 2：交叉核实（merged_source_ids 已由 Merger 写入）
        cross_count = len(state.get("merged_source_ids", []))
        s2 = min(1.0, 0.4 + cross_count * 0.15)
        # 1 源=0.40, 2 源=0.55, 3 源=0.70, 4 源=0.85, 5+ 源=1.00

        # 信号 3：LLM 内容核查
        body_trunc   = self._budget.truncate(
            state["cleaned"]["body"], CallPoint.CREDIBILITY_CHECKER
        )
        llm_result: CredibilityOutput = await self._llm.call(
            CallPoint.CREDIBILITY_CHECKER,
            {
                "title":   state["cleaned"]["title"],
                "body":    body_trunc,
                "summary": state["summary_info"]["summary"],
            },
            output_model=CredibilityOutput,
        )
        s3 = llm_result.score

        # 信号 4：发布时效性
        s4 = self._calc_timeliness(
            state["cleaned"].get("publish_time"),
            state["summary_info"].get("event_time"),
        )

        # 加权聚合
        score = (
            s1 * self.WEIGHTS["source"]     +
            s2 * self.WEIGHTS["cross"]      +
            s3 * self.WEIGHTS["content"]    +
            s4 * self.WEIGHTS["timeliness"]
        )

        state["credibility"] = {
            "score":              round(score, 2),
            "source_credibility": s1,
            "cross_verification": s2,
            "content_check":      s3,
            "timeliness":         s4,
            "flags":              llm_result.flags,
            "verified_by_sources": cross_count,
        }

        # 触发可信度更新事件（供后续 cross_count 增加时重算）
        await self._event_bus.publish(CredibilityComputedEvent(
            url=state["raw"].url,
            score=score,
            cross_count=cross_count,
        ))
        return state

    @staticmethod
    def _calc_timeliness(
        publish_time: datetime | None,
        event_time_str: str | None,
    ) -> float:
        """时效性评分：发布时间与事件时间差越小越可信"""
        if not publish_time or not event_time_str:
            return 0.7   # 无法判断，中性
        try:
            event_time = datetime.fromisoformat(event_time_str)
            if event_time.tzinfo is None:
                event_time = event_time.replace(tzinfo=timezone.utc)
        except ValueError:
            return 0.7

        delta_hours = abs((publish_time - event_time).total_seconds()) / 3600
        if delta_hours <= 6:    return 1.00
        if delta_hours <= 24:   return 0.85
        if delta_hours <= 72:   return 0.65
        if delta_hours <= 168:  return 0.45
        return 0.30
```

#### 可信度动态更新（事件驱动）

```python
# core/event/bus.py 订阅者
class CredibilityUpdater:
    """订阅 CredibilityComputedEvent，当新来源合并进已有文章时重算可信度"""

    async def on_new_merge(self, merged_article_id: str, new_cross_count: int):
        article = await self._article_repo.get(merged_article_id)
        if not article:
            return
        # 仅重算 cross_verification 分项，其余不变
        new_cross_score = min(1.0, 0.4 + new_cross_count * 0.15)
        new_credibility = (
            article.source_credibility  * 0.30 +
            new_cross_score             * 0.25 +
            article.content_check_score * 0.30 +
            article.timeliness          * 0.15   # timeliness 不变
        )
        await self._article_repo.update_credibility(
            article_id=merged_article_id,
            credibility_score=round(new_credibility, 2),
            cross_verification=new_cross_score,
            verified_by_sources=new_cross_count,
        )
```

---

### 6.5 实体解析算法

```python
# modules/graph_store/entity_resolver.py
class EntityResolver:
    """
    算法：
    1. 用实体名 + 类型生成 embedding（entity_extractor 节点已完成，直接复用）
    2. 在 entity_vectors 表做 ANN 查询（cosine > 0.85）
    3. 召回候选 > 0 → LLM 判断是否同一实体
    4. 是 → MERGE 已有节点，追加 alias；否 → 创建新节点
    5. 所有操作使用 Neo4j MERGE 保证幂等（防并发竞态）
    """
    COSINE_THRESHOLD = 0.85

    async def resolve(self, entity: dict, embedding: list[float]) -> str:
        candidates = await self._vector_repo.find_similar_entities(
            embedding=embedding,
            threshold=self.COSINE_THRESHOLD,
            limit=5,
        )

        if not candidates:
            return await self._create_entity(entity, embedding)

        if len(candidates) == 1:
            # 单一候选，直接判定为同一实体（阈值已足够高）
            return await self._merge_entity(candidates[0], entity)

        # 多候选 → LLM 消歧
        llm_result = await self._llm.call(
            CallPoint.ENTITY_RESOLVER,
            {
                "query_entity": entity,
                "candidates":   candidates,
            },
        )
        if llm_result.get("is_same") and llm_result.get("matched_id"):
            return await self._merge_entity(llm_result["matched_id"], entity)
        return await self._create_entity(entity, embedding)

    async def _create_entity(self, entity: dict, embedding: list[float]) -> str:
        """Neo4j MERGE + entity_vectors 写入"""
        neo4j_id = await self._neo4j_repo.merge_entity(entity)
        await self._vector_repo.upsert_entity_vector(neo4j_id, embedding)
        return neo4j_id

    async def _merge_entity(self, existing_id: str, entity: dict) -> str:
        """更新别名、描述等，不创建新节点"""
        await self._neo4j_repo.update_entity_alias(existing_id, entity["name"])
        return existing_id
```

---

## 七、数据流总览

```
SourceScheduler（APScheduler，max_instances=1，coalesce=True）
    │
    ▼
SourceParser（RSS ETag/If-Modified-Since 增量）→ list[NewsItem]
    │   过滤 pubDate <= last_crawl_time
    ▼
Deduplicator（Redis Hash + DB UNIQUE 两级）→ list[NewsItem]
    │
    ▼
Interleaver（按 host 轮转交叉排序）→ list[NewsItem]
    │
    ▼
背压检查（Redis pipeline:task_queue 水位 > 500 → 降级）
    │
    ▼
Crawler（global_sem + per-host_sem + SmartFetcher + trafilatura）
    │
    ▼
LangGraph Pipeline（RedisSaver Checkpoint，TTL 24h）
    ├─ classifier   → cleaner → categorizer → vectorize  【并发】
    │                                              ↓
    ├─────────────────────────────── batch_merger        【批次串行】
    │                                              ↓
    ├─ re_vectorize（含 model_id）                        【并发】
    ├─ analyze（summary + score + sentiment 一次 LLM）
    ├─ credibility_checker（4信号聚合）
    ├─ entity_extractor（spaCy语言路由 + batch_embed + LLM）
    ├─ entity_resolver（vector召回 + LLM消歧 + Neo4j MERGE）
    └─ persist（pg_done → neo4j_done）+ checkpoint_cleanup

补偿任务（APScheduler 每 10 分钟）：
    扫描 persist_status='pg_done' 且 updated_at < NOW()-10min
    → 重新触发 Neo4j 写入
```

---

## 八、HTTP API

### 认证

```python
# api/middleware/auth.py
from fastapi import Security, HTTPException
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key")

async def verify_api_key(key: str = Security(api_key_header)):
    if key != settings.api_key:
        raise HTTPException(status_code=403, detail="Invalid API Key")
```

### 路由一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/sources` | 获取所有资讯源 |
| POST | `/sources` | 新增资讯源 |
| PUT  | `/sources/{id}` | 更新资讯源 |
| DELETE | `/sources/{id}` | 删除资讯源 |
| POST | `/pipeline/trigger` | 异步触发采集（返回 task_id）|
| GET  | `/pipeline/tasks/{task_id}` | 查询任务状态 |
| GET  | `/articles` | 资讯列表（分页/筛选/排序）|
| GET  | `/articles/{id}` | 资讯详情 |
| GET  | `/graph/entities/{name}` | 实体及关系查询 |
| GET  | `/graph/articles/{id}/graph` | 资讯关联图谱 |
| GET  | `/admin/sources/authorities` | 查看待审核来源 |
| PATCH | `/admin/sources/{host}/authority` | 更新来源权威等级 |
| GET  | `/metrics` | Prometheus 指标 |

### 异步触发示例

```python
# api/endpoints/pipeline.py
@router.post("/pipeline/trigger", dependencies=[Depends(verify_api_key)])
@limiter.limit("10/minute")
async def trigger_pipeline(source_id: str, redis: RedisClient = Depends(get_redis)):
    task_id = str(uuid.uuid4())
    await redis.lpush("pipeline:task_queue", json.dumps({
        "task_id": task_id, "source_id": source_id,
        "queued_at": datetime.now(timezone.utc).isoformat()
    }))
    # 更新队列深度 Metrics
    depth = await redis.llen("pipeline:task_queue")
    metrics.pipeline_queue_depth.set(depth)
    return {"task_id": task_id, "status": "queued"}

@router.get("/pipeline/tasks/{task_id}")
async def get_task_status(task_id: str, redis: RedisClient = Depends(get_redis)):
    status = await redis.hget("pipeline:task_status", task_id)
    return {"task_id": task_id, "status": status or "unknown"}
```

---

## 九、Redis Key 设计

| Key | 类型 | 说明 | TTL |
|-----|------|------|-----|
| `crawl:dedup` | Hash | URL 去重，field=sha256(url)[:16]，value=首次采集时间戳 | 永久 |
| `crawl:retry:{host}` | ZSet | 重试队列，score=next_retry_at | 永久 |
| `crawl:dead` | List | 死信队列，JSON 记录 | 永久 |
| `llm:rpm:{provider}` | Hash | 令牌桶状态（tokens, last_time）| 3600s |
| `pipeline:task_queue` | List | Pipeline 触发任务队列 | 永久 |
| `pipeline:task_status` | Hash | 任务状态，field=task_id | 7d |
| `langgraph:checkpoint:{url_hash}` | Hash | LangGraph 断点 | 24h（正常完成后主动删除）|
| `merger:candidates:{category}:{date}` | String | Merger pgvector 查询结果缓存 | 采集间隔/2 |
| `credibility:pending_update` | ZSet | 待重算可信度的文章 ID，score=优先级 | 永久 |

---

## 十、Neo4j 图模型

```cypher
-- 约束（保证幂等，防并发竞态）
CREATE CONSTRAINT entity_unique IF NOT EXISTS
FOR (e:Entity) REQUIRE (e.canonical_name, e.type) IS UNIQUE;

-- Entity 节点（最小集合，Postgres 是主数据源）
(:Entity {
    id:             String,   -- UUID
    canonical_name: String,   -- 规范名称
    type:           String,   -- 人物/组织机构/地点/...
    tier:           Integer,  -- 权威来源优先级 (1=高权威, 2=中等, 3=普通)
    aliases:        [String], -- 别名列表
    description:    String,
    updated_at:     DateTime
})

-- Article 节点（只存图谱定位所需最小字段）
(:Article {
    pg_id:        String,     -- Postgres UUID
    title:        String,
    category:     String,
    publish_time: DateTime,
    score:        Float
})

-- 关系
(:Article)-[:MENTIONS {role: String}]->(:Entity)
(:Entity)-[:RELATED_TO {
    relation_type:     String,
    source_article_id: String,
    created_at:        DateTime
}]->(:Entity)
(:Article)-[:FOLLOWED_BY {time_gap_hours: Float}]->(:Article)

-- MERGE 写入（幂等）
MERGE (e:Entity {canonical_name: $name, type: $type})
ON CREATE SET
    e.id          = $id,
    e.aliases     = [$name],
    e.description = $description,
    e.created_at  = datetime()
ON MATCH SET
    e.aliases     = CASE WHEN NOT $alias IN e.aliases
                         THEN e.aliases + [$alias]
                         ELSE e.aliases END,
    e.updated_at  = datetime()
RETURN e

-- 图数据老化（每周定时，删除 90 天前无后续文章的 Article 节点）
MATCH (a:Article)
WHERE a.publish_time < datetime() - duration({days: 90})
  AND NOT (a)-[:FOLLOWED_BY]->()
DETACH DELETE a
```

---

## 十一、运维

### 11.1 优雅停机

```python
# main.py
import asyncio, signal
from container import Container

async def main():
    container = Container()
    container.config.from_toml("config/settings.toml")
    app = create_app(container)

    loop = asyncio.get_running_loop()

    async def graceful_shutdown(sig):
        print(f"收到信号 {sig}，开始优雅停机...")
        # 1. 停止接受新 Pipeline 任务
        await container.pipeline_manager().stop_accepting()
        # 2. 等待当前节点完成（最多 30s）
        await asyncio.wait_for(
            container.pipeline_manager().drain(),
            timeout=30.0
        )
        # 3. 将 processing 状态文章重新入队（下次启动时恢复）
        await container.article_repo().requeue_processing()
        # 4. 关闭浏览器池
        await container.playwright_pool().shutdown()
        loop.stop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(graceful_shutdown(s)))
```

### 11.2 补偿任务

```python
# APScheduler 定时补偿任务
scheduler.add_job(
    retry_neo4j_writes,       # 扫描 persist_status='pg_done' > 10min
    "interval", minutes=10,
    max_instances=1, coalesce=True,
)
scheduler.add_job(
    flush_retry_queue,        # 将到期的 crawl:retry:{host} 重新入队
    "interval", seconds=30,
    max_instances=1, coalesce=True,
)
scheduler.add_job(
    update_source_auto_scores, # 基于历史文章 content_check 分自动推算 source authority
    "cron", hour=3,            # 每天凌晨 3 点执行
    max_instances=1,
)
scheduler.add_job(
    archive_old_neo4j_nodes,   # 清理 90 天前的 Article 节点
    "cron", weekday="sun", hour=2,
    max_instances=1,
)
```

### 11.3 Dockerfile 关键步骤

```dockerfile
FROM python:3.12-slim

# 安装 uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# 安装 spaCy 模型
RUN uv run python -m spacy download zh_core_web_trf \
 && uv run python -m spacy download en_core_web_trf \
 && uv run python -m spacy download xx_ent_wiki_sm

# 安装 Playwright 浏览器
RUN uv run playwright install chromium --with-deps

COPY . .
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 11.4 HNSW 查询优化

```python
# 每次向量查询 session 中设置 ef_search（提升召回率）
await session.execute("SET hnsw.ef_search = 200;")
```

> 向量规模超过 500 万条时，对 `article_vectors` 按 `vector_type` 做分区表，分别为 `title` / `content` 各建独立 HNSW 索引，避免单索引过大。

### 11.5 Embedding 同源性保障

```
规则：article_vectors 中同一 category + 时间窗口内的向量必须来自同一 model_id。

pgvector 查询时加过滤：
  WHERE av.model_id = :current_model_id

若主模型 Fallback 到备用模型：
  1. 入库时记录 model_id = 备用模型名
  2. 发布 EmbeddingModelMismatchEvent
  3. 低峰期补偿任务用主模型重新向量化，覆写 embedding + model_id
```

---

*最后更新：2026-03*