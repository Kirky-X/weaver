# Weaver 项目安全性审查报告

**审查日期**: 2026-04-14  
**审查人**: Security Expert Agent  
**项目路径**: `/home/dev/projects/weaver`  
**审查范围**: 全面安全性审计 (OWASP Top 10 + Python 特定 + 现代攻击向量)

---

## 📊 审查摘要

| 审查维度 | 问题数量 | 最高严重级别 | 状态 |
|---------|---------|------------|------|
| OWASP A01: 访问控制 | 3 | High | ⚠️ 需改进 |
| OWASP A02: 加密失败 | 2 | Medium | ⚠️ 需改进 |
| OWASP A03: 注入攻击 | 4 | High | ⚠️ 需改进 |
| OWASP A04: 不安全设计 | 1 | Low | ℹ️ 可接受 |
| OWASP A05: 安全配置错误 | 3 | High | ⚠️ 需改进 |
| OWASP A06: 脆弱组件 | 0 | - | ✅ 通过 |
| OWASP A07: 认证与会话 | 2 | Medium | ⚠️ 需改进 |
| OWASP A08: 软件完整性 | 1 | Medium | ⚠️ 需改进 |
| OWASP A09: 日志与监控 | 1 | Low | ℹ️ 可接受 |
| OWASP A10: SSRF | 1 | Low | ✅ 通过 |
| Python 特定检查 | 1 | High | ⚠️ 需改进 |
| 现代攻击向量 | 1 | Medium | ⚠️ 需改进 |

**总体评分**: **72/100**  
**审查结论**: ⚠️ **Changes Requested** - 发现需要修复的高危和中危问题

---

## 🔴 Critical (严重)

### 无 Critical 级别问题

---

## 🟠 High (高危)

### H-01: SQL 注入风险 - f-string 拼接动态表名

**位置**:
- `src/modules/migration/adapters/postgres_source.py:162,196-200,230`
- `src/modules/migration/adapters/duckdb_target.py:194,222`
- `src/modules/migration/adapters/duckdb_source.py:138,216`

**问题描述**:  
迁移适配器中使用 f-string 拼接表名到 SQL 查询中，虽然使用了 SQLAlchemy 的 `text()` 和参数化查询处理值，但表名直接通过 f-string 嵌入。如果 `table` 参数来自用户输入或外部来源，可能导致 SQL 注入。

```python
# 危险代码示例 (postgres_source.py:162)
result = await conn.execute(
    text(f'SELECT * FROM "{table}" OFFSET :offset LIMIT :limit'),
    {"offset": offset, "limit": limit},
)
```

**置信度**: **High** - 代码明确使用 f-string 拼接表名

**修复建议**:
1. 对所有表名进行白名单验证或严格的标识符验证
2. 使用 `validate_sql_identifier()` 函数（已在 `query_builders.py` 中定义）
3. 确保迁移模块的表名仅来自内部配置，不接受用户输入

```python
# 修复示例
from core.db.query_builders import validate_sql_identifier

# 验证表名
validate_sql_identifier(table)
result = await conn.execute(
    text(f'SELECT * FROM "{table}" OFFSET :offset LIMIT :limit'),
    {"offset": offset, "limit": limit},
)
```

**参考**:
- OWASP A03:2021 - Injection
- CWE-89: SQL Injection

**优先级**: 🔥 **立即修复** (本冲刺)

---

### H-02: pickle 反序列化风险 - 受限但可绕过

**位置**: `src/modules/knowledge/search/retrievers/bm25_retriever.py:32-83`

**问题描述**:  
代码实现了 `RestrictedUnpickler` 来限制可反序列化的类，但白名单中包含 `builtins` 的多个基础类型。攻击者如果控制 pickle 数据流，可能通过允许的类型组合构造恶意 payload（例如通过 `__reduce__` 方法或元类攻击）。

虽然代码在索引加载时使用了 `load_signed_json()` 进行 HMAC 签名验证，但需要确保：
1. 签名密钥不被泄露
2. 索引文件存储路径不可被未授权访问

**置信度**: **Medium-High** - 有缓解措施但仍存在理论风险

**修复建议**:
1. 考虑完全弃用 pickle，改用 JSON 或 MessagePack 等安全序列化格式
2. 如果必须使用 pickle，进一步收紧白名单，仅允许 `BM25Document` 和数据结构
3. 确保签名密钥通过 KMS 或环境变量安全管理
4. 添加索引文件完整性监控

**当前缓解措施**: ✅
- HMAC 签名验证 (`load_signed_json`)
- 受限的类白名单
- 签名密钥从环境变量加载

**参考**:
- OWASP A08:2021 - Software and Data Integrity Failures
- CWE-502: Deserialization of Untrusted Data
- Python pickle 安全最佳实践

**优先级**: 🔥 **本冲刺修复**

---

### H-03: 认证缺失 - 多个端点未强制 API Key

**位置**:
- `src/api/endpoints/content/articles.py` (所有路由)
- `src/api/endpoints/content/search.py` (所有路由)
- `src/api/endpoints/graph/graph.py` (所有路由)
- `src/api/endpoints/communities.py` (所有路由)

**问题描述**:  
大量 API 端点没有使用 `Depends(verify_api_key)` 进行认证保护。这些端点包括：
- 文章列表和详情查询
- 搜索接口（普通搜索、漂移搜索、因果搜索、时间搜索）
- 图数据库查询
- 社区检测

攻击者可以在不提供 API Key 的情况下访问这些端点，可能导致：
- 数据泄露（文章、搜索结果）
- 资源滥用（LLM 调用、数据库查询）
- 拒绝服务

```python
# articles.py - 未认证
@router.get("", response_model=APIResponse[ArticleListResponse])
async def list_articles(...):  # ❌ 缺少 Depends(verify_api_key)
    ...

# admin.py - 已认证
@router.get("/authorities", response_model=APIResponse[...])
async def list_authorities(
    _: str = Depends(verify_api_key),  # ✅ 已认证
    ...
):
    ...
```

**置信度**: **High** - 代码审查确认缺少认证装饰器

**修复建议**:
1. 为所有需要保护的端点添加 `Depends(verify_api_key)`
2. 如果某些端点需要公开访问（如健康检查），明确标记并实施速率限制
3. 考虑创建路由器级别的依赖注入，统一应用认证

```python
# 方案 1: 端点级别
@router.get("", response_model=APIResponse[ArticleListResponse])
async def list_articles(
    _: str = Depends(verify_api_key),  # ✅ 添加认证
    ...
):
    ...

# 方案 2: 路由器级别
router = APIRouter(
    prefix="/articles",
    tags=["articles"],
    dependencies=[Depends(verify_api_key)]  # ✅ 应用到所有路由
)
```

**参考**:
- OWASP A01:2021 - Broken Access Control
- CWE-306: Missing Authentication for Critical Function

**优先级**: 🔥 **立即修复** (本冲刺)

---

### H-04: CORS 配置允许凭证 + 宽松源

**位置**: `src/main.py:348-358`

**问题描述**:  
CORS 配置同时设置了 `allow_credentials=True` 和多个源（包括 localhost）。虽然当前源列表相对安全，但存在以下问题：

1. **生产环境风险**: 如果 `CORS_ORIGINS` 环境变量配置不当（如包含 `*`），会导致凭证泄露
2. **localhost 源**: 包含 `http://127.0.0.1:3000` 等本地源，在生产环境中不应存在
3. **缺少验证**: 未对 CORS 源进行格式验证

```python
cors_origins = os.environ.get(
    "CORS_ORIGINS", "http://localhost:3000,http://localhost:8080,http://127.0.0.1:3000"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,  # ⚠️ 与多源组合有风险
    ...
)
```

**置信度**: **High** - 配置明确存在

**修复建议**:
1. 环境分离：开发和生产使用不同的 CORS 配置
2. 添加源格式验证（必须是有效 URL）
3. 生产环境禁止 `localhost` 源
4. 如果可能，避免 `allow_credentials=True`，改用令牌认证

```python
# 修复示例
import os
from urllib.parse import urlparse

def validate_cors_origins(origins_str: str) -> list[str]:
    """验证 CORS 源列表"""
    origins = [o.strip() for o in origins_str.split(",") if o.strip()]

    environment = os.environ.get("ENVIRONMENT", "development")

    for origin in origins:
        parsed = urlparse(origin)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Invalid CORS origin scheme: {origin}")
        if not parsed.hostname:
            raise ValueError(f"Invalid CORS origin (no hostname): {origin}")

        # 生产环境禁止 localhost
        if environment == "production" and parsed.hostname in ("localhost", "127.0.0.1"):
            raise ValueError(f"localhost not allowed in production CORS: {origin}")

    return origins

cors_origins = validate_cors_origins(
    os.environ.get("CORS_ORIGINS", "http://localhost:3000")
)
```

**参考**:
- OWASP A05:2021 - Security Misconfiguration
- CWE-942: Permissive CORS Policy

**优先级**: 🔥 **本冲刺修复**

---

## 🟡 Medium (中危)

### M-01: SSRF 防护 - DNS Rebinding 攻击未防护

**位置**: `src/core/security/validation/ssrf.py`

**问题描述**:  
SSRF 检查器在 `_validate_ip_address()` 中执行 DNS 解析并检查 IP 地址，但存在 **时间窗口漏洞** (TOCTOU - Time of Check to Time of Use)：

1. 验证时解析 DNS → 获取安全 IP
2. 实际请求时再次解析 DNS → 攻击者控制 DNS 返回恶意 IP（DNS Rebinding）

攻击者可以：
- 注册域名 `attacker.com`，初始解析为安全 IP
- SSRF 检查通过后，修改 DNS 记录指向 `169.254.169.254`（云元数据）
- 实际 HTTP 请求访问内网资源

**置信度**: **Medium** - 理论攻击路径复杂但可行

**修复建议**:
1. 使用连接级别的 IP 验证（在发起 HTTP 请求时验证实际连接的 IP）
2. 实施 DNS pinning（缓存 DNS 结果并复用）
3. 使用网络命名空间隔离或代理

```python
# 修复方案：在 httpx 客户端中实施连接级检查
import httpx
from core.security.validation.ssrf import SSRFChecker

class SSRFProtectedTransport(httpx.AsyncHTTPTransport):
    async def handle_async_request(self, request):
        # 获取实际连接的 IP
        url = str(request.url)
        await SSRFChecker().validate(url)  # 再次验证
        return await super().handle_async_request(request)

# 在创建客户端时使用
transport = SSRFProtectedTransport()
async with httpx.AsyncClient(transport=transport) as client:
    response = await client.get(user_url)
```

**当前缓解措施**: ✅
- 白名单方案验证
- 内网 IP 段阻止
- 云元数据端点阻止

**参考**:
- OWASP A10:2021 - SSRF
- DNS Rebinding 攻击防护指南

**优先级**: 📋 **本冲刺或下冲刺**

---

### M-02: 速率限制未全局启用

**位置**: `src/api/middleware/rate_limit.py`, `src/api/endpoints/*.py`

**问题描述**:  
虽然项目集成了 `slowapi` 速率限制库，但：
1. 仅在 `limiter` 对象中定义，未在路由中实际应用
2. 搜索端点、文章查询端点等未添加 `@limiter.limit()` 装饰器
3. 缺少针对不同端点的差异化限流策略

这可能导致：
- API 滥用（爬取所有文章）
- LLM 成本失控（频繁调用搜索+LLM）
- 拒绝服务

**置信度**: **Medium** - 库已集成但未使用

**修复建议**:
1. 为所有公开端点添加速率限制
2. 根据端点敏感性设置不同限制：
   - 搜索: 100 次/分钟/IP
   - 文章查询: 200 次/分钟/IP
   - 管理端点: 50 次/分钟/IP
3. 对认证失败实施更严格的限制（如 10 次/分钟）

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

# 在端点上应用
@router.get("")
@limiter.limit("100/minute")
async def list_articles(request: Request, ...):
    ...

# 登录/认证失败限制
@limiter.limit("10/minute")
async def verify_api_key(...):
    ...
```

**参考**:
- OWASP A04:2021 - Insecure Design
- CWE-770: Allocation of Resources Without Limits

**优先级**: 📋 **本冲刺**

---

### M-03: HTTP 请求日志记录 API Key 片段

**位置**: `src/main.py:204-217` (HTTPLoggingMiddleware)

**问题描述**:  
HTTP 日志中间件记录 API Key 的前 8 个字符：

```python
api_key = headers.get(b"x-api-key", b"").decode("utf-8")
if api_key:
    api_key_display = api_key[:8] + "..."  # ⚠️ 记录部分密钥
else:
    api_key_display = "none"

log.info("http_request", api_key=api_key_display, ...)
```

虽然仅记录前缀，但：
1. 如果 API Key 格式 predictable，可能帮助攻击者推断
2. 日志可能包含在监控系统中，增加暴露面
3. 违反"日志中不包含密钥"的最佳实践

**置信度**: **Medium** - 明确记录密钥片段

**修复建议**:
1. 仅记录密钥的哈希值（如 SHA256 前 8 位）
2. 或使用密钥 ID 而非密钥本身
3. 在开发环境可保留，生产环境禁用

```python
import hashlib

if api_key:
    # 记录哈希值而非密钥本身
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:8]
    api_key_display = f"hash:{key_hash}"
else:
    api_key_display = "none"
```

**参考**:
- OWASP A09:2021 - Security Logging and Monitoring Failures
- CWE-532: Insertion of Sensitive Information into Log File

**优先级**: 📋 **本冲刺**

---

### M-04: 使用 `random` 模块而非 `secrets` 用于安全场景

**位置**:
- `src/core/llm/evaluation/eval_runner.py:96` - `random.random()`
- `src/modules/ingestion/fetching/rate_limiter.py:54` - `random.uniform()`
- `src/core/llm/evaluation/experience.py` - `import random`

**问题描述**:  
Python 的 `random` 模块使用 Mersenne Twister PRNG，**不适合加密用途**。虽然当前使用场景（LLM 评估采样、请求延迟）不是关键安全场景，但：

1. 如果未来用于令牌生成、密码重置等场景，会导致可预测性
2. 最佳实践应统一使用 `secrets` 模块

**置信度**: **Low-Medium** - 当前使用场景风险低，但有误用风险

**修复建议**:
1. 当前场景可保留 `random`（性能更好，非安全关键）
2. 添加代码审查规则，禁止在安全相关代码中使用 `random`
3. 如果用于任何安全目的，立即替换为 `secrets`

```python
# 如果用于安全场景
import secrets

# 生成随机令牌
token = secrets.token_urlsafe(32)

# 随机选择（加密安全）
secure_choice = secrets.choice(options)
```

**参考**:
- OWASP A02:2021 - Cryptographic Failures
- Python `secrets` 文档

**优先级**: 📋 **待办** (添加代码审查规则)

---

### M-05: 缺少 Content-Security-Policy 头

**位置**: `src/main.py:262-283` (SecurityHeadersMiddleware)

**问题描述**:  
安全头中间件设置了多个安全头，但**缺少 Content-Security-Policy (CSP)**：

```python
headers[b"x-content-type-options"] = b"nosniff"
headers[b"x-frame-options"] = b"DENY"
headers[b"x-xss-protection"] = b"1; mode=block"
headers[b"strict-transport-security"] = b"max-age=31536000; includeSubDomains"
# ❌ 缺少 Content-Security-Policy
```

虽然 API 服务主要返回 JSON，但如果未来有 HTML 响应或错误页面，缺少 CSP 会增加 XSS 风险。

**置信度**: **Medium** - 配置缺失

**修复建议**:
1. 添加严格的 CSP 头
2. 对于纯 API 服务，可以使用最严格的策略

```python
headers[b"content-security-policy"] = b"default-src 'none'; frame-ancestors 'none'"
```

**参考**:
- OWASP A05:2021 - Security Misconfiguration
- CSP 最佳实践指南

**优先级**: 📋 **下冲刺**

---

## 🟢 Low (低危)

### L-01: 开发环境允许弱 API Key

**位置**: `src/api/middleware/auth.py:58-72`

**问题描述**:  
在开发模式下，如果 API Key 长度不足 32 字符，仅记录警告但允许通过：

```python
if not expected_key or len(expected_key) < MIN_API_KEY_LENGTH:
    environment = os.environ.get("ENVIRONMENT", "development")
    if environment == "production":
        raise HTTPException(status_code=500, ...)
    # Development mode: warn but allow weak keys
    log.warning("weak_api_key_detected", ...)
```

**置信度**: **Low** - 开发环境行为符合预期

**修复建议**:
1. 当前实现可接受
2. 考虑在开发环境也强制最小长度（如 16 字符）
3. 添加启动时检查，如果检测到弱密钥则发出明确警告

**优先级**: ℹ️ **可接受**

---

### L-02: 异常处理暴露内部错误细节

**位置**: `src/api/middleware/api_response.py:88-95`

**问题描述**:  
HTTP 异常处理器直接返回 `exc.detail` 给客户端：

```python
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    body = _build_error_response(
        code=exc.status_code * 100 + 1,
        message=str(exc.detail) if exc.detail else f"HTTP {exc.status_code}",
    )
```

如果端点代码抛出包含内部信息的 `HTTPException(detail="Database connection failed: postgresql://user:pass@host:5432/db")`，敏感信息可能泄露。

**置信度**: **Low** - 取决于端点实现

**修复建议**:
1. 对 HTTP 异常消息进行白名单过滤
2. 仅返回预定义的错误消息
3. 详细错误仅记录到日志

```python
# 白名单错误消息
SAFE_ERROR_MESSAGES = {
    "Missing API key": "Missing API key. Provide X-API-Key header.",
    "Invalid API Key": "Invalid API Key",
    # ... 其他安全消息
}

message = SAFE_ERROR_MESSAGES.get(str(exc.detail), "Request failed")
```

**优先级**: ℹ️ **可接受** (当前风险低)

---

### L-03: 日志可能记录敏感 URL 参数

**位置**: `src/main.py:210-217`, `src/core/security/cache.py:97,122`

**问题描述**:  
HTTP 日志记录查询字符串：
```python
log.info("http_request", query=query if query else None, ...)
```

如果 URL 包含敏感参数（如 `?api_key=xxx&token=yyy`），可能被记录。

**置信度**: **Low** - API 使用 Header 认证，URL 中不太可能包含密钥

**修复建议**:
1. 对查询参数进行过滤，移除已知的敏感参数名
2. 仅记录非敏感参数

```python
SENSITIVE_PARAMS = {"api_key", "token", "secret", "password", "key"}

def sanitize_query(query: str | None) -> str | None:
    if not query:
        return None
    # 过滤敏感参数
    params = query.split("&")
    safe_params = [
        p for p in params
        if not p.split("=")[0].lower() in SENSITIVE_PARAMS
    ]
    return "&".join(safe_params) if safe_params else None
```

**优先级**: ℹ️ **可接受**

---

## ℹ️ Info (信息)

### I-01: 依赖项使用非官方 PyPI 镜像

**位置**: `uv.lock:700`

**问题描述**:  
依赖从清华大学镜像源下载：
```
source = { registry = "https://pypi.tuna.tsinghua.edu.cn/simple" }
```

虽然这是合法的中国镜像，但应确保：
1. 镜像源的完整性和可用性
2. 供应链安全（镜像未被篡改）

**修复建议**:
1. 使用 `uv` 的哈希验证（已通过 `uv.lock` 实现）✅
2. 考虑配置多个镜像源作为后备
3. 定期审计依赖项的完整性

**优先级**: ℹ️ **信息性**

---

### I-02: 签名密钥开发环境自动生成

**位置**: `src/core/security/crypto/signing.py:77-85`

**问题描述**:  
如果 `INDEX_SIGNING_KEY` 环境变量未设置，代码会生成随机密钥并警告：

```python
generated_key = secrets.token_hex(32)
logger.warning("signing_key_not_configured", ...)
return cls(key=generated_key.encode("utf-8"))
```

这导致：
1. 每次重启服务后密钥变化
2. 已签名的索引文件失效
3. 需要重新生成索引

**修复建议**:
1. 当前行为可接受（开发环境）
2. 生产环境必须配置持久化密钥
3. 添加启动检查，如果生产环境未配置则拒绝启动

**优先级**: ℹ️ **信息性**

---

## 🛡️ 安全优势 (Positive Findings)

在审查中发现以下**良好的安全实践**：

### ✅ 认证与授权
1. **常量时间比较**: API Key 验证使用 `secrets.compare_digest()` 防止时序攻击
2. **最小 API Key 长度**: 强制 32 字符最小长度
3. **管理端点分离**: 支持独立的 Admin API Key
4. **环境变量管理密钥**: 所有敏感配置通过环境变量加载

### ✅ 注入防护
1. **参数化查询**: 数据库查询使用 SQLAlchemy 参数化
2. **SQL 标识符验证**: 提供 `validate_sql_identifier()` 函数
3. **Neo4j 查询参数化**: 图数据库查询使用 `$param` 语法

### ✅ SSRF 防护
1. **完善的 SSRF 检查器**: 阻止内网 IP、云元数据端点
2. **DNS 解析验证**: 检查解析后的 IP 地址
3. **协议白名单**: 仅允许 HTTP/HTTPS

### ✅ 加密与完整性
1. **HMAC 签名**: 索引文件使用 HMAC-SHA256 签名验证
2. **CSPRNG**: 密钥生成使用 `secrets` 模块
3. **SHA-256 哈希**: URL 和内容哈希使用 SHA-256

### ✅ 安全头
1. **HSTS**: 强制 HTTPS (max-age=31536000)
2. **X-Frame-Options**: DENY 防止点击劫持
3. **X-Content-Type-Options**: nosniff 防止 MIME 嗅探

### ✅ 错误处理
1. **统一错误响应**: 不暴露堆栈跟踪
2. **异常处理器**: 捕获所有未处理异常，返回通用消息
3. **详细日志**: 错误记录到日志但客户端仅看到通用消息

### ✅ 依赖管理
1. **锁定文件**: 使用 `uv.lock` 固定依赖版本
2. **现代依赖**: 使用最新版本的 FastAPI、SQLAlchemy 等
3. **安全工具**: 集成 Bandit、detect-secrets

---

## 📋 修复优先级建议

### 🔥 立即修复 (本周/本冲刺)

| 问题 ID | 问题描述 | 预计工作量 | 风险 |
|---------|---------|-----------|------|
| H-01 | SQL 注入 - f-string 拼接表名 | 2-4 小时 | 高 |
| H-03 | 认证缺失 - 多个端点未保护 | 4-6 小时 | 高 |
| H-04 | CORS 配置风险 | 2-3 小时 | 高 |

### 📋 本冲刺修复 (2 周内)

| 问题 ID | 问题描述 | 预计工作量 | 风险 |
|---------|---------|-----------|------|
| H-02 | pickle 反序列化风险 | 4-8 小时 | 高 |
| M-01 | SSRF DNS Rebinding | 6-10 小时 | 中 |
| M-02 | 速率限制未启用 | 3-5 小时 | 中 |
| M-03 | API Key 日志记录 | 1-2 小时 | 中 |

### 📝 待办 (未来迭代)

| 问题 ID | 问题描述 | 预计工作量 | 风险 |
|---------|---------|-----------|------|
| M-04 | random 模块使用 | 1 小时 (添加规则) | 低 |
| M-05 | 缺少 CSP 头 | 1-2 小时 | 低 |
| L-01 | 弱 API Key 开发环境 | 1 小时 | 低 |
| L-02 | 异常细节暴露 | 2-3 小时 | 低 |
| L-03 | URL 参数日志 | 1-2 小时 | 低 |

---

## 📝 合规性检查

| 标准 | 状态 | 备注 |
|-----|------|------|
| OWASP Top 10 (2021) | ⚠️ 部分合规 | 发现 A01, A03, A05 相关问题 |
| Python 安全最佳实践 | ⚠️ 部分合规 | pickle 使用需改进 |
| 认证与授权 | ⚠️ 需改进 | 多个端点缺少认证 |
| 输入验证 | ✅ 良好 | SQL 参数化、URL 验证 |
| 加密实践 | ✅ 良好 | HMAC, SHA-256, secrets |
| 错误处理 | ✅ 良好 | 不暴露堆栈跟踪 |
| 日志安全 | ⚠️ 需改进 | API Key 日志记录 |
| 依赖安全 | ✅ 良好 | 锁定文件、现代版本 |

---

## 🎯 后续行动建议

### 1. 立即行动
- [ ] 修复 H-01: 为所有 SQL 表名添加 `validate_sql_identifier()` 调用
- [ ] 修复 H-03: 为所有需要保护的端点添加 `Depends(verify_api_key)`
- [ ] 修复 H-04: 实施 CORS 源验证和环境分离

### 2. 安全工具集成
- [ ] 在 CI/CD 中运行 Bandit 扫描
- [ ] 在 CI/CD 中运行 `detect-secrets` 扫描
- [ ] 配置依赖项漏洞扫描（如 GitHub Dependabot）
- [ ] 添加 SAST 工具到预提交钩子

### 3. 安全测试
- [ ] 实施渗透测试（重点关注 SQL 注入和认证绕过）
- [ ] 添加安全相关的自动化测试用例
- [ ] 对 SSRF 防护进行红队测试

### 4. 文档与培训
- [ ] 创建安全编码指南文档
- [ ] 为团队进行安全编码培训
- [ ] 记录所有安全控制措施和缓解方案

### 5. 监控与响应
- [ ] 添加安全事件告警（认证失败、权限拒绝等）
- [ ] 实施异常检测（异常 API 调用模式）
- [ ] 创建安全事件响应预案

---

## 📞 联系与支持

如果在修复这些问题时需要进一步的技术支持或安全咨询，请参考：

- **OWASP Cheat Sheet Series**: https://cheatsheetseries.owasp.org/
- **Python Security Best Practices**: https://python-security.readthedocs.io/
- **FastAPI Security**: https://fastapi.tiangolo.com/tutorial/security/

---

**报告结束**

*本审查报告基于静态代码分析和配置审查生成。建议结合动态安全测试（DAST）和渗透测试进行更全面的安全评估。*
