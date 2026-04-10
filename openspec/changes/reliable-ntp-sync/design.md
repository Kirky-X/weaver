## Context

`get_current_time_with_timezone()` 位于 `src/core/utils/time_utils.py`，被 LLM 客户端（`src/core/llm/client.py`）在两个关键路径调用：
1. `_emit_usage_event()` — 记录 LLM 调用时间戳
2. `call_at()` — 注入 system prompt 中的当前时间

当前实现串行遍历 3 个 NTP 服务器，每个超时 3 秒，全部失败时浪费 ~9 秒后降级到本地系统时间。实测在 WSL2/国内网络环境下，Google 和 Cloudflare 的 NTP 服务器因 UDP 123 端口被防火墙拦截而超时。

用户可接受小时级时间差异，因此 NTP 是"锦上添花"而非"必须可靠"。

## Goals / Non-Goals

**Goals:**
- NTP 探测总耗时不超过 1 秒（并发 + 快速失败）
- 成功获取一次 NTP 时间后缓存 1 小时，消除重复网络开销
- 适配多环境（WSL2、Docker、Linux 服务器、国内网络）
- 向下兼容：API 签名和返回值格式不变

**Non-Goals:**
- 不引入外部缓存依赖（Redis 等），使用纯内存缓存
- 不保证 NTP 100% 成功率（允许降级到本地时间）
- 不修改调用方代码

## Decisions

### 1. 并发请求替代串行遍历

**决策:** 使用 `threading.Thread` 同时向所有 NTP 服务器发送请求，通过 `threading.Event` 等待第一个成功响应。

**为什么不用 asyncio:** `ntplib` 是同步库，在 async 环境中用 `asyncio.to_thread()` 包裹仍然需要多个线程。直接用 threading 更简单。

**为什么不用 `concurrent.futures`:** 只需要 "first success" 语义，threading.Event 更轻量。

### 2. TTL 缓存使用模块级字典

**决策:** 用 `{"time": str | None, "expires": float}` 字典 + `time.monotonic()` 实现 3600 秒 TTL。

**为什么不用 `functools.lru_cache`:** 没有时间失效机制，进程生命周期内永久返回同一值。

**为什么不用 `functools.cache` + TTL wrapper:** 增加不必要的抽象层，直接字典更清晰。

### 3. NTP 服务器列表（国内优先）

```
ntp.aliyun.com        — 阿里云 NTP，国内高可用
ntp.tencent.com       — 腾讯云 NTP，国内高可用
pool.ntp.org          — 国际标准池
cn.ntp.org.cn         — 中国 NTP 兜底
time.google.com       — 海外环境备用
```

排序策略：国内服务器在前，海外在后。并发请求下顺序不影响速度，但影响日志可读性（优先记录成功率高的服务器）。

### 4. 超时设为 1 秒

用户接受小时级差异，NTP 不是关键路径。1 秒在国内网络环境下充裕（UDP 延迟通常 <100ms），同时保证失败时快速降级。

### 5. 总超时 = 1 秒（非每服务器 1 秒）

并发模型下所有线程共享同一个 1 秒超时。即使 5 个服务器全不可达，总等待也不超过 1 秒。

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| 进程重启后首次调用增加 1s 延迟 | 可接受：每小时最多发生一次 |
| threading 在极少数环境可能有开销 | 最多 5 个轻量线程，开销可忽略 |
| 缓存时间内系统时钟被修正 | 可接受：用户容忍小时级差异 |
| `time.monotonic()` 在进程重启后重置 | 正确行为：重启后重新探测 NTP |
