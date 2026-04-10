## Why

NTP 时间同步在当前运行环境（WSL2、Docker、国内网络）中几乎总是失败，导致每次调用 `get_current_time_with_timezone()` 浪费 9-10 秒等待超时。该函数被 LLM 客户端频繁调用（usage event 记录、system prompt 注入），直接影响用户体验。

## What Changes

- NTP 超时从 3 秒缩短至 1 秒，快速失败
- NTP 服务器列表扩展为 5 个，优先国内可达地址（阿里云、腾讯云）
- 改为并发请求所有 NTP 服务器，谁先返回用谁，总耗时 = min(最快响应, 1s)
- 新增 1 小时 TTL 内存缓存，消除重复 NTP 请求
- 日志级别从 debug 提升至 info，便于运维监控 NTP 健康状态

## Capabilities

### New Capabilities

- `ntp-time-reliability`: 可靠的 NTP 时间同步能力，包括并发探测、快速失败、TTL 缓存降级

### Modified Capabilities

<!-- 无现有 spec 变更 -->

## Impact

- `src/core/utils/time_utils.py`: 核心实现变更
- `tests/unit/core/test_time_utils.py`: 测试适配新逻辑（并发、缓存、新服务器列表）
- 向下兼容：API 签名不变，返回值格式不变，缓存对调用方透明
