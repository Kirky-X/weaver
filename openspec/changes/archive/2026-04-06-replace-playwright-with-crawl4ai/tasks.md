## 1. Dependencies & Configuration

- [x] 1.1 Update pyproject.toml: remove `playwright>=1.58.0` and `playwright-stealth>=2.0.2`
- [x] 1.2 Update pyproject.toml: add `crawl4ai>=0.8.6,<0.9.0`
- [x] 1.3 Update config/settings.example.toml: remove playwright pool settings
- [x] 1.4 Update config/settings.example.toml: add crawl4ai configuration section
- [x] 1.5 Update src/config/settings.py: add crawl4ai settings model, remove playwright settings

## 2. Crawl4AIFetcher Implementation

- [x] 2.1 Create src/modules/ingestion/fetching/crawl4ai_fetcher.py with class skeleton
- [x] 2.2 Implement Crawl4AIFetcher.__init__ with BrowserConfig and AsyncWebCrawler initialization
- [x] 2.3 Implement Crawl4AIFetcher.fetch() method returning (status_code, html, response_headers)
- [x] 2.4 Implement Crawl4AIFetcher.close() method for resource cleanup
- [x] 2.5 Add error handling for failed crawls (raise exception on result.success=False)
- [x] 2.6 Create tests/unit/modules/ingestion/fetching/test_crawl4ai_fetcher.py

## 3. SPA Detection

- [x] 3.1 Implement _appears_to_be_spa() function in smart_fetcher.py
- [x] 3.2 Add detection for empty root elements (id="app", id="root")
- [x] 3.3 Add detection for framework signatures (__NEXT_DATA__, __NUXT__, ng-version, data-reactroot)
- [x] 3.4 Add detection for script-heavy low-content pages
- [x] 3.5 Create unit tests for SPA detection function

## 4. SmartFetcher Updates

- [x] 4.1 Remove JS_REQUIRED_HOSTS constant from smart_fetcher.py
- [x] 4.2 Add force_browser parameter to SmartFetcher.fetch() signature
- [x] 4.3 Update _do_fetch() to use SPA detection instead of host list
- [x] 4.4 Update _do_fetch() to handle force_browser=True parameter
- [x] 4.5 Replace PlaywrightFetcher dependency with Crawl4AIFetcher
- [x] 4.6 Update tests/unit/modules/ingestion/fetching/test_smart_fetcher.py

## 5. Content Validation in Crawler

- [x] 5.1 Add MIN_ARTICLE_LENGTH constant to crawler.py
- [x] 5.2 Implement content validation logic in crawl_one() for pre-filled body
- [x] 5.3 Add re-fetch logic with force_browser=True when validation fails
- [x] 5.4 Add debug logging for validation failures
- [x] 5.5 Update tests/unit/modules/ingestion/crawling/test_crawler.py

## 6. Container Updates

- [x] 6.1 Remove PlaywrightContextPool import from container.py
- [x] 6.2 Remove init_playwright_pool() method
- [x] 6.3 Remove playwright_pool property
- [x] 6.4 Add init_crawl4ai_fetcher() method
- [x] 6.5 Update init_smart_fetcher() to use Crawl4AIFetcher

## 7. Module Exports

- [x] 7.1 Update src/modules/ingestion/fetching/__init__.py: remove PlaywrightFetcher, PlaywrightContextPool
- [x] 7.2 Update src/modules/ingestion/fetching/__init__.py: add Crawl4AIFetcher export
- [x] 7.3 Update src/modules/ingestion/__init__.py: remove PlaywrightContextPool export

## 8. Cleanup

- [x] 8.1 Delete src/modules/ingestion/fetching/playwright_fetcher.py
- [x] 8.2 Delete src/modules/ingestion/fetching/playwright_pool.py
- [x] 8.3 Delete tests/unit/modules/ingestion/fetching/test_playwright_fetcher.py
- [x] 8.4 Run full test suite and fix any failures
- [x] 8.5 Run linting (ruff) and fix any issues

## 9. Documentation

- [x] 9.1 Update README or relevant docs if they mention Playwright
- [x] 9.2 Add migration notes for configuration changes