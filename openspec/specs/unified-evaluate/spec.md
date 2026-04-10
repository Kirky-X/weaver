## ADDED Requirements

### Requirement: Support HNSW and search evaluation subcommands

The script SHALL support `hnsw` and `search` subcommands to run vector index performance tests and search quality evaluations respectively.

#### Scenario: HNSW performance test
- **WHEN** user runs `scripts/evaluate.py hnsw --num-vectors 1000`
- **THEN** script tests bulk insert performance, query performance, and index usage

#### Scenario: Search quality evaluation
- **WHEN** user runs `scripts/evaluate.py search --k-values 5,10,20`
- **THEN** script evaluates Recall@K, Precision@K, and MRR metrics

### Requirement: Reuse BM25Retriever module

The search evaluation SHALL use `modules.knowledge.search.retrievers.BM25Retriever` instead of reimplementing BM25 logic.

#### Scenario: BM25 search evaluation
- **WHEN** search evaluation runs
- **THEN** BM25Retriever is used for document indexing and retrieval

### Requirement: Support configurable test parameters

The script SHALL support configuration of test parameters via CLI arguments.

#### Scenario: Configure HNSW test parameters
- **WHEN** user runs `scripts/evaluate.py hnsw --num-vectors 2000`
- **THEN** 2000 vectors are used for performance testing

#### Scenario: Configure search evaluation parameters
- **WHEN** user runs `scripts/evaluate.py search --k-values 5,10`
- **THEN** only Recall@5 and Recall@10 are calculated

### Requirement: Support output formats

The script SHALL support `--output` parameter with values `json` and `markdown` for result formatting.

#### Scenario: JSON output
- **WHEN** user runs `scripts/evaluate.py search --output json`
- **THEN** results are printed in JSON format

#### Scenario: Markdown output
- **WHEN** user runs `scripts/evaluate.py hnsw --output markdown`
- **THEN** results are printed in markdown table format

### Requirement: Support output file path

The script SHALL support `--output-path` parameter to specify where results are saved.

#### Scenario: Save results to file
- **WHEN** user runs `scripts/evaluate.py search --output-path ./results/`
- **THEN** results are saved to `./results/search_quality_<timestamp>.json`