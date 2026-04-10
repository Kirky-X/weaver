## 1. 基础设施准备

- [x] 1.1 创建 `src/core/db/safe_query.py` 参数化查询工具函数
- [x] 1.2 创建 `src/core/protocols/services.py` 服务层 Protocol 定义
- [x] 1.3 创建 `src/core/security/signing.py` HMAC 签名验证工具

## 2. SQL 注入修复 - migration 模块

- [x] 2.1 重构 `ladybug_source.py` 使用参数化 SQL 查询
- [x] 2.2 为 ladybug_source.py 添加输入验证（label、property）
- [x] 2.3 编写 ladybug_source.py 安全查询单元测试
- [x] 2.4 重构 `neo4j_source.py` 使用参数化 Cypher 查询
- [x] 2.5 为 neo4j_source.py 添加 label 白名单验证
- [x] 2.6 编写 neo4j_source.py 安全查询单元测试

## 3. SQL/Cypher 注入修复 - core 模块

- [x] 3.1 重构 `graph_query.py` LadybugQueryBuilder 使用参数化查询
- [x] 3.2 重构 `graph_query.py` Neo4jQueryBuilder 使用参数化查询
- [x] 3.3 添加节点标签和关系类型验证函数
- [x] 3.4 编写 graph_query.py 参数化查询测试

## 4. Cypher 注入修复 - knowledge 模块

- [x] 4.1 重构 `local_context.py` 的 Cypher 字符串拼接为参数化查询
- [x] 4.2 为 local_context.py 添加 entity_id、community_id 输入验证
- [x] 4.3 编写 local_context.py 安全查询单元测试

## 5. Pickle 反序列化修复

- [x] 5.1 重构 `bm25_retriever.py` 使用 JSON 格式存储索引
- [x] 5.2 实现索引文件 HMAC 签名验证
- [x] 5.3 添加签名密钥配置（环境变量 `INDEX_SIGNING_KEY`）
- [x] 5.4 实现旧格式索引迁移支持
- [x] 5.5 编写索引签名验证和迁移测试

## 6. 服务层解耦 - management 模块

- [x] 6.1 定义 `PipelineService` Protocol 接口
- [x] 6.2 创建 `PipelineServiceImpl` 实现
- [x] 6.3 在容器中注册 PipelineService
- [x] 6.4 重构 `repair_articles.py` 使用服务接口
- [x] 6.5 移除 repair_articles.py 对 pipeline 内部方法的直接调用
- [x] 6.6 修复 Pipeline 直接使用 SQLAlchemy 违反仓储模式
- [x] 6.7 编写服务层集成测试

## 7. API 依赖注入重构

- [x] 7.1 创建 `get_container` FastAPI dependency 函数
- [x] 7.2 重构 `graph.py` 移除 `_pg_pool` 全局变量
- [x] 7.3 重构 `health.py` 使用公共接口检查状态
- [x] 7.4 创建 `TaskRegistry` 追踪后台任务
- [x] 7.5 重构 `pipeline.py` 注册后台任务到 TaskRegistry
- [x] 7.6 修复 `admin.py` description 字段传递问题
- [x] 7.7 编写 API endpoint 依赖注入测试

## 8. 安全审计增强

- [x] 8.1 更新 Bandit 配置检测 SQL/Cypher 注入模式
- [x] 8.2 添加启动时注入漏洞审计日志
- [x] 8.3 更新安全文档说明新防护机制

## 9. 测试与验证

- [x] 9.1 运行完整测试套件确保无回归
- [x] 9.2 运行 Bandit 安全扫描确认无 HIGH/CRITICAL 问题
- [x] 9.3 手动测试注入攻击防护效果
- [x] 9.4 验证旧索引迁移功能正常工作