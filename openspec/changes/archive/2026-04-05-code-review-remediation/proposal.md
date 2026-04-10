## Why

Weaver 项目代码审查发现多个架构、性能和业务逻辑问题需要系统性修复。主要包括：
- **架构债务**: `container.py` 过大(1190行)，29个缓存属性，职责过重，难以维护
- **性能瓶颈**: Embedding 缓存 N+1 循环 GET（Neo4j 批量写入已解决）
- **业务逻辑风险**: 降级数据字段已定义但未填充

这些问题影响系统可维护性、性能和数据一致性，需要在迭代中逐步解决。

## What Changes

### 架构优化
- 拆分 `container.py` 为 core/repos/scheduler/events 四个模块
- 消除 Repository 层对业务模型的依赖 (`ArticleRepo` → `PipelineState`)
- 统一两套熔断器实现到 `pybreaker`

### 性能优化
- ~~实现 Neo4j 批量写入接口 (`write_batch`)~~ ✅ **已解决**
- Embedding 缓存使用 Redis `MGET` 批量获取
- GlobalSearch 社区实体查询合并为单次 UNWIND
- `HostRateLimiter` 迁移到 `aiolimiter`（部分：`core/llm/pool.py` 已使用，`fetching/rate_limiter.py` 待迁移）

### 业务逻辑修复
- 为 LLM 降级数据填充 `degraded_fields` 字段（字段已定义，需在 fallback 时填充）
- 修复 `aggregate_usage_data()` 9层嵌套问题
- 拆分 `persist_batch_saga()` 为独立阶段方法
- 添加 Redis 故障 fallback 到 DB 查询（基础降级已存在，需添加健康检查探测）

### 代码质量
- 提取魔法数字为常量 (`DEFAULT_BATCH_SIZE`, `DEFAULT_TIMEOUT_SECONDS`)
- 统一错误消息格式，避免暴露内部服务名
- 规划 deprecated 接口移除时间线
- 重构过长函数（全项目 200 个 >50 行函数）和过深嵌套（22 个 >4 层嵌套）

## Capabilities

### New Capabilities
- ~~`batch-neo4j-writer`: Neo4j 批量写入能力~~ ✅ **已实现**
- `degraded-data-tracking`: 降级数据追踪能力（字段定义完成，填充逻辑待实现）
- `redis-fallback`: Redis 故障降级能力（基础降级存在，健康探测待添加）

### Modified Capabilities
- `container-architecture`: Container 分层架构，职责分离
- `embedding-cache`: Embedding 缓存优化，批量获取（待实现）
- `entity-resolver`: 实体解析器重构，拆分匹配逻辑

## Impact

### 直接影响
- **container.py**: 完全重构，拆分为多个模块
- **core/llm/client.py**: 缓存逻辑改为批量获取
- **modules/knowledge/graph/**: ~~批量写入~~ ✅ 已实现
- **modules/analytics/llm_usage/**: 嵌套重构

### API 影响
- 无公开 API 变更，内部实现优化

### 依赖影响
- 无新增依赖，现有 `aiolimiter`, `pybreaker` 更充分利用

### 风险评估
- Container 重构影响面大，需分阶段进行
- ~~批量写入需验证事务一致性~~ ✅ 已验证
- 性能优化需基准测试验证效果