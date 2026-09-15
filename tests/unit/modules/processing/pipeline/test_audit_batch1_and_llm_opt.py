# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Contributors
"""Unit tests for audit-batch-1 fixes + LLM 优化配套机制.

Covers (audit batch 1 fixes + LLM optimization supporting changes):
1. PipelineSettings carries the ``monte_carlo`` field — TOML [monte_carlo]
   is no longer silently dropped (audit P0 #2), so the MC sampler actually
   initializes.
2. content_hash snapshot invalidation is config-driven (``content_hash_version``):
   a version bump turns every stale snapshot into a miss without waiting out
   the 7-day TTL.
3. Graph batch persistence sets NEO4J_DONE only for articles in the success
   set (audit P0 #4 — fail-open eliminated).
4. LLM client emits llm_call_total / llm_call_latency / fallback_total
   (audit P0 #1 — previously defined but never incremented).
5. LLMSettings maps llm.toml ``[global]`` to top-level fields (audit P2 —
   the section used to be a zombie config).
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.llm.resilience.pool import AllProvidersFailedError
from core.llm.types import GlobalConfig, Label, LLMType, ProviderConfig, TokenUsage
from modules.ingestion.domain.models import RawArticle
from modules.processing.pipeline.config import (
    MonteCarloConfig,
    PhaseConfig,
    PipelineSettings,
)
from modules.processing.pipeline.content_hash_cache import ContentHashCacheService
from modules.processing.pipeline.persistence import PipelinePersistence
from modules.processing.pipeline.state import PipelineState


# ── 1. monte_carlo 配置接线 ──────────────────────────────────────


class TestMonteCarloConfigWiring:
    def test_model_defaults(self) -> None:
        cfg = MonteCarloConfig()
        assert cfg.enabled is True
        assert cfg.threshold == 10000
        assert cfg.sample_size == 5
        assert cfg.region_size == 2000
        assert cfg.confidence_threshold == 0.4

    def test_pipeline_settings_field_parses_toml_section(self) -> None:
        settings = PipelineSettings(monte_carlo={"enabled": True, "threshold": 12000})
        assert isinstance(settings.monte_carlo, MonteCarloConfig)
        assert settings.monte_carlo.threshold == 12000

    def test_real_toml_section_no_longer_dropped(self) -> None:
        """仓库 pipeline.toml 带 [monte_carlo] enabled=true —— 修复前
        extra='ignore' 把它静默丢弃，mc_sampler 永远为 None。"""
        settings = PipelineSettings()
        assert settings.monte_carlo.enabled is True

    def test_merge_flag_default_off_and_configurable(self) -> None:
        assert PhaseConfig().merge_analyze_narrative is False
        phase = PhaseConfig(**{"merge_analyze_narrative": True})
        assert phase.merge_analyze_narrative is True

    def test_content_hash_version_configurable(self) -> None:
        # 仓库 pipeline.toml 本次 bump 2→3（analyze_narrative 上线 + payload
        # 变更），加载结果即为 3——配置驱动失效的直接证据
        assert PipelineSettings().content_hash_version == 3
        assert PipelineSettings(content_hash_version=5).content_hash_version == 5


# ── 2. content_hash 配置驱动失效 ─────────────────────────────────


class _FakeCache:
    """Minimal CachePool stand-in: mget backed by a dict."""

    def __init__(self, store: dict[str, str]) -> None:
        self._store = store

    async def mget(self, keys):
        return [self._store.get(k) for k in keys]

    async def set(self, key, value, ex=None):
        self._store[key] = value


def _raw_article() -> RawArticle:
    return RawArticle(
        url="https://example.com/a",
        title="t",
        body="b",
        source="s",
        source_host="example.com",
    )


class TestContentHashVersionInvalidation:
    async def test_stale_version_snapshot_is_miss(self) -> None:
        raw = _raw_article()
        import hashlib

        content = f"{raw.title}\x00{raw.body}"
        key = f"content_hash:{hashlib.sha256(content.encode()).hexdigest()}"
        stale = json.dumps({"_schema_version": 2, "cleaned": {"title": "t"}})
        service = ContentHashCacheService(cache_client=_FakeCache({key: stale}), schema_version=3)

        results = await service.check([raw])

        assert results == [None]  # 版本不匹配 → miss，无需等 TTL 过期

    async def test_current_version_snapshot_hits_and_writes_new_version(self) -> None:
        raw = _raw_article()
        import hashlib

        content = f"{len(raw.title)}:{raw.title}\x00{raw.body}"
        key = f"content_hash:{hashlib.sha256(content.encode()).hexdigest()}"
        store: dict[str, str] = {}
        service = ContentHashCacheService(cache_client=_FakeCache(store), schema_version=4)

        state = PipelineState(raw=raw)
        state["cleaned"] = {"title": "t", "body": "b"}
        await service.write(state)
        assert json.loads(store[key])["_schema_version"] == 4

        results = await service.check([raw])
        assert results[0] is not None


# ── 3. persistence 成功集合置位 ──────────────────────────────────


def _state_with_id(article_id: str) -> PipelineState:
    state = PipelineState(raw=_raw_article())
    state["article_id"] = article_id
    return state


class TestGraphBatchPersistSuccessSet:
    async def test_done_status_only_for_success_set(self) -> None:
        a1 = "00000000-0000-0000-0000-000000000001"
        a2 = "00000000-0000-0000-0000-000000000002"
        article_repo = AsyncMock()
        graph_writer = AsyncMock()
        graph_writer.done_status = "NEO4J_DONE"
        graph_writer.write_batch.return_value = {
            "article_ids": [a1],
            "neo4j_ids": [["n1"]],
            "errors": [(a2, "boom")],
        }
        persistence = PipelinePersistence(
            article_repo=article_repo,
            vector_repo=MagicMock(),
            graph_writer=graph_writer,
            phase3_concurrency=2,
            pending_sync_repo=None,
        )

        batch_completed, batch_failed = await persistence._persist_to_graph_batch(
            [_state_with_id(a1), _state_with_id(a2)], 2, 0, 0
        )

        # a2 失败：绝不能先被置 done（fail-open），只能 mark_failed
        done_calls = article_repo.update_persist_status.await_args_list
        assert [c.args[0] for c in done_calls] == [uuid.UUID(a1)]
        article_repo.mark_failed.assert_awaited_once()
        assert batch_completed == 1
        assert batch_failed == 1

    # ── 4. LLM 指标埋点 ──────────────────────────────────────────────


class TestBM25JobProviderContract:
    async def test_provider_returns_service_runs_rebuild(self) -> None:
        """provider 返回 service 时 scheduled_rebuild 必须被执行——
        回归护栏：接线曾因 provider 恒返回 None 而永久空转。"""
        from modules.scheduler.jobs import SchedulerJobs

        service = AsyncMock()
        service.scheduled_rebuild = AsyncMock(return_value=7)

        async def _provider():
            return service

        jobs = SchedulerJobs(
            relational_pool=MagicMock(),
            cache=MagicMock(),
            graph_writer=MagicMock(),
            vector_repo=MagicMock(),
            article_repo=MagicMock(),
            source_authority_repo=MagicMock(),
            pending_sync_repo=MagicMock(),
            bm25_service_provider=_provider,
        )

        count = await jobs.bm25_rebuild_index()

        assert count == 7
        service.scheduled_rebuild.assert_awaited_once()


def _make_client_with_pool() -> tuple[object, MagicMock]:
    from core.llm.client import LLMClient

    providers = [
        ProviderConfig(
            name="openai",
            type="openai",
            base_url="https://api.openai.com/v1",
            api_key="k",
            rpm_limit=100,
            concurrency=5,
            timeout=30.0,
            priority=100,
            weight=100,
            models={},
        )
    ]
    bus = MagicMock()
    bus.publish = AsyncMock()
    client = LLMClient(
        providers=providers,
        global_config=GlobalConfig(circuit_breaker_threshold=5, circuit_breaker_timeout=60.0),
        event_bus=bus,
    )
    pool = MagicMock()
    response = MagicMock()
    response.content = "{}"
    response.token_usage = TokenUsage()
    response.cache_usage = None
    response.label = Label(llm_type=LLMType.CHAT, provider="openai", model="gpt-4o")
    response.latency_ms = 5.0

    async def _execute(*args, **kwargs):
        # 本机 time.monotonic() 对 <1 个 timer tick 的间隔返回精确 0.0，
        # 延迟直方图需要必然跨 tick 的时间——sleep 50ms。
        import asyncio

        await asyncio.sleep(0.05)
        return response

    pool.execute = _execute
    client._pools["openai"] = pool
    return client, pool


def _counter_value(counter, **labels) -> float:
    return counter.labels(**labels)._value.get()


class TestLLMMetricEmitters:
    async def test_success_increments_call_total_and_latency(self) -> None:
        from core.observability.metrics import metrics

        client, _ = _make_client_with_pool()
        before = _counter_value(
            metrics.llm_call_total, call_point="classifier", provider="openai", status="success"
        )
        lat_before = metrics.llm_call_latency.labels(
            call_point="classifier", provider="openai"
        )._sum.get()

        await client.call("chat.openai.gpt-4o", {"q": "hi"}, call_point="classifier")

        assert (
            _counter_value(
                metrics.llm_call_total, call_point="classifier", provider="openai", status="success"
            )
            == before + 1
        )
        assert (
            metrics.llm_call_latency.labels(call_point="classifier", provider="openai")._sum.get()
            > lat_before
        )

    async def test_failure_and_fallback_counters(self) -> None:
        from core.observability.metrics import metrics

        client, pool = _make_client_with_pool()
        pool.execute = AsyncMock(side_effect=RuntimeError("boom"))
        before_err = _counter_value(
            metrics.llm_call_total, call_point="classifier", provider="openai", status="error"
        )
        before_fb = _counter_value(
            metrics.fallback_total,
            call_point="classifier",
            from_provider="openai",
            reason="RuntimeError",
        )

        # 全候选失败后：fallback provider（anthropic）无池返回空错误 →
        # last_error 被置 None，最终抛 AllProvidersFailedError
        with pytest.raises(AllProvidersFailedError):
            await client.call(
                "chat.openai.gpt-4o",
                {"q": "hi"},
                call_point="classifier",
                # fallback 指向无池 provider：不产生第二次 llm_call_total 计数
                fallback_labels=["chat.anthropic.claude-sonnet-4-20250514"],
            )

        assert (
            _counter_value(
                metrics.llm_call_total, call_point="classifier", provider="openai", status="error"
            )
            == before_err + 1
        )
        # primary 失败后还有候选 → 记一次 fallback
        assert (
            _counter_value(
                metrics.fallback_total,
                call_point="classifier",
                from_provider="openai",
                reason="RuntimeError",
            )
            == before_fb + 1
        )


# ── 5. llm.toml [global] 段映射 ──────────────────────────────────


class TestGlobalSectionMapping:
    def test_global_section_wired_to_fields(self, tmp_path, monkeypatch) -> None:
        import core.llm.config.config as config_mod

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        toml = config_dir / "llm.toml"
        toml.write_text(
            "[global]\ncircuit_breaker_threshold = 9\ncircuit_breaker_timeout = 42.0\n"
            '[call-points.classifier]\nprimary = "chat.openai.gpt-4o"\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(config_mod, "PROJECT_ROOT", tmp_path)

        # 不显式传字段值——必须由 [global] 段映射提供（init 优先级高于 TOML source）
        settings = config_mod.LLMSettings(_env_file=None)

        assert settings.circuit_breaker_threshold == 9
        assert settings.circuit_breaker_timeout == 42.0
        assert "classifier" in settings.call_points


class TestT008LowFixes:
    """Regression tests for T008 LOW findings (#256)."""

    def test_stage_config_forbids_unknown_keys(self):
        """#256: a TOML typo such as ``enableed`` must fail validation."""
        from pydantic import ValidationError

        from modules.processing.pipeline.config import StageConfig

        with pytest.raises(ValidationError):
            StageConfig(**{"name": "x", "enableed": False})

        assert StageConfig(name="x", enabled=False).enabled is False
