## 1. Create unified-pipeline-test script

- [x] 1.1 Create `scripts/test_pipeline.py` with argument parser supporting `--mode` (newsnow/rss/strategy)
- [x] 1.2 Implement infrastructure initialization using `core.db.strategy.create_strategy()`
- [x] 1.3 Implement NewsNow mode data fetching using `modules.ingestion.parsing.NewsNowParser`
- [x] 1.4 Implement RSS mode data fetching using `modules.ingestion.parsing.RSSParser`
- [x] 1.5 Implement strategy mode for database failover testing
- [x] 1.6 Implement `--max-items` parameter to limit processed articles
- [x] 1.7 Implement `--force-news` flag to bypass classifier
- [x] 1.8 Implement `--clear-db` flag for database clearing before test
- [x] 1.9 Add shared verification logic for DuckDB and LadybugDB results
- [x] 1.10 Test all three modes and verify functionality matches original scripts

## 2. Create unified-api-test script

- [x] 2.1 Create `scripts/test_api.py` with subcommand parser (`e2e`, `audit`)
- [x] 2.2 Implement `e2e` subcommand with `--mode`, `--max-items`, `--no-start` parameters
- [x] 2.3 Implement `audit` subcommand with `--port` parameter
- [x] 2.4 Extract shared `wait_for_server()` function from original scripts
- [x] 2.5 Extract shared HTTP client configuration and auth headers
- [x] 2.6 Implement E2E test flow: register sources → trigger pipeline → poll tasks → verify
- [x] 2.7 Implement audit test flow: iterate endpoints → log results → save to JSONL
- [x] 2.8 Add `--api-key` parameter and `WEAVER_API_KEY` env support
- [x] 2.9 Test both subcommands and verify functionality matches original scripts

## 3. Create unified-evaluate script

- [x] 3.1 Create `scripts/evaluate.py` with subcommand parser (`hnsw`, `search`)
- [x] 3.2 Implement `hnsw` subcommand using existing PostgreSQL connection logic
- [x] 3.3 Implement `search` subcommand using `modules.knowledge.search.retrievers.BM25Retriever`
- [x] 3.4 Add `--num-vectors` parameter for HNSW test configuration
- [x] 3.5 Add `--k-values` parameter for search evaluation configuration
- [x] 3.6 Implement `--output` parameter (json/markdown formats)
- [x] 3.7 Implement `--output-path` parameter for saving results
- [x] 3.8 Test both subcommands and verify functionality matches original scripts

## 4. Create unified-manage script

- [x] 4.1 Create `scripts/manage.py` with subcommand parser (`validate`, `seed`)
- [x] 4.2 Implement `validate` subcommand using `core.health.env_validator.EnvironmentValidator`
- [x] 4.3 Implement `--service` parameter for selective validation
- [x] 4.4 Port seed data from `scripts/seed_relation_types.py` (RELATION_TYPES constant)
- [x] 4.5 Implement `seed` subcommand using Settings database connection
- [x] 4.6 Implement `--reset` flag for clearing existing data before seeding
- [x] 4.7 Ensure proper exit codes (0 success, 1 failure)
- [x] 4.8 Test both subcommands and verify functionality matches original scripts

## 5. Cleanup and verification

- [x] 5.1 Run all new scripts and verify functionality
- [x] 5.2 Delete `scripts/test_pipeline_duckdb.py`
- [x] 5.3 Delete `scripts/test_pipeline_rss.py`
- [x] 5.4 Delete `scripts/test_pipeline_duckdb_ladybug.py`
- [x] 5.5 Delete `scripts/run_36kr_full_pipeline.py`
- [x] 5.6 Delete `scripts/http_audit.py`
- [x] 5.7 Delete `scripts/run_performance_tests.py`
- [x] 5.8 Delete `scripts/evaluate_search_quality.py`
- [x] 5.9 Delete `scripts/validate_environment.py`
- [x] 5.10 Delete `scripts/seed_relation_types.py`
- [x] 5.11 Run full test suite to ensure no regressions

## 6. Documentation update

- [x] 6.1 Update README with new script usage examples
- [x] 6.2 Add docstrings to all new scripts following existing patterns
- [x] 6.3 Update any CI/CD configuration referencing old script paths (if applicable)