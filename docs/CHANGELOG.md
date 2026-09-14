# 📋 更新日志

本文件记录本项目的全部重要变更。

格式基于 [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)，
版本号遵循 [语义化版本](https://semver.org/spec/v2.0.0.html)。

## 📋 目录

<details open>
<summary>📑 目录（点击展开）</summary>

- [Unreleased](#-unreleased)

</details>

---

## 🚧 [Unreleased]

### ✨ 新增

#### 🔧 LLM 配置

- **LiveConfig Hot-Reload**: Integrated live configuration reload for LLM module, allowing `config/llm.toml` changes
  without service restart
    - Atomic configuration swap with validation
    - Automatic SmartRouter rebuild on config change
    - File watcher using `watchfiles` library

#### 🔍 搜索能力

- **Explicit Search Mode**: Added `mode` parameter to search endpoint supporting `local`, `global`, and `auto` (default)
  modes
    - `local`: Direct vector search for entity neighborhoods
    - `global`: Community-level search with Map-Reduce pattern
    - `auto`: Intent-based automatic routing (existing behavior)

#### 🏘️ 社区检测

- **LLM-Powered Title Generation**: Automatic community title generation using LLM during community detection
    - Uses dedicated `community_title` call point
    - Configurable via `config/prompts/community_title.toml`
    - Titles limited to 10 characters, extracted from entity themes

#### 💾 数据库与存储

- **EXCITED Sentiment Type**: Added new sentiment type for emotion analysis in `AnalyzeOutput`
- **DuckDB Support**: Added DuckDB as database fallback with dedicated schema initialization
- **E2E Testing**: Docker-less fallback support for E2E tests, enabling testing without container runtime

### 🔄 变更

#### 架构

- **Scripts Consolidation**: Merged `scripts` directory from 12 to 4 core scripts for better maintainability
- **Legacy Code Removal**: Removed backward compatibility code for cleaner codebase
- **Main Config Loading**: Replaced `toml` library with `tomllib` (Python 3.11+ standard library)

#### API 与端点

- **Health Check Simplification**: Simplified health check endpoint for load balancer compatibility
- **Community Report Fields**: Extended community report query with `key_entities`, `key_relationships`, and `rank`
  attributes
- **Public API**: Exposed `list_enabled_sources` as public API endpoint

#### 性能与优化

- **DuckDB Schema Initialization**: Optimized to single session mode for better performance
- **Tracing Configuration**: Enhanced tracing config to support empty endpoint disabling

### 🗑️ 废弃

- **LangChain/LangGraph**: Removed from dependencies (replaced by LiteLLM integration)

### ❌ 移除

- **Legacy Compatibility Code**: Removed old backward compatibility layers
- **Hardcoded Default Password**: Removed `"neo4j_password"` default from `Neo4jSettings`

### 🐛 修复

#### 类型安全

- Fixed dataclass type annotations in `src/core/llm/types.py`: `list[str] = None` → `list[str] | None = None` for
  `RoutingConfig.fallbacks`, `ProviderConfig.models`, `GlobalConfig.defaults`, `GlobalConfig.call_points`
- Fixed `sanitize_dict` return type annotation in `src/core/utils/sanitize.py`: `dict[str, str]` → `dict[str, Any]`
- Fixed variable name conflict in `src/modules/migration/mapping_registry.py` causing type inference errors

#### 🔒 安全

- **BM25 Index Loading**: Added `RestrictedUnpickler` to prevent remote code execution when loading BM25 indices
    - Only allows safe built-in types (dict, list, tuple, str, int, etc.)
    - Blocks arbitrary class instantiation
- **Vector Similarity Queries**: Added input validation for vector similarity query parameters
- **SSRF Protection**: Enhanced SSRF protection with inline URL validation
- **Migration Adapters**: Fixed SQL injection vulnerabilities and added detailed logging
- **API Response Errors**: Made validation errors JSON-serializable in API responses

#### 🐞 Bug 修复

- **DuckDB Schema**: Fixed DuckDB schema initialization in container startup
- **Newsnow Parser**: Corrected list page detection for numeric IDs (e.g., 36kr URLs)
- **Community Repository**: Fixed community repo and Ladybug schema compatibility issues
- **Spacy Package**: Fixed spacy wheel package extraction logic
- **E2E Tests**: Fixed auth middleware settings retrieval and data validator logic
- **Health Check**: Fixed health check endpoint test assertions
- **Test Mocks**: Fixed test mock query count mismatch and configuration defaults

#### Code Quality

- Added debug logging to silent exception handlers in `src/modules/processing/pipeline/graph.py`
- Enhanced error handling with detailed logging across migration adapters and core modules

### ✅ 验证

- All 856 tests pass
- mypy type checking passes for modified files
- ruff lint checks pass
- No new hardcoded secrets detected

## 🔗 相关文档

- [API 文档](API.md) — 完整 API 接口参考
- [用户指南](USER_GUIDE.md) — 快速上手与使用指南
- [架构文档](ARCHITECTURE.md) — 系统设计与架构详解
- [部署指南](DEPLOYMENT.md) — 部署与环境配置
- [项目 README](../README.md) — 返回首页
