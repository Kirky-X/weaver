## Why

测试脚本 `scripts/test_pipeline.py` 中 NewsNow API 基础 URL 已过时（`newsnow.net.cn`），需要更新为当前可用的 `newsnow.world`。同时，源ID（如 `36kr`、`hupu`）硬编码在代码中，缺乏灵活性，无法测试不同的资讯源。

## What Changes

- 更新 `NewsNowParser.API_BASE_URL` 为 `https://www.newsnow.world/api/s?id=`
- 为 `test_pipeline.py` 添加 `--source-id` 命令行参数，支持指定 NewsNow 资讯源ID
- 默认源ID 改为 `36kr`（原硬编码 `hupu`）

## Capabilities

### New Capabilities

- `newsnow-source-param`: 测试脚本支持通过命令行参数指定 NewsNow 资讯源ID

### Modified Capabilities

- `unified-pipeline-test`: 更新 NewsNow API URL 以匹配当前服务端点

## Impact

- `src/modules/ingestion/parsing/newsnow_parser.py` — API_BASE_URL 常量
- `scripts/test_pipeline.py` — 添加 `--source-id` 参数，修改 `fetch_newsnow_data` 函数