## Why

当前系统的 prompt 模板通过 `PromptLoader` 从 TOML 文件加载并永久缓存在内存中，存在以下问题：

1. **无法动态修改**：修改 prompt 需要修改文件并重启应用
2. **无版本追踪**：无法追溯 prompt 的变更历史，不利于调试和回滚
3. **缓存不透明**：所有 prompt 永久占用内存，无法清理或刷新
4. **无管理接口**：运维无法通过 API 查看或管理 prompt

引入数据库驱动的 prompt 管理模块，支持版本控制、热重载和管理 API。

## What Changes

- **BREAKING** 删除现有 `PromptLoader` 文件系统加载器
- 新增 `PromptTemplate` 数据库模型存储 prompt 模板
- 新增 `PromptRepository` 提供 prompt 的 CRUD 操作
- 新增 `PromptCache` 缓存层，使用 `CachePool` 协议
- 新增 `DbPromptLoader` 实现数据库驱动的 prompt 加载
- 新增 `/admin/prompts/*` API 端点支持 prompt 管理
- 扩展 `PromptSettings` 配置项（缓存 TTL、版本历史等）

## Capabilities

### New Capabilities

- `prompt-storage`: 数据库存储 prompt 模板，支持版本历史、回滚功能
- `prompt-cache`: 内存缓存层，TTL 可配置，支持热重载
- `prompt-api`: REST API 管理接口，支持查询、更新、版本管理、文件导入导出

### Modified Capabilities

无现有 capability 需要修改。

## Impact

**删除文件**:
- `src/core/prompt/loader.py` - 删除原有文件系统 loader

**新增文件**:
- `src/core/prompt/models.py` - PromptTemplate ORM 模型
- `src/core/prompt/repo.py` - PromptRepository 数据库操作
- `src/core/prompt/cache.py` - PromptCache 缓存封装
- `src/core/prompt/db_loader.py` - DbPromptLoader 主实现
- `src/api/endpoints/prompts.py` - 管理 API 端点
- `src/api/schemas/prompt.py` - API 请求/响应模型

**修改文件**:
- `src/core/prompt/__init__.py` - 导出 DbPromptLoader
- `src/core/db/models.py` - 添加 PromptTemplate 模型
- `src/config/settings.py` - 扩展 PromptSettings
- `src/api/endpoints/__init__.py` - 注册 prompts router
- `src/container.py` - 替换 prompt_loader() 实现
- `src/core/llm/client.py` - 更新 PromptLoader 类型引用

**数据库迁移**:
- 新增 `prompt_templates` 表

**破坏性变更**:
- 删除 `config/prompts/` 目录下的 TOML 文件（数据已迁移到数据库）
- `PromptLoader` 类被 `DbPromptLoader` 完全替换