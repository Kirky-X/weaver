# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors

# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""时间工具模块 - 支持 NTP 网络时间获取"""

from datetime import UTC, datetime
from threading import Event, Thread
from time import monotonic
from typing import TYPE_CHECKING, Any

import ntplib  # type: ignore[import-untyped]

from core.observability import get_logger

if TYPE_CHECKING:
    from core.cache import RedisClient

log = get_logger(__name__)

# NTP server list (China priority)
NTP_SERVERS = [
    "ntp.aliyun.com",
    "ntp.tencent.com",
    "pool.ntp.org",
    "cn.ntp.org.cn",
    "time.google.com",
]

# NTP 请求超时(秒)
NTP_TIMEOUT = 1

# NTP 缓存 TTL(秒)
CACHE_TTL = 3600

# Redis key for NTP cache
NTP_REDIS_KEY = "weaver:ntp:time"

# 模块级 NTP 缓存 (进程内降级)
_ntp_cache: dict[str, datetime | None | str | float] = {"time": None, "expires": 0.0}

# 单例 NTP 客户端
_ntp_client: ntplib.NTPClient | None = None

# Redis 客户端引用 (由外部注入)
_redis_client: "RedisClient | None" = None


def set_redis_client(redis_client: "RedisClient") -> None:
    """设置 Redis 客户端用于分布式 NTP 缓存.

    Args:
        redis_client: Redis 客户端实例
    """
    global _redis_client
    _redis_client = redis_client


def _get_ntp_client() -> ntplib.NTPClient:
    """获取单例 NTP 客户端."""
    global _ntp_client
    if _ntp_client is None:
        _ntp_client = ntplib.NTPClient()
    return _ntp_client


def get_current_time_with_timezone() -> str:
    """获取当前时间(带本地时区)，优先从 NTP 获取

    尝试顺序:
    1. 并发探测 NTP 服务器 (阿里云、腾讯云、pool.ntp.org、中国NTP、Google)
    2. 本地系统时间(降级)

    Returns:
        ISO 格式时间字符串，如 "2024-01-15T10:30:45+08:00"
    """
    local_tz = datetime.now().astimezone().tzinfo

    ntp_time = _get_ntp_time()
    if ntp_time:
        local_time = ntp_time.astimezone(local_tz)
        return local_time.isoformat()

    return datetime.now(local_tz).isoformat()


def convert_timestamp(ts: Any) -> str | None:
    """Convert timestamp from Neo4j DateTime, LadybugDB INT64, or string to ISO format.

    Handles multiple timestamp formats from Neo4j and LadybugDB:
    - Neo4j DateTime objects (has isoformat/iso_format)
    - Integer timestamps (seconds or milliseconds)
    - Already formatted strings

    Args:
        ts: Timestamp value to convert.

    Returns:
        ISO format string or None.
    """
    if ts is None:
        return None
    if isinstance(ts, int):
        if ts > 1_000_000_000_000:
            return datetime.fromtimestamp(ts / 1000, tz=UTC).isoformat()
        return datetime.fromtimestamp(ts, tz=UTC).isoformat()
    if hasattr(ts, "iso_format"):
        return ts.iso_format()
    if hasattr(ts, "isoformat"):
        return ts.isoformat()
    return str(ts)


def _get_ntp_time() -> datetime | None:
    """从 NTP 服务器获取时间

    使用并发线程同时向所有 NTP 服务器发送请求，第一个成功响应者获胜。
    结果优先从 Redis 缓存读取(跨进程共享),降级到进程内缓存。

    Returns:
        UTC 时间或 None(获取失败时)
    """
    # 优先检查 Redis 缓存 (跨进程共享)
    if _redis_client:
        try:
            cached = _redis_client.get(NTP_REDIS_KEY)
            if cached:
                return datetime.fromisoformat(cached)
        except Exception as exc:
            log.debug("ntp_redis_cache_read_failed", error=str(exc))

    # 降级到进程内缓存
    if monotonic() < _ntp_cache["expires"]:
        return _ntp_cache["time"]  # type: ignore[return-value]

    result: dict[str, datetime | None] = {"time": None}
    ready = Event()

    def _probe(server: str) -> None:
        try:
            client = _get_ntp_client()
            response = client.request(server, version=4, timeout=NTP_TIMEOUT)
            ts = datetime.fromtimestamp(response.tx_time, tz=UTC)
            if result["time"] is None:
                result["time"] = ts
                ready.set()
        except ntplib.NTPException as e:
            log.info("ntp_request_failed", server=server, error=str(e))
        except Exception as e:
            log.info("ntp_unexpected_error", server=server, error=str(e))

    threads = [Thread(target=_probe, args=(s,), daemon=True) for s in NTP_SERVERS]
    for t in threads:
        t.start()

    ready.wait(timeout=NTP_TIMEOUT)

    if result["time"] is not None:
        # 写入 Redis 缓存 (跨进程共享)
        if _redis_client:
            try:
                iso_time = result["time"].isoformat()
                _redis_client.set(NTP_REDIS_KEY, iso_time, ex=CACHE_TTL)
            except Exception as exc:
                log.debug("ntp_redis_cache_write_failed", error=str(exc))

        # 同时更新进程内缓存 (降级保护)
        _ntp_cache["time"] = result["time"]
        _ntp_cache["expires"] = monotonic() + CACHE_TTL
        return result["time"]

    # 全部失败
    log.warning("ntp_all_servers_failed", servers=NTP_SERVERS)
    _ntp_cache["time"] = None
    _ntp_cache["expires"] = monotonic() + CACHE_TTL
    return None
