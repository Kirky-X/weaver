# Proposal: 统一Pipeline测试脚本

## 问题陈述

当前存在两个独立的pipeline测试脚本：

1. **`scripts/test_pipeline.py`** (~700行)
   - 支持三种测试模式：newsnow / rss / strategy
   - 功能完整：数据获取、管道执行、验证、清理
   - **问题**：直接调用Python内部接口，不符合API测试原则

2. **`scripts/test_pipeline_api.py`** (~318行)
   - 通过HTTP API进行所有操作
   - **问题**：仅支持NewsNow模式，验证仍直接访问数据库

需要创建一个统一脚本，结合两者优点：支持所有测试模式，同时确保所有交互通过HTTP API完成。

## 解决方案

创建新脚本 `scripts/test_pipeline_api_unified.py`，实现：

1. **所有交互通过HTTP API**
   - 创建源：`POST /api/v1/sources`
   - 触发管道：`POST /api/v1/pipeline/trigger`
   - 监控任务：`GET /api/v1/pipeline/tasks/{task_id}`
   - 验证结果：`GET /api/v1/articles`、Graph API

2. **保留三种测试模式**
   - `--mode newsnow`：NewsNow数据源测试
   - `--mode rss`：RSS数据源测试
   - `--mode strategy`：数据库故障转移策略测试

3. **保留必要的基础设施操作**
   - `--clear-db`：保留直接清理逻辑（API无此端点）
   - Strategy模式的服务器启动配置

4. **移除不必要功能**
   - `--force-news`：跳过（API不支持）

## 成功标准

- [ ] 所有测试模式通过HTTP API执行
- [ ] 命令行参数简洁直观
- [ ] 三种模式都能正确验证数据存储
- [ ] 旧脚本直接删除，无兼容性要求

## 非目标

- 不修改现有API端点
- 不添加新的API端点（如数据库清理）
- **不需要向后兼容**：旧脚本直接删除，可自由改变参数和结构

## 风险与依赖

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Strategy模式需要基础设施配置 | 中 | 通过环境变量控制，与原脚本一致 |
| 数据库清理绕过API原则 | 低 | 文档说明原因，用户明确接受 |
| API响应时间影响测试性能 | 低 | 添加超时参数，默认300秒 |

## 时间线

- **阶段1**：实现核心框架和NewsNow模式 (2-3小时)
- **阶段2**：添加RSS模式支持 (1小时)
- **阶段3**：添加Strategy模式支持 (1小时)
- **阶段4**：测试验证和文档更新 (1小时)