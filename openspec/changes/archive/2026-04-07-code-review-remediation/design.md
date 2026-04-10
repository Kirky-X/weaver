# 技术设计文档

## Context

### 当前状态
基于全面代码审查（8个专业维度），发现以下经验证需要修复的问题：

| 问题类型 | 位置 | 实际严重程度 | 验证状态 |
|---------|------|-------------|---------|
| Dataclass类型注解错误 | `src/core/llm/types.py` | MEDIUM | 确认存在 |
| 函数返回类型注解错误 | `src/core/utils/sanitize.py` | LOW | 确认存在 |
| 硬编码默认密码 | `src/config/settings.py` | MEDIUM | 部分存在 |
| 异常捕获过于宽泛 | 87处 `except Exception` | MEDIUM | 确认存在 |

### 约束条件
- 保持向后兼容，不破坏现有API
- 最小化代码变更范围
- 确保测试通过率100%

## Goals / Non-Goals

**Goals:**
1. 修复类型注解错误，使 `mypy` 类型检查通过
2. 移除硬编码默认密码，强化安全配置
3. 改进异常处理，添加适当的日志记录
4. 保持代码功能不变

**Non-Goals:**
- Container 类拆分（P2架构优化任务）
- LLM Usage Buffer 优化（P2性能优化任务）
- 数据库索引优化（P3，需根据实际查询模式评估）
- Fast Path 补偿机制（设计层面问题，Slow Path可修复）

## Decisions

### 1. 类型注解修复策略

**决策**: 使用 `| None` 联合类型而非 `field(default_factory)`

**理由**:
- `__post_init__` 中已实现赋值逻辑，使用 `| None` 更简单
- `field(default_factory=list)` 需要修改 `__post_init__` 逻辑
- 保持最小变更范围

**替代方案**:
- 使用 `field(default_factory=list)` - 需更多代码变更
- 使用 `typing.Optional` - 已弃用，推荐使用 `| None`

**代码示例**:
```python
# 当前（错误）
fallbacks: list[str] = None

# 修复后
fallbacks: list[str] | None = None
```

### 2. 默认密码移除策略

**决策**: 移除硬编码默认值，保留空字符串默认值

**理由**:
- 现有安全校验（第798-804行）会在生产环境检测不安全密码
- 空字符串默认值允许开发环境正常启动
- 环境变量 `NEO4J_PASSWORD` 可覆盖

**代码示例**:
```python
# 当前
password: str = "neo4j_password"

# 修复后
password: str = ""  # 必须通过环境变量配置
```

### 3. 异常处理改进策略

**决策**: 添加结构化日志记录，不改变异常处理逻辑

**理由**:
- 保持原有异常处理行为
- 日志记录便于调试和监控
- 使用项目现有的 structlog 日志框架

**代码示例**:
```python
# 当前
except Exception:
    pass

# 修复后
except Exception as exc:
    log.debug("operation_failed", error=str(exc))
```

**分类处理**:
| 异常类型 | 处理方式 |
|---------|---------|
| 静默吞噬（`pass`） | 添加 DEBUG 级别日志 |
| 已有日志记录 | 保持不变 |
| 合理降级场景 | 保持不变，添加注释说明 |

## Risks / Trade-offs

### 风险矩阵

| 风险 | 影响 | 可能性 | 缓解措施 |
|------|------|--------|---------|
| 类型注解修改影响运行时 | LOW | LOW | 仅影响类型检查，不改变运行行为 |
| 移除默认密码影响开发环境 | MEDIUM | MEDIUM | 提供 `.env.example` 指导，启动时警告 |
| 异常处理修改引入回归 | LOW | LOW | 保持原有逻辑，仅添加日志 |

### 技术债务

以下问题经验证后风险较低，作为后续优化任务：

1. **Container 类拆分** - 1242行可接受，架构合理性良好
2. **N+1 查询** - 验证为误报，实际是批量查询
3. **VectorRepo 无 rollback** - 验证为误报，context manager 自动处理

## Migration Plan

### 部署步骤

1. **阶段1: 类型安全修复**
   - 修改 `src/core/llm/types.py`
   - 修改 `src/core/utils/sanitize.py`
   - 运行 `uv run mypy src --ignore-missing-imports` 验证

2. **阶段2: 安全加固**
   - 修改 `src/config/settings.py`
   - 更新 `.env.example`
   - 运行 `uv run pytest tests/unit/config/` 验证

3. **阶段3: 异常处理改进**
   - 逐个模块修改异常处理
   - 每修改一个模块后运行对应测试
   - 最终运行完整测试套件

### 回滚策略

每个阶段独立提交，可单独回滚：
- `git revert <commit-hash>` 回滚特定阶段
- 类型注解修复不影响运行时
- 安全配置通过环境变量覆盖

## Open Questions

1. **异常处理优先级**: 87处异常处理是否需要全部修改？
   - 建议：优先处理静默吞噬（`pass`）的场景
   - 合理降级场景可保持不变

2. **日志级别选择**: DEBUG vs WARNING？
   - 建议：静默吞噬场景使用 DEBUG
   - 实际错误场景使用 WARNING 或 ERROR