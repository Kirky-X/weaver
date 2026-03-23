# Scripts 目录清理分析报告

**分析日期**: 2026-03-23
**分析范围**: scripts/ 目录下的所有脚本

---

## 📊 执行摘要

scripts/ 目录包含 12 个脚本（7个 Python，5个 Shell），其中：
- **5 个脚本应保留**（高价值，有文档引用）
- **7 个脚本应删除**（已失效、有风险或功能重复）

**预计节省**: ~1000 行代码

---

## 🔍 详细分析

### 1. 回滚脚本的严重问题 ⚠️⚠️⚠️

#### rollback_health_endpoint.sh - **破坏性极高**

**问题**：
- 硬编码行号假设健康检查在 368-374 行
- 实际健康检查在 405 行（代码已变更）
- 第 368-374 行实际是 CORS 配置

**执行后果**：
```bash
# 脚本会注释错误的代码
第 368-374 行：CORS 配置 → 被注释 → 跨域功能失效
第 405 行：健康检查端点 → 仍然存在 → 回滚失败
```

**结论**：脚本已完全失效，执行将破坏系统功能

---

#### rollback_saga_pattern.sh - **目标功能不存在**

**发现**：
- `persist_batch_saga()` 方法存在（第 271 行）
- 但**从未被调用**
- 系统实际使用 `_persist_batch()` (简单 bulk_upsert)

**结论**：Saga 模式从未启用，回滚脚本针对不存在的功能

**架构分析**：
```
batch_merger.py:
  └─ persist_batch_saga()      定义但未使用
      └─ 两阶段提交 + 补偿事务

graph.py:
  └─ _persist_batch()          实际使用
      └─ 简单 bulk_upsert（无事务保证）
```

---

#### rollback_hnsw_index.sh - **版本信息错误**

**问题**：
- 脚本检查迁移版本 `c619ab9ba95a`
- 该版本在项目中不存在
- HNSW 索引在初始迁移中创建

**结论**：脚本基于错误的版本信息

---

#### rollback_saga_pattern.sh - **额外问题**

**Python 脚本内部硬编码**：
```python
file_path = "/home/dev/projects/weaver/src/modules/pipeline/nodes/batch_merger.py"
```
在其他机器上无法运行。

---

### 2. 硬编码问题汇总

| 脚本 | 硬编码类型 | 严重程度 |
|------|-----------|---------|
| `test_cctv_source.py` | 绝对路径 `/home/dev/...` | 🔴 致命 |
| `test_cctv_source.py` | 数据库连接 `localhost:5432` | 🔴 高 |
| `test_cctv_source.py` | 源ID `cctvyscj` | 🟡 中 |
| `rollback/*.sh` (4个) | 项目根路径 | 🔴 高 |
| `test_full_pipeline.py` | 默认URL (可覆盖) | 🟢 低 |

---

### 3. 功能重叠分析

#### Pipeline 测试脚本重复

```
run_full_pipeline.py (490行)
├─ 直接调用 Pipeline 代码
├─ RSS 抓取 → 处理 → 存储
├─ 输出到控制台
└─ 最后更新：较早

test_full_pipeline.py (491行)  ← 更完善
├─ 通过 HTTP API 测试
├─ 注册源 → 触发 Pipeline → 轮询状态 → 验证 DB
├─ 完整的 E2E 测试流程
└─ 最后更新：2026-03-21（整合优化）
```

**结论**：`test_full_pipeline.py` 是优化版本，应保留。

---

### 4. CI/CD 与文档依赖

#### CI/CD 依赖
```yaml
.github/workflows/tests.yml:
  └─ 不引用任何 scripts/ 脚本
  └─ 完全独立运行 pytest
```
✅ 可以安全删除脚本

#### 文档依赖
```
docs/36kr_pipeline_test.md:
  ├─ validate_environment.py ✅ 保留
  └─ test_full_pipeline.py ✅ 保留

docs/deployment/database-migration-plan.md:
  ├─ rollback_hnsw_index.sh ❌ 引用已失效脚本
  └─ benchmark/vector_search_benchmark.py ❌ 脚本不存在
```
⚠️ 需要更新文档移除失效引用

---

## 📋 清理建议

### ✅ 应保留的脚本 (5个)

| 脚本 | 价值 | 使用频率 | 维护成本 |
|------|------|---------|---------|
| `validate_environment.py` | ⭐⭐⭐⭐⭐ | 高（文档引用）| 低 |
| `test_full_pipeline.py` | ⭐⭐⭐⭐ | 中（文档引用）| 中 |
| `run_performance_tests.py` | ⭐⭐⭐ | 低（性能基准）| 低 |
| `build_nuitka.py` | ⭐⭐ | 极低（生产构建）| 中 |
| `reset_test_env.sh` | ⭐⭐⭐⭐ | 中（Docker环境）| 低 |

---

### ❌ 应删除的脚本 (7个)

#### 高风险删除（回滚脚本）

```
scripts/rollback/
├── rollback_health_endpoint.sh   破坏性：极高
├── rollback_saga_pattern.sh      目标功能不存在
├── rollback_hnsw_index.sh        版本信息错误
└── master_rollback.sh            协调失效脚本
```

**理由**：
1. 硬编码行号，代码变更后失效
2. 基于错误假设（功能不存在）
3. 无测试验证，无法保证正确性
4. 正确的回滚方式：`git revert <commit>`

---

#### 低价值删除

```
scripts/
├── run_full_pipeline.py          功能被 test_full_pipeline.py 覆盖
├── test_cctv_source.py           硬编码严重，功能单一
└── test_stealth.py               应移至 tests/manual/
```

**详细说明**：

**test_cctv_source.py 问题**：
```python
# 硬编码路径 - 在其他机器无法运行
sys.path.insert(0, "/home/dev/projects/weaver/src")

# 硬编码数据库连接
pool = PostgresPool("postgresql+asyncpg://postgres:postgres@localhost:5432/weaver")

# 硬编码测试源
source_id = "cctvyscj"
```

**test_stealth.py 建议**：
- 功能有价值（测试 Playwright Stealth 反检测）
- 但位置错误：应该在 `tests/manual/` 目录
- 生产代码使用了 stealth 功能（配置完整）

---

## 🎯 执行计划

### Phase 1: 准备工作

```bash
# 1. 创建备份分支
git checkout -b chore/cleanup-scripts

# 2. 检查是否有未提交的更改
git status scripts/
```

---

### Phase 2: 移动 test_stealth.py

```bash
# 创建目录
mkdir -p tests/manual

# 移动文件
git mv scripts/test_stealth.py tests/manual/test_stealth.py
```

---

### Phase 3: 删除脚本

```bash
# 删除回滚脚本（4个）
git rm scripts/rollback/rollback_health_endpoint.sh
git rm scripts/rollback/rollback_saga_pattern.sh
git rm scripts/rollback/rollback_hnsw_index.sh
git rm scripts/rollback/master_rollback.sh
git rm -r scripts/rollback/

# 删除重复脚本
git rm scripts/run_full_pipeline.py

# 删除硬编码脚本
git rm scripts/test_cctv_source.py
```

---

### Phase 4: 更新文档

```bash
# 编辑 docs/deployment/database-migration-plan.md
# 移除回滚脚本引用
# 移除不存在的 benchmark 脚本引用
```

**具体修改**：
- 删除所有 `rollback_hnsw_index.sh` 相关的命令示例
- 删除 `vector_search_benchmark.py` 引用
- 添加注释：推荐使用 `git revert` 进行回滚

---

### Phase 5: 验证清理

```bash
# 1. 运行测试
uv run pytest tests/unit/ -v

# 2. 检查文档引用
grep -r "scripts/" docs/ README.md

# 3. 确认删除
git status
```

---

## 📈 清理后收益

### 代码量减少
```
删除文件：7 个
删除代码行数：~1000 行
减少维护负担：高
```

### 风险降低
```
✅ 移除破坏性脚本
✅ 移除硬编码脚本
✅ 移除重复功能
```

### 项目结构优化
```
scripts/
├── validate_environment.py     ✅ 环境验证
├── test_full_pipeline.py       ✅ E2E 测试
├── run_performance_tests.py    ✅ 性能测试
├── build_nuitka.py             ✅ 生产构建
└── reset_test_env.sh           ✅ Docker 环境

tests/manual/
└── test_stealth.py             ✅ 手动测试工具
```

---

## ⚠️ 注意事项

### 1. 回滚脚本删除不会影响数据安全

**原因**：
- 脚本已失效（硬编码行号错误）
- 正确的回滚方式是 Git 操作
- 数据库迁移有 Alembic 管理

### 2. 文档更新需要同步

**需要修改的文档**：
- `docs/deployment/database-migration-plan.md`

**修改内容**：
- 移除回滚脚本引用
- 推荐使用 `git revert` 或 Alembic downgrade

### 3. 团队沟通

**建议通知团队**：
- 回滚脚本已失效，不推荐使用
- 推荐使用 Git 回滚或 Alembic 迁移
- 新增 `tests/manual/` 目录用于手动测试脚本

---

## 📝 后续建议

### 1. 脚本质量标准

未来添加脚本应满足：
- ✅ 无硬编码路径
- ✅ 参数可配置
- ✅ 有测试覆盖
- ✅ 有文档说明

### 2. 定期审查

建议每季度审查 `scripts/` 目录：
- 移除不再使用的脚本
- 更新过时的脚本
- 合并重复功能

### 3. 文档同步机制

建立脚本删除检查清单：
- [ ] 检查 CI/CD 依赖
- [ ] 检查文档引用
- [ ] 检查代码引用
- [ ] 更新相关文档

---

## 结论

scripts/ 目录清理的收益明显大于风险：

**收益**：
- 移除 7 个失效/重复脚本
- 减少维护负担
- 降低误用风险

**风险**：
- 无（删除的脚本已失效或无依赖）

**建议立即执行清理计划。**