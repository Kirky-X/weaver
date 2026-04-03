# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for Fetcher exception classes."""

import pytest

from modules.ingestion.fetching.exceptions import CircuitOpenError, FetchError


class TestFetchError:
    """Tests for FetchError exception class."""

    def test_init_basic(self):
        """Test basic initialization."""
        error = FetchError(url="https://example.com/article", message="Connection failed")

        assert error.url == "https://example.com/article"
        assert error.message == "Connection failed"
        assert error.cause is None

    def test_init_with_cause(self):
        """Test initialization with cause exception."""
        original_error = ValueError("Original error")
        error = FetchError(
            url="https://example.com/article",
            message="Failed to fetch",
            cause=original_error,
        )

        assert error.url == "https://example.com/article"
        assert error.message == "Failed to fetch"
        assert error.cause is original_error

    def test_str_representation(self):
        """Test string representation."""
        error = FetchError(url="https://example.com/article", message="Connection failed")

        assert str(error) == "https://example.com/article: Connection failed"

    def test_repr_representation(self):
        """Test repr representation."""
        error = FetchError(url="https://example.com/article", message="Connection failed")

        assert (
            repr(error)
            == "FetchError(url='https://example.com/article', message='Connection failed', cause=None)"
        )

    def test_inherits_from_exception(self):
        """Test that FetchError inherits from Exception."""
        error = FetchError(url="https://example.com", message="test")

        assert isinstance(error, Exception)

    def test_catchable_as_exception(self):
        """Test that FetchError can be caught as Exception."""
        error = FetchError(url="https://example.com", message="test")

        try:
            raise error
        except Exception as e:
            assert e is error


class TestCircuitOpenError:
    """Tests for CircuitOpenError exception class."""

    def test_init(self):
        """Test basic initialization."""
        error = CircuitOpenError(host="example.com")

        assert error.host == "example.com"
        assert error.url == ""
        assert "example.com" in error.message
        assert "Circuit breaker open" in error.message

    def test_inherits_from_fetch_error(self):
        """Test that CircuitOpenError inherits from FetchError."""
        error = CircuitOpenError(host="example.com")

        assert isinstance(error, FetchError)
        assert isinstance(error, Exception)

    def test_repr_representation(self):
        """Test repr representation."""
        error = CircuitOpenError(host="example.com")

        assert repr(error) == "CircuitOpenError(host='example.com')"

    def test_message_contains_host(self):
        """Test that message contains host information."""
        error = CircuitOpenError(host="weibo.com")

        assert "weibo.com" in str(error)
        assert "Circuit breaker open" in str(error)

    def test_catchable_as_fetch_error(self):
        """Test that CircuitOpenError can be caught as FetchError."""
        error = CircuitOpenError(host="example.com")

        try:
            raise error
        except FetchError as e:
            assert e is error

    def test_catchable_as_exception(self):
        """Test that CircuitOpenError can be caught as Exception."""
        error = CircuitOpenError(host="example.com")

        try:
            raise error
        except Exception as e:
            assert e is error

    def test_host_attribute_accessible(self):
        """Test that host attribute is accessible."""
        error = CircuitOpenError(host="toutiao.com")

        assert hasattr(error, "host")
        assert error.host == "toutiao.com"
