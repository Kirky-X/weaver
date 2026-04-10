## 1. Configuration

- [x] 1.1 Add `SpacySettings` dataclass to `config/settings.py` with fields: `force_install`, `strict_mode`, `models`, `local_paths`
- [x] 1.2 Add `[spacy]` configuration section to `config/settings.toml`
- [x] 1.3 Add `[spacy]` configuration section to `config/settings.example.toml`

## 2. Core Implementation

- [x] 2.1 Create `src/core/nlp/` directory if not exists
- [x] 2.2 Create `src/core/nlp/__init__.py` with module exports
- [x] 2.3 Create `src/core/nlp/spacy_manager.py` with `SpacyModelConfig` dataclass
- [x] 2.4 Implement `SpacyModelManager.__init__()` with config injection
- [x] 2.5 Implement `_detect_missing_models()` method using `spacy.load()` try/catch
- [x] 2.6 Implement `_install_model()` method with local wheel and network fallback
- [x] 2.7 Implement `_handle_install_failure()` method with strict_mode handling
- [x] 2.8 Implement `check_and_install()` method as main entry point

## 3. Integration

- [x] 3.1 Locate application entry point (`src/main.py` or equivalent)
- [x] 3.2 Add `SpacyModelManager.check_and_install()` call after Settings load
- [x] 3.3 Ensure proper exception handling for startup failure case

## 4. Testing

- [x] 4.1 Create `tests/unit/core/nlp/test_spacy_manager.py`
- [x] 4.2 Test `_detect_missing_models()` with mocked `spacy.load()`
- [x] 4.3 Test `_install_model()` local wheel path (mocked subprocess)
- [x] 4.4 Test `_install_model()` network download (mocked `spacy.cli.download`)
- [x] 4.5 Test `_handle_install_failure()` strict_mode=true raises RuntimeError
- [x] 4.6 Test `_handle_install_failure()` strict_mode=false logs error
- [x] 4.7 Test `check_and_install()` full flow with all models present
- [x] 4.8 Run full test suite to ensure no regressions