# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Core exception classes for the weaver system.

## 异常处理最佳实践

### 1. 结构化日志记录

所有 `except` 块必须使用结构化日志记录，包含 `exc_info=True` 以保留完整堆栈跟踪：

```python
try:
    await some_operation()
except SpecificError as e:
    log.error("operation_failed", context=key, error=str(e), exc_info=True)
    raise
except Exception as e:
    log.warning("unexpected_error", exc_info=True)
    # 根据业务需求决定是否 raise 或返回 fallback
```

### 2. 异常分类

- **预期异常**：业务逻辑中可预见的错误（如状态转换无效、资源不存在）
  → 使用自定义异常类（如 `InvalidStateTransitionError`），明确错误类型

- **非预期异常**：运行时意外错误（如网络超时、数据库连接失败）
  → 使用 `except Exception:` 捕获，记录 `exc_info=True`，按业务需求处理

### 3. 不要静默吞噬

**禁止**：
```python
except Exception:
    pass  # ❌ 永远不要这样做
```

**正确做法**：
```python
except Exception as e:
    log.warning("operation_failed", exc_info=True)
    return fallback_value  # 或 raise 传播到上层
```

### 4. 错误传播策略

- **API 层**：捕获后转换为 HTTPException，保留原始错误信息
- **业务层**：捕获后记录日志，按业务需求决定是否传播
- **基础设施层**：捕获后记录日志，确保资源正确释放

### 5. 异常链保留

使用 `raise ... from original_error` 保留异常链：

```python
try:
    await risky_operation()
except ConnectionError as e:
    raise ServiceUnavailableError("service_down") from e
```
"""


class InvalidStateTransitionError(Exception):
    """Raised when an invalid state transition is attempted.

    Attributes:
        from_status: The current status before transition.
        to_status: The attempted target status.
        message: Human-readable error message.
    """

    def __init__(self, from_status: str, to_status: str) -> None:
        """Initialize the exception with transition details.

        Args:
            from_status: The current status.
            to_status: The attempted target status.
        """
        self.from_status = from_status
        self.to_status = to_status
        self.message = (
            f"Invalid state transition: cannot transition from '{from_status}' to '{to_status}'"
        )
        super().__init__(self.message)
