## 1. CLI Infrastructure

- [x] 1.1 Add `--db` argument parser with support for multiple values (choices: postgres, duckdb, neo4j, ladybug)
- [x] 1.2 Implement database validation helper function
- [x] 1.3 Implement default database selection logic based on subcommand

## 2. DuckDB Stats Implementation

- [x] 2.1 Create `_stats_duckdb()` async function
- [x] 2.2 Implement DuckDB connection using `DuckDBPool` from `core.db.duckdb_pool`
- [x] 2.3 Query DuckDB tables using SQLAlchemy session (articles, sources, article_vectors, entity_vectors, llm_usage_raw, etc.)
- [x] 2.4 Format output to match PostgreSQL stats format
- [x] 2.5 Handle DuckDB disabled and connection error cases

## 3. LadybugDB Stats Implementation

- [x] 3.1 Create `_stats_ladybug()` async function
- [x] 3.2 Implement LadybugDB connection using `LadybugPool` from `core.db.ladybug_pool`
- [x] 3.3 Query LadybugDB node labels using Cypher (`CALL show_tables()`)
- [x] 3.4 Query LadybugDB relationship counts
- [x] 3.5 Format output to match Neo4j stats format
- [x] 3.6 Handle LadybugDB disabled and connection error cases

## 4. DuckDB Article Query Implementation

- [x] 4.1 Create `_article_duckdb()` async function
- [x] 4.2 Query article by ID from DuckDB articles table
- [x] 4.3 Query related tables (article_vectors, entity_mentions equivalent if applicable)
- [x] 4.4 Format output to match PostgreSQL article output

## 5. LadybugDB Random Query Implementation

- [x] 5.1 Create `_random_ladybug()` async function
- [x] 5.2 Query random articles with MENTIONS relationships
- [x] 5.3 Query FOLLOWED_BY and RELATED_TO relationships for each article
- [x] 5.4 Format output to match Neo4j random output

## 6. Integration and Dispatch

- [x] 6.1 Update `cmd_stats()` to dispatch to all database query functions based on `--db` parameter
- [x] 6.2 Update `cmd_article()` to support `--db duckdb` option
- [x] 6.3 Update `cmd_random()` to support `--db ladybug` option
- [x] 6.4 Add disabled database status messages in output

## 7. Testing and Verification

- [x] 7.1 Test `stats --db duckdb` with DuckDB enabled
- [x] 7.2 Test `stats --db ladybug` with LadybugDB enabled
- [x] 7.3 Test `stats` without `--db` queries all enabled databases
- [x] 7.4 Test `article --db duckdb` retrieves article correctly
- [x] 7.5 Test `random --db ladybug` retrieves random articles
- [x] 7.6 Test error handling for disabled databases
- [x] 7.7 Test error handling for connection failures