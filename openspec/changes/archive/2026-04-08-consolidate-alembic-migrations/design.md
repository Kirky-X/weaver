## Context

当前迁移历史：

```
01_initial ─→ 02_llm_failures ─→ 03_remove_article_entities ─→ 04_source_credibility
                                                                    ↓
              ┌─────────────────────┬──────────────────────────────┤
              ↓                     ↓                              ↓
    05_drop_orphan_tables  05_pending_sync  f23755e6c748 (relation_types)
              │                     │              ↓
              │                     │       06_llm_usage
              └─────────────────────┴──────────────┘
                              ↓
                    f26c1d1ee6c748 (空合并)
                              ↓
                    07_prompt_templates
                              ↓
                    ac3bc88e1858 (重命名列)
```

**约束**：
- 生产数据库有 368,874 条数据
- 无法删除重建数据库
- 需保持最终 schema 不变

## Goals / Non-Goals

**Goals:**
- 将 11 个迁移文件合并为 1 个初始迁移
- 保留最终 schema（13 表 + 4 类型 + 向量索引）
- 移除废弃操作（已删除的表创建/删除）
- 生产环境无缝迁移（仅 stamp）

**Non-Goals:**
- 不修改表结构或字段
- 不添加新功能
- 不保留中间版本回滚能力

## Decisions

### 1. 采用完全替换方案

**选择**: 删除所有旧迁移，创建单一初始迁移

**备选方案**:
| 方案 | 优点 | 缺点 |
|------|------|------|
| 保留历史 + 新压缩迁移 | 兼容性最好 | 文件数量不减 |
| 分批压缩（如每季度） | 保留部分历史 | 复杂度高 |

**理由**: 项目早期，历史不长（2 周），一次性清理最干净

### 2. 使用 `alembic stamp` 而非执行迁移

**选择**: 生产环境执行 `alembic stamp 01_initial`

**理由**:
- 数据库已处于最终状态
- 无需执行实际迁移操作
- 避免无意义操作带来的风险

### 3. 保留完整 downgrade

**选择**: `downgrade()` 函数删除所有表和类型

**理由**: 保留回滚到初始状态的能力（虽然丢失中间状态）

## Risks / Trade-offs

| 风险 | 缓解措施 |
|------|----------|
| 生产 stamp 失败 | 先备份数据库，验证 stamp 后再删除旧迁移 |
| 新迁移与实际 schema 不匹配 | 新迁移从现有 schema 反向工程，逐步验证 |
| CI 流水线依赖旧迁移版本 | 更新 CI 配置，确保使用新版本 |

**Trade-off**:
- ❌ 丢失中间版本回滚能力
- ✅ 新部署简化为一步
- ✅ 迁移历史清晰可读

## Migration Plan

### 步骤

1. **创建新迁移文件**
   - 基于当前数据库 schema 生成 `01_initial.py`
   - 验证 `upgrade()` 与现有 schema 一致

2. **验证测试环境**
   - 在测试数据库执行 `alembic upgrade head`
   - 验证所有表、索引、约束正确创建

3. **生产环境标记**
   ```bash
   # 备份数据库
   pg_dump weaver > backup_$(date +%Y%m%d).sql

   # 标记版本（不执行迁移）
   alembic stamp 01_initial
   ```

4. **清理旧迁移**
   - 删除 `src/alembic/versions/` 下除 `01_initial.py` 外的所有文件

### 回滚策略

如果生产 stamp 后发现问题：
1. 恢复旧迁移文件（git revert）
2. `alembic stamp ac3bc88e1858`（回到原版本）

## Open Questions

无。方案明确，可直接实施。