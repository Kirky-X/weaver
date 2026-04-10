## Context

当前系统使用 `PromptLoader` 从 `config/prompts/` 目录加载 TOML 格式的 prompt 模板，所有 prompt 在首次访问后永久缓存在内存中。

**现有架构**:
```
config/prompts/*.toml → PromptLoader → _cache: dict (永久内存) → LLMClient
```

**约束**:
- 缓存层必须使用 `CachePool` 协议，支持 Redis 或 Cashews 内存缓存
- 必须支持 PostgreSQL 和 DuckDB 两种数据库
- **无向后兼容要求**：直接替换现有实现

## Goals / Non-Goals

**Goals:**
- Prompt 模板持久化存储到数据库，支持版本历史追踪
- 版本回滚功能，可激活任意历史版本
- 可配置的缓存 TTL 和热重载机制
- REST API 管理 prompt（查询、更新、版本管理、文件导入导出）
- 启动时从初始数据导入（一次性迁移）

**Non-Goals:**
- 不实现 prompt 模板语法解析或变量替换（保持现有 TOML 格式）
- 不实现 prompt A/B 测试或灰度发布
- 不实现跨环境 prompt 同步
- 不保留原有文件系统 loader

## Decisions

### 1. 数据库表设计

**决策**: 单表存储所有版本，使用 `is_active` 标记当前激活版本

```sql
CREATE TABLE prompt_templates (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    version         VARCHAR(20) NOT NULL,
    prompt_type     VARCHAR(20) NOT NULL,
    content         TEXT NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    change_reason   TEXT,
    metadata        JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    created_by      VARCHAR(100) DEFAULT 'system',

    CONSTRAINT uq_prompt_name_version UNIQUE(name, version)
);

CREATE INDEX idx_prompt_templates_name ON prompt_templates(name);
CREATE INDEX idx_prompt_templates_name_active ON prompt_templates(name, is_active) WHERE is_active = TRUE;
CREATE INDEX idx_prompt_templates_created_at ON prompt_templates(created_at DESC);
```

**备选方案**:
- ❌ 双表设计（主表+历史表）：增加查询复杂度，回滚需要跨表操作
- ✅ 单表设计：简单直观，同一查询获取所有版本

### 2. 版本号生成策略

**决策**: 语义化版本自动递增（PATCH 级别）

当前版本 `1.2.0` → 新版本 `1.2.1`

**备选方案**:
- ❌ 时间戳版本：可读性差，难以理解版本先后
- ❌ 自增整数：无法区分 major/minor/patch 变更
- ✅ 语义化版本：符合行业惯例，支持未来扩展

### 3. 缓存架构

**决策**: 使用 `CachePool` 协议，支持 Redis 或 Cashews 降级

```python
class PromptCache:
    def __init__(self, cache: CachePool, ttl: int, enabled: bool): ...

    async def get(self, name: str, prompt_type: str) -> str | None: ...
    async def set(self, name: str, prompt_type: str, content: str) -> None: ...
    async def delete(self, name: str, prompt_type: str) -> None: ...
    async def delete_all(self, name: str) -> None: ...
```

**缓存 Key 设计**:
- `prompt:{name}:{type}` - prompt 内容
- `prompt:{name}:version` - 当前版本号

**备选方案**:
- ❌ 硬编码 Redis：无法支持 Cashews 降级场景
- ✅ CachePool 协议：与现有架构一致，支持多种缓存后端

### 4. API 端点设计

**决策**: 放在 `/admin/prompts` 路径下，与现有 admin 端点一致

| 端点 | 方法 | 说明 |
|------|------|------|
| `/admin/prompts` | GET | 列出所有活跃 prompt |
| `/admin/prompts/{name}` | GET | 获取单个 prompt 详情 |
| `/admin/prompts/{name}` | PUT | 更新 prompt（创建新版本） |
| `/admin/prompts/{name}/versions` | GET | 获取版本历史 |
| `/admin/prompts/{name}/activate` | POST | 激活指定版本（回滚） |
| `/admin/prompts/{name}/reload` | POST | 热重载缓存 |
| `/admin/prompts/reload` | POST | 热重载所有缓存 |
| `/admin/prompts/import` | POST | 上传 TOML 文件导入 |
| `/admin/prompts/export` | GET | 导出为 ZIP |
| `/admin/prompts/{name}/export` | GET | 导出单个为 TOML |

### 5. 初始数据导入

**决策**: 启动时检测数据库，为空则从 `config/prompts/` 导入，导入后删除目录

**备选方案**:
- ❌ 每次启动都导入：会覆盖手动修改
- ❌ 从不导入：新部署需要手动初始化
- ✅ 空库时导入后删除：一次性迁移，彻底移除文件依赖

## Risks / Trade-offs

### 风险 1：数据库不可用时 prompt 不可用
→ **缓解**: 这是可接受的——核心业务数据也在数据库中，数据库不可用意味着系统不可用

### 风险 2：缓存与数据库不一致
→ **缓解**: 所有修改操作立即清除相关缓存，`reload` API 强制刷新

### 风险 3：版本历史过多影响性能
→ **缓解**: 配置 `max_history_versions` 自动清理旧版本，默认保留 10 个

### 风险 4：API 未授权访问
→ **缓解**: 所有 `/admin/*` 端点已要求 `verify_api_key` 认证

## Migration Plan

### 部署步骤

1. **数据库迁移**: 运行 Alembic 迁移创建 `prompt_templates` 表
2. **部署代码**: 部署新版本代码
3. **自动导入**: 首次启动时自动从 `config/prompts/` 导入 prompt 并删除目录
4. **验证**: 调用 `/admin/prompts` 验证导入成功

### 回滚策略

1. 回滚代码到上一版本
2. 数据库表可保留（不影响旧版本）或手动删除
3. **注意**: 回滚后需要重新创建 `config/prompts/` 目录和 TOML 文件

## Open Questions

无未决问题。设计方案已与用户确认：
- ✅ 缓存 TTL 可配置
- ✅ 版本历史 + 回滚功能
- ✅ 管理 API 端点
- ✅ 使用 CachePool 协议接口
- ✅ API 导入使用文件上传
- ✅ **无向后兼容**：直接替换，删除原有文件系统 loader