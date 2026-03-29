# 变更日志

所有显著的更改都将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
并且本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/) 规范。

---

## [Unreleased]

### Added
- 新增 DRIFT 搜索功能，支持迭代式探索性搜索
- 新增社区检测自动调度器
- 新增关系类型种子数据脚本

### Changed
- 优化 GraphRAG 合并后的测试兼容性
- 改进 LLM 配置管理器和队列管理器

### Fixed
- 修复存储层无效的 BaseRepository 导入

---

## [0.1.0] - 2024-01-15

### Added

#### 核心功能
- **RSS 源管理**：支持订阅、调度、解析 RSS/Atom 源
- **智能爬取**：自动选择 HTTPX 或 Playwright，支持动态页面渲染
- **LLM 处理流水线**：分类、清洗、摘要、情感分析、实体提取
- **知识图谱**：Neo4j 存储实体关系，支持图谱查询
- **向量检索**：pgvector 支持语义相似度搜索
- **可信度评估**：多维度信号聚合计算新闻可信度
- **REST API**：FastAPI 提供完整 API 接口

#### 搜索功能
- **统一搜索端点**：自动路由到合适的搜索引擎
- **本地搜索**：实体聚焦的图谱问答搜索
- **全局搜索**：社区级聚合搜索（Map-Reduce 模式）
- **混合文章搜索**：向量 + BM25 + 重排的混合检索
- **DRIFT 搜索**：迭代式探索性搜索（实验性）

#### 社区检测
- **Hierarchical Leiden 算法**：发现知识图谱中的社区结构
- **社区报告生成**：LLM 驱动的社区语义摘要
- **社区指标**：模块度、层次结构、孤立实体统计
- **自动触发机制**：基于实体变化阈值自动重建

#### 数据一致性
- **Saga 模式**：跨数据库（PostgreSQL + Neo4j）原子性批量持久化
- **PersistStatus 状态机**：追踪文章持久化状态
- **定期对账任务**：异步检查和修复数据不一致
- **补偿事务**：Neo4j 失败时回滚 PostgreSQL

#### 可观测性
- **健康检查端点**：Kubernetes 探针支持
- **Prometheus 指标**：HTTP、Circuit Breaker、数据库、Pipeline 指标
- **OpenTelemetry 集成**：分布式追踪支持
- **结构化日志**：Loguru 日志记录

#### 安全特性
- **SSRF 防护**：多层 URL 验证（协议、IP、主机名、重定向）
- **API Key 认证**：请求头认证机制
- **速率限制**：基于 Redis 的滑动窗口限流
- **依赖注入**：FastAPI Depends 模式管理服务和生命周期

#### 开发工具
- **分层测试**：单元测试、集成测试、E2E 测试
- **性能测试**：HNSW 向量索引性能基准
- **代码质量工具**：Ruff、Black、isort、mypy、bandit
- **数据库迁移**：Alembic 版本控制

### Technical Details

#### 技术栈
- Python 3.12+
- FastAPI 0.135+
- PostgreSQL 15+ with pgvector
- Neo4j 5+
- Redis 7+
- LangChain / LangGraph
- spaCy NLP
- Playwright

#### 架构亮点
- **依赖注入架构**：松耦合、高可测试性
- **Circuit Breaker 线程安全设计**：asyncio.Lock 保护
- **向量索引**：HNSW 索引优化相似性搜索
- **Pipeline 编排**：LangGraph 状态机管理

---

## 版本说明

### 版本号规则

版本号格式：`MAJOR.MINOR.PATCH`

- **MAJOR**：不兼容的 API 更改
- **MINOR**：向下兼容的功能添加
- **PATCH**：向下兼容的问题修复

### 变更类型说明

- **Added**：新增功能
- **Changed**：现有功能的变更
- **Deprecated**：已弃用功能
- **Removed**：已删除功能
- **Fixed**：Bug 修复
- **Security**：安全相关的修复

---

## 如何更新此文件

### 原则

1. **记录显著的更改**：用户关心的功能、修复、变更
2. **分类清晰**：使用标准变更类型标签
3. **时间倒序**：最新的版本放在最前面
4. **参考示例**：遵循 Keep a Changelog 的格式

### 模板

```markdown
## [X.Y.Z] - YYYY-MM-DD

### Added
- 新增功能描述

### Changed
- 功能变更描述

### Deprecated
- 即将移除的功能

### Removed
- 已移除的功能

### Fixed
- Bug 修复描述

### Security
- 安全修复描述
```

---

## 相关链接

- [GitHub Releases](https://github.com/your-org/weaver/releases)
- [Milestone](https://github.com/your-org/weaver/milestones)

---

**Contributors**: 感谢所有为 Weaver 做出贡献的开发者！

[Unreleased]: https://github.com/your-org/weaver/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/your-org/weaver/releases/tag/v0.1.0
