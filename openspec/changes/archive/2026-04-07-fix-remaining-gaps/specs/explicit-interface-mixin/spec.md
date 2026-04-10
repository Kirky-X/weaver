## Requirements

### REQ-001: ExplicitInterfaceMixin 类

系统应提供 `ExplicitInterfaceMixin` 类，允许使用者通过继承方式声明实现的 Protocol，并在类定义时自动验证。

- 类位于 `src/core/protocols/validation.py`
- 通过 `__init_subclass__` 钩子在子类定义时触发验证
- 支持通过类属性 `__implements__` 声明实现的 Protocol 列表
- 验证失败时抛出 `TypeError` 并指明缺失的方法
- 不影响已有 `assert_implements()` 函数

### REQ-002: 使用方式

```python
class MyService(ExplicitInterfaceMixin, protocol=MyProtocol):
    """Implements: MyProtocol"""
    ...
```

或：

```python
class MyService(ExplicitInterfaceMixin):
    __implements__ = [MyProtocol]
```

### REQ-003: 向后兼容

- 已有代码不需要修改
- `assert_implements()` 函数保持不变
- Mixin 是可选工具，不强制使用
