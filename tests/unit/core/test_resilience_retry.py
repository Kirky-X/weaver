# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for unified retry module."""

import pytest

from core.resilience.retry import (
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_WAIT,
    DEFAULT_MIN_WAIT,
    OutputParserException,
    retry_db,
    retry_llm,
    retry_network,
    with_db_retry,
    with_llm_retry,
    with_network_retry,
)


class TestRetryNetwork:
    """Tests for retry_network function."""

    @pytest.mark.asyncio
    async def test_retry_network_success_on_first_attempt(self):
        """Test successful call on first attempt."""
        call_count = 0

        async def successful_call():
            nonlocal call_count
            call_count += 1
            return "success"

        retryer = retry_network()
        async for attempt in retryer:
            with attempt:
                result = await successful_call()
                assert result == "success"
                assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_network_retries_on_connection_error(self):
        """Test retry on ConnectionError."""
        call_count = 0

        async def failing_then_success():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Connection failed")
            return "success"

        retryer = retry_network(max_attempts=3, min_wait=0.01, max_wait=0.1)
        result = None
        async for attempt in retryer:
            with attempt:
                result = await failing_then_success()

        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_network_retries_on_timeout(self):
        """Test retry on TimeoutError."""
        call_count = 0

        async def failing_then_success():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise TimeoutError("Request timed out")
            return "success"

        retryer = retry_network(max_attempts=3, min_wait=0.01, max_wait=0.1)
        result = None
        async for attempt in retryer:
            with attempt:
                result = await failing_then_success()

        assert result == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retry_network_raises_after_max_attempts(self):
        """Test that exception is raised after max attempts."""
        call_count = 0

        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Always fails")

        retryer = retry_network(max_attempts=2, min_wait=0.01, max_wait=0.1)

        with pytest.raises(ConnectionError):
            async for attempt in retryer:
                with attempt:
                    await always_fail()

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retry_network_no_retry_on_value_error(self):
        """Test no retry on non-retryable exception."""
        call_count = 0

        async def raise_value_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("Not retryable")

        retryer = retry_network(max_attempts=3, min_wait=0.01, max_wait=0.1)

        with pytest.raises(ValueError):
            async for attempt in retryer:
                with attempt:
                    await raise_value_error()

        assert call_count == 1


class TestRetryLLM:
    """Tests for retry_llm function."""

    @pytest.mark.asyncio
    async def test_retry_llm_retries_on_output_parser_exception(self):
        """Test retry on OutputParserException."""
        call_count = 0

        async def failing_parse():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise OutputParserException("Parse failed")
            return {"parsed": True}

        retryer = retry_llm(max_attempts=3, min_wait=0.01, max_wait=0.1)
        result = None
        async for attempt in retryer:
            with attempt:
                result = await failing_parse()

        assert result == {"parsed": True}
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retry_llm_retries_on_timeout(self):
        """Test retry on TimeoutError."""
        call_count = 0

        async def timeout_then_success():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise TimeoutError("LLM timeout")
            return "response"

        retryer = retry_llm(max_attempts=3, min_wait=0.01, max_wait=0.1)
        result = None
        async for attempt in retryer:
            with attempt:
                result = await timeout_then_success()

        assert result == "response"


class TestRetryDB:
    """Tests for retry_db function."""

    @pytest.mark.asyncio
    async def test_retry_db_retries_on_connection_error(self):
        """Test retry on database ConnectionError."""
        call_count = 0

        async def db_failing():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("DB connection lost")
            return [{"id": 1}]

        retryer = retry_db(max_attempts=3, min_wait=0.01, max_wait=0.1)
        result = None
        async for attempt in retryer:
            with attempt:
                result = await db_failing()

        assert result == [{"id": 1}]
        assert call_count == 2


class TestWithNetworkRetry:
    """Tests for with_network_retry decorator."""

    @pytest.mark.asyncio
    async def test_decorator_success(self):
        """Test decorator with successful call."""
        call_count = 0

        @with_network_retry(max_attempts=3)
        async def fetch_data():
            nonlocal call_count
            call_count += 1
            return "data"

        result = await fetch_data()
        assert result == "data"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_decorator_retries_on_error(self):
        """Test decorator retries on error."""
        call_count = 0

        @with_network_retry(max_attempts=3, min_wait=0.01, max_wait=0.1)
        async def fetch_with_retry():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Failed")
            return "success"

        result = await fetch_with_retry()
        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_decorator_raises_after_max_attempts(self):
        """Test decorator raises after max attempts."""
        call_count = 0

        @with_network_retry(max_attempts=2, min_wait=0.01, max_wait=0.1)
        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise TimeoutError("Always timeout")

        with pytest.raises(TimeoutError):
            await always_fail()

        assert call_count == 2


class TestWithLLMRetry:
    """Tests for with_llm_retry decorator."""

    @pytest.mark.asyncio
    async def test_llm_decorator_retries_output_parser_exception(self):
        """Test LLM decorator retries on OutputParserException."""
        call_count = 0

        @with_llm_retry(max_attempts=3, min_wait=0.01, max_wait=0.1)
        async def parse_output():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise OutputParserException("Bad output")
            return {"result": "ok"}

        result = await parse_output()
        assert result == {"result": "ok"}
        assert call_count == 2


class TestWithDBRetry:
    """Tests for with_db_retry decorator."""

    @pytest.mark.asyncio
    async def test_db_decorator_retries_connection_error(self):
        """Test DB decorator retries on ConnectionError."""
        call_count = 0

        @with_db_retry(max_attempts=3, min_wait=0.01, max_wait=0.1)
        async def query_db():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("DB connection failed")
            return [{"row": 1}]

        result = await query_db()
        assert result == [{"row": 1}]
        assert call_count == 2


class TestDefaultConstants:
    """Tests for default constants."""

    def test_default_max_attempts(self):
        """Test default max attempts value."""
        assert DEFAULT_MAX_ATTEMPTS == 3

    def test_default_min_wait(self):
        """Test default min wait value."""
        assert DEFAULT_MIN_WAIT == 1.0

    def test_default_max_wait(self):
        """Test default max wait value."""
        assert DEFAULT_MAX_WAIT == 30.0


class TestOutputParserException:
    """Tests for OutputParserException."""

    def test_exception_is_exception(self):
        """Test OutputParserException is an Exception."""
        assert issubclass(OutputParserException, Exception)

    def test_exception_message(self):
        """Test OutputParserException message."""
        exc = OutputParserException("Failed to parse output")
        assert str(exc) == "Failed to parse output"

    def test_exception_can_be_raised(self):
        """Test OutputParserException can be raised and caught."""
        with pytest.raises(OutputParserException):
            raise OutputParserException("Test exception")
