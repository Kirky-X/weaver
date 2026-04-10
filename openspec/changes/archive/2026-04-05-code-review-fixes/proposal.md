## Why

代码审查发现项目存在多个需要改进的领域：过期依赖包可能带来安全风险、部分代码存在安全警告、大文件影响可维护性、以及异常处理不规范等问题。这些问题若不及时处理，将增加技术债务和潜在的安全风险。

## What Changes

- **依赖更新**: 更新 25 个过期依赖包至最新稳定版本
- **安全加固**: 修复 `0.0.0.0` 绑定警告、改进异常处理日志
- **代码质量**: 修复格式化问题、追踪 TODO 标记、拆分超大文件
- **工具维护**: 刷新 GitNexus 索引保持代码智能同步

## Capabilities

### New Capabilities

- `dependency-update`: 依赖包版本更新和兼容性验证流程
- `security-hardening`: 安全配置改进和异常处理标准化
- `code-quality-improvements`: 代码格式化、大文件拆分、TODO 追踪

### Modified Capabilities

无现有 spec 行为变更，仅实现层面改进。

## Impact

- **依赖**: 25 个 Python 包版本更新
- **配置**: `src/config/settings.py` 默认绑定地址
- **安全**: 3 处异常处理位置添加日志
- **代码**: 1 个格式化文件修复，4 个大文件待拆分
- **索引**: GitNexus 索引落后 102 个提交需刷新