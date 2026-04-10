## 1. Core Algorithm Replacement

- [x] 1.1 Replace `_run_hierarchical_leiden` in `src/modules/graph_store/community_detector.py`: implement recursive Leiden using `leidenalg.find_partition` + `igraph.Graph` subgraph splitting, with max_depth=10 guard
- [x] 1.2 Replace `_run_hierarchical_leiden` in `src/modules/knowledge/community/detector.py`: apply identical implementation as 1.1 (mirror file)

## 2. Remove Graspologic Guards

- [x] 2.1 Remove `GRASPOLOGIC_AVAILABLE` try/except import block and `hierarchical_leiden = None` fallback in both detector files
- [x] 2.2 Remove `if not GRASPOLOGIC_AVAILABLE:` early-return guard in `detect_communities()` of both detector files
- [x] 2.3 Add `import igraph as ig` and `import leidenalg` at module top level in both detector files

## 3. Dependency Cleanup

- [x] 3.1 Remove `"graspologic>=3.4.4"` from `pyproject.toml` dependencies
- [x] 3.2 Remove `"ignore:invalid escape sequence:SyntaxWarning:graspologic"` and `"ignore:invalid escape sequence:SyntaxWarning:hyppo"` from `pyproject.toml` filterwarnings
- [x] 3.3 Remove `"ignore::SyntaxWarning:graspologic"` and `"ignore::SyntaxWarning:hyppo"` from `pytest.ini` filterwarnings
- [x] 3.4 Run `uv sync` to update lock file and verify graspologic is removed

## 4. Test Updates

- [x] 4.1 Remove `GRASPOLOGIC_AVAILABLE` import from `tests/unit/modules/graph_store/test_community_detector.py`
- [x] 4.2 Remove `@pytest.mark.skipif(not GRASPOLOGIC_AVAILABLE, ...)` from `TestCommunityDetectorRunHierarchicalLeiden` and `TestCommunityDetectorDetectCommunities`
- [x] 4.3 Update `test_run_hierarchical_leiden_returns_clusters` and `test_run_hierarchical_leiden_respects_seed` to verify correct `HierarchicalCluster` output format (node, cluster, level, parent_cluster, is_final_cluster)
- [x] 4.4 Update `test_detect_communities_returns_result` and related tests to work without graspologic skip guard

## 5. Verification

- [x] 5.1 Run full test suite: `uv run pytest` — all 2210+ tests must pass with 0 failures
- [x] 5.2 Confirm 0 tests are skipped due to graspologic (the previous 6 skips should now run and pass)
- [x] 5.3 Run `uv run ruff check src/modules/graph_store/community_detector.py src/modules/knowledge/community/detector.py` — zero lint errors
