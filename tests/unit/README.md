# Unit Tests Directory Structure

本目录包含 Weaver 项目的所有单元测试。测试文件按功能模块组织，便于维护和查找。

## 📁 目录结构

```
tests/unit/
├── api/              # API 层测试
├── core/             # 核心功能测试
├── modules/          # 业务模块测试
│   ├── collector/    # 数据采集器
│   ├── fetcher/      # 数据抓取器
│   ├── graph_store/  # 图存储
│   ├── llm/          # LLM 相关
│   ├── nlp/          # NLP 处理
│   ├── pipeline/     # 数据处理流水线
│   ├── scheduler/    # 调度器
│   ├── search/       # 搜索
│   ├── source/       # 数据源管理
│   └── storage/      # 存储（预留）
├── neo4j/            # Neo4j 数据库测试
├── postgres/         # PostgreSQL 数据库测试
└── redis/            # Redis 缓存测试
```

## 🗂️ 各目录说明

### `api/` - API 层测试

测试 API 端点、认证、授权、输入验证等。

**包含内容**:

- RESTful API 端点测试
- 认证和授权测试
- 输入验证和注入防护测试
- API 依赖注入测试
- 速率限制测试

**文件示例**:

- `test_api.py` - API 综合测试
- `test_api_auth.py` - 认证测试
- `test_api_dependencies.py` - 依赖注入测试
- `test_cypher_injection.py` - Cypher 注入防护测试
- `test_input_validation.py` - 输入验证测试

### `core/` - 核心功能测试

测试核心基础设施、工具类、通用组件等。

**包含内容**:

- 数据库初始化和管理
- 健康检查机制
- 断路器模式实现
- 重试机制
- 事件总线
- 全局上下文管理
- 性能优化
- 状态机
- 队列管理
- 速率限制器
- 令牌桶算法
- 时间工具
- Union-Find 数据结构
- Saga 模式实现

**文件示例**:

- `test_db_initializer.py` - 数据库初始化测试
- `test_health.py` - 健康检查测试
- `test_circuit_breaker.py` - 断路器测试
- `test_retry.py` - 重试机制测试
- `test_event_bus_sharing.py` - 事件总线测试
- `test_saga_persistence.py` - Saga 模式测试

### `modules/` - 业务模块测试

#### `collector/` - 数据采集器

测试数据采集相关的模型和处理逻辑。

**文件**:

- `test_collector_models.py` - 采集器模型测试
- `test_collector_processor.py` - 采集器处理逻辑测试

#### `fetcher/` - 数据抓取器

测试网页抓取、HTTP 请求、浏览器自动化等。

**文件**:

- `test_crawler.py` - 爬虫测试
- `test_httpx_fetcher.py` - HTTPX 抓取器测试
- `test_playwright_fetcher.py` - Playwright 抓取器测试
- `test_playwright_pool.py` - Playwright 池测试
- `test_rss_parser.py` - RSS 解析器测试
- `test_newsnow_parser.py` - NewsNow 解析器测试
- `test_fetcher_exceptions.py` - 抓取器异常处理测试
- `test_smart_fetcher_circuit_breaker.py` - 智能抓取断路器测试

#### `graph_store/` - 图存储

测试 Neo4j 图数据库操作、社区检测、图算法等。

**文件**:

- `test_community_detector.py` - 社区检测器测试
- `test_community_repo.py` - 社区仓库测试
- `test_community_report_generator.py` - 社区报告生成器测试
- `test_graph_pruner.py` - 图剪枝器测试
- `test_incremental_community_updater.py` - 社区增量更新器测试
- `test_relation_type_normalizer.py` - 关系类型规范化器测试
- `test_graph_metrics.py` - 图指标测试
- `test_context_builder.py` - 上下文构建器测试
- `test_relation_type_models.py` - 关系类型模型测试

#### `llm/` - LLM 相关

测试大语言模型调用、token 管理、使用统计等。

**文件**:

- `test_llm_call_result_adapter.py` - LLM 调用结果适配器测试
- `test_llm_failure_cleanup.py` - LLM 失败清理测试
- `test_llm_failure_repo.py` - LLM 失败仓库测试
- `test_llm_token_metrics.py` - LLM token 指标测试
- `test_llm_usage_aggregator.py` - LLM 使用聚合器测试
- `test_llm_usage_api.py` - LLM 使用 API 测试
- `test_llm_usage_buffer.py` - LLM 使用缓冲器测试
- `test_llm_usage_event_publish.py` - LLM 使用事件发布测试
- `test_llm_usage_repo.py` - LLM 使用仓库测试
- `test_anthropic_provider.py` - Anthropic 提供商测试
- `test_embedding_provider.py` - Embedding 提供商测试
- `test_rerank_provider.py` - Rerank 提供商测试

#### `nlp/` - NLP 处理

测试自然语言处理相关的组件。

**文件**:

- `test_analyze.py` - 分析器测试
- `test_categorizer.py` - 分类器测试
- `test_classifier.py` - 分类器测试
- `test_entity_extractor.py` - 实体抽取器测试
- `test_entity_resolver.py` - 实体解析器测试
- `test_name_normalizer.py` - 名称规范化器测试
- `test_spacy_extractor.py` - SpaCy 抽取器测试
- `test_credibility_calc.py` - 可信度计算器测试
- `test_credibility_checker.py` - 可信度检查器测试
- `test_output_validator.py` - 输出验证器测试
- `test_resolution_rules.py` - 解析规则测试

#### `pipeline/` - 数据处理流水线

测试数据处理流水线的配置、执行、状态管理等。

**文件**:

- `test_pipeline_config.py` - 流水线配置测试
- `test_pipeline_endpoint.py` - 流水线端点测试
- `test_pipeline_graph.py` - 流水线图测试
- `test_pipeline_resume.py` - 流水线恢复测试
- `test_pipeline_state_models.py` - 流水线状态模型测试
- `test_pipeline_task_propagation.py` - 流水线任务传播测试

#### `scheduler/` - 调度器

测试任务调度相关的功能。

**文件**:

- `test_scheduler_jobs.py` - 调度作业测试

#### `search/` - 搜索

测试搜索相关的组件，包括 BM25、重排序、混合搜索等。

**文件**:

- `test_bm25_index_service.py` - BM25 索引服务测试
- `test_bm25_retriever.py` - BM25 检索器测试
- `test_drift_search.py` - Drift 搜索测试
- `test_flashrank_reranker.py` - FlashRank 重排序器测试
- `test_hybrid_search.py` - 混合搜索测试
- `test_mmr_reranker.py` - MMR 重排序器测试
- `test_relation_search.py` - 关系搜索测试
- `test_rrf.py` - RRF(Reciprocal Rank Fusion) 测试
- `test_temporal_decay.py` - 时间衰减测试
- `test_search_api.py` - 搜索 API 测试
- `test_local_search.py` - 本地搜索测试
- `test_global_search.py` - 全局搜索测试
- `test_edge_query_semantic.py` - 边查询语义测试

#### `source/` - 数据源管理

测试数据源的配置、调度、权限管理等。

**文件**:

- `test_source_authority_repo.py` - 数据源权限仓库测试
- `test_source_base.py` - 数据源基础测试
- `test_source_config_model.py` - 数据源配置模型测试
- `test_source_config_repo.py` - 数据源配置仓库测试
- `test_source_plugin.py` - 数据源插件测试
- `test_source_registry.py` - 数据源注册表测试
- `test_source_scheduler.py` - 数据源调度器测试
- `test_sources_api.py` - 数据源 API 测试

#### `storage/` - 存储（预留）

预留给未来的存储相关测试，包括文件系统、对象存储等。

### `neo4j/` - Neo4j 数据库测试

测试 Neo4j 数据库相关的操作。

**文件**:

- `test_neo4j_article_repo.py` - Neo4j 文章仓库测试
- `test_neo4j_config_toggle.py` - Neo4j 配置切换测试
- `test_neo4j_entity_repo.py` - Neo4j 实体仓库测试
- `test_neo4j_writer.py` - Neo4j 写入器测试
- `test_vector_repo.py` - 向量仓库测试
- `test_vectorize.py` - 向量化测试

### `postgres/` - PostgreSQL 数据库测试

预留给 PostgreSQL 特定的测试。

**当前状态**:
PostgreSQL 相关测试目前分布在：

- `tests/unit/core/test_db_initializer.py` - 数据库初始化
- `tests/unit/core/test_health.py` - 健康检查
- `tests/unit/core/test_pre_startup_health.py` - 启动前检查

**未来扩展**:
当需要添加 PostgreSQL 特定功能的深度测试时，在此目录创建专门的测试文件。

### `redis/` - Redis 缓存测试

预留给 Redis 特定的测试。

**当前状态**:
Redis 相关测试目前分布在：

- `tests/unit/core/test_health.py` - 健康检查
- `tests/unit/core/test_pre_startup_health.py` - 启动前检查

**未来扩展**:
当需要添加 Redis 特定功能的深度测试时（如缓存策略、分布式锁等），在此目录创建专门的测试文件。

## 🎯 测试运行

### 运行所有单元测试

```bash
python -m pytest tests/unit/ -v
```

### 运行特定目录的测试

```bash
# 运行 API 层测试
python -m pytest tests/unit/api/ -v

# 运行核心功能测试
python -m pytest tests/unit/core/ -v

# 运行 Neo4j 测试
python -m pytest tests/unit/neo4j/ -v

# 运行特定模块测试
python -m pytest tests/unit/modules/llm/ -v
```

### 运行特定文件的测试

```bash
python -m pytest tests/unit/api/test_api.py -v
```

### 查看测试覆盖率

```bash
python -m pytest tests/unit/ --cov=src --cov-report=html
```

## 📝 命名规范

### 测试文件命名

- 文件名格式：`test_<module_or_feature>.py`
- 例如：`test_api.py`, `test_health.py`, `test_pipeline_config.py`

### 测试类命名

- 类名格式：`Test<ClassName>` 或 `Test<FeatureName>`
- 例如：`TestHealthChecker`, `TestPipelineConfig`

### 测试函数命名

- 函数名格式：`test_<method_name>_<scenario>_<expected_result>`
- 例如：`test_check_postgres_success`, `test_check_redis_failure`

## ✅ 测试标准

根据项目规范，新功能测试必须满足以下要求：

1. **单元测试覆盖率**: ≥80%
2. **边界条件测试**: 必须覆盖所有边界情况
3. **异常处理测试**: 必须测试错误处理路径
4. **正常流程测试**: 必须测试主要功能
5. **集成测试**: 对于涉及多个组件的功能，需要集成测试
6. **端到端测试**: 对于关键业务流程，需要 E2E 测试
7. **性能测试**: 对于性能敏感的代码，需要性能测试

## 🔧 配置文件

测试配置位于：

- `pytest.ini` - Pytest 主配置
- `pyproject.toml` - 补充配置和工具配置

关键配置项：

```ini
[pytest]
testpaths = tests
pythonpath = src
asyncio_mode = auto
addopts = -m "not integration and not e2e" -n auto
```

## 📚 相关文档

- [单元测试编写指南](../../../docs/TESTING.md)
- [测试覆盖率要求](../../../docs/TESTING.md#coverage-requirements)
- [Pytest 使用手册](https://docs.pytest.org/)
