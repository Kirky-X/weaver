"""时间工具模块 - 支持 NTP 网络时间获取"""

import socket
import struct
from datetime import datetime, timezone


def get_current_time_with_timezone() -> str:
    """获取当前时间（带本地时区），优先从 NTP 获取

    尝试顺序:
    1. NTP 服务器 (pool.ntp.org, time.google.com)
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

    Returns:
        UTC 时间或 None（获取失败时）
    """
    NTP_SERVERS = [
        "pool.ntp.org",
        "time.google.com",
        "time.cloudflare.com",
    ]

    for server in NTP_SERVERS:
        try:
            return _query_ntp(server)
        except Exception:
            continue
    return None


def _query_ntp(server: str) -> datetime:
    """查询单个 NTP 服务器"""
    NTP_PACKET = b'\x1b' + 47 * b'\0'
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(3)
    sock.sendto(NTP_PACKET, (server, 123))
    response, _ = sock.recvfrom(1024)
    sock.close()

    unpacked = struct.unpack('!12I', response)
    timestamp = unpacked[10] - 2208988800
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)
