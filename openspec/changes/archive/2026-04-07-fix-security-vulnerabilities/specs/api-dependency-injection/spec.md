## ADDED Requirements

### Requirement: No global variables in API endpoints

API endpoint 文件 MUST NOT 定义全局状态变量（如 `_pool`, `_client`, `_service`）。

#### Scenario: graph.py removes global pool

- **WHEN** 查看 `src/api/endpoints/graph.py`
- **THEN** 不存在 `_pg_pool` 或类似的全局连接池变量
- **AND** 连接池通过 FastAPI Depends 获取

#### Scenario: pipeline.py removes background task global

- **WHEN** 查看 `src/api/endpoints/pipeline.py`
- **THEN** 后台任务通过 TaskRegistry 追踪而非全局变量
- **AND** `asyncio.create_task` 返回值被注册到 registry

### Requirement: Dependency injection for container access

API endpoint MUST 通过依赖注入获取容器实例，而非访问全局单例。

#### Scenario: Container injection via Depends

- **WHEN** API endpoint 需要访问数据库或服务
- **THEN** 使用 `Depends(get_container)` 或类似依赖注入函数
- **AND** 参数类型为 Protocol 接口而非具体实现类

#### Scenario: health.py uses public interface

- **WHEN** 查看 `src/api/endpoints/health.py` 的容器状态检查
- **THEN** 不访问 `_postgres`, `_neo4j`, `_redis` 等私有属性
- **AND** 使用容器提供的 `is_healthy()` 公共方法

### Requirement: Task tracking for background operations

后台启动的异步任务 MUST 被追踪，允许状态查询和取消。

#### Scenario: Background task registration

- **WHEN** 使用 `asyncio.create_task()` 启动后台任务
- **THEN** 任务 ID 被注册到 `TaskRegistry`
- **AND** 可通过任务 ID 查询状态和进度

#### Scenario: Task cancellation support

- **WHEN** 用户请求取消后台任务
- **THEN** 系统可通过 TaskRegistry 找到并取消任务
- **AND** 返回取消成功或任务已完成状态

### Requirement: Service layer for cross-module calls

跨模块调用 MUST 通过服务层接口，禁止直接访问其他模块内部方法。

#### Scenario: repair_articles.py uses service interface

- **WHEN** 查看 `src/modules/management/commands/repair_articles.py`
- **THEN** 不直接调用 `pipeline._phase3_per_article()`
- **AND** 通过 `PipelineService` 接口调用公共方法

#### Scenario: PipelineService protocol definition

- **WHEN** 查看 `src/core/protocols/services.py`
- **THEN** `PipelineService` Protocol 定义了 `run_phase3_per_article()` 方法
- **AND** 方法签名包含必要的输入输出类型