## 1. Configuration

- [x] 1.1 Add `EntitySettings` class to `src/config/settings.py` with `disable_data_metrics_nodes: bool = False`
- [x] 1.2 Add `entity: EntitySettings` field to `Settings` class
- [x] 1.3 Update `config/settings.toml.example` with `[entity]` section example

## 2. SpaCy Extractor Filtering

- [x] 2.1 Add `disable_data_metrics: bool = False` parameter to `_extract_from_doc()` method
- [x] 2.2 Add filtering logic to skip "数据指标" entities when parameter is `True`
- [x] 2.3 Update `extract()` method to pass the parameter
- [x] 2.4 Update `extract_batch()` method to pass the parameter

## 3. LLM Entity Extractor Filtering

- [x] 3.1 Add `Settings` parameter to `EntityExtractorNode.__init__()`
- [x] 3.2 Add filtering logic after Phase 3 LLM result processing
- [x] 3.3 Update `src/container.py` to inject `Settings` into `EntityExtractorNode`

## 4. Entity Resolver Filtering

- [x] 4.1 Add `disable_data_metrics: bool = False` parameter to `EntityResolver.__init__()`
- [x] 4.2 Add configuration-driven filter check at the start of `resolve_entity()`
- [x] 4.3 Update `src/container.py` to inject configuration into `EntityResolver`

## 5. SpacyExtractor Dependency Injection

- [x] 5.1 Add `Settings` parameter to `SpacyExtractor.__init__()` or pass flag at call sites
- [x] 5.2 Update call sites in `EntityExtractorNode` to pass configuration

## 6. Tests

- [x] 6.1 Add test for `EntitySettings` configuration loading in `tests/unit/config/test_settings.py`
- [x] 6.2 Add test for spaCy filtering in `tests/unit/modules/processing/nlp/test_spacy_extractor.py`
- [x] 6.3 Add test for LLM entity filtering in `tests/unit/modules/processing/nodes/test_entity_extractor.py`
- [x] 6.4 Add test for resolver filtering in `tests/unit/modules/knowledge/graph/test_entity_resolver.py`

## 7. Documentation

- [x] 7.1 Update README.md or relevant documentation to describe the new configuration option