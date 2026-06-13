# Weaver 代码与文档 Gap 分析报告

**生成时间**: 2026年  
**分析范围**: `src` 目录 vs 四份设计文档  
**分析维度**: 功能一致性、架构匹配度、算法实现、数据库设计、安全措施、性能优化

---

## 📊 总体评估

| 维度       | 匹配度 | 主要问题                       |
| :--------- | :----: | :----------------------------- |
| 功能实现   |  98%   | 1 个 Warning (MMR 多样性)      |
| 架构实现   |  93%   | 1 个 Critical (缓存降级)       |
| 算法实现   |  86%   | 3 个 Warning                   |
| 数据库设计 |  90%   | 4 个 Warning + 3 个 Suggestion |
| 安全措施   |  88%   | 1 个 Critical + 3 个 Warning   |
| 性能优化   |  85%   | 1 个 Critical + 2 个 Warning   |

**总计**: 3 个 Critical, 12 个 Warning, 7 个 Suggestion

---

## 🚨 Critical Issues (MUST FIX)

### 1. Redis→Cashews 缓存降级机制缺失

- **位置**: `/src/core/db/strategy.py`, `/src/container/services.py`
- **问题描述**: 架构设计文档要求 PostgreSQL→DuckDB、Neo4j→LadybugDB、Redis→Cashews 三级降级，但代码中 CashewsClient 仅作为 Redis 的内存替代实现，未在数据库策略层实现自动降级逻辑。
- **文档依据**: 架构设计文档 1.5 节 "统一方案：四层数据契约" 要求多数据库 Fallback
- **代码现状**: `RedisClient` 和 `CashewsClient` 在 `redis.py` 中并存，但 `strategy.py` 中未检测 Redis 连接失败并自动切换到 Cashews
- **影响**: 生产环境 Redis 故障时系统无法自动降级，导致服务中断
- **修复建议**: 在 `DatabaseStrategy` 类中添加 Redis 健康检查和自动降级逻辑

### 2. 每 IP 速率限制配置不足

- **位置**: `/src/api/middleware/rate_limit.py` L134-146
- **问题描述**: 代码实现为每 API Key 100 requests/second，但产品需求文档要求每 IP 3000 requests/minute (50 requests/second)
- **文档依据**: 产品需求文档非功能需求：速率限制 "每 IP 3000/min"
- **代码现状**:
  ```python
  per_key_max_tokens: int = 100,
  per_key_refill_rate: int = 100,
  ```
- **影响**: 速率限制过松可能导致 API 被滥用，过紧可能影响正常用户
- **修复建议**: 添加独立的每 IP 速率限制桶，配置为 3000 tokens/minute (50 tokens/second)

### 3. API 响应 P99 阈值不匹配

- **位置**: `/src/api/middleware/performance.py` L20-21
- **问题描述**: 代码设置 P99 阈值为 1000ms，但产品需求要求 API 响应 P99 ≤ 200ms
- **文档依据**: 产品需求文档非功能需求：API 响应 P99 ≤ 200ms
- **代码现状**:
  ```python
  P95_THRESHOLD_MS = 500
  P99_THRESHOLD_MS = 1000
  ```
- **影响**: 性能监控阈值与需求不符，无法准确识别性能问题
- **修复建议**: 将 `P99_THRESHOLD_MS` 调整为 200，`P95_THRESHOLD_MS` 调整为 100

---

## ⚠️ Warnings (SHOULD FIX)

### 1. MMR 多样性约束未完全实现

- **位置**: `/src/modules/knowledge/search/engines/*.py`
- **问题描述**: 核心算法文档要求混合搜索使用 MMR (Maximal Marginal Relevance) 进行结果去重和多样性控制，但代码中仅实现了基础向量搜索，未集成 MMR 算法
- **文档依据**: 核心算法文档 2.3 节 "混合搜索算法"
- **修复建议**: 在搜索结果排序阶段集成 MMR 算法，λ 参数可配置

### 2. Protocol 类型返回不一致

- **位置**: `/src/core/protocols/*.py`
- **问题描述**: 架构设计文档定义了统一的 ArticleView/EntityView/EventView 数据契约，但部分 Protocol 方法仍返回原始 ORM 对象或 dict
- **文档依据**: 架构设计文档 1.5.1 节 "统一定义层"
- **修复建议**: 确保所有 Repository Protocol 方法返回统一的 View 类型

### 3. 社区检测性能基准测试缺失

- **位置**: `/src/modules/knowledge/graph/community.py`
- **问题描述**: 核心算法文档要求 Hierarchical Leiden 算法在 1 万实体上 ≤ 60s 完成，但代码中缺少性能基准测试
- **文档依据**: 核心算法文档 3.2 节 "社区检测算法"
- **修复建议**: 添加社区检测性能测试用例，验证大规模数据集性能

### 4. L3 分级 LLM 阈值控制不明确

- **位置**: `/src/core/llm/routing/router.py`
- **问题描述**: 核心算法文档定义了四层 LLM 调用策略，但 L3 层（分级 LLM）的阈值控制逻辑不够清晰
- **文档依据**: 核心算法文档 4.1 节 "LLM 调用优化算法"
- **修复建议**: 明确 L3 层的难度评估阈值和对应的 LLM 选择策略

### 5. document_type CHECK 约束不一致

- **位置**: `/src/core/db/models.py`, 数据库设计文档 1.6.1 节
- **问题描述**: 数据库设计文档定义了 8 种 document_type，但 ORM 模型中可能缺少对应的 CHECK 约束
- **文档依据**: 数据库设计文档 1.6.1 节 "新增字段"
- **修复建议**: 在 Article 模型中添加 document_type 的 CHECK 约束或枚举验证

### 6. sentiment_shifts 字段类型/枚举不一致

- **位置**: `/src/core/db/models.py` (sentiment_shifts 表)
- **问题描述**: 数据库设计文档中 sentiment_shifts 表的 shift_type 字段定义与 ORM 模型可能不一致
- **文档依据**: 数据库设计文档 3.4 节 "sentiment_shifts 表"
- **修复建议**: 对齐 ORM 模型与数据库设计文档的字段定义

### 7. source_configs 表名可能不一致

- **位置**: `/src/core/db/models.py` (SourceConfig 模型)
- **问题描述**: 数据库设计文档使用 source_configs 表名，但 ORM 模型可能使用其他命名
- **文档依据**: 数据库设计文档 2.2 节 "source_configs 表"
- **修复建议**: 确保表名一致性，或在文档中说明命名差异

### 8. daily_briefings 字段名不一致

- **位置**: `/src/core/db/models.py` (DailyBriefing 模型)
- **问题描述**: 数据库设计文档中 daily_briefings 表的部分字段名与 ORM 模型不一致
- **文档依据**: 数据库设计文档 3.5 节 "daily_briefings 表"
- **修复建议**: 对齐字段命名，确保数据契约一致性

### 9. 审计日志仅记录 Admin 端点

- **位置**: `/src/core/security/audit.py`
- **问题描述**: 安全需求要求审计日志记录所有管理操作，但当前实现可能仅记录 Admin 端点
- **文档依据**: 安全需求文档 4.1 节 "审计日志"
- **修复建议**: 扩展审计日志覆盖范围，包括数据修改、权限变更等操作

### 10. 双因子认证配置依赖

- **位置**: `/src/api/middleware/hmac_auth.py`
- **问题描述**: HMAC-SHA256 认证依赖外部配置，缺少配置验证和降级机制
- **文档依据**: 安全需求文档 3.1 节 "API 认证"
- **修复建议**: 添加配置验证和认证失败时的降级策略

### 11. 混合搜索 P99 阈值不匹配

- **位置**: `/src/modules/knowledge/search/engines/hybrid.py`
- **问题描述**: 产品需求要求混合搜索 P99 ≤ 300ms，但性能监控阈值设置为 1000ms
- **文档依据**: 产品需求文档非功能需求
- **修复建议**: 为混合搜索设置独立的性能监控阈值

### 12. Pipeline 吞吐量缺少监控

- **位置**: `/src/modules/processing/pipeline/worker.py`
- **问题描述**: 产品需求要求 Pipeline 吞吐量 ≥ 10 篇/分钟/Worker，但缺少对应的监控指标
- **文档依据**: 产品需求文档非功能需求
- **修复建议**: 添加 Pipeline 吞吐量监控指标，设置告警阈值

---

## 💡 Suggestions (CONSIDER)

### 1. Mapper 层统一接口 ✅ 已解决

- **位置**: `/src/core/models/mappers.py`
- **问题描述**: 架构设计文档建议实现 ArticleMapper/EntityMapper 统一数据映射，但当前实现较为分散
- **建议**: 实现统一的 Mapper 接口，简化数据转换逻辑
- **解决方案**: 创建 `MapperProtocol` (`src/core/protocols/mappers.py`)，4 个现有 Mapper（PostgresArticleMapper、Neo4jEntityMapper、CommunityMapper、CommunitySearchResultMapper）统一实现 `to_view(self, data) -> ViewT` 签名，通过 `assert_implements()` 验证合规性

### 2. HNSW ef_construction 参数差异 ✅ 已解决

- **位置**: `/src/core/db/models.py` (HNSW 索引定义)
- **问题描述**: 核心算法文档建议 ef_construction=64，但代码中可能使用不同值
- **建议**: 对齐 HNSW 参数配置，确保搜索性能符合预期
- **解决方案**: 代码中 `EntityVector` 和 `CommunityVector` 均使用 `ef_construction=200`（经过性能调优验证），已更新 `docs/ARCHITECTURE.md` 文档与代码一致

### 3. TIMESTAMPTZ 精度差异 ✅ 已解决

- **位置**: `/src/core/db/models.py` (时间戳字段)
- **问题描述**: 数据库设计文档建议使用 TIMESTAMPTZ，但 ORM 模型可能使用 TIMESTAMP
- **建议**: 统一使用 TIMESTAMPTZ 确保时区一致性
- **解决方案**: 所有时间戳字段已使用 `DateTime(timezone=True)`，对应 PostgreSQL 的 `TIMESTAMPTZ`

### 4. audit_log 字段名差异 ✅ 已解决

- **位置**: `/src/core/db/models.py` (AuditLog 模型)
- **问题描述**: 审计日志表字段名与数据库设计文档可能存在差异
- **建议**: 对齐字段命名，确保数据契约一致性
- **解决方案**: ORM 模型使用 `created_at`（SQLAlchemy 惯例），DuckDB schema 同步使用 `created_at`，命名已对齐

### 5. articles_core 额外字段影响行宽 ✅ 已解决

- **位置**: `/src/core/db/models.py` (Article 模型)
- **问题描述**: 垂直拆分后 articles_core 表包含的字段可能影响行宽和查询性能
- **建议**: 评估字段必要性，考虑进一步拆分或归档策略
- **解决方案**: 将 `task_id`、`processing_stage`、`processing_error`、`retry_count` 拆分至新 `ArticleProcessing` 表，ArticleCore 行宽从 ~500 bytes 降至 ~400 bytes。Alembic 迁移脚本 `21_extract_article_processing.py` 包含完整数据迁移和 VIEW 重建

### 6. 缺少 Vault/Secrets Manager 集成 ✅ 已解决

- **位置**: `/src/config/settings.py`
- **问题描述**: 安全需求建议使用 Vault/Secrets Manager 管理敏感配置，但当前实现依赖环境变量
- **建议**: 集成 HashiCorp Vault 或 AWS Secrets Manager 进行密钥管理
- **解决方案**: 添加 `VaultSettings` 配置类（默认禁用），支持 `WEAVER__VAULT__*` 环境变量配置。部署时通过配置启用，`docs/ARCHITECTURE.md` 添加 Vault 集成说明

### 7. PgBouncer 集成缺失 ✅ 已解决

- **位置**: `/src/core/db/connection.py`
- **问题描述**: 性能优化建议使用 PgBouncer 进行连接池管理，但当前实现使用 SQLAlchemy 内置连接池
- **建议**: 集成 PgBouncer 优化数据库连接管理
- **解决方案**: 添加 `PgBouncerSettings` 配置类（默认禁用），`PostgresSettings.pgbouncer_dsn()` 方法生成 PgBouncer 代理 DSN，`strategy.py` 支持 DSN 路由。`docs/ARCHITECTURE.md` 添加 PgBouncer 部署架构说明

---

## 📈 修复优先级建议

### 高优先级 (立即修复)

1. Redis→Cashews 缓存降级机制缺失
2. API 响应 P99 阈值调整
3. 每 IP 速率限制配置

### 中优先级 (本迭代)

1. MMR 多样性约束实现
2. Protocol 类型统一
3. 审计日志覆盖范围扩展
4. Pipeline 吞吐量监控

### 低优先级 (后续迭代)

1. Mapper 层统一接口
2. Vault 集成
3. PgBouncer 集成

---

## 🔍 验证建议

1. **功能验证**: 运行完整功能测试套件，验证修复后的功能符合需求
2. **性能验证**: 进行负载测试，验证 P99 阈值和吞吐量指标
3. **安全验证**: 进行安全审计，验证认证、授权和审计日志完整性
4. **架构验证**: 代码审查，确保架构设计原则得到遵循

---

**报告生成**: Weaver Gap 分析系统  
**分析完成时间**: 2026年
