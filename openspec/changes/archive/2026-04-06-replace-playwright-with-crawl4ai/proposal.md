## Why

当前项目使用 Playwright + playwright-stealth 实现 JS 渲染网页抓取，但存在以下问题：
1. **维护成本高** - 自行维护浏览器池（PlaywrightContextPool）约 200 行代码
2. **功能受限** - 缺少代理轮换、高级重试机制、内存自适应并发等现代爬虫能力
3. **硬编码列表** - `JS_REQUIRED_HOSTS` 硬编码了需要 JS 渲染的网站，难以维护

crawl4ai 是专为 LLM 优化的开源爬虫库，内置 stealth 模式、会话管理、并发控制、代理轮换等能力，可以简化代码并增强功能。

## What Changes

- **删除** `playwright_fetcher.py` - 不再需要
- **删除** `playwright_pool.py` - 不再需要
- **新建** `crawl4ai_fetcher.py` - 基于 crawl4ai 的新 fetcher 实现
- **修改** `smart_fetcher.py`:
  - 移除硬编码 `JS_REQUIRED_HOSTS`
  - 新增 HTML 特征检测判断 SPA 页面
  - 新增 `force_browser` 参数支持强制使用浏览器
- **修改** `crawler.py`:
  - 新增统一内容验证逻辑（trafilatura 提取验证）
  - 验证失败后强制使用 crawl4ai 重试
- **修改** `container.py` - 移除 PlaywrightContextPool 初始化
- **修改** `pyproject.toml` - 移除 playwright/playwright-stealth，新增 crawl4ai
- **更新** 相关测试文件

## Capabilities

### New Capabilities

- `crawl4ai-integration`: crawl4ai 库集成，提供 JS 渲染、stealth 模式、会话管理能力
- `smart-content-validation`: 智能内容验证，使用 trafilatura 统一验证 HTML/纯文本内容
- `spa-detection`: SPA 页面检测，通过 HTML 特征自动判断是否需要 JS 渲染

### Modified Capabilities

无现有 spec 需修改（这是实现层变更，不改变外部 API 行为）

## Impact

**代码影响：**
- `src/modules/ingestion/fetching/` - 删除 2 个文件，新建 1 个文件，修改 2 个文件
- `src/modules/ingestion/crawling/crawler.py` - 新增验证逻辑
- `src/container.py` - 移除 PlaywrightContextPool 相关代码

**依赖影响：**
- 移除: `playwright>=1.58.0`, `playwright-stealth>=2.0.2`
- 新增: `crawl4ai>=0.8.6`

**配置影响：**
- 移除 `settings.toml` 中 playwright 相关配置
- 新增 crawl4ai 配置项

**测试影响：**
- 删除 `test_playwright_fetcher.py`
- 新建 `test_crawl4ai_fetcher.py`
- 更新 `test_smart_fetcher.py`
- 更新 `test_crawler.py`

**兼容性：**
- 外部 API 不变（`BaseFetcher` 接口保持一致）
- 配置格式有变化，需要迁移