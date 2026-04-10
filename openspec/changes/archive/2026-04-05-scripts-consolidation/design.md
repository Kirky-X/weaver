## Context

`scripts/` 目录包含 14 个脚本，主要问题：

1. **Pipeline 测试脚本重复**：`test_pipeline_duckdb.py`、`test_pipeline_rss.py`、`test_pipeline_duckdb_ladybug.py` 三个脚本共享 ~70% 的代码（基础设施初始化、数据库连接、验证逻辑）
2. **未复用现有模块**：`src/core/health/env_validator.py` 已实现完整的环境验证逻辑（718 行），但 `scripts/validate_environment.py` 重新实现了相同功能（868 行）
3. **数据库策略分散**：`src/core/db/strategy.py` 提供统一的故障转移策略，但脚本各自实现数据库初始化

### 现有可复用模块

| 模块 | 功能 | 可替代脚本代码 |
|------|------|---------------|
| `core.db.strategy.create_strategy()` | 数据库故障转移 | ~200 行初始化代码 |
| `core.health.env_validator.EnvironmentValidator` | 环境验证 | `validate_environment.py` 全部 |
| `modules.processing.pipeline.graph.Pipeline` | 处理管道 | 重复的管道构建 |
| `modules.knowledge.search.retrievers.BM25Retriever` | BM25 检索 | `evaluate_search_quality.py` 部分 |

## Goals / Non-Goals

**Goals:**

1. 将 14 个脚本整合为 9 个，减少 ~70% 代码量
2. 复用 `src/` 中的现有模块，消除重复实现
3. 提供统一的 CLI 接口，使用子命令模式
4. 保持所有现有功能不变

**Non-Goals:**

1. 不修改 `src/` 中的任何模块代码
2. 不添加新功能（仅合并现有功能）
3. 不修改 CI/CD 配置（由后续任务处理）
4. 不更新文档（由后续任务处理）

## Decisions

### D1: CLI 模式选择 — 子命令模式

**决定**: 使用子命令模式（如 `script.py <subcommand>`）而非独立脚本

**理由**:
- 逻辑相近的功能可共享公共代码
- 减少文件数量，降低认知负担
- 与 `db_query.py` 现有模式一致

**替代方案**:
- 保留独立脚本：无法共享公共代码，维护成本高
- 单一入口脚本：文件过大，不利于并行开发

### D2: `test_pipeline.py` 架构

**决定**: 单一脚本 + `--mode` 参数，内部使用策略模式

```python
# test_pipeline.py 结构
async def main():
    args = parse_args()

    # 公共：基础设施初始化（复用 core.db.strategy）
    strategy = await create_strategy(...)

    # 模式选择：数据源
    if args.mode == "newsnow":
        parser = NewsNowParser(fetcher)
        source = SourceConfig(id="test-newsnow", ...)
    elif args.mode == "rss":
        parser = RSSParser(fetcher)
        source = SourceConfig(id="test-solidot", url="https://solidot.org/index.rss", ...)
    elif args.mode == "strategy":
        # 使用策略模式，测试故障转移
        ...

    # 公共：Pipeline 执行
    pipeline = Pipeline(...)
    results = await pipeline.process_batch(articles)

    # 公共：验证
    await verify_results(strategy, results)
```

**复用模块**:
- `core.db.strategy.create_strategy()` — 数据库初始化 + 故障转移
- `modules.processing.pipeline.graph.Pipeline` — 处理管道
- `modules.ingestion.parsing.NewsNowParser/RSSParser` — 数据解析

### D3: `test_api.py` 架构

**决定**: 合并 E2E 测试和 API 审计为子命令

```python
# test_api.py 结构
def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")

    # e2e 子命令（原 run_36kr_full_pipeline.py）
    p_e2e = sub.add_parser("e2e")
    p_e2e.add_argument("--mode", choices=["36kr", "rss", "all"])
    p_e2e.add_argument("--max-items", type=int)
    p_e2e.add_argument("--no-start", action="store_true")

    # audit 子命令（原 http_audit.py）
    p_audit = sub.add_parser("audit")
    p_audit.add_argument("--port", type=int, default=8001)

    args = parser.parse_args()
    if args.command == "e2e":
        asyncio.run(run_e2e_test(args))
    elif args.command == "audit":
        asyncio.run(run_audit(args))
```

**共享代码**:
- `wait_for_server()` — 等待服务器就绪
- HTTP 客户端配置和认证头

### D4: `evaluate.py` 架构

**决定**: 合并性能测试和搜索评估

```python
# evaluate.py 结构
def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")

    # hnsw 子命令（原 run_performance_tests.py）
    p_hnsw = sub.add_parser("hnsw")
    p_hnsw.add_argument("--num-vectors", type=int, default=1000)

    # search 子命令（原 evaluate_search_quality.py）
    p_search = sub.add_parser("search")
    p_search.add_argument("--k-values", default="5,10,20")
```

**复用模块**:
- `modules.knowledge.search.retrievers.BM25Retriever` — BM25 搜索评估

### D5: `manage.py` 架构

**决定**: 直接调用现有模块，最小化代码

```python
# manage.py 结构（约 80 行）
from core.health.env_validator import EnvironmentValidator

async def cmd_validate(args):
    settings = Settings()
    validator = EnvironmentValidator(settings)
    results = await validator.validate_all(args.services)
    validator.print_report(results)
    return validator.get_exit_code(results)

async def cmd_seed(args):
    # 复用 seed_relation_types.py 的种子数据
    # 使用 settings 中的数据库连接
    ...
```

## Risks / Trade-offs

### R1: CLI 参数变更导致用户困惑

**风险**: 用户习惯旧命令路径

**缓解**:
- 在旧路径创建软链接或打印弃用警告
- 更新 README 和开发指南
- 保留 2 个版本的过渡期

### R2: 合并引入新 bug

**风险**: 合并过程中可能引入回归

**缓解**:
- 每个合并脚本独立测试
- 保留原脚本作为参考（git history）
- 实现前先验证现有脚本功能

### R3: 子命令模式增加使用复杂度

**风险**: 用户需要记忆更多子命令

**缓解**:
- 提供 `--help` 详细说明
- 保持子命令名称直观（`e2e`, `audit`, `hnsw`, `search`）
- 脚本顶部添加使用示例

## Migration Plan

### Phase 1: 创建合并脚本（不删除旧脚本）

1. 创建 `test_pipeline.py`
2. 创建 `test_api.py`
3. 创建 `evaluate.py`
4. 创建 `manage.py`
5. 测试所有新脚本功能

### Phase 2: 更新引用

1. 更新 CI/CD 配置中的脚本调用
2. 更新 README 和文档

### Phase 3: 删除旧脚本

1. 确认所有引用已更新
2. 删除 9 个旧脚本文件
3. 更新 `scripts/README.md`（如存在）

### Rollback

如发现问题，可立即恢复：
```bash
git checkout HEAD~1 -- scripts/
```

## Open Questions

无。设计方案已明确。