## 1. Update constants and server list

- [x] 1.1 Change `NTP_TIMEOUT` from 3 to 1
- [x] 1.2 Replace `NTP_SERVERS` with extended list: ntp.aliyun.com, ntp.tencent.com, pool.ntp.org, cn.ntp.org.cn, time.google.com
- [x] 1.3 Add `CACHE_TTL = 3600` constant
- [x] 1.4 Add module-level `_ntp_cache` dict with `time` and `expires` keys

## 2. Implement concurrent NTP probing

- [x] 2.1 Rewrite `_get_ntp_time()` to use `threading.Thread` for concurrent requests
- [x] 2.2 Use `threading.Event` for first-success signaling
- [x] 2.3 Ensure total timeout does not exceed `NTP_TIMEOUT` (1s)
- [x] 2.4 Handle all exceptions per-thread without propagating

## 3. Implement TTL cache

- [x] 3.1 Add cache check at entry of `_get_ntp_time()` using `time.monotonic()`
- [x] 3.2 Store successful result with expiration timestamp
- [x] 3.3 Cache miss triggers concurrent NTP probe
- [x] 3.4 Cache `None` results (all servers failed) to avoid repeated probing within TTL

## 4. Improve logging

- [x] 4.1 Change individual server failure log from `debug` to `info`
- [x] 4.2 Keep `warning` for all-servers-failed case
- [x] 4.3 Add info log when cache hit occurs (optional, debug level)

## 5. Update tests

- [x] 5.1 Update existing tests for new server list and timeout value
- [x] 5.2 Add test for concurrent probing (fastest wins)
- [x] 5.3 Add test for TTL cache hit/miss behavior
- [x] 5.4 Add test for cache expiration
- [x] 5.5 Verify all existing tests still pass
