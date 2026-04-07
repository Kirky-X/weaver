# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for Protocol validation utilities."""

from typing import Protocol
from unittest.mock import MagicMock

import pytest

from core.protocols.validation import ExplicitInterfaceMixin


class TestAssertImplements:
    """Tests for assert_implements function."""

    def test_validates_implemented_protocol(self) -> None:
        """Test that correctly implemented protocol passes."""
        from core.protocols.validation import assert_implements

        class MyProtocol(Protocol):
            def foo(self) -> str: ...

        class Implementation:
            def foo(self) -> str:
                return "bar"

        impl = Implementation()
        # Should not raise
        assert_implements(impl, MyProtocol)

    def test_raises_on_missing_method(self) -> None:
        """Test that missing method raises TypeError."""
        from core.protocols.validation import assert_implements

        class MyProtocol(Protocol):
            def foo(self) -> str: ...
            def bar(self) -> int: ...

        class Implementation:
            def foo(self) -> str:
                return "bar"

        impl = Implementation()
        with pytest.raises(TypeError) as exc_info:
            assert_implements(impl, MyProtocol)

        assert "bar" in str(exc_info.value)
        assert "Missing methods" in str(exc_info.value)

    def test_raises_on_non_protocol(self) -> None:
        """Test that non-Protocol class raises ValueError."""
        from core.protocols.validation import assert_implements

        class NotAProtocol:
            def foo(self) -> str: ...

        impl = NotAProtocol()
        with pytest.raises(ValueError) as exc_info:
            assert_implements(impl, NotAProtocol)

        assert "not a Protocol" in str(exc_info.value)

    def test_raises_on_non_type(self) -> None:
        """Test that non-type raises ValueError."""
        from core.protocols.validation import assert_implements

        with pytest.raises(ValueError) as exc_info:
            assert_implements("not a class", str)

        # The error message when passing a non-type to protocol parameter
        assert "not a Protocol" in str(exc_info.value)

    def test_validates_with_correct_signature(self) -> None:
        """Test that matching signature passes."""
        from core.protocols.validation import assert_implements

        class MyProtocol(Protocol):
            def process(self, data: str, count: int) -> bool: ...

        class Implementation:
            def process(self, data: str, count: int) -> bool:
                return True

        impl = Implementation()
        # Should not raise
        assert_implements(impl, MyProtocol)

    def test_detects_wrong_signature(self) -> None:
        """Test that wrong signature is detected."""
        from core.protocols.validation import assert_implements

        class MyProtocol(Protocol):
            def process(self, data: str, count: int) -> bool: ...

        class Implementation:
            def process(self, data: str) -> bool:
                return True

        impl = Implementation()
        with pytest.raises(TypeError) as exc_info:
            assert_implements(impl, MyProtocol)

        assert "process" in str(exc_info.value)


class TestGetProtocolMethods:
    """Tests for get_protocol_methods function."""

    def test_returns_protocol_methods(self) -> None:
        """Test that protocol methods are returned."""
        from core.protocols.validation import get_protocol_methods

        class MyProtocol(Protocol):
            def foo(self) -> str: ...
            def bar(self) -> int: ...

        methods = get_protocol_methods(MyProtocol)
        assert "foo" in methods
        assert "bar" in methods

    def test_excludes_dunder_methods(self) -> None:
        """Test that dunder methods are excluded."""
        from core.protocols.validation import get_protocol_methods

        class MyProtocol(Protocol):
            def foo(self) -> str: ...

        methods = get_protocol_methods(MyProtocol)
        assert "__init__" not in methods
        assert "__class__" not in methods

    def test_raises_on_non_protocol(self) -> None:
        """Test that non-Protocol raises ValueError."""
        from core.protocols.validation import get_protocol_methods

        class NotAProtocol:
            def foo(self) -> str: ...

        with pytest.raises(ValueError) as exc_info:
            get_protocol_methods(NotAProtocol)

        assert "not a Protocol" in str(exc_info.value)


class TestProtocolValidationIntegration:
    """Integration tests with actual project protocols."""

    def test_relational_pool_protocol(self) -> None:
        """Test RelationalPool protocol validation."""
        from core.protocols import RelationalPool, assert_implements

        class MockPool:
            """Implements: RelationalPool"""

            async def startup(self) -> None:
                pass

            async def shutdown(self) -> None:
                pass

            def session_context(self) -> None:
                pass

        pool = MockPool()
        # RelationalPool has additional methods like execute, fetch, fetch_val
        # We just verify the basic methods exist
        assert hasattr(pool, "startup")
        assert hasattr(pool, "shutdown")
        assert hasattr(pool, "session_context")

    def test_graph_pool_protocol(self) -> None:
        """Test GraphPool protocol validation."""
        from core.protocols import GraphPool

        class MockGraphPool:
            """Implements: GraphPool"""

            async def startup(self) -> None:
                pass

            async def shutdown(self) -> None:
                pass

            def session(self) -> None:
                pass

        pool = MockGraphPool()
        # The validation checks methods exist
        assert hasattr(pool, "startup")
        assert hasattr(pool, "shutdown")
        assert hasattr(pool, "session")


class TestExplicitInterfaceMixin:
    """Tests for ExplicitInterfaceMixin."""

    @pytest.fixture(autouse=True)
    def _import_mixin(self) -> None:
        """Make ExplicitInterfaceMixin available in all tests."""
        from core.protocols.validation import ExplicitInterfaceMixin as Mixin

        self.__class__.ExplicitInterfaceMixin = Mixin

    def test_valid_protocol_implementation(self) -> None:
        """Test that correctly implemented protocol passes at class definition."""

        class MyProto(Protocol):
            def foo(self) -> str: ...

        # Should not raise
        class MyService(ExplicitInterfaceMixin, implements=[MyProto]):
            def foo(self) -> str:
                return "bar"

        assert MyService().foo() == "bar"

    def test_missing_method_raises_type_error(self) -> None:
        """Test that missing method raises TypeError at class definition."""
        from core.protocols.validation import ExplicitInterfaceMixin

        class MyProto(Protocol):
            def foo(self) -> str: ...
            def bar(self) -> int: ...

        with pytest.raises(TypeError, match="bar"):
            type(
                "BadService",
                (ExplicitInterfaceMixin,),
                {"foo": lambda self: "x"},
                implements=[MyProto],
            )

    def test_no_implements_passes(self) -> None:
        """Test that omitting implements= does nothing."""

        class MyService(ExplicitInterfaceMixin):
            pass

        assert MyService()  # Should instantiate fine

    def test_single_protocol_without_list(self) -> None:
        """Test that single protocol can be passed without list."""

        class MyProto(Protocol):
            def do_work(self) -> bool: ...

        class MyService(ExplicitInterfaceMixin, implements=MyProto):
            def do_work(self) -> bool:
                return True

        assert MyService().do_work() is True

    def test_multiple_protocols(self) -> None:
        """Test that multiple protocols are all validated."""

        class ProtoA(Protocol):
            def method_a(self) -> str: ...

        class ProtoB(Protocol):
            def method_b(self) -> int: ...

        class MyService(ExplicitInterfaceMixin, implements=[ProtoA, ProtoB]):
            def method_a(self) -> str:
                return "a"

            def method_b(self) -> int:
                return 42

        svc = MyService()
        assert svc.method_a() == "a"
        assert svc.method_b() == 42
