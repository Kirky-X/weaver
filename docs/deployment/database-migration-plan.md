# 数据库迁移计划：HNSW 索引部署

## 文档信息

- **迁移版本**: e283f4aed36a
- **迁移名称**: add_hnsw_indexes_to_vector_tables
- **创建日期**: 2026-03-18
- **目标**: 为 `article_vectors` 和 `entity_vectors` 表添加 HNSW 索引
- **影响范围**: PostgreSQL 向量查询性能

---

## 1. 执行摘要

### 1.1 迁移目标

为向量相似性搜索添加 HNSW (Hierarchical Navigable Small World) 索引，提升查询性能：

- **目标表**: `article_vectors`, `entity_vectors`
- **索引类型**: HNSW (pgvector)
- **向量维度**: 1024
- **距离度量**: 余弦相似度 (vector_cosine_ops)
- **索引参数**: m=16, ef_construction=64

### 1.2 预期收益

- **查询性能提升**: 相比暴力搜索，查询时间降低 50-90%
- **召回率**: 保持在 90-95% 以上
- **存储开销**: 索引大小约为原始向量数据的 1.5-2 倍

### 1.3 关键风险

| 风险 | 等级 | 缓解措施 |
|------|------|----------|
| 索引创建时间长 | 高 | 在低峰期执行，使用 CONCURRENTLY |
| 磁盘空间不足 | 中 | 预先检查磁盘空间，预留 3 倍向量数据大小 |
| 内存溢出 | 中 | 监控内存使用，准备回滚方案 |
| 索引创建失败 | 低 | 自动回滚，保留原始状态 |

---

## 2. HNSW 索引创建时间估算

### 2.1 时间估算表

基于 PostgreSQL pgvector 和 AWS RDS 实例（db.r6g.xlarge, 4 vCPU, 32GB RAM）的性能基准：

| 数据量级别 | 向量数量 | 索引创建时间（单表） | 磁盘空间需求 | 内存需求 |
|-----------|---------|---------------------|-------------|---------|
| 小型 | 10 万 | 2-3 分钟 | 300 MB | 2 GB |
| 中型 | 50 万 | 8-12 分钟 | 1.5 GB | 4 GB |
| 中大型 | 100 万 | 15-25 分钟 | 3 GB | 6 GB |
| 大型 | 500 万 | 1.5-2.5 小时 | 15 GB | 12 GB |
| 超大型 | 1000 万 | 3-5 小时 | 30 GB | 20 GB |

**注意**:
- 时间为单表索引创建时间，两个表需分别执行
- 使用 `CONCURRENTLY` 不会阻塞读写操作，但创建时间会增加 10-20%
- 实际时间受硬件配置、并发负载、磁盘 I/O 影响

### 2.2 影响时间的关键因素

#### 2.2.1 HNSW 参数影响

| 参数 | 当前值 | 影响 | 调优建议 |
|------|-------|------|---------|
| m | 16 | 每个节点的最大连接数 | 更大值提高召回率，但增加构建时间和内存 |
| ef_construction | 64 | 构建时候选列表大小 | 更大值提高索引质量，但增加构建时间 |

**调优场景**:
- **快速构建**: m=8, ef_construction=32 (时间减少 30-40%，召回率降低 5-10%)
- **高召回率**: m=32, ef_construction=128 (时间增加 50-80%，召回率提升 2-5%)

#### 2.2.2 硬件配置建议

| 配置级别 | CPU | 内存 | 磁盘 | 适用场景 |
|---------|-----|------|------|---------|
| 最小配置 | 4 核 | 16 GB | SSD 100 GB | < 100 万向量 |
| 推荐配置 | 8 核 | 32 GB | SSD 500 GB | 100-500 万向量 |
| 高性能配置 | 16 核 | 64 GB | NVMe 1 TB | > 500 万向量 |

---

## 3. 迁移前准备工作

### 3.1 数据备份

#### 3.1.1 数据库完整备份

```bash
# 备份整个数据库
pg_dump -h localhost -U postgres -d weaver -F c -f /backup/weaver_pre_hnsw_$(date +%Y%m%d_%H%M%S).dump

# 仅备份向量表（可选，节省时间）
pg_dump -h localhost -U postgres -d weaver -t article_vectors -t entity_vectors -F c -f /backup/vectors_pre_hnsw_$(date +%Y%m%d_%H%M%S).dump
```

#### 3.1.2 迁移状态备份

```bash
# 备份当前 Alembic 迁移状态
cd /home/dev/projects/weaver/src
alembic history > /backup/alembic_history_$(date +%Y%m%d_%H%M%S).txt
alembic current >> /backup/alembic_history_$(date +%Y%m%d_%H%M%S).txt
```

### 3.2 系统资源检查

#### 3.2.1 磁盘空间检查

```bash
# 检查磁盘空间（需要至少 3 倍向量数据大小）
df -h /var/lib/postgresql

# 检查向量表大小
psql -h localhost -U postgres -d weaver -c "
SELECT
  tablename,
  pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size,
  pg_total_relation_size(schemaname||'.'||tablename) as bytes
FROM pg_tables
WHERE tablename IN ('article_vectors', 'entity_vectors')
ORDER BY bytes DESC;
"
```

**最小磁盘空间要求**:
```
向量表大小 × 3 + 20 GB (安全余量)
```

#### 3.2.2 内存检查

```bash
# 检查系统内存
free -h

# 检查 PostgreSQL 配置
psql -h localhost -U postgres -d weaver -c "
SHOW shared_buffers;
SHOW work_mem;
SHOW maintenance_work_mem;
"
```

**推荐配置**:
- `shared_buffers`: 总内存的 25%
- `work_mem`: 256 MB
- `maintenance_work_mem`: 1 GB (索引创建时临时提升)

#### 3.2.3 连接数检查

```bash
# 检查当前连接数
psql -h localhost -U postgres -d weaver -c "
SELECT count(*) as active_connections
FROM pg_stat_activity
WHERE datname = 'weaver';
"
```

### 3.3 监控准备

#### 3.3.1 启用性能监控

```bash
# 在 PostgreSQL 中启用性能统计
psql -h localhost -U postgres -d weaver -c "
ALTER SYSTEM SET track_activities = on;
ALTER SYSTEM SET track_counts = on;
ALTER SYSTEM SET track_io_timing = on;
ALTER SYSTEM SET track_functions = 'pl';
SELECT pg_reload_conf();
"
```

#### 3.3.2 配置监控仪表盘

确保以下监控指标可见：
- PostgreSQL 连接数
- 磁盘 I/O 使用率
- 内存使用率
- 活跃查询数
- 索引创建进度

#### 3.3.3 准备告警规则

临时提高以下告警阈值（迁移期间）：
- CPU 使用率告警：90% → 95%
- 磁盘 I/O 告警：80% → 95%
- 连接数告警：80% → 90%

### 3.4 回滚准备

#### 3.4.1 验证回滚方案

**注意**: 项目已移除回滚脚本，推荐使用 Git 回滚或 Alembic 迁移管理。

**推荐回滚方式**:
```bash
# 方式 1: 使用 Alembic downgrade
cd /home/dev/projects/weaver/src
alembic downgrade -1  # 回滚到上一个版本

# 方式 2: 使用 Git revert（如果迁移通过 commit 提交）
git revert <migration-commit-hash>

# 方式 3: 从备份恢复
pg_restore -h localhost -U postgres -d weaver \
  --clean --if-exists \
  -t article_vectors -t entity_vectors \
  /backup/vectors_pre_hnsw.dump
```

#### 3.4.2 准备回滚检查清单

- [ ] 回滚脚本可执行
- [ ] 数据库备份已创建
- [ ] 回滚执行窗口确认（预计 5-10 分钟）
- [ ] 回滚验证步骤明确

---

## 4. 详细迁移步骤

### 4.1 迁移执行阶段

#### 阶段 0: 前置检查（预计 5 分钟）

**目标**: 验证系统满足迁移前提条件

**执行步骤**:

```bash
# 1. 检查当前数据库状态
cd /home/dev/projects/weaver/src
alembic current

# 2. 验证向量表存在且有数据
psql -h localhost -U postgres -d weaver -c "
SELECT COUNT(*) as article_count FROM article_vectors;
SELECT COUNT(*) as entity_count FROM entity_vectors;
"

# 3. 检查磁盘空间
df -h /var/lib/postgresql

# 4. 检查系统负载
uptime

# 5. 验证环境变量配置（如需自定义参数）
echo "HNSW_M=${HNSW_M:-16}"
echo "HNSW_EF_CONSTRUCTION=${HNSW_EF_CONSTRUCTION:-64}"
```

**成功标准**:
- [x] 当前迁移版本为 c619ab9ba95a
- [x] 向量表存在且有数据
- [x] 磁盘空间充足（至少 3 倍向量数据大小）
- [x] 系统负载 < 2.0
- [x] 无活跃的长时间查询

**失败处理**: 任何检查失败 → 停止迁移，排查问题

---

#### 阶段 1: 数据备份（预计 10-30 分钟，取决于数据量）

**目标**: 创建完整数据备份，确保可恢复

**执行步骤**:

```bash
# 1. 创建备份目录
mkdir -p /home/dev/projects/weaver/.migration_backups/hnsw_$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/home/dev/projects/weaver/.migration_backups/hnsw_$(date +%Y%m%d_%H%M%S)"

# 2. 备份向量表结构和数据
pg_dump -h localhost -U postgres -d weaver \
  -t article_vectors -t entity_vectors \
  -F c -f "${BACKUP_DIR}/vectors_backup.dump"

# 3. 备份迁移状态
cd /home/dev/projects/weaver/src
alembic history > "${BACKUP_DIR}/alembic_history.txt"
alembic current > "${BACKUP_DIR}/alembic_current.txt"

# 4. 记录当前索引状态
psql -h localhost -U postgres -d weaver -c "
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename IN ('article_vectors', 'entity_vectors')
ORDER BY tablename, indexname;
" > "${BACKUP_DIR}/current_indexes.txt"

# 5. 验证备份文件
ls -lh "${BACKUP_DIR}/"
```

**成功标准**:
- [x] 备份文件创建成功
- [x] 备份文件大小合理（非空）
- [x] 迁移状态已记录
- [x] 当前索引状态已保存

**失败处理**: 备份失败 → 停止迁移，检查权限和磁盘空间

---

#### 阶段 2: 性能优化配置（预计 2 分钟）

**目标**: 临时调整 PostgreSQL 配置以加速索引创建

**执行步骤**:

```bash
# 1. 提升维护工作内存（仅当前会话）
psql -h localhost -U postgres -d weaver << 'EOF'
-- 记录原始配置
SHOW maintenance_work_mem;
SHOW max_parallel_maintenance_workers;

-- 临时提升配置
SET LOCAL maintenance_work_mem = '2GB';
SET LOCAL max_parallel_maintenance_workers = 4;

-- 验证配置
SHOW maintenance_work_mem;
SHOW max_parallel_maintenance_workers;
EOF
```

**注意**: 配置仅在当前会话有效，连接断开后自动恢复

**成功标准**:
- [x] maintenance_work_mem 提升至 2GB
- [x] max_parallel_maintenance_workers 设置为 4

---

#### 阶段 3: 执行迁移（预计 15 分钟 - 5 小时，取决于数据量）

**目标**: 创建 HNSW 索引

**执行步骤**:

```bash
# 1. 开始迁移
cd /home/dev/projects/weaver/src
alembic upgrade e283f4aed36a

# 2. 监控进度（另开终端）
watch -n 5 'psql -h localhost -U postgres -d weaver -c "
SELECT
  pid,
  now() - pg_stat_activity.query_start AS duration,
  query,
  state
FROM pg_stat_activity
WHERE (query NOT ILIKE '\''%pg_stat_activity%'\'' AND query NOT ILIKE '\''%idle%'\'')
ORDER BY duration DESC;
"'

# 3. 监控索引创建进度（另开终端）
watch -n 10 'psql -h localhost -U postgres -d weaver -c "
SELECT
  phase,
  round(100.0 * blocks_done / NULLIF(blocks_total, 0), 2) as progress_pct,
  blocks_done,
  blocks_total
FROM pg_stat_progress_create_index;
"'
```

**成功标准**:
- [x] Alembic 迁移成功完成，无错误
- [x] 索引创建进程正常退出
- [x] 日志中无错误或警告

**失败处理**:
- 迁移失败 → 检查日志 `/home/dev/projects/weaver/logs/alembic.log`
- 索引创建超时（> 预计时间的 2 倍）→ 考虑回滚并调整参数

---

#### 阶段 4: 索引验证（预计 5 分钟）

**目标**: 验证索引创建成功且可用

**执行步骤**:

```bash
# 1. 检查索引是否创建
psql -h localhost -U postgres -d weaver -c "
SELECT
  schemaname,
  tablename,
  indexname,
  pg_size_pretty(pg_relation_size(indexname::regclass)) as index_size
FROM pg_indexes
WHERE indexname LIKE '%hnsw%'
ORDER BY tablename;
"

# 2. 验证索引大小合理
psql -h localhost -U postgres -d weaver -c "
SELECT
  tablename,
  pg_size_pretty(pg_total_relation_size('article_vectors')) as total_size,
  pg_size_pretty(pg_relation_size('article_vectors')) as table_size,
  pg_size_pretty(pg_indexes_size('article_vectors')) as indexes_size
FROM pg_tables
WHERE tablename = 'article_vectors';
"

# 3. 测试索引是否被使用
psql -h localhost -U postgres -d weaver << 'EOF'
-- 生成随机查询向量（1024 维）
SET enable_seqscan = off;

EXPLAIN ANALYZE
SELECT article_id, 1 - (embedding <=> '[0.1,0.2,0.3,...]'::vector) as similarity
FROM article_vectors
ORDER BY embedding <=> '[0.1,0.2,0.3,...]'::vector
LIMIT 10;

RESET enable_seqscan;
EOF

# 4. 检查查询计划使用索引
psql -h localhost -U postgres -d weaver -c "
EXPLAIN (ANALYZE, BUFFERS)
SELECT article_id, embedding <=> '[0.1,0.2,...]'::vector as distance
FROM article_vectors
ORDER BY embedding <=> '[0.1,0.2,...]'::vector
LIMIT 10;
"
```

**成功标准**:
- [x] 两个 HNSW 索引存在（idx_article_vectors_hnsw, idx_entity_vectors_hnsw）
- [x] 索引大小合理（约为向量数据的 1.5-2 倍）
- [x] 查询计划显示使用 `Index Scan using idx_*_hnsw`
- [x] 查询时间 < 100ms（< 100 万向量）

**失败处理**:
- 索引未创建 → 检查迁移日志，重新执行
- 索引未被使用 → 分析查询计划，可能需要 `SET enable_seqscan = off` 测试

---

#### 阶段 5: 性能测试（预计 10 分钟）

**目标**: 验证索引带来预期的性能提升

**执行步骤**:

```bash
# 1. 运行性能测试套件
cd /home/dev/projects/weaver
pytest tests/performance/test_hnsw_performance.py -v --tb=short

# 2. 手动测试查询性能
psql -h localhost -U postgres -d weaver << 'EOF'
\timing on

-- 测试不同查询向量的性能
SELECT article_id, embedding <=> '[0.1,0.2,...]'::vector as distance
FROM article_vectors
ORDER BY embedding <=> '[0.1,0.2,...]'::vector
LIMIT 10;

SELECT article_id, embedding <=> '[0.5,0.6,...]'::vector as distance
FROM article_vectors
ORDER BY embedding <=> '[0.5,0.6,...]'::vector
LIMIT 10;

-- 测试并发查询性能（另开多个终端同时执行）
\timing off
EOF

# 3. 对比索引前后的性能（如有基准数据）
# 假设之前记录了基准查询时间
```

**成功标准**:
- [x] 性能测试套件全部通过
- [x] 单次查询时间 < 100ms（< 100 万向量）
- [x] 并发查询时间 < 200ms
- [x] 查询召回率 >= 90%（通过业务测试验证）

---

#### 阶段 6: 应用验证（预计 15 分钟）

**目标**: 验证应用功能正常，索引集成正确

**执行步骤**:

```bash
# 1. 重启应用服务
cd /home/dev/projects/weaver
docker-compose restart app

# 2. 健康检查
curl http://localhost:8000/health

# 3. 测试向量检索 API
curl -X POST http://localhost:8000/api/v1/search/similar \
  -H "Content-Type: application/json" \
  -d '{
    "query": "test query",
    "top_k": 10
  }'

# 4. 检查应用日志
tail -f logs/app.log | grep -i "vector\|hnsw\|index"

# 5. 运行集成测试
pytest tests/integration/test_vector_search.py -v
```

**成功标准**:
- [x] 应用启动成功
- [x] 健康检查返回 200 OK
- [x] 向量检索 API 返回正确结果
- [x] 应用日志无错误
- [x] 集成测试通过

---

### 4.2 迁移后清理（预计 5 分钟）

**目标**: 清理临时文件，恢复正常配置

**执行步骤**:

```bash
# 1. 恢复告警阈值（如有临时调整）
# 通过监控平台恢复原始告警配置

# 2. 归档迁移日志
mkdir -p /home/dev/projects/weaver/logs/migration
mv /home/dev/projects/weaver/logs/alembic.log /home/dev/projects/weaver/logs/migration/alembic_hnsw_$(date +%Y%m%d_%H%M%S).log

# 3. 记录迁移完成状态
echo "$(date): HNSW 索引迁移成功完成" >> /home/dev/projects/weaver/.migration_backups/migration_history.log

# 4. 清理临时配置（如创建了环境变量）
unset HNSW_M
unset HNSW_EF_CONSTRUCTION
```

---

## 5. 低峰期执行窗口建议

### 5.1 执行时间窗口选择

根据数据量和业务特征，建议的执行窗口：

| 数据量级别 | 建议执行时间 | 预计完成时间 | 风险等级 |
|-----------|-------------|-------------|---------|
| 小型 (< 10 万) | 任意时间，避开高峰 | 10-15 分钟 | 低 |
| 中型 (10-50 万) | 工作日晚间 22:00-02:00 | 30-45 分钟 | 低 |
| 中大型 (50-100 万) | 周末凌晨 00:00-04:00 | 1-1.5 小时 | 中 |
| 大型 (100-500 万) | 周末凌晨 00:00-06:00 | 2-3 小时 | 中 |
| 超大型 (> 500 万) | 维护窗口期，提前通知用户 | 4-6 小时 | 高 |

### 5.2 具体执行时间建议

#### 场景 1: 业务低峰期（推荐）

**时间**: 周六凌晨 01:00 - 05:00

**优势**:
- 用户访问量最低
- 系统负载低，索引创建速度快
- 有充足时间处理问题

**准备工作**:
- 周五下午完成备份和预检查
- 周六凌晨 00:30 开始监控
- 周六凌晨 01:00 正式开始迁移

#### 场景 2: 工作日晚间

**时间**: 工作日 22:00 - 02:00

**优势**:
- 适合中型数据量
- 次日有充足时间验证和修复

**注意事项**:
- 确保值班人员在岗
- 准备好回滚方案
- 监控告警通知到位

#### 场景 3: 紧急迁移

**时间**: 即刻执行

**适用条件**:
- 性能问题严重影响业务
- 数据量较小 (< 10 万)
- 有回滚预案

**风险缓解**:
- 全程监控
- 准备即时回滚
- 通知所有相关方

### 5.3 执行窗口检查清单

- [ ] 确认当前时间在计划的执行窗口内
- [ ] 验证当前系统负载低于阈值（CPU < 50%, 内存 < 70%）
- [ ] 确认无其他计划内的维护任务
- [ ] 确认备份已完成
- [ ] 确认监控和告警配置正确
- [ ] 确认值班人员在线
- [ ] 确认回滚脚本可用

---

## 6. 验证步骤和成功标准

### 6.1 技术验证

#### 6.1.1 索引验证

| 验证项 | 验证方法 | 成功标准 | 验证命令 |
|--------|---------|---------|---------|
| 索引存在 | 查询 pg_indexes | 两个 HNSW 索引存在 | `SELECT indexname FROM pg_indexes WHERE indexname LIKE '%hnsw%';` |
| 索引大小 | pg_relation_size | 约为向量数据 1.5-2 倍 | `SELECT pg_size_pretty(pg_relation_size('idx_article_vectors_hnsw'));` |
| 索引可用 | EXPLAIN ANALYZE | 使用 Index Scan | `EXPLAIN ANALYZE SELECT ... ORDER BY embedding <=> ... LIMIT 10;` |
| 查询性能 | 性能测试 | < 100ms | `pytest tests/performance/test_hnsw_performance.py` |

#### 6.1.2 数据完整性验证

```bash
# 验证向量数据未丢失
psql -h localhost -U postgres -d weaver -c "
SELECT
  (SELECT COUNT(*) FROM article_vectors) as article_count,
  (SELECT COUNT(*) FROM entity_vectors) as entity_count;
"

# 验证向量维度正确
psql -h localhost -U postgres -d weaver -c "
SELECT
  array_length(embedding, 1) as dimension,
  COUNT(*) as count
FROM article_vectors
GROUP BY array_length(embedding, 1);
"

# 验证数据可正常查询
psql -h localhost -U postgres -d weaver -c "
SELECT COUNT(*) FROM article_vectors WHERE embedding IS NOT NULL;
SELECT COUNT(*) FROM entity_vectors WHERE embedding IS NOT NULL;
"
```

**成功标准**:
- [x] 向量数量与迁移前一致
- [x] 向量维度均为 1024
- [x] 无 NULL 向量
- [x] 数据可正常查询

### 6.2 功能验证

#### 6.2.1 API 功能测试

```bash
# 1. 相似文章检索
curl -X POST http://localhost:8000/api/v1/articles/similar \
  -H "Content-Type: application/json" \
  -d '{"article_id": 1, "top_k": 10}'

# 2. 实体相似性查询
curl -X POST http://localhost:8000/api/v1/entities/similar \
  -H "Content-Type: application/json" \
  -d '{"entity_id": "entity_1", "top_k": 10}'

# 3. 向量检索
curl -X POST http://localhost:8000/api/v1/search/vector \
  -H "Content-Type: application/json" \
  -d '{"query": "test query", "top_k": 10}'
```

**成功标准**:
- [x] 所有 API 返回 200 OK
- [x] 返回结果格式正确
- [x] 返回结果包含相似度分数
- [x] 结果排序合理（相似度从高到低）

#### 6.2.2 端到端测试

```bash
# 运行集成测试套件
pytest tests/integration/test_vector_search.py -v

# 运行端到端测试
pytest tests/e2e/test_search_workflow.py -v
```

**成功标准**:
- [x] 所有测试通过
- [x] 无性能退化
- [x] 无数据丢失

### 6.3 性能验证

#### 6.3.1 查询性能基准

| 查询类型 | 目标性能 | 验证方法 |
|---------|---------|---------|
| 单向量查询（top-10） | < 100ms | EXPLAIN ANALYZE |
| 单向量查询（top-100） | < 200ms | EXPLAIN ANALYZE |
| 并发查询（10 并发） | < 300ms | 性能测试脚本 |
| 批量查询（100 向量） | < 2s | 性能测试脚本 |

#### 6.3.2 性能对比测试

```bash
# 手动对比查询性能
cd /home/dev/projects/weaver

# 记录迁移前查询时间
psql -h localhost -U postgres -d weaver -c "\timing on" -c "SELECT article_id FROM article_vectors ORDER BY embedding <=> '[...]'::vector LIMIT 10;"

# 迁移后再次执行相同查询，对比时间
```

**注意**: 可使用性能测试脚本 `scripts/run_performance_tests.py` 进行基准测试。

**成功标准**:
- [x] 查询时间降低 >= 50%（相比暴力搜索）
- [x] 召回率 >= 90%
- [x] 并发性能稳定

### 6.4 监控验证

#### 6.4.1 监控指标检查

```bash
# 检查 Prometheus 指标
curl http://localhost:8000/metrics | grep vector_search

# 检查查询延迟
curl http://localhost:8000/metrics | grep query_duration_seconds

# 检查索引使用率
psql -h localhost -U postgres -d weaver -c "
SELECT
  schemaname,
  tablename,
  indexname,
  idx_scan as index_scans,
  idx_tup_read as tuples_read,
  idx_tup_fetch as tuples_fetched
FROM pg_stat_user_indexes
WHERE indexname LIKE '%hnsw%';
"
```

**成功标准**:
- [x] Prometheus 指标正常导出
- [x] 查询延迟指标可见
- [x] 索引扫描次数增加（表示被使用）

---

## 7. 回滚预案

### 7.1 回滚触发条件

满足以下任一条件，立即执行回滚：

#### 关键触发条件（立即回滚）

- [x] 索引创建失败，无法继续
- [x] 数据完整性验证失败（数据丢失或损坏）
- [x] 应用启动失败或核心功能不可用
- [x] 查询性能严重退化（> 5 倍）
- [x] 系统资源耗尽（磁盘满、内存溢出）

#### 次要触发条件（评估后决定）

- [x] 索引创建时间超过预期 2 倍
- [x] 查询召回率 < 85%
- [x] 并发性能不稳定（延迟波动 > 50%）
- [x] 应用出现非关键错误

### 7.2 回滚执行步骤

#### 快速回滚流程（5-10 分钟）

```bash
# 1. 停止应用服务
docker-compose stop app

# 2. 执行 Alembic 回滚
cd /home/dev/projects/weaver/src
alembic downgrade -1

# 3. 验证回滚成功
psql -h localhost -U postgres -d weaver -c "
SELECT indexname FROM pg_indexes WHERE indexname LIKE '%hnsw%';
"
# 应返回 0 行

# 4. 重启应用
docker-compose start app

# 5. 健康检查
curl http://localhost:8000/health

# 6. 功能验证
pytest tests/integration/test_vector_search.py -v
```

#### 完整回滚流程（15-30 分钟）

如果快速回滚失败，执行完整回滚：

```bash
# 1. 停止所有服务
docker-compose down

# 2. 从备份恢复向量表
pg_restore -h localhost -U postgres -d weaver \
  --clean --if-exists \
  -t article_vectors -t entity_vectors \
  /backup/vectors_pre_hnsw.dump

# 3. 重置迁移状态
cd /home/dev/projects/weaver/src
alembic downgrade c619ab9ba95a

# 4. 验证数据完整性
psql -h localhost -U postgres -d weaver -c "
SELECT COUNT(*) FROM article_vectors;
SELECT COUNT(*) FROM entity_vectors;
"

# 5. 重启服务
cd /home/dev/projects/weaver
docker-compose up -d

# 6. 完整功能验证
pytest tests/integration/ -v
```

### 7.3 回滚验证清单

- [ ] 索引已删除（查询 pg_indexes 返回 0 行）
- [ ] 数据完整性验证通过（数量一致）
- [ ] 应用启动成功
- [ ] 健康检查返回 200 OK
- [ ] 核心功能可用（API 测试通过）
- [ ] 查询性能恢复到迁移前水平
- [ ] 监控指标正常
- [ ] 日志无错误

### 7.4 回滚后行动

#### 7.4.1 问题分析

- 记录回滚原因和现象
- 收集相关日志和监控数据
- 分析失败根本原因
- 制定改进方案

#### 7.4.2 重新迁移准备

根据问题类型调整迁移计划：

| 问题类型 | 调整措施 |
|---------|---------|
| 磁盘空间不足 | 清理磁盘或扩容 |
| 内存不足 | 增加内存或减少并行度 |
| 索引参数不合适 | 调整 m 和 ef_construction |
| 硬件性能不足 | 升级硬件或分批迁移 |
| 数据质量问题 | 清理数据，修复异常向量 |

---

## 8. 风险评估和缓解措施

### 8.1 风险矩阵

| 风险类型 | 风险描述 | 概率 | 影响 | 风险等级 | 缓解措施 |
|---------|---------|------|------|---------|---------|
| **性能风险** | 索引创建时间长于预期 | 中 | 中 | 中 | 在低峰期执行，预留充足时间窗口 |
| **资源风险** | 磁盘空间不足 | 中 | 高 | 高 | 提前检查磁盘空间，预留 3 倍空间 |
| **资源风险** | 内存溢出 | 低 | 高 | 中 | 监控内存使用，调整 work_mem |
| **数据风险** | 数据丢失或损坏 | 低 | 极高 | 高 | 完整备份，验证数据完整性 |
| **功能风险** | 查询结果不正确 | 低 | 高 | 中 | 充分测试，验证召回率 |
| **集成风险** | 应用启动失败 | 低 | 高 | 中 | 准备回滚方案，验证环境配置 |
| **监控风险** | 监控指标缺失 | 中 | 中 | 中 | 提前验证监控配置 |

### 8.2 详细风险缓解措施

#### 8.2.1 索引创建时间过长

**风险描述**: 数据量增长或硬件性能不足，导致索引创建时间远超预期

**缓解措施**:
1. **提前测试**: 在测试环境使用生产数据副本测试迁移时间
2. **分批创建**: 如果是超大表（> 1000 万），考虑分批创建：
   ```sql
   -- 创建部分索引
   CREATE INDEX CONCURRENTLY idx_article_vectors_hnsw_partial
   ON article_vectors USING hnsw (embedding vector_cosine_ops)
   WHERE created_at >= '2026-01-01'
   WITH (m = 16, ef_construction = 64);
   ```
3. **调整参数**: 使用更小的 m 和 ef_construction 加速创建
4. **监控进度**: 定期检查 `pg_stat_progress_create_index` 视图
5. **设置超时**: 为 Alembic 迁移设置合理超时时间

#### 8.2.2 磁盘空间不足

**风险描述**: 索引创建需要额外空间，导致磁盘满，迁移失败甚至数据库崩溃

**缓解措施**:
1. **提前检查**: 执行前检查磁盘空间，确保有 3 倍向量数据大小的空闲空间
2. **清理空间**: 删除不必要的日志、临时文件、旧备份
3. **临时扩容**: 如果云环境，临时增加磁盘大小
4. **监控告警**: 设置磁盘使用率告警，达到 85% 立即通知
5. **快速释放**: 准备快速删除临时文件的脚本

#### 8.2.3 内存溢出

**风险描述**: 索引创建消耗大量内存，导致 OOM 或数据库崩溃

**缓解措施**:
1. **调整参数**: 设置合理的 `maintenance_work_mem`（不超过总内存的 50%）
   ```sql
   SET LOCAL maintenance_work_mem = '2GB';
   ```
2. **减少并行度**: 降低 `max_parallel_maintenance_workers`
3. **监控内存**: 使用 `top` 或 `htop` 监控内存使用
4. **预留缓冲**: 确保至少 20% 内存空闲
5. **分批处理**: 如果内存不足，考虑分批创建索引

#### 8.2.4 数据完整性问题

**风险描述**: 迁移过程中数据损坏或丢失

**缓解措施**:
1. **完整备份**: 迁移前创建完整数据库备份
2. **验证备份**: 测试备份可恢复性
3. **数据校验**: 迁移前后对比记录数量和校验和
4. **事务保护**: 使用事务确保数据一致性
5. **日志记录**: 记录详细操作日志，便于审计和恢复

#### 8.2.5 查询性能退化

**风险描述**: 索引创建后，查询性能反而下降

**缓解措施**:
1. **性能测试**: 在测试环境充分测试性能
2. **参数调优**: 调整 `ef_search` 参数（查询时使用）
   ```sql
   SET hnsw.ef_search = 100;  -- 默认 40，提高召回率
   ```
3. **统计信息更新**: 迁移后执行 `ANALYZE`
   ```sql
   ANALYZE article_vectors;
   ANALYZE entity_vectors;
   ```
4. **查询计划分析**: 使用 `EXPLAIN ANALYZE` 验证索引使用
5. **回滚准备**: 准备快速回滚方案

#### 8.2.6 召回率不足

**风险描述**: HNSW 索引是近似算法，可能无法返回精确的最近邻

**缓解措施**:
1. **参数调优**: 提高构建参数（m=32, ef_construction=128）
2. **查询调优**: 提高查询参数（ef_search=100-200）
3. **混合策略**: 对于关键查询，结合精确搜索和 HNSW
4. **召回率测试**: 编写测试验证召回率 >= 90%
5. **业务评估**: 与业务团队确认召回率要求

#### 8.2.7 应用集成失败

**风险描述**: 应用无法正常使用新索引，出现错误或异常

**缓解措施**:
1. **环境一致性**: 确保测试环境与生产环境一致
2. **充分测试**: 在测试环境完整运行集成测试
3. **配置检查**: 验证所有环境变量和配置正确
4. **日志监控**: 监控应用日志，及时发现错误
5. **灰度发布**: 如果可能，先在部分节点部署

#### 8.2.8 监控缺失

**风险描述**: 迁移后监控指标缺失或异常，无法评估效果

**缓解措施**:
1. **提前验证**: 迁移前验证监控配置正确
2. **指标清单**: 准备需要监控的指标清单
3. **仪表盘更新**: 更新 Grafana 仪表盘，添加新指标
4. **告警规则**: 添加针对向量查询的告警规则
5. **基准数据**: 记录迁移前的基准性能数据

### 8.3 应急响应流程

#### 8.3.1 问题分级

| 级别 | 描述 | 响应时间 | 处理方式 |
|------|------|---------|---------|
| P0 - 致命 | 数据丢失、服务不可用 | 立即 | 立即回滚 |
| P1 - 严重 | 性能严重退化、功能异常 | 15 分钟 | 评估后决定回滚或修复 |
| P2 - 一般 | 性能轻微退化、非关键功能异常 | 1 小时 | 记录问题，计划修复 |
| P3 - 轻微 | 监控缺失、日志异常 | 4 小时 | 记录问题，后续处理 |

#### 8.3.2 应急响应步骤

1. **发现问题**: 通过监控、告警、用户反馈发现问题
2. **评估影响**: 确定问题级别和影响范围
3. **快速止损**: 如果是 P0/P1 问题，立即回滚
4. **根因分析**: 收集日志、监控数据，分析根因
5. **修复验证**: 在测试环境修复并验证
6. **重新部署**: 修复后重新执行迁移
7. **复盘总结**: 记录问题、原因、解决方案，更新文档

### 8.4 风险沟通计划

#### 8.4.1 沟通对象

| 角色 | 沟通内容 | 沟通时机 |
|------|---------|---------|
| 技术团队 | 迁移计划、技术风险、执行进度 | 迁移前、执行中、完成后 |
| 运维团队 | 监控配置、告警规则、回滚预案 | 迁移前、执行中 |
| 产品团队 | 业务影响、用户体验变化 | 迁移前、完成后 |
| 管理层 | 迁移进度、风险评估、成本收益 | 迁移前、关键节点 |

#### 8.4.2 沟通渠道

- **即时通讯**: 技术团队 Slack/企业微信群
- **邮件通知**: 正式通知、进度报告
- **文档共享**: 迁移计划、风险报告、操作手册
- **会议沟通**: 迁移前动员会、迁移后总结会

---

## 9. 检查清单

### 9.1 迁移前检查清单

#### 数据备份

- [ ] 创建完整数据库备份
- [ ] 验证备份文件完整性
- [ ] 测试备份可恢复性
- [ ] 记录当前迁移状态
- [ ] 保存当前索引状态

#### 系统资源

- [ ] 磁盘空间充足（>= 3 倍向量数据大小）
- [ ] 内存充足（>= 推荐配置）
- [ ] CPU 负载低（< 50%）
- [ ] 无长时间运行的事务
- [ ] 连接数在正常范围

#### 监控准备

- [ ] Prometheus 指标正常收集
- [ ] Grafana 仪表盘已配置
- [ ] 告警规则已更新
- [ ] 监控值班人员已确认
- [ ] 日志收集正常

#### 回滚准备

- [ ] 回滚脚本已测试
- [ ] 回滚步骤已文档化
- [ ] 回滚执行人员已确认
- [ ] 回滚验证标准已明确

#### 团队准备

- [ ] 技术团队已通知
- [ ] 运维团队已通知
- [ ] 执行时间已确认
- [ ] 应急联系方式已确认

### 9.2 迁移执行检查清单

#### 阶段 0: 前置检查

- [ ] 当前迁移版本正确
- [ ] 向量表存在且有数据
- [ ] 系统负载正常
- [ ] 无其他维护任务

#### 阶段 1: 数据备份

- [ ] 备份文件已创建
- [ ] 备份大小合理
- [ ] 迁移状态已记录

#### 阶段 2: 性能配置

- [ ] maintenance_work_mem 已提升
- [ ] 并行度已配置

#### 阶段 3: 执行迁移

- [ ] Alembic 迁移启动成功
- [ ] 索引创建进程正常
- [ ] 监控进度正常
- [ ] 无错误日志

#### 阶段 4: 索引验证

- [ ] 索引已创建
- [ ] 索引大小合理
- [ ] 索引被查询使用
- [ ] 查询性能达标

#### 阶段 5: 性能测试

- [ ] 性能测试套件通过
- [ ] 查询时间达标
- [ ] 并发性能达标
- [ ] 召回率达标

#### 阶段 6: 应用验证

- [ ] 应用启动成功
- [ ] 健康检查通过
- [ ] API 功能正常
- [ ] 集成测试通过

### 9.3 迁移后检查清单

#### 技术验证

- [ ] 索引存在且可用
- [ ] 数据完整性验证通过
- [ ] 查询性能达标
- [ ] 监控指标正常

#### 功能验证

- [ ] 所有 API 功能正常
- [ ] 端到端测试通过
- [ ] 用户体验无退化

#### 监控验证

- [ ] Prometheus 指标可见
- [ ] Grafana 仪表盘更新
- [ ] 告警规则生效
- [ ] 日志正常收集

#### 文档更新

- [ ] 迁移记录已更新
- [ ] 运维文档已更新
- [ ] 架构文档已更新
- [ ] 团队已通知

#### 清理工作

- [ ] 临时文件已删除
- [ ] 监控告警阈值已恢复
- [ ] 迁移日志已归档
- [ ] 备份文件已整理

---

## 10. 附录

### 10.1 相关文档

- **迁移脚本**: `src/alembic/versions/e283f4aed36a_add_hnsw_indexes_to_vector_tables.py`
- **性能测试**: `tests/performance/test_hnsw_performance.py`
- **集成测试**: `tests/integration/test_vector_search.py`
- **监控配置**: `monitoring/prometheus/alerts.yml`

### 10.2 命令速查

```bash
# 检查当前迁移版本
cd /home/dev/projects/weaver/src && alembic current

# 执行迁移
alembic upgrade e283f4aed36a

# 回滚迁移
alembic downgrade -1

# 检查索引
psql -h localhost -U postgres -d weaver -c "SELECT indexname FROM pg_indexes WHERE indexname LIKE '%hnsw%';"

# 查看索引大小
psql -h localhost -U postgres -d weaver -c "SELECT pg_size_pretty(pg_relation_size('idx_article_vectors_hnsw'));"

# 测试查询性能
psql -h localhost -U postgres -d weaver -c "EXPLAIN ANALYZE SELECT article_id FROM article_vectors ORDER BY embedding <=> '[0.1,0.2,...]'::vector LIMIT 10;"

# 运行性能测试
pytest tests/performance/test_hnsw_performance.py -v

# 回滚迁移（如需）
alembic downgrade -1
```

### 10.3 环境变量

| 变量名 | 默认值 | 说明 |
|--------|-------|------|
| HNSW_M | 16 | HNSW 参数 m（每节点最大连接数） |
| HNSW_EF_CONSTRUCTION | 64 | HNSW 参数 ef_construction（构建时候选列表大小） |
| DATABASE_URL | postgresql://postgres:postgres@localhost:5432/weaver | 数据库连接 URL |

### 10.4 性能调优参数

#### PostgreSQL 配置

```sql
-- 临时提升维护工作内存
SET LOCAL maintenance_work_mem = '2GB';

-- 提升并行度
SET LOCAL max_parallel_maintenance_workers = 4;

-- 查询时调整 ef_search
SET hnsw.ef_search = 100;

-- 更新统计信息
ANALYZE article_vectors;
ANALYZE entity_vectors;
```

#### HNSW 参数建议

| 场景 | m | ef_construction | ef_search | 特点 |
|------|---|----------------|-----------|------|
| 快速构建 | 8 | 32 | 40 | 构建快，召回率低 |
| 平衡模式 | 16 | 64 | 64 | 推荐，平衡性能和召回率 |
| 高召回率 | 32 | 128 | 100 | 召回率高，构建慢 |

### 10.5 故障排查指南

#### 问题：索引创建卡住不动

**诊断步骤**:
```sql
-- 检查索引创建进度
SELECT * FROM pg_stat_progress_create_index;

-- 检查活跃查询
SELECT pid, query, state, now() - query_start AS duration
FROM pg_stat_activity
WHERE query LIKE '%CREATE INDEX%';

-- 检查锁等待
SELECT * FROM pg_locks WHERE NOT granted;
```

**解决方案**:
1. 等待：索引创建需要时间，耐心等待
2. 终止：如果确实卡住，终止进程并回滚
   ```sql
   SELECT pg_cancel_backend(<pid>);
   ```

#### 问题：查询未使用 HNSW 索引

**诊断步骤**:
```sql
-- 强制使用索引
SET enable_seqscan = off;
EXPLAIN ANALYZE SELECT ...;

-- 检查统计信息
SELECT * FROM pg_stats WHERE tablename = 'article_vectors';

-- 检查索引是否有效
SELECT * FROM pg_index WHERE indexrelid = 'idx_article_vectors_hnsw'::regclass;
```

**解决方案**:
1. 更新统计信息：`ANALYZE article_vectors;`
2. 重建索引：`REINDEX INDEX CONCURRENTLY idx_article_vectors_hnsw;`
3. 调整查询：确保查询条件与索引匹配

#### 问题：查询召回率低

**诊断步骤**:
```sql
-- 对比精确搜索和 HNSW 结果
-- 精确搜索
SELECT article_id FROM article_vectors ORDER BY embedding <=> '[...]'::vector LIMIT 10;

-- HNSW 搜索
SET hnsw.ef_search = 40;
SELECT article_id FROM article_vectors ORDER BY embedding <=> '[...]'::vector LIMIT 10;
```

**解决方案**:
1. 提高 ef_search：`SET hnsw.ef_search = 100;`
2. 重建索引，使用更高参数：m=32, ef_construction=128
3. 结合精确搜索和 HNSW

---

## 11. 总结

本文档详细规划了 HNSW 索引迁移的全流程，包括：

1. **时间估算**: 提供不同数据量级别的时间估算，帮助合理安排执行窗口
2. **准备工作**: 完整的备份、检查、监控准备清单
3. **执行步骤**: 分阶段详细步骤，每阶段有明确的目标和验证标准
4. **执行窗口**: 针对不同数据量建议最佳执行时间
5. **验证标准**: 技术、功能、性能三个维度的完整验证方案
6. **回滚预案**: 明确触发条件、执行步骤和验证清单
7. **风险管理**: 8 大风险类别，详细缓解措施和应急响应流程

**关键成功因素**:
- 充分的准备工作（备份、监控、回滚预案）
- 合适的执行窗口（低峰期、充足时间）
- 完整的验证流程（技术、功能、性能）
- 有效的风险管理（识别、缓解、应急）
- 清晰的沟通计划（团队协作、信息同步）

**预期成果**:
- 向量查询性能提升 50-90%
- 查询召回率保持在 90-95%
- 系统稳定性和可靠性提升
- 监控和运维能力增强

---

**文档版本**: v1.0
**最后更新**: 2026-03-18
**维护者**: 技术团队