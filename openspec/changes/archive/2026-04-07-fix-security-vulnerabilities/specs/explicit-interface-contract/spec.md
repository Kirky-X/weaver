## ADDED Requirements

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