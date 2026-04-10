## Why

项目中的 spaCy 模型经常出现报错，提示模型未安装，即使用户已经手动安装过仍然会出现此问题。这导致应用启动后运行时失败，用户体验差。需要在应用启动早期增加模型检测机制，并提供自动安装选项，确保模型在业务逻辑执行前就绪。

## What Changes

- 新增 `[spacy]` 配置段，支持配置模型列表、安装行为、本地 wheel 路径
- 新增 `SpacyModelManager` 组件，负责模型检测与安装
- 在应用启动流程（Settings 加载后、容器初始化前）插入模型检测逻辑
- 支持离线安装（本地 wheel 文件）和在线下载两种方式
- 提供严格模式（安装失败则启动失败）和宽松模式（仅警告）

## Capabilities

### New Capabilities

- `spacy-model-manager`: spaCy 模型检测、安装与生命周期管理

### Modified Capabilities

- `startup-bootstrap`: 应用启动流程新增 spaCy 模型检测阶段

## Impact

- **新增文件**: `src/core/nlp/spacy_manager.py`
- **修改文件**:
  - `config/settings.py` — 添加 `SpacySettings` 数据类
  - `config/settings.toml` — 添加 `[spacy]` 配置段
  - `config/settings.example.toml` — 添加配置示例
  - `src/main.py`（或应用入口）— 调用 `SpacyModelManager.check_and_install()`
- **依赖**: 使用已有的 `uv` 和 `spacy` 包，无需新增依赖