## 1. Delete Obsolete Test Files

- [x] 1.1 Delete `tests/unit/modules/fetcher/test_playwright_fetcher.py`
- [x] 1.2 Delete `tests/unit/modules/fetcher/test_playwright_pool.py`
- [x] 1.3 Delete `tests/manual/test_stealth.py`

## 2. Update Test Fixtures

- [x] 2.1 Remove `mock_playwright_context()` fixture from `tests/conftest.py`
- [x] 2.2 Remove `mock_playwright_page()` fixture from `tests/conftest.py`
- [x] 2.3 Add `mock_crawl4ai_fetcher()` fixture to `tests/conftest.py` (if needed)

## 3. Update SmartFetcher Tests

- [x] 3.1 Update `tests/unit/modules/fetcher/test_smart_fetcher_circuit_breaker.py`: replace `playwright_fetcher` with `crawl4ai_fetcher`
- [x] 3.2 Update `tests/integration/test_ssrf_protection.py`: replace `playwright_fetcher` with `crawl4ai_fetcher`

## 4. Update Scripts

- [x] 4.1 Update `scripts/test_pipeline.py`: replace PlaywrightFetcher with Crawl4AIFetcher
- [x] 4.2 Update `scripts/build_nuitka.py`: remove Playwright from hiddenimports list

## 5. Clean Configuration

- [x] 5.1 Remove `playwright_pool_size` from `config/settings.toml`

## 6. Update Documentation

- [x] 6.1 Update `src/modules/ingestion/__init__.py` docstring: "HTTPX/Playwright" → "HTTPX/Crawl4AI"

## 7. Verification

- [x] 7.1 Run `ruff check` to verify no lint errors
- [x] 7.2 Run `pytest tests/unit/modules/ingestion/fetching/` to verify fetcher tests pass
- [x] 7.3 Run `pytest tests/integration/test_ssrf_protection.py` to verify SSRF tests pass
- [x] 7.4 Run full test suite to ensure no regressions