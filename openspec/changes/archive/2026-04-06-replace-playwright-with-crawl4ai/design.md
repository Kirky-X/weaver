## Context

**当前架构：**
```
Crawler.crawl_batch()
    └── SmartFetcher.fetch()
            ├── httpx_fetcher (轻量 HTTP)
            └── playwright_fetcher → PlaywrightContextPool
```

**问题：**
- PlaywrightContextPool 自行管理浏览器池，代码复杂（~200 行）
- 硬编码 `JS_REQUIRED_HOSTS` 难以维护
- 缺少现代爬虫能力（代理轮换、自适应并发）

**约束：**
- 保持 `BaseFetcher` 接口不变
- 保持 SmartFetcher 作为唯一 fetcher 入口
- crawl4ai 最新版本 0.8.6

## Goals / Non-Goals

**Goals:**
- 简化代码：删除 PlaywrightContextPool，由 crawl4ai 内部管理浏览器
- 智能判断：移除硬编码列表，通过 HTML 特征检测 SPA
- 统一验证：所有内容（预填充 + fetch）都经过 trafilatura 验证
- 增强能力：获得 crawl4ai 内置的会话管理、并发控制能力

**Non-Goals:**
- 不重构 Crawler 层并发控制（保持现有 Semaphore 模式）
- 不利用 crawl4ai 的 markdown 输出能力（保持返回 HTML）
- 不改变外部 API 行为

## Decisions

### 1. crawl4ai vs 保留 PlaywrightContextPool

**决定：使用 crawl4ai 替换**

| 方案 | 优点 | 缺点 |
|------|------|------|
| 保留 PlaywrightContextPool | 资源可控、无冷启动 | 维护成本高、功能受限 |
| crawl4ai | 内置高级功能、代码简化 | 冷启动延迟、黑盒管理 |

**理由：** crawl4ai 内置 stealth、会话管理、并发控制，简化维护。冷启动延迟可通过单例 AsyncWebCrawler 缓解。

### 2. SPA 检测策略

**决定：SmartFetcher 层 HTML 特征检测 + Crawler 层 trafilatura 验证**

| 层级 | 检测方式 | 目的 |
|------|----------|------|
| SmartFetcher | HTML 特征检测（空根节点、框架标识） | 初步判断，避免不必要的 JS 渲染 |
| Crawler | trafilatura 提取验证 | 深度验证，确保内容有效 |

**理由：** 双层检测避免硬编码，同时保持性能（先快后慢）。

### 3. 内容验证位置

**决定：Crawler 层统一处理**

**理由：**
- 预填充内容可能来自不同 SourceParser，需要统一验证
- 验证失败后的重试逻辑与 fetch 紧密相关
- SmartFetcher 保持职责单一：获取内容

### 4. 重试机制

**决定：SmartFetcher 提供 `force_browser` 参数**

```python
async def fetch(
    self,
    url: str,
    headers: dict[str, str] | None = None,
    force_browser: bool = False,  # 新增
) -> tuple[int, str, dict[str, str]]:
```

**理由：**
- 保持 SmartFetcher 作为唯一 fetcher 入口
- Crawler 验证失败后可调用 `fetch(url, force_browser=True)`
- 易于扩展未来策略

## Risks / Trade-offs

### Risk 1: crawl4ai 冷启动延迟

**风险：** 首次请求可能较慢（浏览器启动）

**缓解：**
- Crawl4AIFetcher 使用单例 AsyncWebCrawler
- 容器启动时预热（调用一次 fetch）

### Risk 2: crawl4ai 版本兼容性

**风险：** crawl4ai 仍在快速迭代（0.8.x），API 可能变化

**缓解：**
- 锁定版本 `crawl4ai>=0.8.6,<0.9.0`
- 封装在 Crawl4AIFetcher 内部，隔离变化

### Risk 3: trafilatura 对纯文本处理

**风险：** 纯文本内容 trafilatura 返回 None

**缓解：**
- 检测 trafilatura 返回值
- 返回空时保留原文本

### Trade-off: 未利用 crawl4ai 高级特性

**取舍：** 当前仅使用 crawl4ai 的浏览器渲染能力，未利用其 markdown 输出、结构化提取等功能

**理由：** 保持最小改动，后续可按需迭代

## Migration Plan

### 阶段 1：添加新实现（不破坏现有功能）
1. 新增 `crawl4ai_fetcher.py`
2. 更新 `pyproject.toml` 依赖
3. 更新测试

### 阶段 2：切换 SmartFetcher
1. 修改 SmartFetcher 使用 Crawl4AIFetcher
2. 添加 SPA 检测逻辑
3. 添加 `force_browser` 参数

### 阶段 3：更新 Crawler
1. 添加统一内容验证逻辑
2. 添加重试机制

### 阶段 4：清理
1. 删除 `playwright_fetcher.py`
2. 删除 `playwright_pool.py`
3. 更新 `container.py`
4. 更新配置文件

### 回滚策略
- Git 分支隔离
- 每个阶段独立提交
- 阶段 4 之前可随时回退到 PlaywrightFetcher