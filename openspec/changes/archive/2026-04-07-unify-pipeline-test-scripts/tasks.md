# Tasks: 统一Pipeline测试脚本

## Phase 1: 核心框架

### Task 1.1: 创建脚本骨架和CLI解析
- [x] 创建 `scripts/test_pipeline_api_unified.py`
- [x] 实现argparse命令行参数解析
- [x] 实现phase_header和step辅助函数
- [x] 实现main()入口和asyncio.run()

### Task 1.2: 实现API客户端类
- [x] 创建 `PipelineAPIClient` 类
- [x] 实现 `create_source()` 方法
- [x] 实现 `trigger_pipeline()` 方法
- [x] 实现 `get_task_status()` 方法
- [x] 实现 `list_articles()` 方法

### Task 1.3: 实现服务器管理
- [x] 实现 `start_server()` 函数
- [x] 实现 `shutdown_server()` 函数

## Phase 2: 三种测试模式

### Task 2.1: NewsNow模式
- [x] 实现 `run_newsnow_test()` 函数
- [x] 创建NewsNow源配置

### Task 2.2: RSS模式
- [x] 实现 `run_rss_test()` 函数
- [x] 定义RSS源配置（solidot, cnbeta, huxiu）

### Task 2.3: Strategy模式
- [x] 实现 `setup_strategy_mode()` 函数（环境变量配置）
- [x] 实现 `run_strategy_test()` 函数
- [x] 验证fallback数据库类型

## Phase 3: 数据库清理

### Task 3.1: 实现数据库清理功能
- [x] 实现 `clear_databases()` 函数
- [x] DuckDB/PostgreSQL表清理
- [x] LadybugDB/Neo4j节点清理

## Phase 4: 验证和清理

### Task 4.1: 端到端测试
- [x] 测试NewsNow模式
- [x] 测试RSS模式
- [x] 测试Strategy模式
- [x] 测试--clear-db参数（代码已实现）

### Task 4.2: 清理旧脚本
- [x] 删除 `scripts/test_pipeline.py`
- [x] 删除 `scripts/test_pipeline_api.py`
- [x] 重命名新脚本为 `scripts/test_pipeline.py`

## 依赖关系

```
Phase 1 (核心框架)
    │
    └──▶ Phase 2 (三种模式)
             │
             └──▶ Phase 3 (数据库清理)
                      │
                      └──▶ Phase 4 (验证和清理)
```

## 预估时间

| Phase | 预估时间 |
|-------|----------|
| Phase 1 | 1.5小时 |
| Phase 2 | 2小时 |
| Phase 3 | 0.5小时 |
| Phase 4 | 1小时 |
| **总计** | **5小时** |