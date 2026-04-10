## Why

Weaver 应用启动时若配置端口被占用会导致启动失败，用户需要手动查找可用端口并修改配置。这在本地开发（多实例运行）和 Docker 部署（容器端口冲突）场景下尤其麻烦。需要自动检测端口可用性并在冲突时智能分配新端口，提升开发运维体验。

## What Changes

- **新增** `PortFinder` 工具类：使用 socket 检测端口可用性，支持双向搜索（优先向上递增）
- **新增** `PortAnnouncer` 工具类：公告实际使用端口（日志、.env 文件、Prometheus 指标）
- **新增** `APISettings.port_auto_detect` 配置项：控制是否启用端口自动检测（默认启用）
- **新增** `APISettings.port_max_attempts` 配置项：控制最大尝试次数（默认 100）
- **修改** `APISettings.__init__()`：在初始化时自动解析可用端口
- **修改** `Dockerfile`：healthcheck 使用动态端口（通过 `.env.weaver` 读取）
- **修改** `start.sh`：启动时输出实际端口信息

## Capabilities

### New Capabilities

- `port-auto-detection`: 应用启动时自动检测端口可用性，若被占用则双向搜索找到可用端口，并通过日志、文件、指标多种方式公告实际端口

### Modified Capabilities

- 无（此为新增功能，不改变现有 API 行为）

## Impact

### 代码变更

| 文件 | 变更类型 |
|------|---------|
| `src/core/net/__init__.py` | 新增 |
| `src/core/net/port_finder.py` | 新增 |
| `src/core/net/port_announcer.py` | 新增 |
| `src/core/net/errors.py` | 新增 |
| `src/config/settings.py` | 修改 |
| `docker/Dockerfile` | 修改 |
| `scripts/start.sh` | 修改 |

### API 变更

- 无 API 接口变更，仅启动行为变化

### 依赖变更

- 无新增外部依赖，使用 Python 标准库 `socket`

### 系统影响

- **日志**：新增结构化日志 `port_check`、`port_resolved`
- **文件**：启动时创建 `.env.weaver` 文件存储实际端口
- **指标**：新增 Prometheus 指标 `weaver_server_port`