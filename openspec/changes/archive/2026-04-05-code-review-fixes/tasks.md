## 1. Dependency Updates

- [x] 1.1 Update security-critical packages (`sqlalchemy`, `anthropic`, `numpy`)
- [x] 1.2 Update toolchain packages (`black`, `ruff`, `pytest-env`)
- [x] 1.3 Update framework packages (`langchain`, `langgraph`, `litellm`)
- [x] 1.4 Update remaining outdated packages
- [x] 1.5 Run full test suite to verify compatibility
- [x] 1.6 Commit updated `uv.lock` and `pyproject.toml`

## 2. Security Hardening

- [x] 2.1 Update `src/config/settings.py` to use `os.getenv("HOST", "127.0.0.1")`
- [x] 2.2 Add warning log to `src/api/endpoints/graph_metrics.py:189`
- [x] 2.3 Add warning log to `src/api/endpoints/graph_metrics.py:231`
- [x] 2.4 Add warning log to `src/modules/ingestion/fetching/playwright_fetcher.py:109`
- [x] 2.5 Run `bandit -r src/` to verify no HIGH/CRITICAL issues
- [x] 2.6 Commit security improvements

## 3. Code Quality

- [x] 3.1 Run `black tests/unit/modules/scheduler/test_scheduler_jobs_dynamic_batch.py`
- [x] 3.2 Run `black --check src/ tests/ scripts/` to verify all formatted
- [x] 3.3 Run `npx gitnexus analyze` to refresh code intelligence index
- [x] 3.4 Create GitHub Issues for TODO markers found in source
- [x] 3.5 Commit formatting fixes

## 4. Verification

- [x] 4.1 Run `uv run pytest --cov=src` to verify test coverage >= 80%
- [x] 4.2 Run `uv run ruff check src/ tests/ scripts/` to verify lint passes
- [x] 4.3 Run `uv run mypy src/` to verify type checking passes
- [x] 4.4 Run `uv run bandit -r src/` to verify security scan passes
- [x] 4.5 Final commit with message `fix(review): address code review findings`