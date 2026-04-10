# Design: 统一Pipeline测试脚本

## 架构概览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    test_pipeline_api_unified.py                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                          CLI Layer                                    │  │
│  │  argparse: --mode, --source, --source-id, --max-items, --clear-db,   │  │
│  │            --timeout, --port, --use-fallback                         │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                    │                                        │
│                                    ▼                                        │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                       Infrastructure Layer                            │  │
│  │                                                                       │  │
│  │  setup_server()          → 启动FastAPI服务器                         │  │
│  │  setup_strategy()        → 配置数据库故障转移策略 (strategy模式)      │  │
│  │  clear_databases()       → 清理测试数据 (保留直接访问)                │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                    │                                        │
│                                    ▼                                        │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                         API Client Layer                              │  │
│  │                                                                       │  │
│  │  create_source_api()     → POST /api/v1/sources                      │  │
│  │  trigger_pipeline_api()  → POST /api/v1/pipeline/trigger             │  │
│  │  wait_for_task_api()     → GET  /api/v1/pipeline/tasks/{id}          │  │
│  │  verify_articles_api()   → GET  /api/v1/articles                     │  │
│  │  verify_entities_api()   → GET  /api/v1/graph/entities/{name}        │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                    │                                        │
│                                    ▼                                        │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                        Test Flow Layer                                │  │
│  │                                                                       │  │
│  │  run_newsnow_test()      → NewsNow模式测试流程                       │  │
│  │  run_rss_test()          → RSS模式测试流程                           │  │
│  │  run_strategy_test()     → Strategy模式测试流程                      │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 数据流

### NewsNow模式

```
┌─────────┐    ┌──────────────┐    ┌─────────────┐    ┌──────────────┐
│  Start  │───▶│ Create Source│───▶│   Trigger   │───▶│   Monitor    │
│         │    │    (API)     │    │  Pipeline   │    │    Task      │
└─────────┘    └──────────────┘    └─────────────┘    └──────────────┘
                                                             │
                                                             ▼
┌─────────┐    ┌──────────────┐    ┌─────────────┐    ┌──────────────┐
│  Done   │◀───│   Report     │◀─── │   Verify    │◀───│  Wait Done   │
│         │    │   Results    │    │   (API)     │    │   or Fail    │
└─────────┘    └──────────────┘    └─────────────┘    └──────────────┘
```

### RSS模式

```
与NewsNow模式相同，区别在于Source创建时的source_type="rss"
```

### Strategy模式

```
┌─────────┐    ┌──────────────┐    ┌─────────────┐    ┌──────────────┐
│  Start  │───▶│ Setup Env    │───▶│   Create    │───▶│   Trigger    │
│         │    │ Variables    │    │   Source    │    │   Pipeline   │
└─────────┘    └──────────────┘    └─────────────┘    └──────────────┘
      │               │                                        │
      │               │ 配置故障转移                            │
      │               ▼                                        ▼
      │        ┌──────────────┐    ┌─────────────┐    ┌──────────────┐
      │        │ Force Fallback│───▶│   Monitor   │───▶│   Verify     │
      │        │   Databases   │    │    Task     │    │  DB Type     │
      │        └──────────────┘    └─────────────┘    └──────────────┘
      │                                                          │
      └──────────────────────────────────────────────────────────┘
                    验证使用了fallback数据库
```

## 核心组件设计

### 1. APIClient类

```python
class PipelineAPIClient:
    """HTTP API客户端，封装所有API交互"""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key
        self._client = httpx.AsyncClient(timeout=300.0)

    async def create_source(self, config: SourceConfig) -> dict:
        """创建数据源"""

    async def trigger_pipeline(self, source_id: str, max_items: int) -> str:
        """触发管道，返回task_id"""

    async def get_task_status(self, task_id: str) -> TaskStatus:
        """获取任务状态"""

    async def count_articles(self) -> int:
        """获取文章总数"""

    async def get_entity(self, name: str) -> dict | None:
        """获取实体信息"""
```

### 2. SourceConfigBuilder类

```python
class SourceConfigBuilder:
    """根据测试模式构建Source配置"""

    @staticmethod
    def for_newsnow(source_id: str) -> dict:
        return {
            "id": f"newsnow-{source_id}",
            "name": f"NewsNow {source_id}",
            "url": f"https://www.newsnow.world/api/s?id={source_id}",
            "source_type": "newsnow",
            "enabled": True,
            "interval_minutes": 30,
        }

    @staticmethod
    def for_rss(source: str) -> dict:
        RSS_SOURCES = {
            "solidot": {
                "url": "https://www.solidot.org/index.rss",
                "name": "Solidot",
                "credibility": 0.70,
            },
            # ... 其他RSS源
        }
        # ...
```

### 3. TestRunner类

```python
class PipelineTestRunner:
    """测试执行器"""

    async def run_newsnow_test(self, args: Namespace) -> TestResult:
        """执行NewsNow模式测试"""

    async def run_rss_test(self, args: Namespace) -> TestResult:
        """执行RSS模式测试"""

    async def run_strategy_test(self, args: Namespace) -> TestResult:
        """执行Strategy模式测试"""
```

## 数据库清理策略

由于API不提供清理端点，保留直接清理逻辑：

```python
async def clear_databases_if_requested(clear_db: bool, pool, graph_pool) -> None:
    """仅在用户明确请求时清理数据库

    注意：此操作绕过API，直接访问数据库。
    原因：API不提供清理端点，测试需要清理功能。
    """
    if not clear_db:
        return

    # 清理DuckDB/PostgreSQL
    # 清理LadybugDB/Neo4j
```

## Strategy模式实现

Strategy模式需要测试数据库故障转移，实现策略：

```python
async def setup_strategy_mode() -> tuple[Container, dict]:
    """配置Strategy模式环境

    通过环境变量强制使用fallback数据库：
    - PostgreSQL不可达 → DuckDB
    - Neo4j不可达 → LadybugDB
    - Redis不可达 → Cashews内存缓存
    """
    os.environ["POSTGRES_HOST"] = "nonexistent.invalid"
    os.environ["NEO4J_URI"] = "bolt://nonexistent.invalid:7687"
    os.environ["REDIS_HOST"] = "nonexistent.invalid"

    # 初始化Container，会自动选择fallback
    container = await setup_container()

    # 验证使用了fallback
    strategy = container._strategy
    assert strategy.relational_type == "duckdb"
    assert strategy.graph_type == "ladybug"

    return container, {
        "relational_type": strategy.relational_type,
        "graph_type": strategy.graph_type,
    }
```

## 验证逻辑

### 文章验证

```python
async def verify_articles(client: PipelineAPIClient, min_count: int = 1) -> bool:
    """验证文章已存储"""
    response = await client.list_articles(page=1, page_size=1)
    total = response["total"]
    return total >= min_count
```

### 实体验证（可选）

```python
async def verify_entities(client: PipelineAPIClient) -> bool:
    """验证实体已存储（可选）"""
    # 通过Graph API查询实体
    # 注意：可能没有实体（取决于管道处理结果）
    return True
```

### Strategy验证

```python
async def verify_strategy_mode(container: Container) -> bool:
    """验证使用了正确的数据库类型"""
    strategy = container._strategy
    return (
        strategy.relational_type == "duckdb" and
        strategy.graph_type == "ladybug"
    )
```

## 命令行参数

**不需要向后兼容**，参数设计更简洁直观：

```python
parser = argparse.ArgumentParser(description="Unified pipeline test via HTTP API")
parser.add_argument("--mode", choices=["newsnow", "rss", "strategy"], default="newsnow",
                    help="Test mode (default: newsnow)")
parser.add_argument("--source", default="solidot",
                    help="RSS source name for rss mode (default: solidot)")
parser.add_argument("--source-id", default="36kr",
                    help="NewsNow source ID for newsnow mode (default: 36kr)")
parser.add_argument("--max-items", type=int, default=5,
                    help="Maximum items to process (default: 5)")
parser.add_argument("--clear-db", action="store_true",
                    help="Clear databases before testing")
parser.add_argument("--timeout", type=int, default=300,
                    help="Pipeline timeout in seconds (default: 300)")
parser.add_argument("--port", type=int, default=8000,
                    help="API server port (default: 8000)")
```

## 错误处理

```python
class TestError(Exception):
    """测试错误基类"""
    pass

class APITimeoutError(TestError):
    """API超时"""
    pass

class VerificationError(TestError):
    """验证失败"""
    pass

async def run_with_retry(coro, max_retries: int = 3, delay: float = 1.0):
    """带重试的执行"""
    for attempt in range(max_retries):
        try:
            return await coro
        except httpx.HTTPError as e:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(delay * (attempt + 1))
```

## 输出格式

```
============================================================
  PHASE 0: Infrastructure Initialization
============================================================
  ✓ FastAPI server started (port 8000)
  ✓ Database strategy: duckdb + ladybug

============================================================
  PHASE 1: Source Creation
============================================================
  ✓ Created source: newsnow-36kr

============================================================
  PHASE 2: Pipeline Execution
============================================================
  ✓ Pipeline triggered (task_id: abc-123)
  ✓ Task status: running, processed: 3, completed: 2
  ✓ Task completed (status: completed)

============================================================
  PHASE 3: Verification
============================================================
  ✓ Articles stored: 5
  ✓ Entities created: 12

============================================================
  SUMMARY
============================================================
  Elapsed: 45.2s
  Articles: 5
  Entities: 12
  Database: duckdb + ladybug

  Pipeline test PASSED
```