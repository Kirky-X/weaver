# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Tests for core.resilience.retry module."""

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from core.resilience.retry import (
    DB_EXCEPTIONS,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_WAIT,
    DEFAULT_MIN_WAIT,
    LLM_EXCEPTIONS,
    NETWORK_EXCEPTIONS,
    _create_retry_strategy,
    _log_retry_attempt,
    retry_db,
    retry_llm,
    retry_network,
)


class TestRetryConstants:
    """Test retry configuration constants."""

    def test_network_exceptions(self):
        """Test NETWORK_EXCEPTIONS includes expected types."""
        assert ConnectionError in NETWORK_EXCEPTIONS
        assert TimeoutError in NETWORK_EXCEPTIONS
        assert OSError in NETWORK_EXCEPTIONS

    def test_llm_exceptions(self):
        """Test LLM_EXCEPTIONS includes expected types."""
        assert TimeoutError in LLM_EXCEPTIONS
        assert ConnectionError in LLM_EXCEPTIONS

    def test_db_exceptions(self):
        """Test DB_EXCEPTIONS includes expected types."""
        assert ConnectionError in DB_EXCEPTIONS
        assert TimeoutError in DB_EXCEPTIONS
        assert OSError in DB_EXCEPTIONS

    def test_default_values(self):
        """Test default retry configuration values."""
        assert DEFAULT_MAX_ATTEMPTS == 3
        assert DEFAULT_MIN_WAIT == 1.0
        assert DEFAULT_MAX_WAIT == 30.0


class TestLogRetryAttempt:
    """Test _log_retry_attempt function."""

    def test_logs_warning_on_failure(self):
        """Test logs warning when retry state has exception."""
        mock_state = MagicMock()
        mock_exception = ValueError("Test error")
        mock_state.outcome.exception.return_value = mock_exception
        mock_state.attempt_number = 2
        mock_state.idle_for = 1.5

        with patch("core.resilience.retry.log") as mock_log:
            _log_retry_attempt(mock_state)

            mock_log.warning.assert_called_once()
            call_kwargs = mock_log.warning.call_args[1]
            assert call_kwargs["attempt"] == 2
            assert call_kwargs["exception_type"] == "ValueError"

    def test_no_log_when_no_outcome(self):
        """Test no logging when outcome is None."""
        mock_state = MagicMock()
        mock_state.outcome = None

        with patch("core.resilience.retry.log") as mock_log:
            _log_retry_attempt(mock_state)

            mock_log.warning.assert_not_called()

    def test_no_log_when_no_exception(self):
        """Test no logging when outcome has no exception."""
        mock_state = MagicMock()
        mock_state.outcome.exception.return_value = None

        with patch("core.resilience.retry.log") as mock_log:
            _log_retry_attempt(mock_state)

            mock_log.warning.assert_not_called()


class TestCreateRetryStrategy:
    """Test _create_retry_strategy function."""

    def test_creates_strategy_with_defaults(self):
        """Test creates retry strategy with default configuration."""
        strategy = _create_retry_strategy((ValueError,))

        assert strategy is not None
        # Strategy should be AsyncRetrying instance
        assert hasattr(strategy, "__aiter__")

    def test_creates_strategy_with_custom_params(self):
        """Test creates retry strategy with custom parameters."""
        strategy = _create_retry_strategy(
            (ValueError,),
            max_attempts=5,
            min_wait=2.0,
            max_wait=60.0,
            jitter=2.0,
        )

        assert strategy is not None

    def test_creates_strategy_with_max_delay(self):
        """Test creates retry strategy with max_delay."""
        strategy = _create_retry_strategy(
            (ValueError,),
            max_delay=120.0,
        )

        assert strategy is not None


class TestRetryNetworkOperation:
    """Test retry_network decorator."""

    @pytest.mark.asyncio
    async def test_succeeds_on_first_attempt(self):
        """Test operation that succeeds on first attempt."""
        mock_func = AsyncMock(return_value="success")

        decorated = retry_network(mock_func)
        result = await decorated()

        assert result == "success"
        mock_func.assert_called_once()

    @pytest.mark.asyncio
    async def test_retries_on_network_error(self):
        """Test retries on network errors."""
        call_count = 0

        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Connection lost")
            return "success"

        decorated = retry_network(flaky_func)
        result = await decorated()

        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_fails_after_max_attempts(self):
        """Test fails after max attempts."""

        async def failing_func():
            raise ConnectionError("Permanent failure")

        decorated = retry_network(failing_func, max_attempts=2)

        with pytest.raises(ConnectionError):
            await decorated()

    @pytest.mark.asyncio
    async def test_does_not_retry_on_other_errors(self):
        """Test does not retry on non-network errors."""
        call_count = 0

        async def value_error_func():
            nonlocal call_count
            call_count += 1
            raise ValueError("Not a network error")

        decorated = retry_network(value_error_func)

        with pytest.raises(ValueError):
            await decorated()

        assert call_count == 1  # Only called once, no retry


class TestRetryLLMOperation:
    """Test retry_llm decorator."""

    @pytest.mark.asyncio
    async def test_succeeds_on_first_attempt(self):
        """Test LLM operation succeeds on first attempt."""
        mock_func = AsyncMock(return_value={"result": "data"})

        decorated = retry_llm(mock_func)
        result = await decorated()

        assert result == {"result": "data"}

    @pytest.mark.asyncio
    async def test_retries_on_llm_timeout(self):
        """Test retries on LLM timeout."""
        call_count = 0

        async def timeout_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise TimeoutError("LLM timeout")
            return {"result": "success"}

        decorated = retry_llm(timeout_func)
        result = await decorated()

        assert result == {"result": "success"}
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_does_not_retry_on_parse_error(self):
        """Test does not retry on OutputParserException."""
        from core.llm.utils.json_parser import OutputParserException

        call_count = 0

        async def parse_error_func():
            nonlocal call_count
            call_count += 1
            raise OutputParserException("Invalid JSON")

        decorated = retry_llm(parse_error_func)

        with pytest.raises(OutputParserException):
            await decorated()

        assert call_count == 1


class TestRetryDBOperation:
    """Test retry_db decorator."""

    @pytest.mark.asyncio
    async def test_succeeds_on_first_attempt(self):
        """Test DB operation succeeds on first attempt."""
        mock_func = AsyncMock(return_value=[{"id": 1}])

        decorated = retry_db(mock_func)
        result = await decorated()

        assert result == [{"id": 1}]

    @pytest.mark.asyncio
    async def test_retries_on_db_connection_error(self):
        """Test retries on DB connection errors."""
        call_count = 0

        async def db_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise OSError("Database connection lost")
            return [{"id": 1}]

        decorated = retry_db(db_func)
        result = await decorated()

        assert result == [{"id": 1}]
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_fails_after_exhausting_retries(self):
        """Test fails after exhausting retries."""

        async def failing_db_func():
            raise TimeoutError("Query timeout")

        decorated = retry_db(failing_db_func, max_attempts=2)

        with pytest.raises(TimeoutError):
            await decorated()


class TestRetryStrategyIntegration:
    """Integration tests for retry strategies."""

    @pytest.mark.asyncio
    async def test_network_retry_with_backoff(self):
        """Test network retry with exponential backoff."""
        call_times = []

        async def flaky_network():
            import time

            call_times.append(time.time())
            if len(call_times) < 3:
                raise ConnectionError("Network issue")
            return "connected"

        decorated = retry_network(flaky_network, max_attempts=3)
        result = await decorated()

        assert result == "connected"
        assert len(call_times) == 3

        # Verify backoff (each retry should take longer)
        if len(call_times) >= 3:
            interval1 = call_times[1] - call_times[0]
            interval2 = call_times[2] - call_times[1]
            # With jitter, just verify they're not instantaneous
            assert interval1 >= 0.5
            assert interval2 >= 0.5
