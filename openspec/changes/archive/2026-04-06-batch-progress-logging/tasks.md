## 1. 数据结构

- [x] 1.1 在 Pipeline 类 `__init__` 中添加 `_batch_total`、`_batch_completed`、`_batch_failed` 实例属性

## 2. 计数器管理

- [x] 2.1 在 `process_batch` 入口处重置三个计数器

## 3. 进度记录逻辑

- [x] 3.1 在 `_persist_batch` 中实现成功计数逻辑：文章成功持久化后递增 `_batch_completed`
- [x] 3.2 在 `_persist_batch` 中实现失败计数逻辑：持久化失败时递增 `_batch_failed`
- [x] 3.3 在 `_persist_batch` 中实现 terminal 文章跳过逻辑：不计入任何计数

## 4. 日志输出

- [x] 4.1 实现进度日志格式化函数：生成 `[{completed}/{total}] {rate}% success ({failed} failed) | {url}` 格式
- [x] 4.2 在每条资讯持久化完成后输出进度日志

## 5. 测试验证

- [x] 5.1 验证单篇文章成功处理的日志输出
- [x] 5.2 验证持久化失败时失败计数正确递增
- [x] 5.3 验证 terminal 文章不计入统计
- [x] 5.4 验证多批次连续处理时计数器正确重置