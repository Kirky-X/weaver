## Context

Weaver 项目经过全面代码审查，发现以下核心问题需要系统性修复：

| 类别 | 问题 | 状态 | 影响 |
|------|------|------|------|
| 架构 | `container.py` 1190行，29个缓存属性 | 🔴 待修复 | 难以维护、测试、扩展 |
| 性能 | Embedding 缓存 N+1 (循环 `GET`) | 🔴 待修复 | 延迟增加 200-500ms |
| 性能 | Neo4j 批量写入 | ✅ 已解决 | - |
| 业务 | 降级字段 `degraded_fields` 未填充 | 🔴 待修复 | 数据质量不可追溯 |
| 代码 | 200个过长函数 (>50行)，22个过深嵌套 (>4层) | 🔴 待修复 | 可读性差，问题规模超预期 |

**验证结果** (2026-04-05):
- 缓存属性：实际 29 个 (非文档原记录的 45+)
- 过长函数：全项目 200 个 >50 行 (非 6 个)，最长达 292 行
- 过深嵌套：22 个 >4 层 (非 6 个)，最深 9 层
- Neo4j 批量写入：`Neo4jWriter._write_entities()` 已实现批量操作
- 降级字段：`PipelineState` 已定义 `degraded_fields` 和 `degradation_reasons`，但无代码填充

**约束**:
- 不改变公开 API 行为
- 分阶段实施，每阶段可独立部署
- 保持测试覆盖率 > 80%

## Goals / Non-Goals

**Goals:**
1. 重构 `container.py` 为职责清晰的模块化架构
2. 消除 Embedding 缓存 N+1 性能瓶颈
3. 填充降级数据字段，建立追踪机制
4. 提升代码可读性（函数拆分、常量提取）

**Non-Goals:**
- 不改变业务逻辑核心流程
- 不引入新的外部依赖
- 不修改 API 端点签名
- 不处理分布式事务（留待后续迭代）
- 不一次性修复所有过长函数（按优先级分批处理）

## Decisions

### D1: Container 分层架构

**决策**: 将 `container.py` 拆分为 4 个专职模块

```
src/container/
├── __init__.py          # 导出 get_container()
├── core.py              # 核心服务管理 (~200行)
├── repos.py             # Repository 工厂 (~150行)  
├── scheduler.py         # 调度器配置 (~200行)
├── events.py            # 事件订阅配置 (~100行)
└── legacy.py            # 兼容层 (deprecated accessors)
```

**理由**:
- 单一职责原则，每个模块 < 300 行
- 便于独立测试和维护
- 渐进式迁移，保留兼容层

**替代方案**:
- ❌ 使用 `dependency-injector` 库：引入新依赖，学习成本高
- ❌ FastAPI 内置依赖注入：不适合非请求上下文的 singleton

### D2: Neo4j 批量写入 ✅ 已解决

**状态**: 已实现于 `Neo4jWriter._write_entities()`

**实现方式**:
- `merge_entities_batch()` 批量 MERGE 实体
- `find_entities_by_keys()` 批量查询实体 ID
- `merge_mentions_batch()` 批量创建 MENTIONS 关系

~~**决策**: 新增 `write_batch(states: list[PipelineState])` 方法~~

### D3: Embedding 缓存批量获取 🔴 待修复

**当前问题** (`core/llm/client.py:283-293`):
```python
# N+1 循环 GET
for i, text in enumerate(texts):
    cache_key = self._make_cache_key(text)
    cached = await self._redis.get(cache_key)  # 每次循环一次 Redis 调用
    if cached:
        all_embeddings[i] = json.loads(cached)
```

**决策**: 使用 Redis `MGET` 替代循环 `GET`

```python
# 优化后
keys = [self._make_cache_key(text) for text in texts]
values = await self._redis.mget(keys)
for i, val in enumerate(values):
    if val:
        all_embeddings[i] = json.loads(val)
```

**理由**: 32 个文本从 32 次 Redis 调用减少到 1 次

### D4: 降级数据标记 🔴 待填充

**当前状态**: `PipelineState` 已定义字段但未使用

```python
# src/modules/processing/pipeline/state.py:84-85
degraded_fields: list[str]  # 已定义
degradation_reasons: dict[str, str]  # 已定义
```

**需要填充的位置**:
- `modules/processing/nodes/cleaner.py` - LLM 清洗失败时
- `modules/processing/nodes/entity_extractor.py` - 实体提取失败时
- `modules/processing/nodes/categorizer.py` - 分类失败时

**填充方式**:
```python
state["degraded_fields"].append("cleaned")
state["degradation_reasons"]["cleaned"] = "LLM cleaner failed: timeout"
```

### D5: HostRateLimiter 统一 ⚠️ 部分完成

**当前状态**: 两套实现并存
- `core/llm/pool.py` - 已使用 `aiolimiter`
- `modules/ingestion/fetching/rate_limiter.py` - 自实现 (~69行)

**决策**: 迁移 `fetching/rate_limiter.py` 到 `aiolimiter`，保留随机延迟特性

```python
from aiolimiter import AsyncLimiter

class HostRateLimiter:
    def __init__(self, rpm: int = 30, jitter: float = 0.5):
        self._limiters: dict[str, AsyncLimiter] = {}
        self._jitter = jitter

    async def acquire(self, url: str) -> None:
        host = urlparse(url).netloc
        limiter = self._limiters.setdefault(host, AsyncLimiter(1, 2.0))
        await limiter.acquire()
        await asyncio.sleep(random.uniform(0, self._jitter))
```

**理由**: 减少 ~70 行自实现代码，使用成熟库

## Risks / Trade-offs

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Container 重构影响面大 | 高 | 分3阶段：1)创建新模块 2)迁移调用 3)删除旧代码 |
| ~~批量写入事务边界变化~~ | ~~中~~ | ~~保持单条 `write()` 接口不变，新增 `write_batch()`~~ ✅ 已解决 |
| 缓存批量获取内存增加 | 低 | 已有 embedding 内存占用远大于 key 列表 |
| 嵌套重构引入回归 | 中 | 先写测试，增量重构，每步验证 |

## Migration Plan

### Phase 1: 安全重构 (1-2天)
1. 提取魔法数字到 `core/constants.py`
2. 拆分 `aggregate_usage_data()` 嵌套
3. 填充降级数据字段

### Phase 2: 性能优化 (2-3天)
1. ~~实现 `Neo4jWriter.write_batch()`~~ ✅ 已完成
2. Embedding 缓存改为 `MGET`
3. `HostRateLimiter` 迁移到 `aiolimiter`

### Phase 3: 架构重构 (3-5天)
1. 创建 `container/` 模块结构
2. 迁移核心服务初始化
3. 迁移 Repository 工厂
4. 迁移调度器配置
5. 添加兼容层，标记 deprecated
6. 逐步更新调用点

### 回滚策略
- 每个阶段独立可回滚
- Phase 1/2 不改变模块结构，git revert 即可
- Phase 3 保留 `container.py` 作为兼容入口，渐进迁移

## Open Questions

1. ~~**批量写入失败处理**: 部分成功时是否需要回滚已创建实体？~~ ✅ 已解决
   - 实现: 记录成功 ID，返回部分成功状态

2. **Container 重构时机**: 是否需要同步更新所有测试？
   - 建议: 兼容层保持旧 API 可用，测试渐进更新

3. **性能基准测试**: 优化效果如何量化？
   - 建议: 在 Phase 2 后运行基准测试，对比延迟和吞吐

4. **过长函数优先级**: 200 个过长函数如何排序？
   - 建议: 按调用频率和影响范围，优先处理核心路径上的函数