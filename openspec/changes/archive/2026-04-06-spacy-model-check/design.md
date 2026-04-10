## Context

项目使用 spaCy 进行 NER（命名实体识别），模型按语言配置（zh_core_web_lg、en_core_web_sm 等）。当前问题：

1. 模型检测在 `SpacyExtractor._load()` 中按需执行，失败时仅 log warning
2. 用户手动安装模型后仍可能因环境隔离、路径问题导致检测失败
3. 应用启动时无明确警告，运行时才暴露问题

**约束**：
- uv 是项目包管理工具，安装速度快但无稳定 Python API
- spaCy 提供 `spacy.cli.download()` Python API 用于网络下载
- 本地 wheel 安装需通过 CLI 调用 uv/pip

## Goals / Non-Goals

**Goals:**
- 在应用启动最早期（Settings 加载后）检测模型状态
- 支持配置化的模型列表和行为控制
- 支持离线安装（本地 wheel 文件）
- 提供严格/宽松两种失败处理模式
- 串行阻塞式安装，确保完成后再继续启动

**Non-Goals:**
- 不修改现有 `SpacyExtractor` 的懒加载逻辑
- 不支持并发安装（模型通常只有 2-3 个）
- 不处理模型版本兼容性（由用户自行管理）

## Decisions

### 1. 检测时机：Settings 加载后立即执行

**选择原因**：
- 满足"最早期"需求，在容器初始化前完成
- 配置已就绪，可读取模型列表和行为配置
- 失败时可快速失败，不浪费后续初始化资源

**备选方案**：
- 容器初始化时检测 → 不满足"最早期"需求
- 按需检测 → 与现有懒加载相同，无法提前发现问题

### 2. 安装方式：混合使用 spaCy API + uv CLI

**选择原因**：
- 网络下载：`spacy.cli.download()` 是官方 Python API，无需 subprocess
- 本地安装：uv CLI 比 pip 快 10-100 倍，uv.find_uv_bin() 提供跨平台路径

**备选方案**：
- 全部用 subprocess 调用 → 网络下载可用 spaCy API 更简洁
- 用 pip 内部 API → pip 官方明确不推荐，API 不稳定

### 3. 配置结构：独立 [spacy] 段 + 按模型配置本地路径

**选择原因**：
- 配置内聚，不污染其他配置段
- 按模型配置路径灵活，支持部分模型本地、部分网络下载

**备选方案**：
- 单一路径存放所有 wheel → 文件命名需规范，不如按模型映射灵活

## Risks / Trade-offs

| 风险 | 缓解措施 |
|------|----------|
| 本地 wheel 路径不存在 | 检测文件存在性，不存在时 fallback 到网络下载 |
| 网络下载失败 | 严格模式下启动失败，宽松模式下记录警告 |
| spacy.cli.download 失败调用 sys.exit | 捕获 SystemExit 异常，统一处理 |
| uv 未安装 | 项目已依赖 uv，属于环境问题 |