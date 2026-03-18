# 回滚脚本

本目录包含用于回滚 P0/P1 级修复的脚本。

## 脚本列表

### 1. rollback_health_endpoint.sh

**用途**: 回滚健康检查端点

**功能**:
- 注释 `src/main.py` 中的 `/health` 端点定义
- 注释健康检查相关导入
- 创建备份文件
- 验证 Python 语法

**使用方法**:
```bash
# 实际执行
./rollback_health_endpoint.sh

# 模拟执行（不修改文件）
./rollback_health_endpoint.sh --dry-run
```

**影响**:
- 移除 `/health` 端点
- 移除依赖健康检查功能
- 应用仍可正常启动

**回滚时间**: < 1 分钟

**风险评估**: 低风险
- 不影响数据库
- 可快速恢复（使用备份文件）

---

### 2. rollback_saga_pattern.sh

**用途**: 回滚 Saga 模式持久化

**功能**:
- 注释 `src/modules/pipeline/nodes/batch_merger.py` 中的 `persist_batch_saga()` 方法
- 检查并提示调用代码修改
- 创建备份文件
- 验证 Python 语法

**使用方法**:
```bash
# 实际执行
./rollback_saga_pattern.sh

# 模拟执行（不修改文件）
./rollback_saga_pattern.sh --dry-run
```

**影响**:
- 移除跨数据库原子性保证
- 需要修改调用 `persist_batch_saga()` 的代码
- 可能影响数据处理流程

**回滚时间**: < 5 分钟（不包括代码修改）

**风险评估**: 中等风险
- 需要修改调用代码
- 可能影响数据处理一致性
- 建议在测试环境验证后再在生产环境执行

**注意事项**:
- 执行前确认已了解 Saga 模式的实现
- 准备好替代的持久化逻辑
- 完整测试数据处理流程

---

### 3. rollback_hnsw_index.sh

**用途**: 回滚 HNSW 向量索引

**功能**:
- 使用 Alembic downgrade 回滚数据库迁移
- 删除 `article_vectors` 表的 HNSW 索引
- 删除 `entity_vectors` 表的 HNSW 索引
- 备份迁移状态
- 验证索引已删除

**使用方法**:
```bash
# 实际执行
./rollback_hnsw_index.sh

# 模拟执行（不修改数据库）
./rollback_hnsw_index.sh --dry-run
```

**影响**:
- 向量相似性查询性能下降（可能 10x - 100x）
- 数据库表持有锁，可能影响并发操作
- 查询响应时间增加

**回滚时间**: 5 - 30 分钟（取决于数据量）

**风险评估**: 高风险
- 需要数据库连接
- 在表上持有锁
- 影响查询性能
- 建议在低峰期执行

**注意事项**:
- 确保数据库连接正常
- 在低峰期执行
- 监控数据库性能
- 准备好恢复计划

---

### 4. master_rollback.sh

**用途**: 主回滚脚本，协调所有回滚操作

**功能**:
- 提供统一的回滚入口
- 支持选择性回滚特定组件
- 按顺序执行多个回滚操作
- 提供详细的执行日志

**使用方法**:
```bash
# 回滚所有组件
./master_rollback.sh

# 模拟回滚所有组件
./master_rollback.sh --dry-run

# 仅回滚特定组件
./master_rollback.sh -c health -c saga

# 模拟回滚特定组件
./master_rollback.sh -c hnsw --dry-run
```

**支持的组件**:
- `health` - 健康检查端点
- `saga` - Saga 模式
- `hnsw` - HNSW 索引
- `all` - 所有组件（默认）

**执行顺序**:
1. 健康检查端点
2. Saga 模式
3. HNSW 索引

**日志**: 所有操作记录到 `logs/master_rollback_<timestamp>.log`

---

## 通用特性

所有脚本都包含以下特性:

### 1. Dry-run 模式
使用 `--dry-run` 或 `-n` 参数模拟执行，不实际修改文件或数据库

### 2. 确认提示
实际执行前会要求用户确认（除了 dry-run 模式）

### 3. 详细日志
- 所有操作记录到日志文件
- 日志位置: `logs/rollback_<component>_<timestamp>.log`
- 包含时间戳、操作步骤、错误信息

### 4. 错误处理
- 自动检测错误并停止执行
- 失败时自动恢复备份
- 清晰的错误消息

### 5. 验证步骤
- 文件修改后验证 Python 语法
- 数据库操作后验证结果
- 显示详细的执行结果

### 6. 备份机制
- 文件修改前自动创建备份
- 备份位置: `.rollback_backups/`
- 备份文件包含时间戳

---

## 执行流程

### 标准流程

1. **准备阶段**
   ```bash
   # 检查脚本权限
   ls -l scripts/rollback/

   # 查看帮助信息
   ./master_rollback.sh --help
   ```

2. **模拟执行**
   ```bash
   # 模拟回滚所有组件
   ./master_rollback.sh --dry-run

   # 查看模拟执行日志
   tail -f logs/master_rollback_*.log
   ```

3. **实际执行**
   ```bash
   # 回滚所有组件
   ./master_rollback.sh

   # 或选择性回滚
   ./master_rollback.sh -c health -c saga
   ```

4. **验证结果**
   ```bash
   # 检查应用启动
   python -m src.main

   # 运行测试
   pytest tests/

   # 检查日志
   tail -f logs/app.log
   ```

5. **监控性能**
   ```bash
   # 监控数据库查询性能
   # (如回滚了 HNSW 索引)

   # 监控应用健康
   curl http://localhost:8000/health
   ```

---

## 恢复操作

### 从备份恢复

所有备份文件存储在 `.rollback_backups/` 目录:

```bash
# 查看备份
ls -l .rollback_backups/

# 恢复文件
cp .rollback_backups/main.py.backup_<timestamp> src/main.py
cp .rollback_backups/batch_merger.py.backup_<timestamp> src/modules/pipeline/nodes/batch_merger.py
```

### 使用 Alembic 恢复

如果回滚了 HNSW 索引:

```bash
cd src/

# 查看当前版本
alembic current

# 恢复到最新版本
alembic upgrade head

# 验证版本
alembic current
```

---

## 注意事项

### 执行前

1. **备份数据**: 确保数据库已备份
2. **测试验证**: 在测试环境先验证
3. **选择时机**: 在低峰期执行
4. **检查依赖**: 确认数据库连接正常

### 执行中

1. **监控日志**: 实时查看日志输出
2. **不要中断**: 让脚本完整执行
3. **记录结果**: 保存日志文件

### 执行后

1. **验证功能**: 运行测试套件
2. **监控性能**: 观察系统性能指标
3. **检查日志**: 查看应用日志是否有错误
4. **更新文档**: 记录回滚原因和结果

---

## 故障排查

### 问题 1: 脚本执行权限被拒绝

**解决方案**:
```bash
chmod +x scripts/rollback/*.sh
```

### 问题 2: 数据库连接失败

**检查项**:
- 数据库服务是否运行
- 环境变量是否配置正确
- 网络连接是否正常

**解决方案**:
```bash
# 检查数据库服务
docker ps | grep postgres

# 检查环境变量
echo $DATABASE_URL

# 测试连接
psql $DATABASE_URL -c "SELECT 1;"
```

### 问题 3: Python 语法验证失败

**原因**: 注释代码后可能破坏语法结构

**解决方案**:
- 检查错误日志
- 手动编辑文件修复语法
- 从备份恢复

### 问题 4: Alembic 迁移失败

**检查项**:
- 迁移文件是否存在
- 数据库权限是否足够
- 表是否被锁定

**解决方案**:
```bash
# 查看迁移历史
alembic history

# 检查数据库锁
psql $DATABASE_URL -c "SELECT * FROM pg_locks;"

# 手动执行 SQL
# (参考迁移文件中的 downgrade() 方法)
```

---

## 联系方式

如有问题，请联系:
- 开发团队: dev@example.com
- 运维团队: ops@example.com

---

## 更新日志

- 2026-03-18: 初始版本，包含健康检查、Saga 模式、HNSW 索引回滚脚本