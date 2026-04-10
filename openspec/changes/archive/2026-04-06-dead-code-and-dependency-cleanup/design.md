## Context

基于 2026-04-06 的报告与代码交叉验证分析：

**当前状态**:
- `TemporalParser` 在 `IntentRouter` 中实例化但从未被调用
- `flashrank` 依赖被注释但代码保留，实际上 FlashrankReranker 是可选增强功能
- `langchain` 系列依赖被注释而非删除，代码中已无任何导入

**约束**:
- 必须保持 HybridSearchEngine 的优雅降级机制
- 不能破坏现有的搜索功能
- 保持向后兼容（API 无变更）

## Goals / Non-Goals

**Goals:**
- 删除 TemporalParser 相关代码和目录
- 将 flashrank 移至可选依赖，保持功能可用性
- 彻底移除 langchain 系列依赖声明
- 清理构建配置中的遗留条目

**Non-Goals:**
- 不修改 HybridSearchEngine 的核心逻辑
- 不删除 FlashrankReranker/MMRReranker 代码（它们是可选增强功能）
- 不修改任何 API 端点

## Decisions

### 决策 1: TemporalParser 删除方式

**选择**: 完整删除 `temporal/` 目录

**理由**:
- `self._temporal` 只在 `IntentRouter.__init__` 赋值，所有路由方法中均无调用
- 与 MAGMA memory 模块的时序图功能重叠
- 无外部依赖，删除不影响其他模块

**替代方案**:
- 保留代码但添加 `# TODO` 标记 → 拒绝：结构性死代码应彻底清理

### 决策 2: flashrank 依赖处理

**选择**: 移至 `[project.optional-dependencies]` 作为 `search-enhancement` 组

**理由**:
- FlashrankReranker 是可选增强功能，有优雅降级机制
- 用户可选择是否安装 reranking 能力
- 减少默认安装的依赖数量

**替代方案**:
- 完全删除依赖 → 拒绝：这会破坏可选功能
- 保留在主依赖中 → 拒绝：对于可选功能不够精确

### 决策 3: langchain 依赖处理

**选择**: 彻底删除依赖声明（不是注释）

**理由**:
- 代码中已无任何 langchain 导入
- 项目使用 litellm 作为 LLM 统一接口
- 注释保留造成混淆，不如彻底删除

## Risks / Trade-offs

| 风险 | 影响 | 缓解措施 |
|-----|------|---------|
| TemporalParser 删除后 WHEN 意图无时序处理 | 低：当前代码未使用该功能 | 确认 WHEN 意图路由方法无依赖 |
| flashrank 移至可选依赖后安装缺失 | 低：已有优雅降级机制 | 文档说明如何安装可选依赖 |
| langchain 彻底删除后难以恢复 | 低：git 历史可恢复 | 无需缓解，可随时重新添加 |

## Migration Plan

1. 删除 `temporal/` 目录
2. 更新 `IntentRouter` 移除 `_temporal` 属性
3. 更新 `pyproject.toml`：
   - 删除注释的 langchain 依赖行
   - 添加 `[project.optional-dependencies]` 的 `search-enhancement` 组
4. 更新 `build_nuitka.py` 删除已注释的条目
5. 运行测试验证无回归
6. 提交更改