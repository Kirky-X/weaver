# Copyright (c) 2026 KirkyX. All Rights Reserved
"""时间工具模块 - 支持 NTP 网络时间获取"""

from datetime import UTC, datetime

import ntplib

from core.observability.logging import get_logger

log = get_logger("time_utils")

# NTP 服务器列表
NTP_SERVERS = [
    "pool.ntp.org",
    "time.google.com",
    "time.cloudflare.com",
]

# NTP 请求超时(秒)
NTP_TIMEOUT = 3


def get_current_time_with_timezone() -> str:
    """获取当前时间(带本地时区)，优先从 NTP 获取

    尝试顺序:
    1. NTP 服务器 (pool.ntp.org, time.google.com, time.cloudflare.com)
    2. 本地系统时间

    Returns:
        ISO 格式时间字符串，如 "2024-01-15T10:30:45+08:00"
    """
    local_tz = datetime.now().astimezone().tzinfo

    ntp_time = _get_ntp_time()
    if ntp_time:
        local_time = ntp_time.astimezone(local_tz)
        return local_time.isoformat()

    return datetime.now(local_tz).isoformat()


def _get_ntp_time() -> datetime | None:
    """从 NTP 服务器获取时间

    使用 ntplib 库替代手动 socket 实现，提供更好的错误处理和协议支持。

    Returns:
        UTC 时间或 None(获取失败时)
    """
    client = ntplib.NTPClient()

    for server in NTP_SERVERS:
        try:
            response = client.request(server, version=3, timeout=NTP_TIMEOUT)
            return datetime.fromtimestamp(response.tx_time, tz=UTC)
        except ntplib.NTPException as e:
            log.debug("ntp_request_failed", server=server, error=str(e))
            continue
        except Exception as e:
            log.debug("ntp_unexpected_error", server=server, error=str(e))
            continue

    log.warning("ntp_all_servers_failed", servers=NTP_SERVERS)
    return None
