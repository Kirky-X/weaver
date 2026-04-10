## Why

`replace-playwright-with-crawl4ai` 迁移已完成，但代码库中残留多处 Playwright 相关引用：
- 已删除的 `playwright_fetcher.py` 和 `playwright_pool.py` 对应的测试文件仍然存在
- 测试 fixtures 和 mock 对象引用已不存在的 Playwright 组件
- 配置文件和构建脚本中保留过时的 Playwright 设置
- 文档字符串描述过时

这些残留会导致**测试导入错误**和**维护混淆**。

## What Changes

### 删除
- `tests/unit/modules/fetcher/test_playwright_fetcher.py` — 测试已删除模块
- `tests/unit/modules/fetcher/test_playwright_pool.py` — 测试已删除模块
- `tests/manual/test_stealth.py` — 引用已删除的 PlaywrightContextPool

### 修改
- `tests/conftest.py` — 删除 `mock_playwright_context()`, `mock_playwright_page()` fixtures
- `tests/integration/test_ssrf_protection.py` — `playwright_fetcher` 参数改为 `crawl4ai_fetcher`
- `tests/unit/modules/fetcher/test_smart_fetcher_circuit_breaker.py` — `playwright_fetcher` 参数改为 `crawl4ai_fetcher`
- `scripts/test_pipeline.py` — 使用 Crawl4AIFetcher 替代 PlaywrightFetcher
- `scripts/build_nuitka.py` — 删除 Playwright hiddenimports
- `config/settings.toml` — 删除 `playwright_pool_size`，已有 `crawl4ai_*` 配置
- `src/modules/ingestion/__init__.py` — docstring "HTTPX/Playwright" 改为 "HTTPX/Crawl4AI"

## Capabilities

### New Capabilities

无新增能力，这是清理工作。

### Modified Capabilities

无规格变更，这是代码清理和测试修复。

## Impact

- **测试套件**: 修复导入错误，确保测试可以正常运行
- **构建系统**: 移除过时的 Playwright 依赖引用
- **文档**: 更新过时的描述
- **配置**: 清理过时的配置项

**风险**: 低 — 删除的是已失效的测试和配置，不影响生产代码