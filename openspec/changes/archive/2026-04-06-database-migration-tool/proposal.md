## Why

Weaver 项目需要在 PostgreSQL/DuckDB（关系型）和 Neo4j/LadybugDB（图数据库）之间进行数据迁移。目前缺乏统一的数据迁移工具，导致：
1. 开发/测试环境搭建时需要手动复制数据，效率低且易出错
2. 数据库故障转移后无法方便地同步数据
3. 大规模数据迁移（>100万行）缺乏可靠的批处理机制

## What Changes

- 新增统一的数据迁移模块 `src/modules/migration/`
- 支持四种数据库之间的双向迁移：
  - PostgreSQL ↔ DuckDB（关系型）
  - Neo4j ↔ LadybugDB（图数据库）
- 提供流式批处理引擎，支持大规模数据迁移
- 实现 Rich 进度条实时展示迁移进度
- 支持全量迁移和增量迁移（基于时间戳或 ID）
- 提供自定义映射规则（YAML 配置）
- FastAPI 路由 + Typer CLI 双入口
- 支持文件上传/下载（DuckDB/LadybugDB 文件）

## Capabilities

### New Capabilities

- `relational-migration`: PostgreSQL ↔ DuckDB 关系型数据迁移，包括表结构读取、数据类型转换、批量读写、增量同步
- `graph-migration`: Neo4j ↔ LadybugDB 图数据迁移，包括节点/关系模式读取、节点优先迁移策略、引用完整性保证
- `migration-progress`: 迁移进度跟踪与展示，使用 Rich 进度条，支持 API 查询
- `migration-mapping`: 自定义映射规则，支持节点/关系的属性映射和默认值

### Modified Capabilities

（无现有能力需要修改）

## Impact

### 新增代码

- `src/modules/migration/` - 迁移模块（约 1500-2000 行）
- `src/core/protocols/migration.py` - 迁移 Protocol 定义
- `tests/modules/migration/` - 测试代码

### 依赖变更

- 新增依赖：`rich`（进度条展示）
- 新增依赖：`typer`（CLI，如项目未安装）

### API 变更

- 新增路由 `/api/migration/*`
- 新增 CLI 命令 `weaver migration`

### 配置变更

- 新增配置目录 `config/mappings/` 用于存放映射规则文件