# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for OTel auto-instrumentation of SQLAlchemy, Redis, and httpx."""

from unittest.mock import MagicMock, patch


class TestInstrumentDependencies:
    """Test instrument_dependencies registers all three instrumentors."""

    def test_all_three_registered_with_engine_and_redis(self):
        """When engine and redis_client are provided, all 3 instrumentors run."""
        from core.observability.tracing import instrument_dependencies

        mock_engine = MagicMock()
        mock_redis = MagicMock()

        with (
            patch(
                "opentelemetry.instrumentation.sqlalchemy.SQLAlchemyInstrumentor.instrument"
            ) as sa_inst,
            patch("opentelemetry.instrumentation.redis.RedisInstrumentor.instrument") as redis_inst,
            patch(
                "opentelemetry.instrumentation.httpx.HTTPXClientInstrumentor.instrument"
            ) as httpx_inst,
        ):
            instrument_dependencies(engine=mock_engine, redis_client=mock_redis)

        sa_inst.assert_called_once_with(engine=mock_engine)
        redis_inst.assert_called_once_with()
        httpx_inst.assert_called_once_with()

    def test_sqlalchemy_skipped_when_engine_none(self):
        """SQLAlchemy instrumentor is skipped when engine is None."""
        from core.observability.tracing import instrument_dependencies

        with (
            patch(
                "opentelemetry.instrumentation.sqlalchemy.SQLAlchemyInstrumentor.instrument"
            ) as sa_inst,
            patch("opentelemetry.instrumentation.redis.RedisInstrumentor.instrument") as redis_inst,
            patch(
                "opentelemetry.instrumentation.httpx.HTTPXClientInstrumentor.instrument"
            ) as httpx_inst,
        ):
            instrument_dependencies(engine=None, redis_client=None)

        sa_inst.assert_not_called()
        redis_inst.assert_not_called()
        # httpx is always instrumented
        httpx_inst.assert_called_once_with()

    def test_httpx_always_registered(self):
        """httpx instrumentor runs regardless of engine/redis being None."""
        from core.observability.tracing import instrument_dependencies

        with patch(
            "opentelemetry.instrumentation.httpx.HTTPXClientInstrumentor.instrument"
        ) as httpx_inst:
            instrument_dependencies()

        httpx_inst.assert_called_once_with()

    def test_sqlalchemy_failure_does_not_block_others(self):
        """If SQLAlchemy instrumentor raises, Redis and httpx still register."""
        from core.observability.tracing import instrument_dependencies

        mock_engine = MagicMock()

        with (
            patch(
                "opentelemetry.instrumentation.sqlalchemy.SQLAlchemyInstrumentor.instrument",
                side_effect=ImportError("mock"),
            ),
            patch("opentelemetry.instrumentation.redis.RedisInstrumentor.instrument") as redis_inst,
            patch(
                "opentelemetry.instrumentation.httpx.HTTPXClientInstrumentor.instrument"
            ) as httpx_inst,
        ):
            instrument_dependencies(engine=mock_engine, redis_client=MagicMock())

        redis_inst.assert_called_once_with()
        httpx_inst.assert_called_once_with()

    def test_redis_failure_does_not_block_httpx(self):
        """If Redis instrumentor raises, httpx still registers."""
        from core.observability.tracing import instrument_dependencies

        with (
            patch(
                "opentelemetry.instrumentation.redis.RedisInstrumentor.instrument",
                side_effect=RuntimeError("mock"),
            ),
            patch(
                "opentelemetry.instrumentation.httpx.HTTPXClientInstrumentor.instrument"
            ) as httpx_inst,
        ):
            instrument_dependencies(redis_client=MagicMock())

        httpx_inst.assert_called_once_with()


class TestImportSmoke:
    """Import smoke tests — no circular dependencies."""

    def test_tracing_module_imports(self):
        """tracing.py imports without circular dependency errors."""
        from core.observability import tracing

    def test_instrument_dependencies_callable(self):
        """instrument_dependencies is importable and callable."""
        from core.observability.tracing import instrument_dependencies

        assert callable(instrument_dependencies)
