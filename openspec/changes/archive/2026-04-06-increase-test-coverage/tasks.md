## 1. DuckDB 测试覆盖 (优先级: 高)

- [x] 1.1 创建 `tests/unit/core/db/test_duckdb_handler.py` 测试文件
- [x] 1.2 实现连接初始化测试 (成功、缺失文件、清理资源)
- [x] 1.3 实现查询执行测试 (正常结果、空结果、语法错误)
- [x] 1.4 实现事务支持测试 (提交、回滚)
- [x] 1.5 运行测试验证覆盖率提升

## 2. SpaCy NLP 提取器测试覆盖 (优先级: 高)

- [x] 2.1 扩展 `tests/unit/modules/processing/nlp/test_spacy_extractor.py`
- [x] 2.2 实现多实体类型提取测试 (PERSON, ORG, GPE)
- [x] 2.3 实现语言检测和模型选择测试
- [x] 2.4 实现边缘情况测试 (空文本、长文本、特殊字符)
- [x] 2.5 运行测试验证覆盖率提升

## 3. 图度量计算测试覆盖 (优先级: 中)

- [x] 3.1 扩展 `tests/unit/modules/knowledge/graph/test_metrics.py`
- [x] 3.2 实现节点度数计算测试 (入度、出度、孤立节点)
- [x] 3.3 实现社区检测度量测试 (模块度、大小分布)
- [x] 3.4 实现边权重计算测试 (加权中心性、零权重处理)
- [x] 3.5 运行测试验证覆盖率提升

## 4. 增量社区更新测试覆盖 (优先级: 中)

- [x] 4.1 扩展 `tests/unit/modules/knowledge/graph/test_incremental_community_updater.py`
- [x] 4.2 实现增量更新测试 (新增实体、删除实体、批量更新)
- [x] 4.3 实现失败回滚测试 (部分更新回滚、一致性保持)
- [x] 4.4 实现并发更新测试 (序列化、冲突检测)
- [x] 4.5 运行测试验证覆盖率提升

## 5. 批量合并测试覆盖 (优先级: 中)

- [x] 5.1 扩展 `tests/unit/modules/processing/nodes/test_batch_merger.py`
- [x] 5.2 实现实体合并测试 (精确匹配、相似度阈值、不同实体)
- [x] 5.3 实现冲突解决测试 (属性冲突、关系冲突)
- [x] 5.4 实现性能测试 (大批量、内存限制)
- [x] 5.5 运行测试验证覆盖率提升

## 6. 验证与收尾

- [x] 6.1 运行完整测试套件验证所有测试通过
- [x] 6.2 使用 `uv run pytest --cov=src --cov-report=term-missing` 验证覆盖率达到 85%
- [x] 6.3 确认无新增警告或错误
- [x] 6.4 更新测试覆盖率报告