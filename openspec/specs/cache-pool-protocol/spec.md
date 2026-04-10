## ADDED Requirements

### Requirement: CachePool Protocol Definition

系统 SHALL 定义 `CachePool` Protocol，作为所有缓存实现的统一接口。

`CachePool` Protocol MUST 包含以下方法签名：

**生命周期管理:**
- `async def startup(self) -> None` - 初始化缓存连接
- `async def shutdown(self) -> None` - 关闭缓存连接
- `async def ping(self) -> bool` - 检查缓存连接状态

**Key/Value 操作:**
- `async def get(self, key: str) -> str | None` - 获取值
- `async def set(self, key: str, value: str, ex: int | None = None) -> None` - 设置值（可选 TTL）
- `async def delete(self, *keys: str) -> int` - 删除键
- `async def expire(self, name: str, seconds: int) -> bool` - 设置过期时间

**Hash 操作:**
- `async def hget(self, name: str, key: str) -> str | None` - 获取哈希字段
- `async def hset(self, name: str, key: str, value: str) -> None` - 设置哈希字段
- `async def hexists(self, name: str, key: str) -> bool` - 检查字段存在
- `async def hgetall(self, name: str) -> dict[str, str]` - 获取所有字段

**List 操作:**
- `async def lpush(self, name: str, *values: str) -> int` - 左推入列表
- `async def rpop(self, name: str) -> str | None` - 右弹出列表
- `async def llen(self, name: str) -> int` - 获取列表长度

**Sorted Set 操作:**
- `async def zadd(self, name: str, mapping: dict[str, float]) -> int` - 添加有序集合成员
- `async def zrangebyscore(self, name: str, min_score: float, max_score: float, start: int = 0, num: int = 100) -> list[str]` - 按分数范围查询
- `async def zrem(self, name: str, *members: str) -> int` - 删除有序集合成员

**Scan 操作:**
- `async def scan(self, cursor: int = 0, match: str | None = None, count: int = 10) -> tuple[int, list[str]]` - 增量扫描键

#### Scenario: RedisClient implements CachePool

- **WHEN** 检查 `RedisClient` 类是否实现 `CachePool` Protocol
- **THEN** `isinstance(RedisClient("redis://localhost"), CachePool)` 返回 `True`

#### Scenario: CashewsRedisFallback implements CachePool

- **WHEN** 检查 `CashewsRedisFallback` 类是否实现 `CachePool` Protocol
- **THEN** `isinstance(CashewsRedisFallback(), CachePool)` 返回 `True`

### Requirement: CachePool Location

`CachePool` Protocol MUST 定义在 `src/core/protocols/pools.py` 文件中，并在 `src/core/protocols/__init__.py` 中重导出。

#### Scenario: CachePool import path

- **WHEN** 代码需要使用 `CachePool` Protocol
- **THEN** 可以通过 `from core.protocols import CachePool` 导入

### Requirement: Cache Implementations Declaration

所有缓存实现类 MUST 在其文档字符串中显式声明实现的 Protocol：

```python
class RedisClient:
    """Redis async client.

    Implements:
        - CachePool: Cache protocol with Redis backend
    """
```

#### Scenario: RedisClient has explicit declaration

- **WHEN** 查看 `RedisClient` 类的文档字符串
- **THEN** 文档字符串包含 "Implements:" 部分并声明 `CachePool`

#### Scenario: CashewsRedisFallback has explicit declaration

- **WHEN** 查看 `CashewsRedisFallback` 类的文档字符串
- **THEN** 文档字符串包含 "Implements:" 部分并声明 `CachePool`