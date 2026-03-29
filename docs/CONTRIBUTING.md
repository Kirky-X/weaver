# 贡献指南

感谢您对 Weaver 项目的关注！本文档将帮助您了解如何参与项目贡献。

## 目录

- [行为准则](#行为准则)
- [如何贡献](#如何贡献)
- [开发环境搭建](#开发环境搭建)
- [代码规范](#代码规范)
- [提交规范](#提交规范)
- [审查流程](#审查流程)
- [发布流程](#发布流程)

---

## 行为准则

### 我们的承诺

为了营造一个开放和友好的环境，我们作为贡献者和维护者承诺：

- 无论年龄、体型、残疾、种族、性别特征、性别认同和表达、经验水平、教育程度、社会经济地位、国籍、个人外貌、种族、宗教或性取向如何，都对每个人表示尊重和礼貌
- 接受建设性批评，并以优雅的方式接受
- 关注对社区最有利的事情
- 对其他社区成员表示同理心

### 不可接受的行为

- 使用性化语言或图像，以及不受欢迎的性关注或挑逗
- 发表挑衅、侮辱性/贬损性评论，以及人身或政治攻击
- 公开或私下骚扰
- 未经明确许可，发布他人的私人信息
- 其他在专业环境中被认为不适当的行为

---

## 如何贡献

### 报告 Bug

如果您发现了 Bug，请通过 [GitHub Issues](https://github.com/your-org/weaver/issues) 报告，并包含以下信息：

1. **问题描述**：清晰简洁地描述 Bug
2. **复现步骤**：详细说明如何复现该问题
3. **期望行为**：描述您期望发生的行为
4. **实际行为**：描述实际发生的行为
5. **环境信息**：
   - 操作系统及版本
   - Python 版本
   - 相关依赖版本
6. **附加信息**：截图、日志片段等

### 建议新功能

如果您有新功能建议：

1. 先检查是否已有类似的 Issue
2. 如果没有，创建新的 Issue，使用 "Feature Request" 标签
3. 详细描述：
   - 功能的使用场景
   - 期望的行为
   - 可能的实现方案（如果您有想法）

### 提交代码

#### 工作流程

1. **Fork 仓库**
   ```bash
   git clone https://github.com/yourusername/weaver.git
   cd weaver
   ```

2. **创建分支**
   ```bash
   git checkout -b feature/your-feature-name
   # 或
   git checkout -b fix/bug-description
   ```

3. **进行更改**
   - 编写代码
   - 添加测试
   - 更新文档

4. **提交更改**
   ```bash
   git add .
   git commit -m "feat: 添加新功能描述"
   ```

5. **推送到您的 Fork**
   ```bash
   git push origin feature/your-feature-name
   ```

6. **创建 Pull Request**
   - 在 GitHub 上创建 PR
   - 填写 PR 模板
   - 等待审查

---

## 开发环境搭建

### 前提条件

- Python 3.12+
- PostgreSQL 15+ (带 pgvector 扩展)
- Neo4j 5+
- Redis 7+

### 安装步骤

1. **克隆仓库**
   ```bash
   git clone https://github.com/your-org/weaver.git
   cd weaver
   ```

2. **安装依赖**
   ```bash
   # 使用 uv (推荐)
   uv sync

   # 或使用 pip
   pip install -e ".[dev]"
   ```

3. **安装浏览器**
   ```bash
   uv run playwright install chromium
   ```

4. **安装 NLP 模型**
   ```bash
   uv pip install "spacy-pkuseg>=0.0.27,<0.1.0"
   uv run python -m spacy download zh_core_web_sm
   ```

5. **配置环境**
   ```bash
   cp config/settings.example.toml config/settings.toml
   # 编辑 settings.toml 配置数据库连接
   ```

6. **运行数据库迁移**
   ```bash
   uv run alembic upgrade head
   ```

7. **验证安装**
   ```bash
   uv run pytest tests/unit/ -v
   ```

### 开发服务器

```bash
# 启动开发服务器
uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# 或使用脚本
uv run python -m src.main
```

---

## 代码规范

### Python 代码风格

我们使用以下工具确保代码质量：

| 工具 | 用途 | 配置 |
|------|------|------|
| **Ruff** | 代码格式化和 Lint | `pyproject.toml` |
| **Black** | 代码格式化 | `pyproject.toml` |
| **isort** | Import 排序 | `pyproject.toml` |
| **mypy** | 静态类型检查 | `pyproject.toml` |
| **bandit** | 安全漏洞扫描 | `pyproject.toml` |

### 运行代码检查

```bash
# 格式化代码
uv run ruff check --fix src/
uv run black src/
uv run isort src/

# 类型检查
uv run mypy src/

# 安全扫描
uv run bandit -r src/

# 运行所有检查
uv run ruff check src/ && uv run mypy src/ && uv run bandit -r src/
```

### 代码风格指南

#### 命名规范

```python
# 模块名：小写，下划线分隔
# ✓ article_processor.py
# ✗ ArticleProcessor.py

# 类名：驼峰命名
class ArticleProcessor:
    pass

# 函数/方法名：小写，下划线分隔
def process_article(article: Article) -> ProcessedArticle:
    pass

# 常量：大写，下划线分隔
MAX_RETRY_COUNT = 3
DEFAULT_TIMEOUT = 30.0

# 私有成员：下划线前缀
class MyClass:
    def __init__(self):
        self._private_var = 0
        self.public_var = 1

    def _private_method(self):
        pass
```

#### 类型注解

```python
from typing import Optional, List, Dict, Any

# 函数参数和返回值必须有类型注解
def fetch_article(
    url: str,
    timeout: float = 30.0,
    headers: Optional[Dict[str, str]] = None
) -> Optional[Article]:
    """获取文章内容.

    Args:
        url: 文章 URL
        timeout: 超时时间（秒）
        headers: 可选的请求头

    Returns:
        文章对象，如果获取失败则返回 None
    """
    pass

# 类属性也需要类型注解
class Article(BaseModel):
    id: UUID
    title: str
    content: Optional[str] = None
    tags: List[str] = []
    metadata: Dict[str, Any] = {}
```

#### 文档字符串

使用 Google 风格的文档字符串：

```python
def process_articles(
    articles: List[Article],
    batch_size: int = 100,
    concurrent: bool = True
) -> ProcessingResult:
    """批量处理文章.

    该函数支持并发处理，可以显著提高大批量文章的处理速度。
    处理过程中会自动进行错误处理和重试。

    Args:
        articles: 待处理的文章列表
        batch_size: 每批处理的数量，默认为 100
        concurrent: 是否启用并发处理，默认为 True

    Returns:
        ProcessingResult 包含处理结果统计信息

    Raises:
        ValueError: 如果 batch_size 小于 1
        ProcessingError: 如果处理过程中发生严重错误

    Example:
        >>> articles = [Article(title="Test", content="Content")]
        >>> result = process_articles(articles, batch_size=50)
        >>> print(f"成功: {result.success_count}")
    """
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    # ...
```

#### 错误处理

```python
# 使用具体的异常类型
try:
    article = await fetcher.fetch(url)
except URLValidationError as e:
    # URL 验证失败
    logger.warning(f"Invalid URL: {e.message}")
    return None
except FetchTimeoutError:
    # 超时
    logger.warning(f"Fetch timeout for {url}")
    raise RetryableError("Timeout, will retry")
except FetchError as e:
    # 其他获取错误
    logger.error(f"Fetch failed: {e}")
    return None

# 不要捕获所有异常而不处理
try:
    result = process()
except Exception:  # ❌ 不好
    pass

# 如果要捕获所有异常，至少要记录
try:
    result = process()
except Exception as e:  # ✓ 可以，但仅在顶层使用
    logger.exception("Unexpected error occurred")
    raise
```

---

## 提交规范

### 提交信息格式

我们使用 [Conventional Commits](https://www.conventionalcommits.org/) 规范：

```
<type>(<scope>): <subject>

<body>

<footer>
```

#### Type

| 类型 | 说明 |
|------|------|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `docs` | 文档更新 |
| `style` | 代码格式（不影响功能的更改） |
| `refactor` | 代码重构 |
| `perf` | 性能优化 |
| `test` | 测试相关 |
| `chore` | 构建/工具链/依赖更新 |
| `ci` | CI/CD 相关 |
| `revert` | 回滚提交 |

#### Scope

可选，表示更改的范围：

- `api` - API 端点
- `pipeline` - 处理流水线
- `storage` - 存储层
- `fetcher` - 抓取器
- `search` - 搜索功能
- `graph` - 知识图谱
- `deps` - 依赖

#### 示例

```bash
# 新功能
feat(api): 添加文章批量导出接口

# Bug 修复
fix(pipeline): 修复重复文章去重逻辑

# 文档
docs(readme): 更新安装说明

# 重构
refactor(storage): 优化数据库查询性能

# 带范围的提交
feat(search): 实现混合检索算法

# 带主体的提交
feat(api): 添加速率限制支持

添加基于 Redis 的滑动窗口速率限制，支持按 IP 和 API Key 两种维度限制。

- 实现 RateLimiter 类
- 添加中间件集成
- 支持自定义限制规则

Closes #123
```

### 提交前检查清单

在提交代码前，请确保：

- [ ] 代码遵循项目代码风格
- [ ] 所有测试通过
- [ ] 新增功能有测试覆盖
- [ ] 类型检查通过
- [ ] 安全扫描无高危问题
- [ ] 文档已更新（如需要）

---

## 审查流程

### Pull Request 流程

1. **创建 PR**
   - 使用清晰的标题
   - 填写 PR 模板
   - 关联相关 Issue

2. **自动化检查**
   - CI 会运行测试
   - 代码覆盖率检查
   - Lint 检查

3. **代码审查**
   - 至少需要 1 个审查者批准
   - 解决所有评论
   - 保持 PR 小而专注

4. **合并**
   - 使用 "Squash and Merge"
   - 确保提交信息符合规范

### PR 模板

```markdown
## 描述
简要描述这个 PR 的目的和更改内容。

Fixes # (issue)

## 更改类型
- [ ] Bug 修复
- [ ] 新功能
- [ ] 破坏性变更
- [ ] 文档更新
- [ ] 性能优化
- [ ] 代码重构

## 检查清单
- [ ] 代码遵循项目代码风格
- [ ] 测试通过
- [ ] 添加/更新了测试
- [ ] 文档已更新
- [ ] 所有 CI 检查通过

## 测试说明
描述如何测试这些更改。

## 截图（如适用）
添加截图帮助理解更改。
```

---

## 发布流程

### 版本号规范

使用 [语义化版本](https://semver.org/lang/zh-CN/) (SemVer)：

```
MAJOR.MINOR.PATCH
```

- **MAJOR**：不兼容的 API 更改
- **MINOR**：向下兼容的功能添加
- **PATCH**：向下兼容的问题修复

### 发布步骤

1. **更新版本号**
   ```bash
   # 更新 pyproject.toml
   version = "0.2.0"
   ```

2. **更新 CHANGELOG**
   记录所有更改

3. **创建发布 PR**
   - 标题: "Release v0.2.0"
   - 包含所有更改

4. **合并后打标签**
   ```bash
   git tag -a v0.2.0 -m "Release version 0.2.0"
   git push origin v0.2.0
   ```

5. **创建 GitHub Release**
   - 填写发布说明
   - 附上二进制文件（如需要）

---

## 获取帮助

如果您在贡献过程中遇到问题：

1. 查看 [README](../README.md)
2. 搜索 [Issues](https://github.com/your-org/weaver/issues)
3. 发起 [Discussion](https://github.com/your-org/weaver/discussions)
4. 联系维护者

---

## 许可证

通过提交代码，您同意您的贡献将在 [MIT 许可证](./LICENSE) 下发布。

---

感谢您的贡献！🎉
