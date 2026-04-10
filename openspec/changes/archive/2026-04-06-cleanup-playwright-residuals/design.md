## Context

`replace-playwright-with-crawl4ai` 迁移已完成核心工作，但残留文件和引用会导致测试失败。当前状态：

```
已删除源码:
  src/modules/ingestion/fetching/playwright_fetcher.py ❌
  src/modules/ingestion/fetching/playwright_pool.py ❌

残留测试:
  tests/unit/modules/fetcher/test_playwright_fetcher.py ⚠️ 导入错误
  tests/unit/modules/fetcher/test_playwright_pool.py ⚠️ 导入错误
  tests/manual/test_stealth.py ⚠️ 导入错误

残留引用:
  tests/conftest.py:322-333 ⚠️ mock fixtures
  tests/integration/test_ssrf_protection.py:131-159 ⚠️ playwright_fetcher 参数
  tests/unit/modules/fetcher/test_smart_fetcher_circuit_breaker.py ⚠️ playwright_fetcher 参数
  scripts/test_pipeline.py:286-325 ⚠️ PlaywrightFetcher 使用
  scripts/build_nuitka.py:176-180 ⚠️ hiddenimports
  config/settings.toml:55 ⚠️ playwright_pool_size
```

## Goals / Non-Goals

**Goals:**
- 清理所有 Playwright 残留，确保测试可运行
- 更新测试使用 Crawl4AIFetcher
- 清理配置和构建脚本

**Non-Goals:**
- 不修改 SmartFetcher 核心逻辑（已正确实现）
- 不添加新功能

## Decisions

### 1. 测试文件处理

| 文件 | 决策 | 理由 |
|------|------|------|
| `test_playwright_fetcher.py` | **删除** | 测试已删除模块，无迁移价值 |
| `test_playwright_pool.py` | **删除** | 测试已删除模块，无迁移价值 |
| `test_stealth.py` | **删除** | 手动测试脚本，Playwright 特有功能 |
| `test_smart_fetcher_circuit_breaker.py` | **修改** | 将 `playwright_fetcher` 参数改为 `crawl4ai_fetcher` |
| `test_ssrf_protection.py` | **修改** | 将 `playwright_fetcher` 参数改为 `crawl4ai_fetcher` |

**替代方案考虑**: 保留测试文件并更新导入？
- ❌ 不采用：Playwright 和 Crawl4AI API 不同，测试逻辑不兼容
- ✅ 采用：直接删除过时测试，为 Crawl4AI 编写新测试

### 2. Fixtures 更新

```python
# 删除 (conftest.py)
def mock_playwright_context(): ...  # ❌ 删除
def mock_playwright_page(): ...     # ❌ 删除

# 替换为 (如需要)
def mock_crawl4ai_fetcher():       # ✅ 新增
    """Mock Crawl4AIFetcher for testing."""
    mock = MagicMock()
    mock.fetch = AsyncMock(return_value=(200, "<html>content</html>", {}))
    mock.close = AsyncMock()
    return mock
```

### 3. SmartFetcher 测试参数更新

```python
# 修改前
smart_fetcher = SmartFetcher(
    httpx_fetcher=mock_httpx,
    playwright_fetcher=mock_playwright,  # ❌
)

# 修改后
smart_fetcher = SmartFetcher(
    httpx_fetcher=mock_httpx,
    crawl4ai_fetcher=mock_crawl4ai,      # ✅
)
```

### 4. scripts/test_pipeline.py 处理

该脚本使用 PlaywrightFetcher 进行测试。方案：

```python
# 修改前
from modules.ingestion.fetching.playwright_fetcher import PlaywrightFetcher
from modules.ingestion.fetching.playwright_pool import PlaywrightContextPool

playwright_pool = PlaywrightContextPool(pool_size=1, stealth_enabled=True)
await playwright_pool.startup()
playwright_fetcher = PlaywrightFetcher(pool=playwright_pool)

# 修改后
from modules.ingestion.fetching.crawl4ai_fetcher import Crawl4AIFetcher

crawl4ai_fetcher = Crawl4AIFetcher(
    headless=True,
    stealth_enabled=True,
)
```

## Risks / Trade-offs

| 风险 | 缓解措施 |
|------|----------|
| 删除测试可能掩盖功能缺失 | Crawl4AI 已有 `test_crawl4ai_fetcher.py` 覆盖核心功能 |
| 修改 `test_smart_fetcher_circuit_breaker.py` 可能破坏测试逻辑 | 仅替换参数名，保持测试逻辑不变 |
| `test_pipeline.py` 脚本功能变化 | Crawl4AI 提供等效的浏览器渲染能力 |

## Migration Plan

无需迁移 — 这是清理工作，直接修改即可。

执行顺序：
1. 删除过时测试文件
2. 更新 `conftest.py` fixtures
3. 更新 `test_smart_fetcher_circuit_breaker.py` 参数
4. 更新 `test_ssrf_protection.py` 参数
5. 更新 `scripts/test_pipeline.py`
6. 清理配置和构建脚本
7. 运行测试验证