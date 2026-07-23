# Weaver Scripts

统一的开发和运维脚本目录。

## 目录结构

| 脚本                      | 描述                                                                          |
| ------------------------- | ----------------------------------------------------------------------------- |
| `pipeline.py`             | 管道测试、待处理文章处理、重新处理、**源初始化**（`seed-sources` 子命令）     |
| `db.py`                   | 数据库查询、检查、**DuckDB 综合审计**（`audit` 子命令）、修复工具             |
| `data_io.py`              | PG↔DuckDB / Neo4j↔LadybugDB 导入/导出 + **跨库一致性校验**（`verify` 子命令） |
| `tools.py`                | 性能评估、环境验证、数据库种子、代码检查                                      |
| `build_nuitka.py`         | Nuitka 生产编译构建                                                           |
| `run_4db_combinations.sh` | 双故障转移架构下 4 种 DB 组合的实例启停/状态/健康检查                         |
| `_common.py`              | 共享工具（`init_script_container`，非独立运行，被其他脚本 import）            |
| `specmark/`               | specmark 工作流归档工具子目录（`archive_change.sh` + `merge_delta_spec.py`）  |

---

## pipeline.py

统一的管道管理脚本,支持管道测试、待处理文章处理、重新处理不完整文章,以及数据源初始化。

### 用法

```bash
# 管道测试 - NewsNow 模式
uv run scripts/pipeline.py test --mode newsnow --max-items 5

# 管道测试 - RSS 模式
uv run scripts/pipeline.py test --mode rss --source solidot

# 管道测试 - 全部源
uv run scripts/pipeline.py test --mode all --clear-db

# 管道测试 - 数据库故障转移模式
uv run scripts/pipeline.py test --mode strategy

# 处理待处理文章
uv run scripts/pipeline.py process-pending

# 重新处理不完整文章
uv run scripts/pipeline.py reprocess --incomplete
uv run scripts/pipeline.py reprocess --incomplete --dry-run
uv run scripts/pipeline.py reprocess --incomplete --batch-size 5 --delay 30
uv run scripts/pipeline.py reprocess --article-id <uuid>

# 初始化所有数据源（原 seed_sources.py，已合并）
uv run scripts/pipeline.py seed-sources                    # 创建所有源配置
uv run scripts/pipeline.py seed-sources --pipeline         # 创建并触发管道
uv run scripts/pipeline.py seed-sources --dry-run          # 仅预览
```

### 子命令

| 子命令            | 描述                                                                              |
| ----------------- | --------------------------------------------------------------------------------- |
| `test`            | 管道端到端测试（`--mode newsnow/rss/strategy/all`）                               |
| `process-pending` | 处理所有 `persist_status='pending'` 的文章                                        |
| `reprocess`       | 重新处理不完整文章（`--incomplete`/`--article-id`/`--dry-run`）                   |
| `seed-sources`    | 创建所有 NewsNow + RSS 源配置，可选触发管道（`--pipeline`/`--dry-run`/`--batch`） |

---

## db.py

数据库查询和检查工具,支持 PostgreSQL、DuckDB、Neo4j、LadybugDB,并集成 DuckDB 综合数据质量审计。

### 用法

```bash
# 表统计
uv run scripts/db.py stats
uv run scripts/db.py stats --db duckdb

# 文章查询
uv run scripts/db.py article --id <article-uuid>
uv run scripts/db.py random --limit 3

# 分页查询表数据
uv run scripts/db.py rows articles --limit 20 --page 1

# LadybugDB 数据质量检查
uv run scripts/db.py dq-check

# DuckDB 综合审计（原 audit_db.py，已合并）
uv run scripts/db.py audit                              # 全部 5 个 phase
uv run scripts/db.py audit --db-path data/weaver.duckdb
uv run scripts/db.py audit --phase 1a                   # 仅 NOT NULL 检查
uv run scripts/db.py audit --output ./report.json

# 修复损坏的 model_id
uv run scripts/db.py fix-model-id --dry-run
uv run scripts/db.py fix-model-id --execute
```

### 子命令

| 子命令         | 描述                                                                                        |
| -------------- | ------------------------------------------------------------------------------------------- |
| `stats`        | 显示各库表记录数                                                                            |
| `article`      | 按 ID 查询文章完整信息                                                                      |
| `random`       | 随机查询文章及实体关系                                                                      |
| `rows`         | 分页+排序查询表行                                                                           |
| `null-fields`  | 检查 PG/DuckDB 表的 NULL/空字段                                                             |
| `dq-check`     | LadybugDB 数据质量检查                                                                      |
| `audit`        | **DuckDB 综合数据质量审计**（NOT NULL/业务字段/FK/枚举规则/50% 抽样，`--phase 1a..1e/all`） |
| `fix-model-id` | 修复 article_vectors 中损坏的 model_id（`--dry-run`/`--execute`）                           |

---

## data_io.py

PG↔DuckDB / Neo4j↔LadybugDB 数据导入/导出迁移工具,并集成跨 4 库数据一致性校验（用于备份、恢复和双数据库故障转移架构下的数据对账）。

### 用法

```bash
# PostgreSQL → DuckDB 导出（备份）
uv run python scripts/data_io.py export --from postgres --to duckdb \
    --pg-dsn 'postgresql+asyncpg://postgres:weavertest@localhost:5432/weaver' \
    --duckdb-path data/weaver.duckdb

# DuckDB → PostgreSQL 导入（恢复）
uv run python scripts/data_io.py import --from duckdb --to postgres \
    --duckdb-path data/weaver.duckdb \
    --pg-dsn 'postgresql+asyncpg://postgres:weavertest@localhost:5432/weaver'

# Neo4j → LadybugDB 导出（图数据库备份）
uv run python scripts/data_io.py export --from neo4j --to ladybug \
    --neo4j-uri bolt://localhost:7687 --neo4j-user neo4j \
    --neo4j-password weavertest --ladybug-path data/weaver_graph.ladybug

# 跨库一致性校验（原 verify_db_consistency.py，已合并）
uv run python scripts/data_io.py verify --mode all
uv run python scripts/data_io.py verify --mode pg-duckdb \
    --pg-dsn 'postgresql+asyncpg://...' --duckdb-path data/weaver.duckdb
uv run python scripts/data_io.py verify --mode neo4j-ladybug \
    --neo4j-uri bolt://localhost:7687 --neo4j-password "$WEAVER_NEO4J__PASSWORD"
```

### 子命令

| 子命令   | 描述                                                                                                                                    |
| -------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `export` | 主库 → 备库（postgres→duckdb、neo4j→ladybug），原子文件替换                                                                             |
| `import` | 备库 → 主库（duckdb→postgres）                                                                                                          |
| `verify` | **跨 4 库一致性校验**：PG↔DuckDB（27 表行数+MD5+抽样）、Neo4j↔Ladybug（8 标签+13 关系计数+抽样）。退出码 0 全过 / 1 不一致 / 2 用法错误 |

### 特性

- **27 张 PG/DuckDB 表**: FK 安全的截断/导入顺序,逐表行数验证
- **8 个 LadybugDB 节点标签 + 13 种关系类型**: 与 `ladybug_schema.py` 保持一致
- **原子文件替换** (PG→DuckDB): 写入 `.tmp` 文件,验证后 `os.replace()` 原子替换
- **快照一致性**: PG 导出/校验使用 `REPEATABLE READ` 隔离级别,避免并发写入导致表间漂移
- **序列重置**: PG→DuckDB 导入后重置 BIGINT PK 序列为 `MAX(id)+1`
- **行数验证**: 每张表导出/导入后断言行数一致,不匹配则非零退出
- **Schema 漂移检测**: PK 类型不兼容时跳过表并警告

---

## tools.py

统一的工具脚本,包含性能评估、环境验证、数据库种子和代码质量检查。

### 用法

```bash
# HNSW 向量索引性能测试
uv run scripts/tools.py evaluate hnsw --num-vectors 2000

# BM25 搜索质量评估
uv run scripts/tools.py evaluate search --k-values 5,10,20

# 验证环境服务
uv run scripts/tools.py validate --service postgres --service redis

# 种子关系类型字典（注意：种的是知识图谱关系类型，与 pipeline.py seed-sources 的数据源配置不同）
uv run scripts/tools.py seed
uv run scripts/tools.py seed --reset

# 检查日志规范（禁止 logging 模块，改用 loguru）
uv run scripts/tools.py check-logging
uv run scripts/tools.py check-logging --fix-hint
```

### 子命令

| 子命令              | 描述                                                |
| ------------------- | --------------------------------------------------- |
| `evaluate hnsw`     | HNSW 向量索引性能测试（插入/查询/索引使用）         |
| `evaluate search`   | BM25 搜索质量评估（Recall@K/Precision@K/MRR）       |
| `validate`          | 验证环境服务（postgres/neo4j/redis/llm/embedding）  |
| `seed`              | 种子知识图谱关系类型与别名到 RelationType 表        |
| `check-logging`     | 扫描违禁 `logging` 模块用法（pre-commit hook 调用） |
| `monitor`           | 数据库索引监控（查未使用索引）                      |
| `regenerate-titles` | 用 LLM 重生成社区（community）标题                  |

---

## build_nuitka.py

Nuitka 编译构建脚本,用于生成独立的二进制文件。

```bash
uv run scripts/build_nuitka.py
```

编译产物位于 `dist/` 目录。

---

## run_4db_combinations.sh

双故障转移架构下 4 种 DB 后端组合（pg-neo4j / pg-ladybug / duckdb-neo4j / duckdb-ladybug，端口 18001–18004）的实例生命周期管理。

```bash
bash scripts/run_4db_combinations.sh start all       # 启动全部 4 个组合
bash scripts/run_4db_combinations.sh status          # 查看运行状态
bash scripts/run_4db_combinations.sh health pg-neo4j # 健康检查单个组合
bash scripts/run_4db_combinations.sh stop all        # 停止全部
```

该脚本不修改 `.env` 或 `src/` 下任何文件；通过 `WEAVER_POSTGRES__ENABLED` / `WEAVER_NEO4J__ENABLED` 环境变量切换后端。

---

## specmark/ 子目录

specmark 工作流归档工具（语义上属于 specmark skill 配套，放在此处便于项目级调用）:

- `archive_change.sh` — specmark archive 阶段的确定性执行器（flock 保护 + commit SHA 锚定归档）
- `merge_delta_spec.py` — delta spec 的确定性三路合并器（`archive_change.sh --sync` 调用）

```bash
bash scripts/specmark/archive_change.sh <change-name> [--sync]
python scripts/specmark/merge_delta_spec.py --main <spec.md> --delta <delta.md> --out <out.md>
```
