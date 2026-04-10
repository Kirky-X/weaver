## Context

当前代码库存在多个安全漏洞和架构违规问题：
- **注入漏洞**: SQL/Cypher注入分布在 migration、core、knowledge 模块
- **反序列化风险**: pickle.load 存在恶意文件利用风险
- **架构违规**: 模块耦合、全局变量、私有属性访问

已存在的安全机制：
- `QueryBuilder` 模式已在 `vector_repo.py`、`entity_repo.py` 中成功应用
- Protocol 接口抽象已在 `src/core/protocols/` 中定义
- edge_type 正则验证在 `entity_repo.py` 中已实现

## Goals / Non-Goals

**Goals:**
- 修复所有 P0 级别注入漏洞（SQL、Cypher）
- 替换 pickle 反序列化为安全方案
- 解耦 management 模块对 pipeline 内部方法的依赖
- 消除 API endpoint 全局变量和私有属性访问

**Non-Goals:**
- 不重构未在报告中指出的模块
- 不添加新的安全框架（使用现有 QueryBuilder 和 Protocol）
- 不改变 API 外部行为（保持向后兼容）

## Decisions

### D1: 参数化查询统一使用 QueryBuilder

**决策**: 所有数据库查询改用 QueryBuilder 模式，不再使用 f-string 拼接。

**理由**:
- QueryBuilder 已在 storage 模块验证有效
- 参数化查询从根本上防止注入
- 统一模式便于审计和维护

**替代方案**:
- 手动转义输入：不可靠，易遗漏边界情况
- ORM 框架：引入新依赖，迁移成本高

### D2: pickle 反序列化改用 JSON + 签名验证

**决策**: BM25Retriever 使用 JSON 存储索引数据，加载时验证签名。

**理由**:
- JSON 是安全格式，无代码执行风险
- 签名验证防止恶意文件替换
- 保持向后兼容（支持迁移旧索引）

**替代方案**:
- 仅使用 JSON 无签名：仍可被恶意文件替换
- protobuf：引入新依赖，序列化复杂度高

### D3: 服务层解耦管理模块

**决策**: 创建 `PipelineService` Protocol，management 模块通过服务接口调用。

**理由**:
- 符合现有 Protocol 架构
- 避免直接访问内部方法
- 便于测试和替换实现

### D4: 依赖注入替代全局变量

**决策**: API endpoint 通过 FastAPI Depends 获取容器实例。

**理由**:
- FastAPI 原生支持依赖注入
- 避免全局状态污染
- 便于测试时注入 mock

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| QueryBuilder 迁移遗漏边界查询 | 全面 grep 搜索 f-string + SQL 关键词 |
| JSON 签名验证性能开销 | 仅在加载时验证，运行时无开销 |
| 服务层引入增加间接层 | 保持接口精简，仅暴露必要方法 |
| 旧索引文件格式迁移 | 提供迁移脚本，检测旧格式自动转换 |

## Migration Plan

### Phase 1: 安全漏洞修复（P0）
1. 创建 `SafeQueryBuilder` 扩展类，支持参数化 Cypher
2. 迁移 migration 模块的 ladybug_source.py、neo4j_source.py
3. 迁移 core 模块的 graph_query.py
4. 迁移 knowledge 模块的 local_context.py
5. 替换 bm25_retriever.py 的 pickle 为 JSON+签名

### Phase 2: 架构违规修复（P1）
1. 定义 `PipelineService` Protocol
2. 创建 `PipelineServiceImpl` 实现
3. 重构 repair_articles.py 使用服务接口
4. 创建 FastAPI dependency 获取容器
5. 重构 API endpoints 使用依赖注入

### Rollback Strategy
- 每个 Phase 可独立回滚
- 保留旧代码路径作为 fallback（短期）
- 测试覆盖确保无回归

## Open Questions

1. **签名密钥存储**: 使用环境变量还是配置文件？
2. **服务层粒度**: `PipelineService` 应暴露多少方法？
3. **旧索引迁移时机**: 自动迁移还是手动触发？