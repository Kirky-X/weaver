## Why

Weaver 项目的代码结构存在模块内聚性不足的问题：大型模块文件平铺混放（如 `modules/knowledge/graph/` 中 16 个文件 8,172 行混在一起，`core/llm/` 中 18 个文件 3,457 行平铺），导致代码导航困难、修改影响范围不可控、新成员理解成本高。同时，架构文档（ARCHITECTURE.md、API.md 等）与实际代码存在偏差，缺少 Smart LLM Router、MAGMA Memory、Intent-Aware Routing 等新特性说明，API 文档缺少新增端点，部署文档环境变量不匹配。此变更通过模块重构提升代码可维护性，并同步更新文档确保准确性。

## What Changes

### 代码重构（8个部分，按优先级 P0-P3）

**P0 - 最高优先级**:
- 提取 `modules/knowledge/graph/community` 子模块：将 10 个 community 相关文件（5,172 行）组织到 `community/` 子目录，包含 `health/` 子模块
- 更新所有导入路径（约 23 处外部引用）

**P1 - 高优先级**:
- 重组 `core/llm` 为功能域：创建 `core/`、`routing/`、`config/`、`resilience/`、`validation/`、`evaluation/` 6 个子目录
- 优化 `modules/storage`：创建 `base/` 提取公共抽象，补充 DuckDB 缺失的 repo
- 优化 `modules/ingestion`：创建 `deduplication/models.py` 和 `fetching/models.py`

**P2 - 中优先级**:
- 重组 `modules/processing/nodes` 为 5 个子目录：`extraction/`、`classification/`、`merging/`、`quality/`、`vectorization/`
- 优化 `modules/memory`：提取 `core/models.py` 纯数据模型
- 确认 `modules/knowledge/search` 结构合理性

**P3 - 低优先级**:
- 重组 `core/security`：创建 `crypto/` 和 `validation/` 子目录
- 重组 `api/endpoints`：创建 `admin/`、`graph/`、`content/` 业务域分组
- 其他小优化

### 文档更新（10 个任务）

- **ARCHITECTURE.md**: 更新依赖注入架构、多数据库策略、Event Bus、Smart LLM Router、MAGMA Memory、后台调度器
- **API.md**: 添加 `/api/v1/status`、`/api/v1/config` 端点，更新搜索端点 Intent-Aware Routing 说明
- **USER_GUIDE.md**: 添加 Intent-Aware Routing 使用示例、Output Mode 指南、实体聚合功能
- **DEPLOYMENT.md**: 修正环境变量格式、添加多数据库部署说明、删除废弃变量

### 新增内容

- 导入路径变更日志（记录所有重构前后的路径映射）
- 模块结构导航指南
- 路径验证脚本（`scripts/verify_refactor.py`）

## Capabilities

### New Capabilities

- `module-structure`: 模块化的代码组织结构，相关文件聚集在功能子目录中，支持独立理解和测试
- `import-path-consistency`: 统一的导入路径约定，通过 `__init__.py` 导出保持向后兼容（注：本次不要求向后兼容，直接更新所有引用）
- `documentation-accuracy`: 文档与代码的实时一致性，所有代码示例可直接运行

### Modified Capabilities

<!-- 无现有功能的需求变更，仅为代码组织和文档更新 -->

## Impact

### 受影响代码
- **模块导入路径**: 约 150+ 个导入语句需要更新（包括 src/、tests/ 目录）
- **测试文件**: 约 20+ 个测试文件需要更新导入路径
- **__init__.py 导出**: 约 15 个模块的导出声明需要更新

### 受影响文档
- `docs/ARCHITECTURE.md`: 代码示例路径、目录结构图
- `docs/API.md`: 端点说明（无路径依赖）
- `docs/USER_GUIDE.md`: 使用示例（无路径依赖）
- `docs/DEPLOYMENT.md`: 环境变量说明（无路径依赖）

### 开发工具
- IDE 自动补全路径变更
- GitNexus 索引需要重新分析
- 路径验证脚本需要运行

### 风险
- 导入路径遗漏导致 ImportError（通过 GitNexus impact analysis 和自动化脚本缓解）
- 循环导入问题（通过保持原有依赖方向缓解）
- 测试失败（每个阶段独立运行完整测试套件）
