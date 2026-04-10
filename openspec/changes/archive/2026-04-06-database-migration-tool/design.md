## Context

Weaver 项目采用双数据库架构：关系型（PostgreSQL/DuckDB）和图数据库（Neo4j/LadybugDB），通过 Protocol 接口实现故障转移。现有代码包含：

- `RelationalPool` / `GraphPool` Protocol 定义（`src/core/db/pool_protocols.py`）
- 数据库连接池实现（PostgreSQL, DuckDB, Neo4j, LadybugDB）
- SQLAlchemy ORM 模型（`src/core/db/models.py`）
- 定时同步任务（`src/modules/scheduler/jobs.py`）

迁移工具需要复用这些基础设施，提供统一的数据迁移能力。

## Goals / Non-Goals

**Goals:**
- 统一的数据迁移引擎，支持四种数据库双向迁移
- 流式批处理，支持大规模数据（>100万行）
- Rich 进度条实时展示
- 全量 + 增量迁移模式
- FastAPI + CLI 双入口
- 自定义映射规则支持

**Non-Goals:**
- 实时 CDC（Change Data Capture）同步
- 分布式并行迁移
- 数据清洗/转换管道
- 跨版本数据库兼容性处理

## Decisions

### D1: Protocol 抽象设计

**决策**: 使用 Python Protocol 类定义 `MigrationSource` 和 `MigrationTarget` 接口，而非继承抽象类。

**理由**:
- 与现有 `RelationalPool` / `GraphPool` 模式一致
- 支持鸭子类型，适配器无需继承公共基类
- `@runtime_checkable` 便于运行时验证

**备选方案**:
- ABC 抽象基类：强制继承，灵活性较差
- 无接口定义：类型安全性差

### D2: 关系型与图迁移分离

**决策**: 为关系型和图数据库定义独立的 Protocol 集合（`MigrationSource`/`MigrationTarget` vs `GraphMigrationSource`/`GraphMigrationTarget`）。

**理由**:
- 读写模式差异大（SQL 查询 vs Cypher 查询）
- 图迁移需要节点优先策略保证引用完整性
- 类型系统更清晰，避免 Union 类型泛滥

### D3: 批处理流式设计

**决策**: 使用 offset-based 分页读取 + 批量写入，而非一次性加载全部数据。

**理由**:
- 内存可控，支持大规模数据
- 增量读取使用 keyset pagination（`WHERE key > last_value`），避免 OFFSET 大偏移性能问题
- 每批在事务内执行，失败可回滚当前批次

**备选方案**:
- 游标流式读取：需要长事务，连接占用时间长
- 全量内存加载：仅适用于小数据集

### D4: 进度展示方案

**决策**: 使用 Rich 库而非 tqdm。

**理由**:
- Rich 提供更丰富的 UI 组件（Panel、Table、Spinner）
- 支持彩色进度条和图标
- 与 Typer CLI 集成良好

**备选方案**:
- tqdm：功能较基础
- 自定义实现：工作量大

### D5: 映射规则格式

**决策**: 使用 YAML 格式定义自定义映射规则。

**理由**:
- 可读性好，支持注释
- Python 原生支持（`yaml.safe_load`）
- 与现有配置风格一致

## Risks / Trade-offs

### R1: 大数据量内存溢出

**风险**: 单批次数据过大导致内存溢出。

**缓解**:
- 默认 batch_size=5000，可配置
- 每批处理完立即释放内存
- 提供预估功能，提示用户调整批大小

### R2: 类型转换数据丢失

**风险**: PostgreSQL → DuckDB 类型映射可能丢失精度或格式。

**缓解**:
- 完整的类型映射表，记录降级规则
- 类型转换失败时记录错误行，继续处理（可配置严格模式）
- 提供 `--dry-run` 预览模式

### R3: 图迁移引用完整性

**风险**: 关系引用的节点尚未迁移，导致写入失败。

**缓解**:
- 强制节点优先迁移策略
- 验证目标节点存在后再写入关系
- 孤立节点检测和报告

### R4: 网络中断

**风险**: 远程数据库连接中断导致迁移失败。

**缓解**:
- 指数退避重试机制（最多 3 次）
- 记录已迁移偏移量，支持断点续传
- 提供 cancel 优雅停止

### R5: SQL 注入

**风险**: 动态构建 SQL 查询可能引入注入风险。

**缓解**:
- 表名通过 schema 读取白名单校验
- 参数使用绑定变量（`$1`, `:param`）
- 禁止用户直接输入 SQL 片段