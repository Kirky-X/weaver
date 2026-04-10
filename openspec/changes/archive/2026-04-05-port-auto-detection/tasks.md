## 1. Core Infrastructure

- [x] 1.1 Create `src/core/net/__init__.py` module
- [x] 1.2 Create `src/core/net/errors.py` with `PortError`, `PortExhaustionError` exception classes
- [x] 1.3 Create `src/core/net/port_finder.py` with `PortFinder` class implementing `is_port_available()` and `find_available_port()`
- [x] 1.4 Create `src/core/net/port_announcer.py` with `PortAnnouncer` class implementing `announce()`

## 2. Configuration Integration

- [x] 2.1 Add `port_auto_detect: bool = True` field to `APISettings` in `src/config/settings.py`
- [x] 2.2 Add `port_max_attempts: int = 100` field to `APISettings`
- [x] 2.3 Implement `APISettings._resolve_port()` method calling `PortFinder` and `PortAnnouncer`
- [x] 2.4 Update `APISettings.__init__()` to call `_resolve_port()` when `port_auto_detect` is enabled

## 3. Prometheus Metrics

- [x] 3.1 Add `weaver_server_port` Gauge metric to `src/core/observability/metrics.py`
- [x] 3.2 Update `PortAnnouncer` to set the metric when announcing port

## 4. Docker Support

- [x] 4.1 Update `docker/Dockerfile` healthcheck to read port from `.env.weaver`
- [x] 4.2 Update `scripts/start.sh` to output port information on startup

## 5. Unit Tests

- [x] 5.1 Create `tests/unit/core/net/__init__.py`
- [x] 5.2 Create `tests/unit/core/net/test_port_finder.py` with tests for `is_port_available()` and `find_available_port()`
- [x] 5.3 Create `tests/unit/core/net/test_port_announcer.py` with tests for `announce()`
- [x] 5.4 Create tests for `APISettings._resolve_port()` in `tests/unit/config/`

## 6. Integration Tests

- [x] 6.1 Create `tests/integration/test_port_detection_integration.py` with end-to-end tests
- [x] 6.2 Verify port detection works with `uvicorn` startup

## 7. Documentation

- [x] 7.1 Update `docs/ARCHITECTURE.md` to document port auto-detection feature
- [x] 7.2 Add usage examples to `docs/USER_GUIDE.md`