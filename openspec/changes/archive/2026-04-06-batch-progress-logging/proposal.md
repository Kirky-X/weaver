## Why

当前 `process_batch` 仅在开始和结束时有日志输出，无法实时了解批次处理进度和健康状况。运维人员难以监控长时间运行的批处理任务，无法及时发现处理异常。

## What Changes

- 在 Pipeline 类中添加批次进度追踪计数器
- 每条资讯处理完成后输出进度统计日志
- 日志包含：总文章数、已完成数、失败数、成功率、当前 URL

## Capabilities

### New Capabilities

- `batch-progress-tracking`: 批次进度追踪能力，实时输出资讯处理进度统计

### Modified Capabilities

无

## Impact

- **代码改动**: `src/modules/processing/pipeline/graph.py`（约 20-30 行新增）
- **日志输出**: 新增进度日志，每条资讯一条，不影响现有日志格式
- **性能**: 无影响，仅计数器操作
- **依赖**: 无新增依赖