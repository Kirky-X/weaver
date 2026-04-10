## ADDED Requirements

### Requirement: No Playwright references in test files
The codebase SHALL NOT contain test files that import or reference deleted Playwright modules.

#### Scenario: Playwright test files removed
- **WHEN** searching for `test_playwright_*.py` files
- **THEN** no such files exist in `tests/` directory

#### Scenario: No Playwright imports in tests
- **WHEN** searching for `playwright_fetcher` or `playwright_pool` imports
- **THEN** no results found in `tests/` directory

### Requirement: SmartFetcher tests use Crawl4AIFetcher
Tests for SmartFetcher SHALL use `crawl4ai_fetcher` parameter instead of `playwright_fetcher`.

#### Scenario: Circuit breaker tests use Crawl4AI
- **WHEN** running `test_smart_fetcher_circuit_breaker.py`
- **THEN** tests pass using `crawl4ai_fetcher` mock

#### Scenario: SSRF tests use Crawl4AI
- **WHEN** running `test_ssrf_protection.py`
- **THEN** tests pass using `crawl4ai_fetcher` mock

### Requirement: Configuration files updated
Configuration files SHALL NOT contain Playwright-specific settings.

#### Scenario: settings.toml has no Playwright config
- **WHEN** reading `config/settings.toml`
- **THEN** no `playwright_` prefixed settings exist

### Requirement: Build scripts updated
Build and deployment scripts SHALL NOT reference Playwright.

#### Scenario: Nuitka build excludes Playwright
- **WHEN** reading `scripts/build_nuitka.py`
- **THEN** no `playwright` entries in `hiddenimports`

### Requirement: Documentation updated
Module docstrings and documentation SHALL reference Crawl4AI instead of Playwright.

#### Scenario: Module docstring updated
- **WHEN** reading `src/modules/ingestion/__init__.py`
- **THEN** docstring mentions "HTTPX/Crawl4AI" not "HTTPX/Playwright"

## REMOVED Requirements

### Requirement: Playwright test infrastructure
**Reason**: Playwright has been replaced with Crawl4AI
**Migration**: Use `Crawl4AIFetcher` and its corresponding test fixtures