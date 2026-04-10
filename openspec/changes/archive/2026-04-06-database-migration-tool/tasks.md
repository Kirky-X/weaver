## 1. 项目基础设施

- [x] 1.1 创建 `src/modules/migration/` 模块目录结构
- [x] 1.2 添加 `rich` 依赖到 pyproject.toml
- [x] 1.3 添加 `typer` 依赖（如未安装）
- [x] 1.4 创建 `src/core/protocols/migration.py` 定义迁移 Protocol
- [x] 1.5 创建 `src/modules/migration/models.py` 定义数据模型
- [x] 1.6 创建 `src/modules/migration/exceptions.py` 定义异常类

## 2. 类型映射系统

- [x] 2.1 创建 `src/modules/migration/type_mapping.py` 定义 PostgreSQL ↔ DuckDB 类型映射
- [x] 2.2 实现图数据库类型映射（Neo4j ↔ LadybugDB）
- [x] 2.3 实现 `convert_value()` 函数处理值转换
- [x] 2.4 编写类型映射单元测试

## 3. 关系型数据库适配器

- [x] 3.1 创建 `src/modules/migration/adapters/__init__.py`
- [x] 3.2 实现 `PostgresSource` 适配器（schema 读取、批量读取、增量读取）
- [x] 3.3 实现 `PostgresTarget` 适配器（schema 创建、批量写入、验证）
- [x] 3.4 实现 `DuckDBSource` 适配器
- [x] 3.5 实现 `DuckDBTarget` 适配器
- [x] 3.6 编写 PostgreSQL 适配器单元测试
- [x] 3.7 编写 DuckDB 适配器单元测试

## 4. 图数据库适配器

- [x] 4.1 实现 `Neo4jSource` 适配器（节点/关系 schema 读取、批量读取）
- [x] 4.2 实现 `Neo4jTarget` 适配器（节点/关系创建、批量写入）
- [x] 4.3 实现 `LadybugSource` 适配器
- [x] 4.4 实现 `LadybugTarget` 适配器
- [x] 4.5 编写 Neo4j 适配器单元测试
- [x] 4.6 编写 LadybugDB 适配器单元测试

## 5. 迁移引擎核心

- [x] 5.1 创建 `src/modules/migration/engine.py` 实现 MigrationEngine 类
- [x] 5.2 实现关系型迁移主流程 `_run_relational()`
- [x] 5.3 实现单表迁移 `_migrate_table()` 含批处理循环
- [x] 5.4 实现图迁移主流程 `_run_graph()` 含节点优先策略
- [x] 5.5 实现节点迁移 `_migrate_nodes()`
- [x] 5.6 实现关系迁移 `_migrate_rels()`
- [x] 5.7 实现增量迁移支持
- [x] 5.8 实现错误处理和重试逻辑
- [x] 5.9 实现取消迁移 `cancel()` 方法

## 6. 进度展示系统

- [x] 6.1 创建 `src/modules/migration/progress.py` 实现 MigrationProgressDisplay
- [x] 6.2 实现 Rich Panel 标题展示
- [x] 6.3 实现多任务进度条（关系型/图）
- [x] 6.4 实现节点/关系图标区分
- [x] 6.5 实现迁移摘要表格
- [x] 6.6 集成进度展示到 MigrationEngine

## 7. 自定义映射规则

- [x] 7.1 创建 `src/modules/migration/mapping_registry.py`
- [x] 7.2 实现 YAML 文件解析
- [x] 7.3 实现节点映射规则应用 `transform_node()`
- [x] 7.4 实现关系映射规则应用 `transform_rel()`
- [x] 7.5 创建示例映射文件 `config/mappings/example.yaml`
- [x] 7.6 编写映射规则单元测试

## 8. FastAPI 路由

- [x] 8.1 创建 `src/modules/migration/api/schemas.py` 定义 Pydantic 模型
- [x] 8.2 创建 `src/modules/migration/api/dependencies.py` 定义依赖注入
- [x] 8.3 创建 `src/modules/migration/api/routes.py` 定义路由
- [x] 8.4 实现 `POST /migration/relational` 启动关系型迁移
- [x] 8.5 实现 `GET /migration/relational/{task_id}/progress` 查询进度
- [x] 8.6 实现 `POST /migration/relational/{task_id}/cancel` 取消迁移
- [x] 8.7 实现 `POST /migration/graph` 启动图迁移
- [x] 8.8 实现 `GET /migration/graph/{task_id}/progress` 查询图迁移进度
- [x] 8.9 实现 `POST /migration/mappings` 上传映射规则
- [x] 8.10 实现 `GET /migration/mappings` 列出映射规则
- [x] 8.11 实现 `GET /migration/download/{task_id}` 下载迁移结果
- [x] 8.12 实现 `POST /migration/upload` 上传源数据文件
- [x] 8.13 注册路由到主应用

## 9. CLI 命令

- [x] 9.1 创建 `src/modules/migration/cli/commands.py`
- [x] 9.2 实现 `migration relational` 命令
- [x] 9.3 实现 `migration graph` 命令
- [x] 9.4 实现 `--dry-run` 预览模式
- [x] 9.5 实现 `migration status` 查询任务状态
- [x] 9.6 实现 `migration list-mappings` 列出映射规则
- [x] 9.7 注册 CLI 命令到主应用

## 10. 集成测试

- [x] 10.1 创建 `tests/modules/migration/conftest.py` 测试 fixtures
- [x] 10.2 编写 PostgreSQL → DuckDB 集成测试
- [x] 10.3 编写 DuckDB → PostgreSQL 集成测试
- [x] 10.4 编写 Neo4j → LadybugDB 集成测试
- [x] 10.5 编写 LadybugDB → Neo4j 集成测试
- [x] 10.6 编写增量迁移集成测试
- [x] 10.7 编写 API 端到端测试

## 11. 文档

- [x] 11.1 创建 `docs/migration/README.md` 快速开始指南
- [x] 11.2 创建 `docs/migration/api-reference.md` API 文档
- [x] 11.3 创建 `docs/migration/cli-reference.md` CLI 文档
- [x] 11.4 创建 `docs/migration/type-mapping.md` 类型映射参考表
- [x] 11.5 创建 `docs/migration/custom-mappings.md` 映射规则指南
- [x] 11.6 创建 `docs/migration/examples/` 示例文档