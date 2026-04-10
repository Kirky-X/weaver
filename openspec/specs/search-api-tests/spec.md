## REMOVED Requirements

### Requirement: 搜索端点 - 手动 mode 覆盖
**Reason**: The `mode` parameter is deprecated in favor of automatic intent-based routing. Manual mode selection (`?mode=local`, `?mode=global`, `?mode=articles`) will be removed in a future release.
**Migration**: Remove `mode`, `entity_names`, and `max_tokens` query parameters from client requests. Use `GET /api/v1/search?q=...` for automatic intent routing.
