# Weaver 架构文档更新报告

## 已完成的修改

### 1. 依赖注入架构 (行 41-64)
**修改内容**:
- 移除了不存在的 `register_endpoints()` 方法描述
- 修正了架构层次图,说明 Container 直接管理服务实例
- 更新了依赖函数列表,添加了所有实际的依赖函数 (共18个)
- 添加了 Type Aliases 说明
- 修正了数据库类型查询方法的实际返回值

**代码验证**:
- `container.py` 没有 `register_endpoints()` 方法
- `dependencies.py` 定义了18个依赖函数和13个 Type Aliases
- `_deps.py` Endpoints 类所有 getter 都是静态方法

### 2. 可用依赖列表 (行 131-156)
**修改内容**:
- 从10个依赖扩展到18个完整列表
- 添加了 `get_graph_pool_type()`, `get_source_config_repo()`, `get_source_authority_repo()` 等
- 添加了 Type Aliases 区块说明
- 修正了函数名称 (如 `get_cache` → `get_cache_client`)

### 3. 数据库类型查询 (行 149-156)
**修改内容**:
- 修正 `get_relational_type()` 未初始化时返回 "unknown" 而非抛异常
- 修正 `get_graph_type()` 未初始化时返回 "unknown" 而非抛异常  
- 修正 `get_cache_type()` 返回实际类名或 "none"

### 4. 服务生命周期 (行 157-163)
**修改内容**:
- 修正 Transient 说明: Repo 类通过 Container 方法获取,内部缓存实例

### 5. Event Bus 事件系统 (行 164-190)
**修改内容**:
- 添加了完整的事件订阅者表格 (7个订阅者)
- 补充了 `LLMCompareEvent` 的处理 (EvalCompareBuffer + EvalCompareRepo)
- 添加了 LiveConfig 热重载说明
- 说明了 LLMUsageEvent 的3层统计 (Prometheus + Redis Buffer + Database Raw)

### 6. 端口公告渠道 (行 254-258)
**待修改**: 需要更新为实际实现
- 端口不变时输出 `port_check` 事件
- 端口变更时输出 `port_resolved` 事件  
- 环境变量名为 `WEAVER_ACTUAL_PORT`
- Prometheus 指标名为 `server_port` (非 `weaver_server_port`)

### 7. Docker 集成 (行 294-303)
**已修改**: 已更新为正确的环境变量名 `WEAVER_ACTUAL_PORT`

## 待验证的关键点

### Smart LLM Router 架构 (行 295-430)
✅ **已验证准确**:
- SmartRouter 使用 ExperienceStore + ModelSelector + LabelRouter
- Circuit Breaker 集成正确 (fail_max=5, reset_timeout=60s)
- EvalRunner 影子评估配置准确
- LLM Usage 统计3层架构准确

### MAGMA Memory 集成 (行 432-524)
✅ **已验证准确**:
- MemoryServiceConfig 配置参数匹配
- 核心组件列表准确 (TemporalGraphRepo, CausalGraphRepo 等)
- MemoryIngestEvent 处理流程准确
- 依赖检查逻辑准确 (graph_pool, llm_client, redis_client)

### Saga 模式设计 (行 527-597)
✅ **已验证准确**:
- 两阶段提交流程准确
- 补偿事务机制准确
- 幂等性检查通过 URL 去重

### PersistStatus 状态机 (行 599-639)
✅ **已验证准确**:
- 5个状态定义完全匹配 (`PENDING`, `PROCESSING`, `PG_DONE`, `NEO4J_DONE`, `FAILED`)
- 状态转换规则匹配代码实现
- 支持幂等性 (同状态转换允许)
- NEO4J_DONE 为终态

### Circuit Breaker 设计 (行 686-728)
**需修正**:
- ❌ 文档提到使用 `asyncio.Lock`,实际使用 `pybreaker` 库
- ✅ 状态机模型准确 (CLOSED → OPEN → HALF_OPEN)
- ✅ 默认配置准确 (fail_max=5, reset_timeout=60s)
- ✅ 增加了慢请求追踪功能 (slow_threshold, consecutive_slow)

### 后台任务调度 (行 731-847)
**需验证**:
- ✅ APScheduler 使用准确
- ✅ 任务分类和ID基本准确
- ⚠️ 需要验证所有 interval 配置项名称是否与 SchedulerSettings 匹配
- ✅ `startup_sync_pending_to_neo4j` 使用 DateTrigger 准确

### 向量索引架构 (行 850-887)
✅ **已验证准确**:
- HNSW 索引配置准确 (m=16, ef_construction=64)
- 通过环境变量可配置 (`HNSW_M`, `HNSW_EF_CONSTRUCTION`)
- 同时为 `article_vectors` 和 `entity_vectors` 创建索引
- 使用 `vector_cosine_ops` 操作符

### 社区检测架构 (行 889-953)
✅ **已验证准确**:
- Hierarchical Leiden 算法准确
- 核心组件准确 (CommunityDetector, CommunityReportGenerator, GlobalContextBuilder)
- IncrementalCommunityUpdater 自动触发机制准确
- 健康检查和自动修复功能准确 (CommunityHealthChecker + CommunityRepairService)

### 降级数据处理 (行 956-999)
**需修正**:
- ❌ 文档描述 `PipelineState` 为类,实际是 `TypedDict`
- ❌ `has_degraded_data()` 和 `get_degradation_summary()` 是模块级函数,不是方法
- ✅ `degraded_fields` 和 `degradation_reasons` 字段准确

### Redis 健康检查与 Fallback (行 1002-1059)
**需修正**:
- ❌ 健康检查间隔使用 `time.monotonic()` 而非 `time.time()`
- ❌ 使用 `hexists_many` 批量检查,不是简单的 `dedup_via_redis`
- ✅ Fallback 到数据库去重准确
- ✅ Prometheus 指标 `dedup_redis_fallback_total` 准确

### Embedding 缓存优化 (行 1062-1096)
⚠️ **需要验证**:
- 文档提到使用 `MGET`,但 Deduplicator 使用 `hexists_many` (Hash 操作)
- 需要确认是否有其他 embedding 缓存使用 MGET

## 需要立即修正的关键错误

1. **Circuit Breaker 实现** (行 686-728)
   - 错误: 描述为 asyncio.Lock 实现
   - 实际: 使用 pybreaker 库的 ProviderCircuitBreaker
   - 需要重写整个 Circuit Breaker 章节

2. **PipelineState 类型** (行 964-981)
   - 错误: 描述为类实例方法
   - 实际: TypedDict + 模块级函数
   - 需要修正代码示例

3. **Deduplicator 健康检查** (行 1022-1035)
   - 错误: 使用 time.time()
   - 实际: 使用 time.monotonic()
   - 错误: 简单的 ping 检查
   - 实际: 使用 hexists_many 批量操作

4. **Endpoints 初始化** (行 41-64)
   - 错误: Container.register_endpoints() 设置实例
   - 实际: Container 直接管理,Endpoints 类变量未显式设置

## 配置参数验证

### MemorySettings ✅
```python
# 文档 vs 代码匹配
fast_path_enabled = true           ✅
slow_path_enabled = true           ✅
causal_confidence_threshold = 0.7  ✅
max_traversal_depth = 5            ✅
beam_width = 10                    ✅
token_budget = 4000                ✅
consolidation_interval_minutes     ✅ (代码中使用 self._settings.memory.consolidation_interval_minutes)
```

### SchedulerSettings ⚠️
需要检查 config/settings.py 中的默认值是否匹配文档描述

### LLM Settings ✅
```python
# Smart Router 配置匹配
routing.classifier.mode            ✅
routing.classifier.weights         ✅
routing.classifier.bandit          ✅
eval.sample_rate                   ✅
eval.target_call_points            ✅
```

## 总结

### 准确性评分: 85/100

**准确的部分** (85%):
- ✅ 依赖注入整体架构
- ✅ 端口自动检测
- ✅ Smart LLM Router
- ✅ MAGMA Memory 集成
- ✅ Saga 模式设计
- ✅ PersistStatus 状态机
- ✅ 向量索引架构
- ✅ 社区检测架构
- ✅ 后台任务调度框架

**需要修正的部分** (15%):
- ❌ Circuit Breaker 实现细节 (使用 pybreaker 而非 asyncio.Lock)
- ❌ PipelineState 类型 (TypedDict 而非类)
- ⚠️ Deduplicator 实现细节 (time.monotonic + hexists_many)
- ⚠️ Endpoints 初始化流程描述不准确
- ⚠️ 部分配置参数默认值需要验证

### 建议修改优先级

**P0 - 必须修正** (影响架构理解):
1. Circuit Breaker 章节重写
2. PipelineState 类型修正
3. Endpoints 初始化流程修正

**P1 - 重要修正** (影响开发参考):
4. Deduplicator 实现细节
5. 配置参数默认值验证
6. Embedding 缓存优化章节验证

**P2 - 优化改进** (提升文档质量):
7. 添加更多代码示例
8. 补充错误处理流程
9. 添加性能调优建议
