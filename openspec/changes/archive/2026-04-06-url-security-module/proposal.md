## Why

Weaver 项目当前仅有 SSRF 防护机制，无法检测恶意 URL（钓鱼、恶意软件分发等）。在爬取外部 URL 时存在安全风险：可能访问恶意站点、暴露用户于钓鱼攻击、或爬取恶意内容。需要增加多层 URL 安全检查机制，在请求发出前识别和阻断恶意 URL。

## What Changes

- 新增 URLhaus API 集成，支持实时恶意 URL 查询（可选，需配置 API key）
- 新增 PhishTank 离线黑名单，定期同步钓鱼 URL 数据
- 新增启发式检测引擎，识别可疑 URL 特征（编码混淆、可疑关键词、域名异常等）
- 新增 SSL 证书验证器，检测可疑证书特征（自签名、非 EV、即将过期等）
- 新增差异化缓存机制，安全结果缓存 6 小时，恶意结果缓存 15 分钟
- 扩展 HttpxFetcher，新增 `post()` 方法支持 POST 请求
- 重构现有 URLValidator 为分层架构，SSRF 检查器独立为模块

## Capabilities

### New Capabilities

- `url-security-checker`: 多层 URL 安全检查能力，包括 URLhaus API 检查、PhishTank 黑名单、启发式检测、SSL 证书验证
- `urlhaus-client`: URLhaus API 客户端，支持恶意 URL 查询和错误回退
- `phishtank-sync`: PhishTank 数据同步和本地查询能力
- `url-heuristic-checker`: URL 启发式安全检测能力
- `ssl-verifier`: SSL 证书安全验证能力

### Modified Capabilities

- `url-validator`: 重构为门面模式，集成多层安全检查

## Impact

**新增文件**:
- `src/core/security/models.py` - 数据模型
- `src/core/security/validator.py` - URLValidator 门面
- `src/core/security/ssrf.py` - SSRF 检查器（从 url_validator.py 提取）
- `src/core/security/cache.py` - 缓存层
- `src/core/security/malicious_url/__init__.py`
- `src/core/security/malicious_url/urlhaus_client.py`
- `src/core/security/malicious_url/phishtank_sync.py`
- `src/core/security/malicious_url/heuristic_checker.py`
- `src/core/security/malicious_url/ssl_verifier.py`

**修改文件**:
- `src/core/security/__init__.py` - 更新导出
- `src/core/security/url_validator.py` - 删除，逻辑迁移到新模块
- `src/modules/ingestion/fetching/httpx_fetcher.py` - 新增 `post()` 方法
- `src/config/settings.py` - 新增 `URLSecuritySettings`

**配置变更**:
- 新增 `[url_security]` 配置节
- 新增环境变量 `WEAVER_URL_SECURITY__URLHAUS_API_KEY`

**数据存储**:
- `data/phishtank.json` - PhishTank 本地数据缓存