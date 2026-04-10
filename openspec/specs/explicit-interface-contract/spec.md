## ADDED Requirements

### Requirement: API endpoint pool type annotations

API 端点中的数据库池类型注解 MUST 使用 Protocol 类型。

#### Scenario: graph.py uses RelationalPool type
- **WHEN** 查看 `src/api/endpoints/graph.py` 中的 `_pg_pool` 变量声明
- **THEN** 类型注解为 `RelationalPool | None`（而非 `PostgresPool | None`）

#### Scenario: graph.py setter uses Protocol type
- **WHEN** 查看 `set_postgres_pool` 函数（或重命名后的 `set_relational_pool`）
- **THEN** 参数类型为 `RelationalPool`（而非 `PostgresPool`）

#### Scenario: DuckDB pool accepted by setter
- **WHEN** 传入 `DuckDBPool` 实例
- **THEN** 类型检查通过
- **AND** 变量被正确设置

### Requirement: API endpoint function signatures

API 端点函数签名 MUST 使用依赖注入获取 Protocol 类型的实例。

#### Scenario: Endpoint uses Depends for pool
- **WHEN** 端点需要关系型数据库连接
- **THEN** 使用 `Depends(get_relational_pool)` 而非硬编码 `PostgresPool`

#### Scenario: Endpoint uses Depends for graph pool
- **WHEN** 端点需要图数据库连接
- **THEN** 使用 `Depends(get_neo4j_pool)` （返回 `GraphPool` Protocol）

### Requirement: Service layer Protocol definitions

跨模块服务接口 MUST 定义为 Protocol，放在 `src/core/protocols/services.py`。

#### Scenario: PipelineService protocol exists

- **WHEN** 查看 `src/core/protocols/services.py`
- **THEN** 存在 `PipelineService` Protocol 定义
- **AND** 包含 `run_phase3_per_article()` 方法签名

#### Scenario: Service protocol import from central location

- **WHEN** 需要使用服务接口
- **THEN** 可通过 `from core.protocols import PipelineService` 导入
- **AND** 类型检查工具可正确验证实现

### Requirement: Service implementation registration

服务实现 MUST 在容器启动时注册到服务注册表。

#### Scenario: Service registration at startup

- **WHEN** 容器初始化完成
- **THEN** `PipelineService` 的具体实现已注册
- **AND** 可通过 `container.get_service(PipelineService)` 获取

#### Scenario: Service injection in commands

- **WHEN** management command 需要调用 pipeline 服务
- **THEN** 通过构造函数注入 `PipelineService`
- **AND** 参数类型为 Protocol 而非具体实现类