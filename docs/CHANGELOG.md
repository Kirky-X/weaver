# 📋 更新日志

本文件记录本项目的全部重要变更。

格式基于 [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)，
版本号遵循 [语义化版本](https://semver.org/spec/v2.0.0.html)。

## 📋 目录

<details open>
<summary>📑 目录（点击展开）</summary>

- [Unreleased](#-unreleased)
- [v0.2.0](#-v020---2026-07-21)

</details>

---

## 🚀 [v0.2.0] - 2026-07-21

- 首个公开 Release：采集 → LLM 流水线 → 知识图谱 → 搜索全链路
- 技术栈：FastAPI + LiteLLM + Neo4j/LadybugDB（图）+ PostgreSQL/DuckDB（关系）

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
- **Extended Search Endpoints**: Added `drift`, `causal`, and `temporal` search endpoints
- **Bing Web Search**: Optional Bing web search backfill via `WEAVER_BING__ENABLED` (disabled by default)

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

#### 文档

- **Docs Cleanup**: Removed process documents (`docs/技术缺口审计报告.md`, `docs/LLM调用优化方案.md`) and renamed
  `docs/asserts/` → `docs/assets/`; READMEs restructured with a unified CN/EN section layout
- **Docs Accuracy**: README test counts, LLM call-point table (25 `CallPoint` entries) and scheduled-jobs table (30
  jobs) synced with implementation; API.md added 7 missing endpoint groups (monitoring memory/causal/graph/communities,
  admin database monitoring, api-keys, memory diagnostics); CONTRIBUTING.md switched black → `ruff format`; USER_GUIDE
  fixed unsupported `mode=articles`; DEPLOYMENT.md added Docker Compose deployment path

#### 架构

- **Scripts Consolidation**: Consolidated scripts directory to 6 core scripts (7 files incl. helpers), exposed as 4
  `weaver-*` CLI entry points
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

- Fixed `None` defaults in `src/core/llm/types.py`: `RoutingConfig.fallbacks`, `ProviderConfig.models`,
  `GlobalConfig.defaults`, and `GlobalConfig.call_points` now default to empty collections (`fallbacks: list[str] = []`,
  `models: dict[str, ModelConfig] = {}`, `defaults`/`call_points: dict[str, RoutingConfig] = {}`); these are pydantic
  `BaseModel` fields

#### 🔒 安全

- **BM25 Index Loading**: Added `RestrictedUnpickler` to prevent remote code execution when loading BM25 indices
    - Only allows safe built-in types (dict, list, tuple, str, int, etc.)
    - Blocks arbitrary class instantiation
- **Vector Similarity Queries**: Added input validation for vector similarity query parameters
- **SSRF Protection**: Enhanced SSRF protection with inline URL validation
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
- Enhanced error handling with detailed logging across core modules

### ✅ 验证

- All affected-module tests pass (full suite now 9,300+ tests)
- mypy type checking passes for modified files
- ruff lint checks pass
- No new hardcoded secrets detected

## 🔗 相关文档

- [API 文档](API.md) — 完整 API 接口参考
- [用户指南](USER_GUIDE.md) — 快速上手与使用指南
- [架构文档](ARCHITECTURE.md) — 系统设计与架构详解
- [部署指南](DEPLOYMENT.md) — 部署与环境配置
- [项目 README](../README.md) — 返回首页
