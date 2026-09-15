# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors

# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""时间工具模块 - 支持 NTP 网络时间获取"""

from datetime import UTC, datetime
from threading import Event, Lock, Thread
from time import monotonic
from typing import Any

import ntplib  # type: ignore[import-untyped]

from core.observability import get_logger

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

# 模块级 NTP 缓存 (进程内)
_ntp_cache: dict[str, datetime | None | float] = {"time": None, "expires": 0.0}

# 保护缓存读写的锁：避免过期后多线程并发重建探测线程（惊群），
# 以及 time/expires 两个字段写入交错导致的不一致状态。
_ntp_cache_lock = Lock()

# NTP 探测进行中标志（配合 _ntp_cache_lock 使用）
_ntp_probing = False


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


def get_current_date() -> str:
    """获取当前本地日期（YYYY-MM-DD）。

    供 LLM system_prompt 尾部时间锚定使用：日粒度保证同一自然日内
    prompt 逐字节稳定（客户端缓存 key 与服务端前缀缓存均可用），
    因此刻意不走 NTP——秒级精度对日期无意义且会破坏日内稳定性。
    """
    return datetime.now().astimezone().date().isoformat()


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
    结果缓存到进程内缓存（TTL=3600s）。

    Note: Previously attempted Redis cross-process cache, but RedisClient is async
    and cannot be awaited in this sync function (coroutine never awaited
    caused fromisoformat TypeError). Removed — NTP is low-frequency (1hr TTL),
    process-local cache is sufficient for single-process uvicorn deployment.

    Returns:
        UTC 时间或 None(获取失败时)
    """
    # 进程内缓存（锁内 double-check，防止惊群与缓存状态不一致）
    global _ntp_probing
    with _ntp_cache_lock:
        if monotonic() < _ntp_cache["expires"]:
            return _ntp_cache["time"]  # type: ignore[return-value]
        if _ntp_probing:
            # 另一线程正在探测：直接降级本地时间，不再重复探测
            return _ntp_cache["time"]  # type: ignore[return-value]
        _ntp_probing = True

    try:
        result: dict[str, datetime | None] = {"time": None}
        ready = Event()

        def _probe(server: str) -> None:
            # 每个探测线程使用独立的 NTPClient，避免共享实例的内部状态问题
            try:
                client = ntplib.NTPClient()
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

        with _ntp_cache_lock:
            if result["time"] is not None:
                _ntp_cache["time"] = result["time"]
                _ntp_cache["expires"] = monotonic() + CACHE_TTL
                return result["time"]

            # 全部失败
            log.warning("ntp_all_servers_failed", servers=NTP_SERVERS)
            _ntp_cache["time"] = None
            _ntp_cache["expires"] = monotonic() + CACHE_TTL
            return None
    finally:
        with _ntp_cache_lock:
            _ntp_probing = False
