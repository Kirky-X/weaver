## Why

当前存在 11 个 Alembic 迁移文件，包含分支合并历史，导致：
- 新部署需要顺序执行多次迁移，复杂且易出错
- 迁移历史包含已废弃的操作（创建后删除的表）
- 无法清晰看到最终 schema 全貌

项目已上线且数据库有大量生产数据，需要一个干净的起点，便于未来维护和新环境部署。

## What Changes

- **删除** 所有现有迁移文件（11 个）
- **创建** 单一 `01_initial.py`，包含最终 schema（13 个表、4 个自定义类型、向量索引）
- **移除** 中间迁移历史中的废弃操作（`article_entities` 表创建/删除、孤儿表删除）

**BREAKING**:
- 丢失所有中间版本的 `downgrade` 能力
- 生产环境需执行 `alembic stamp 01_initial` 标记版本

## Capabilities

### New Capabilities

无新功能。此为内部重构，不改变系统行为。

### Modified Capabilities

无。现有 API 和数据结构保持不变。

## Impact

### 受影响文件

- `src/alembic/versions/*.py` — 删除 11 个文件，创建 1 个文件

### 数据库

- 生产数据库：无需执行迁移，仅需 `alembic stamp`
- 新数据库：执行 `alembic upgrade head` 即可

### 下游影响

- CI/CD 流水线：无变化（迁移命令不变）
- 开发环境：`alembic downgrade` 将只支持回到初始状态