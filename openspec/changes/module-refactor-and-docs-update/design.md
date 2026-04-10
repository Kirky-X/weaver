## Context

Weaver 项目当前代码结构存在以下问题：
- `modules/knowledge/graph/` 中 16 个文件（8,172 行）平铺混放，community 相关功能分散
- `core/llm/` 中 18 个文件（3,457 行）平铺，功能域边界不清晰
- `modules/processing/nodes/` 中 13 个节点文件混放，难以查找
- 文档与实际代码存在偏差，导入路径、API 端点、环境变量不准确

**约束条件**:
- 不需要向后兼容（用户明确要求）
- 必须使用 Git Worktree 隔离重构工作
- 每个重构阶段必须通过完整测试套件
- 文档更新必须在重构完成后进行（严格串行策略）

## Goals / Non-Goals

**Goals:**
- 将大型模块按功能域分组到子目录，提升代码组织性
- 单文件控制在 500 行以内，子模块控制在 2,000 行以内
- 更新所有文档使其与实际代码完全一致
- 所有代码示例可直接复制运行
- 建立路径验证机制确保文档与代码同步

**Non-Goals:**
- 不改变任何业务逻辑（仅调整文件位置和导入路径）
- 不添加新功能（仅为代码组织和文档更新）
- 不提供向后兼容的导入路径（直接更新所有引用）
- 不优化性能或修复 bug（除非由重构直接引入）

## Decisions

### Decision 1: 严格串行策略（先重构后文档）

**选择**: 先完成所有代码重构（Week 1-3），再更新所有文档（Week 4）

**理由**:
- 零冲突风险：文档始终引用正确的最终路径
- 简化协调：无需在重构中途更新文档
- 符合项目规则：分支开发与测试合并规范要求独立验证

**替代方案**:
- 分阶段并行（方案B）：协调复杂度高，PR 依赖管理困难
- 双轨独立（方案C）：最高冲突风险，需要路径映射文档

### Decision 2: 不使用向后兼容导出

**选择**: 直接更新所有导入路径，不在 `__init__.py` 中保留旧路径的 re-export

**理由**:
- 用户明确要求"不需要任何向后兼容"
- 减少维护负担，避免双重导入路径混淆
- 内部项目，可以一次性更新所有引用

**替代方案**:
- 在 `__init__.py` 中同时导出新旧路径（增加维护成本）
- 分阶段迁移（延长重构周期）

### Decision 3: 使用 Git Worktree 隔离

**选择**: 创建独立 worktree `../weaver-refactor` 进行所有重构

**理由**:
- 不影响主分支的日常工作
- 可以随时回滚到干净状态
- 符合项目规则中的 Git Worktree 强制使用要求

**工作流程**:
```bash
git worktree add ../weaver-refactor refactor/restructure
cd ../weaver-refactor
# 进行重构...
cd /home/dev/projects/weaver
git merge refactor/restructure
git worktree remove ../weaver-refactor
```

### Decision 4: 按功能域分组而非按文件类型

**选择**: `core/llm/routing/` 包含所有路由相关文件（smart_router.py、model_selector.py、router.py）

**理由**:
- 功能内聚性更高，修改路由逻辑时只需关注一个目录
- 符合"相关文件聚集"原则
- 便于未来微服务拆分（路由可作为独立服务）

**替代方案**:
- 按文件类型分组（所有 models.py 放一起）：跨功能查找困难

### Decision 5: 自动化路径验证

**选择**: 创建 `scripts/verify_refactor.py` 脚本自动检查导入路径和文档路径

**理由**:
- 人工检查容易遗漏
- 可集成到 CI/CD 流程
- 提供即时的反馈循环

**验证内容**:
- 关键导入是否有效（exec 测试）
- 文档中的代码路径是否存在（Path.exists 测试）
- GitNexus impact analysis 验证影响范围

## Risks / Trade-offs

### Risk 1: 导入路径遗漏导致 ImportError
**概率**: 中 | **影响**: 高

**缓解措施**:
- 使用 GitNexus impact analysis 全面扫描引用
- 运行 `scripts/verify_refactor.py` 自动化验证
- 每个阶段完成后运行完整测试套件
- 使用 grep 全面搜索所有引用路径

### Risk 2: 循环导入问题
**概率**: 低 | **影响**: 高

**缓解措施**:
- 保持原有依赖方向，不改变调用关系
- 使用 TYPE_CHECKING 和字符串类型注解打破循环
- 在子模块 `__init__.py` 中使用懒加载

### Risk 3: 测试文件更新不完整
**概率**: 中 | **影响**: 中

**缓解措施**:
- 使用 grep 搜索所有 `from modules.xxx` 和 `from core.xxx`
- 运行完整测试套件 `pytest tests/ -v`
- 使用 GitNexus detect_changes 验证影响范围

### Risk 4: 文档更新遗漏
**概率**: 低 | **影响**: 中

**缓解措施**:
- 维护路径变更清单（temp/path_changes.yaml）
- 运行路径验证脚本检查文档中的代码引用
- 人工审查所有代码示例

### Trade-off 1: 重构周期较长（3周）
**接受理由**:
- 严格串行策略确保零冲突
- 分阶段验证降低风险
- 文档滞后是可接受的短期代价

### Trade-off 2: 不保留旧导入路径
**接受理由**:
- 用户明确要求
- 内部项目可一次性更新
- 减少长期维护负担

## Migration Plan

### Phase 1: 代码重构（Week 1-3）

**Week 1**: P0 + P1 重构
```bash
# 创建 worktree
git worktree add ../weaver-refactor refactor/restructure
cd ../weaver-refactor

# P0: community 子模块
mkdir -p src/modules/knowledge/graph/community/health
# 移动文件、更新导入、创建 __init__.py
pytest tests/ -v  # 验证

# P1: core/llm 重组
mkdir -p src/core/llm/{core,routing,config,resilience,validation,evaluation}
# 移动文件、更新导入
pytest tests/ -v  # 验证
```

**Week 2**: P1 + P2 重构
```bash
# P1: storage/ingestion 优化
# P2: processing/memory 重组
pytest tests/ -v  # 验证
```

**Week 3**: P2 + P3 重构
```bash
# P2: search 确认
# P3: security/endpoints 重组
pytest tests/ -v  # 验证

# 合并回主分支
cd /home/dev/projects/weaver
git merge refactor/restructure
git worktree remove ../weaver-refactor
```

### Phase 2: 文档更新（Week 4）

```bash
# 基于最终代码结构更新文档
# 任务 1-4: ARCHITECTURE.md
# 任务 5-6: API.md
# 任务 7: USER_GUIDE.md
# 任务 8-10: DEPLOYMENT.md + 全局审查

# 运行验证脚本
python scripts/verify_refactor.py
```

### Phase 3: 全局审查（Week 5）

```bash
# 完整测试
pytest tests/ -v --tb=short

# GitNexus 重新索引
npx gitnexus analyze

# 影响范围检查
npx gitnexus detect_changes --scope all
```

### Rollback Strategy

如果重构出现严重问题：
```bash
# 放弃未提交的更改
cd /home/dev/projects/weaver
git reset --hard HEAD

# 删除 worktree
git worktree remove ../weaver-refactor

# 重新开始
git worktree add ../weaver-refactor main
```

## Open Questions

无。所有设计决策已明确。
