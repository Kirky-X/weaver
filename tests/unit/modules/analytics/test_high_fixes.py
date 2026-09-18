# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""High-severity fixes verification for analytics modules.

Covers: cooldown race, TTL reset, raw insert unique violation, hget TOCTOU,
min/max blind write, comma delimiter, non-object JSON, bp==0 guard,
0.0 falsy, feature-order coupling.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.event import LLMCompareEvent, LLMUsageEvent

# ── shift_detector bp==0 guard ─────────────────────────────


class TestShiftDetectorBpZero:
    """bp==0 must not fabricate a shift from an empty before-window."""

    def _detector(self):
        from modules.analytics.shift_detector import SentimentShiftDetector, ShiftConfig

        return SentimentShiftDetector(ShiftConfig())

    def test_bp_zero_is_skipped(self):
        detector = self._detector()
        signal = [0.1, 0.2, 0.1, 0.9, 0.8, 0.9]

        fake_algo = MagicMock()
        fake_algo.fit.return_value = None
        fake_algo.predict.return_value = [0]  # breakpoint at index 0
        with patch("modules.analytics.shift_detector.rpt.Pelt", return_value=fake_algo):
            shifts = detector._detect_pelt(signal, None)

        assert shifts == []

    def test_normal_breakpoint_still_detected(self):
        detector = self._detector()
        signal = [0.1, 0.1, 0.1, 0.9, 0.9, 0.9]

        fake_algo = MagicMock()
        fake_algo.predict.return_value = [3]
        with patch("modules.analytics.shift_detector.rpt.Pelt", return_value=fake_algo):
            shifts = detector._detect_pelt(signal, None)

        assert len(shifts) == 1
        assert shifts[0]["breakpoint"] == 3


# ── storage get_shifts 0.0 falsy ───────────────────────────


class TestGetShiftsZeroValues:
    """0.0 must survive as 0.0, not be mapped to None."""

    @pytest.mark.asyncio
    async def test_zero_before_avg_preserved(self):
        from modules.analytics.storage import AnalyticsStorage

        row = MagicMock()
        row.community_id = "c1"
        row.community_title = "t"
        row.shift_type = "pelt"
        row.direction = "positive"
        row.magnitude = 0.0
        row.confidence = 0.0
        row.detected_at = datetime(2026, 1, 1, tzinfo=UTC)
        row.window_start = None
        row.window_end = None
        row.before_avg = 0.0  # legitimate zero, must NOT become None
        row.after_avg = 0.5

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [row]
        session = AsyncMock()
        session.execute.return_value = mock_result

        pool = MagicMock()
        pool.session_context = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=session), __aexit__=AsyncMock()
            )
        )

        storage = AnalyticsStorage(pool)
        shifts = await storage.get_shifts()

        assert len(shifts) == 1
        assert shifts[0]["before_avg"] == 0.0
        assert shifts[0]["magnitude"] == 0.0

    @pytest.mark.asyncio
    async def test_none_before_avg_stays_none(self):
        from modules.analytics.storage import AnalyticsStorage

        row = MagicMock()
        row.community_id = "c1"
        row.community_title = "t"
        row.shift_type = "pelt"
        row.direction = "positive"
        row.magnitude = None
        row.confidence = None
        row.detected_at = None
        row.window_start = None
        row.window_end = None
        row.before_avg = None
        row.after_avg = None

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [row]
        session = AsyncMock()
        session.execute.return_value = mock_result

        pool = MagicMock()
        pool.session_context = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=session), __aexit__=AsyncMock()
            )
        )

        storage = AnalyticsStorage(pool)
        shifts = await storage.get_shifts()

        assert shifts[0]["before_avg"] is None


# ── sentiment LLM non-object JSON ──────────────────────────


class TestSentimentNonObjectJson:
    @pytest.mark.asyncio
    async def test_json_array_response_returns_default(self):
        from modules.analytics.sentiment_analyzer import SentimentAnalyzer

        llm = MagicMock()
        llm.call_at = AsyncMock(return_value='["positive", 0.9]')  # valid JSON, not an object
        analyzer = SentimentAnalyzer(
            config=MagicMock(
                enabled=False, max_input_length=512, confidence_threshold=0.6, fallback_to_llm=True
            ),
            llm_client=llm,
        )
        analyzer._skep = None

        result = await analyzer.analyze("some text")

        assert result["source"] == "llm"
        assert result["sentiment"] == "neutral"
        assert result["sentiment_score"] == 0.5

    @pytest.mark.asyncio
    async def test_json_object_response_still_works(self):
        from modules.analytics.sentiment_analyzer import SentimentAnalyzer

        llm = MagicMock()
        llm.call_at = AsyncMock(return_value='{"sentiment": "positive", "sentiment_score": 0.9}')
        analyzer = SentimentAnalyzer(
            config=MagicMock(
                enabled=False, max_input_length=512, confidence_threshold=0.6, fallback_to_llm=True
            ),
            llm_client=llm,
        )
        analyzer._skep = None

        result = await analyzer.analyze("some text")

        assert result["sentiment"] == "positive"


# ── alert cooldown race ────────────────────────────────────


class TestAlertCooldownLock:
    @pytest.mark.asyncio
    async def test_concurrent_triggers_respect_cooldown(self):
        """Second concurrent trigger for the same rule must be blocked."""
        import asyncio

        from modules.analytics.alert_service import AlertService

        rule = MagicMock()
        rule.id = 1
        rule.enabled = True
        rule.cooldown_minutes = 60
        rule.entity_name = "e"

        recent_event = MagicMock()
        recent_event.triggered_at = datetime.now(UTC)

        session = MagicMock()

        # Call sequence: (trigger A: rule, no recent, insert) then
        # (trigger B: rule, recent found → blocked)
        results = [
            _scalars_first(rule),  # A: select rule
            _scalars_first(None),  # A: no recent event
            _scalars_first(rule),  # B: select rule
            _scalars_first(recent_event),  # B: recent event found
        ]
        session.execute = AsyncMock(side_effect=results)
        session.flush = AsyncMock()
        session.commit = AsyncMock()

        pool = MagicMock()
        pool.session_context = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=session), __aexit__=AsyncMock()
            )
        )

        service = AlertService(pool)

        async def slow_insert(*args, **kwargs):
            # Hold the session open long enough for B to overlap with A
            await asyncio.sleep(0.01)
            return

        task_a = service.trigger_alert(rule_id=1, metric_value=5.0)
        task_b = service.trigger_alert(rule_id=1, metric_value=5.0)
        out_a, out_b = await asyncio.gather(task_a, task_b)

        # The lock serializes the two evaluations: exactly one creates the
        # event, the other is blocked by cooldown (order is not deterministic).
        assert (out_a is None) != (out_b is None)


def _scalars_first(value):
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = value
    mock_result.scalar.return_value = value
    return mock_result


# ── EvalCompareBuffer TTL reset ────────────────────────────


class TestEvalCompareBufferTtl:
    def _event(self):
        return LLMCompareEvent(
            timestamp=datetime(2026, 4, 14, 10, 30, 0, tzinfo=UTC),
            call_point="cp",
            primary_model="p",
            candidate_model="c",
            primary_latency=1.0,
            candidate_latency=2.0,
            primary_success=True,
            candidate_success=True,
        )

    @pytest.mark.asyncio
    async def test_ttl_set_only_on_first_write(self):
        from modules.analytics.llm_compare.buffer import EvalCompareBuffer

        cache = MagicMock()
        cache.hgetall = AsyncMock(side_effect=[{}, {"f": "1"}])
        cache.hincrby = AsyncMock()
        cache.expire = AsyncMock()
        mock_pipe = MagicMock()
        mock_pipe.execute = AsyncMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_pipe)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        cache.pipeline = MagicMock(return_value=mock_cm)

        buffer = EvalCompareBuffer(cache=cache, ttl_seconds=3600)
        await buffer.accumulate(self._event())
        await buffer.accumulate(self._event())

        cache.expire.assert_called_once()

    @pytest.mark.asyncio
    async def test_hgetall_failure_disables_ttl_write(self):
        from modules.analytics.llm_compare.buffer import EvalCompareBuffer

        cache = MagicMock()
        cache.hgetall = AsyncMock(side_effect=Exception("redis down"))
        cache.hincrby = AsyncMock()
        cache.expire = AsyncMock()

        buffer = EvalCompareBuffer(cache=cache, ttl_seconds=3600)
        await buffer.accumulate(self._event())  # must not raise

        cache.expire.assert_not_called()


# ── LLMUsageBuffer min/max blind write ─────────────────


class TestUsageBufferMinMaxFailure:
    def _event(self, latency: float) -> LLMUsageEvent:
        from core.llm.types import TokenUsage

        return LLMUsageEvent(
            label="l",
            call_point="cp",
            llm_type="chat",
            provider="p",
            model="m",
            tokens=TokenUsage(
                input_tokens=1, output_tokens=1, total_tokens=2, cached_tokens=0, reasoning_tokens=0
            ),
            latency_ms=latency,
            success=True,
            cost_usd=0.0,
        )

    @pytest.mark.asyncio
    async def test_hget_failure_skips_min_max_write(self):
        from modules.analytics.llm_usage.buffer import LLMUsageBuffer

        cache = MagicMock()
        cache.pipeline = MagicMock(
            return_value=MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock())
        )
        cache.hget = AsyncMock(side_effect=Exception("redis blip"))
        cache.hset = AsyncMock()
        cache.hgetall = AsyncMock(return_value={"x": "1"})
        cache.expire = AsyncMock()

        buffer = LLMUsageBuffer(cache=cache, ttl_seconds=3600)
        await buffer.accumulate(self._event(200.0))

        # Blind write must NOT happen when the current min/max is unknown
        min_writes = [c for c in cache.hset.call_args_list if "latency_min" in str(c)]
        max_writes = [c for c in cache.hset.call_args_list if "latency_max" in str(c)]
        assert min_writes == []
        assert max_writes == []


# ── #217: LLMUsageBuffer TTL check must precede writes ───────────────


class TestUsageBufferTtlSetOnFirstWrite:
    """The is-new check must run before the pipeline writes.

    A post-write hgetall is always non-empty, so expire was dead code and
    unflushed buckets never received a TTL.
    """

    def _event(self, latency: float) -> LLMUsageEvent:
        from core.llm.types import TokenUsage

        return LLMUsageEvent(
            label="l",
            call_point="cp",
            llm_type="chat",
            provider="p",
            model="m",
            timestamp=datetime(2026, 4, 14, 10, 30, 0, tzinfo=UTC),
            tokens=TokenUsage(
                input_tokens=1, output_tokens=1, total_tokens=2, cached_tokens=0, reasoning_tokens=0
            ),
            latency_ms=latency,
            success=True,
            cost_usd=0.0,
        )

    def _cache(self, existing):
        cache = MagicMock()
        mock_pipe = MagicMock()
        mock_pipe.execute = AsyncMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_pipe)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        cache.pipeline = MagicMock(return_value=mock_cm)
        cache.hget = AsyncMock(return_value=None)
        cache.hset = AsyncMock()
        cache.hgetall = AsyncMock(return_value=existing)
        cache.expire = AsyncMock()
        return cache

    @pytest.mark.asyncio
    async def test_ttl_set_when_bucket_new(self):
        from modules.analytics.llm_usage.buffer import LLMUsageBuffer

        cache = self._cache({})

        buffer = LLMUsageBuffer(cache=cache, ttl_seconds=3600)
        await buffer.accumulate(self._event(200.0))

        cache.expire.assert_called_once_with("llm:usage:2026041410", 3600)

    @pytest.mark.asyncio
    async def test_ttl_not_reset_when_bucket_exists(self):
        from modules.analytics.llm_usage.buffer import LLMUsageBuffer

        cache = self._cache({"l::cp::count": "3"})

        buffer = LLMUsageBuffer(cache=cache, ttl_seconds=3600)
        await buffer.accumulate(self._event(200.0))

        cache.expire.assert_not_called()


# ── aggregator uses hgetall snapshot for min/max ───────────


class TestAggregatorSnapshotMinMax:
    @pytest.mark.asyncio
    async def test_flush_does_not_call_hget(self):
        from modules.analytics.llm_usage.aggregator import flush_usage_buffer

        cache = MagicMock()

        async def _keys(*args, **kwargs):
            yield "llm:usage:2026040510"

        cache.scan_iter = _keys
        cache.hgetall = AsyncMock(
            return_value={
                "l::cp::count": "2",
                "l::cp::latency_ms": "300",
                "l::cp::latency_min": "100",
                "l::cp::latency_max": "200",
                "l::cp::success": "2",
                "l::cp::failure": "0",
            }
        )
        cache.hget = AsyncMock(side_effect=AssertionError("hget must not be called"))
        cache.delete = AsyncMock()

        repo = MagicMock()
        repo.upsert_hourly = AsyncMock()

        with patch("modules.analytics.llm_usage.repo.LLMUsageRepo", return_value=repo):
            # relational_pool is not a DuckDBPool instance → LLMUsageRepo path
            processed, errors = await flush_usage_buffer(cache, MagicMock())

        assert (processed, errors) == (1, 0)
        kwargs = repo.upsert_hourly.call_args.kwargs
        assert kwargs["latency_min"] == 100.0
        assert kwargs["latency_max"] == 200.0


# ── \x1f delimiter parsing ─────────────────────────────────


class TestAggDelimiter:
    def test_pg_and_duckdb_share_delimiter(self):
        from core.constants import AGG_DELIMITER
        from modules.analytics.llm_usage.repo import AGG_DELIMITER as PG, LLMUsageRepo
        from modules.storage.duckdb.llm_usage_repo import DuckDBLLMUsageRepo

        # Single source in core.constants; the DuckDB repo subclasses the PG
        # repo, so both write paths share this delimiter.
        assert PG is AGG_DELIMITER == "\x1f"
        assert issubclass(DuckDBLLMUsageRepo, LLMUsageRepo)

    def test_label_with_comma_survives_roundtrip(self):
        from modules.analytics.llm_usage.repo import AGG_DELIMITER

        labels = ["gpt-4", "model, with comma"]
        joined = AGG_DELIMITER.join(labels)
        assert joined.split(AGG_DELIMITER) == labels

    @pytest.mark.asyncio
    async def test_query_hourly_splits_on_delimiter(self):
        from modules.analytics.llm_usage.repo import AGG_DELIMITER, LLMUsageRepo

        row = MagicMock()
        row.time_bucket = datetime(2026, 4, 5, 10, tzinfo=UTC)
        row.call_count = 1
        row.input_tokens_sum = 1
        row.output_tokens_sum = 1
        row.total_tokens_sum = 2
        row.latency_avg_ms = 1.0
        row.latency_min_ms = 1.0
        row.latency_max_ms = 1.0
        row.success_count = 1
        row.failure_count = 0
        row.labels = AGG_DELIMITER.join(["gpt-4", "model, x"])
        row.call_points = "cp"
        row.llm_types = "chat"
        row.providers = "p"
        row.models = "m"

        mock_result = MagicMock()
        mock_result.all.return_value = [row]
        session = AsyncMock()
        session.execute.return_value = mock_result
        pool = MagicMock()
        pool.session = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=session), __aexit__=AsyncMock()
            )
        )

        repo = LLMUsageRepo(pool)
        out = await repo.query_hourly(
            start_time=datetime(2026, 4, 1, tzinfo=UTC), end_time=datetime(2026, 4, 30, tzinfo=UTC)
        )

        # The comma inside a label must not be treated as a delimiter
        assert "model, x" in out[0]["label"]


# ── feature order coupling ────────────────────────────


class TestFakeNewsFeatureOrder:
    def _features_dict(self) -> dict[str, float]:
        from modules.analytics.fake_news_detector import FEATURE_ORDER

        return dict.fromkeys(FEATURE_ORDER, 0.5)

    def test_ordered_vector_by_name(self):
        from modules.analytics.fake_news_detector import FEATURE_ORDER, FakeNewsDetector

        detector = FakeNewsDetector.__new__(FakeNewsDetector)
        features = {name: i / 11 for i, name in enumerate(FEATURE_ORDER)}
        vector = detector._ordered_feature_vector(features)
        assert vector == [features[name] for name in FEATURE_ORDER]

    def test_mismatched_keys_return_none(self):
        from modules.analytics.fake_news_detector import FakeNewsDetector

        detector = FakeNewsDetector.__new__(FakeNewsDetector)
        assert detector._ordered_feature_vector({"a": 1.0, "b": 2.0}) is None

    def test_rule_based_falls_back_on_mismatch(self):
        from modules.analytics.fake_news_detector import FakeNewsDetector, FakeNewsDetectorConfig

        config = FakeNewsDetectorConfig()
        detector = FakeNewsDetector(config)
        score = detector._rule_based_predict({"bogus": 0.1})
        assert score == 0.5

    def test_weights_align_with_feature_order(self):
        from modules.analytics.fake_news_detector import FEATURE_ORDER, FakeNewsDetectorConfig

        assert len(FakeNewsDetectorConfig().weights) == len(FEATURE_ORDER)
