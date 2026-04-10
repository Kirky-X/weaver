## ADDED Requirements

### Requirement: SmartFetcher detects SPA pages

SmartFetcher SHALL detect Single Page Application (SPA) pages by analyzing HTML characteristics.

#### Scenario: Empty root element detected
- **WHEN** HTML contains empty root elements like `<div id="app"></div>` or `<div id="root">`
- **THEN** the page is classified as SPA

#### Scenario: Framework signatures detected
- **WHEN** HTML contains framework signatures like `__NEXT_DATA__`, `__NUXT__`, `ng-version`, `data-reactroot`
- **THEN** the page is classified as SPA

#### Scenario: Script-heavy low-content page detected
- **WHEN** HTML has many script tags but minimal visible text content
- **THEN** the page is classified as potentially SPA

### Requirement: SPA detection triggers crawl4ai fallback

SmartFetcher SHALL use crawl4ai for pages detected as SPA.

#### Scenario: SPA page uses crawl4ai
- **WHEN** httpx response is detected as SPA
- **THEN** SmartFetcher falls back to crawl4ai_fetcher

### Requirement: SmartFetcher supports force_browser parameter

SmartFetcher SHALL accept a force_browser parameter to bypass httpx and use crawl4ai directly.

#### Scenario: force_browser=True skips httpx
- **WHEN** fetch(url, force_browser=True) is called
- **THEN** httpx is NOT attempted, crawl4ai_fetcher is used directly

#### Scenario: force_browser=False uses normal flow
- **WHEN** fetch(url, force_browser=False) is called (default)
- **THEN** the normal httpx-first-with-fallback flow is used

### Requirement: JS_REQUIRED_HOSTS constant is removed

The hardcoded JS_REQUIRED_HOSTS set SHALL be removed from SmartFetcher.

#### Scenario: No hardcoded host list
- **WHEN** SmartFetcher decides which fetcher to use
- **THEN** it uses SPA detection instead of checking a hardcoded host list