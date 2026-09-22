# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for scripts/pipeline.py import-sources subcommand helpers."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from scripts.pipeline import (
    _resolve_imports,
    build_newsnow_entry,
    build_rss_entry,
    cmd_import_sources,
    parse_source_list,
    slug_from_url,
    verify_newsnow_feed,
    verify_rss_feed,
)


class TestParseSourceList:
    def test_strips_comments_blank_lines_and_dedupes(self):
        text = (
            "# header comment\n"
            "https://a.example.com/feed\n"
            "\n"
            "  https://b.example.com/feed  \n"
            "# inline next\n"
            "https://a.example.com/feed\n"
        )
        assert parse_source_list(text) == [
            "https://a.example.com/feed",
            "https://b.example.com/feed",
        ]

    def test_empty_text_returns_empty(self):
        assert parse_source_list("") == []
        assert parse_source_list("# only a comment\n") == []

    def test_over_limit_raises(self, monkeypatch):
        import scripts.pipeline as mod

        monkeypatch.setattr(mod, "_MAX_IMPORT_ENTRIES", 3)
        text = "https://a/1\nhttps://a/2\nhttps://a/3\nhttps://a/4\n"
        with pytest.raises(ValueError, match="limit"):
            parse_source_list(text)


class TestSlugFromUrl:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://plink.anyfeeder.com/bbc/business", "anyfeeder-bbc-business"),
            ("https://feedpress.me/sixcolors", "feedpress-sixcolors"),
            ("https://www.solidot.org/index.rss", "solidot-index-rss"),
            ("https://example.com/", "example"),
            ("https://example.com/path/?x=1", "example-path"),
        ],
    )
    def test_slug_shapes(self, url: str, expected: str):
        assert slug_from_url(url) == expected

    def test_userinfo_not_leaked_into_slug(self):
        slug = slug_from_url("https://user:secret@feedpress.me/sixcolors")
        assert "secret" not in slug and "user" not in slug
        assert slug == "feedpress-sixcolors"

    def test_slug_capped_at_90_chars(self):
        slug = slug_from_url("https://example.com/" + "x" * 200)
        assert len(slug) <= 90

    def test_idn_only_slug_raises(self):
        with pytest.raises(ValueError, match="slug"):
            slug_from_url("https://例え.jp/")

    @pytest.mark.parametrize("url", ["ftp://example.com/x", "not-a-url", ""])
    def test_invalid_url_raises(self, url: str):
        with pytest.raises(ValueError):
            slug_from_url(url)


class TestBuildEntries:
    def test_rss_entry_fields(self):
        entry = build_rss_entry("https://plink.anyfeeder.com/bbc/business")
        assert entry["id"] == "rss-anyfeeder-bbc-business"
        assert entry["url"] == "https://plink.anyfeeder.com/bbc/business"
        assert entry["source_type"] == "rss"
        assert entry["enabled"] is True
        assert entry["interval_minutes"] == 30
        assert entry["credibility"] == 0.70
        assert entry["tier"] == 2
        assert entry["name"]

    def test_newsnow_entry_fields(self):
        entry = build_newsnow_entry("36kr")
        assert entry["id"] == "newsnow-36kr"
        assert entry["url"] == "https://newsnow.czl.net/api/s?id=36kr"
        assert entry["source_type"] == "newsnow"
        assert entry["enabled"] is True
        assert entry["name"] == "NewsNow 36kr"

    def test_newsnow_custom_api_base(self):
        entry = build_newsnow_entry("36kr", api_base="https://newsnow.world/api/s?id=")
        assert entry["url"] == "https://newsnow.world/api/s?id=36kr"

    def test_newsnow_id_url_encoded(self):
        entry = build_newsnow_entry("a&b#c")
        assert entry["url"] == "https://newsnow.czl.net/api/s?id=a%26b%23c"

    def test_newsnow_empty_id_raises(self):
        with pytest.raises(ValueError):
            build_newsnow_entry("  ")


@dataclass
class FakeStreamResponse:
    status_code: int
    content: bytes

    async def aiter_bytes(self):
        yield self.content


@dataclass
class FakeStreamCtx:
    response: FakeStreamResponse

    async def __aenter__(self) -> FakeStreamResponse:
        return self.response

    async def __aexit__(self, *exc) -> None:
        return None


class FakeClient:
    """Mirrors the httpx.AsyncClient surface _fetch_limited uses (stream only)."""

    def __init__(self, responses: dict[str, FakeStreamResponse | Exception]):
        self._responses = responses

    def stream(self, method: str, url: str, headers: dict | None = None) -> FakeStreamCtx:
        result = self._responses[url]
        if isinstance(result, Exception):
            raise result
        return FakeStreamCtx(result)


class TestVerifyRssFeed:
    RSS = b"<?xml version='1.0'?><rss><channel><item><link>https://x/1</link><title>t</title></item></channel></rss>"

    def test_ok_with_entries(self):
        client = FakeClient({"https://f/1": FakeStreamResponse(200, self.RSS)})
        ok, detail = asyncio.run(verify_rss_feed("https://f/1", client=client))
        assert ok and detail == "ok"

    def test_zero_entries_fails(self):
        empty = b"<?xml version='1.0'?><rss><channel></channel></rss>"
        client = FakeClient({"https://f/2": FakeStreamResponse(200, empty)})
        ok, detail = asyncio.run(verify_rss_feed("https://f/2", client=client))
        assert not ok and "0 linked entries" in detail

    def test_non_200_fails(self):
        client = FakeClient({"https://f/3": FakeStreamResponse(503, b"<html>down</html>")})
        ok, detail = asyncio.run(verify_rss_feed("https://f/3", client=client))
        assert not ok and "503" in detail

    def test_request_error_fails(self):
        client = FakeClient({"https://f/4": RuntimeError("boom")})
        ok, detail = asyncio.run(verify_rss_feed("https://f/4", client=client))
        assert not ok and "RuntimeError" in detail


class TestVerifyNewsnowFeed:
    def test_ok_with_status_success(self):
        payload = json.dumps(
            {"status": "success", "items": [{"url": "https://a/1", "title": "t"}]}
        ).encode()
        client = FakeClient({"https://n/1": FakeStreamResponse(200, payload)})
        ok, detail = asyncio.run(verify_newsnow_feed("https://n/1", client=client))
        assert ok and detail == "ok"

    def test_ok_with_status_cache(self):
        payload = json.dumps(
            {"status": "cache", "items": [{"url": "https://a/2", "title": "t"}]}
        ).encode()
        client = FakeClient({"https://n/2": FakeStreamResponse(200, payload)})
        ok, _ = asyncio.run(verify_newsnow_feed("https://n/2", client=client))
        assert ok

    def test_item_without_title_not_counted(self):
        payload = json.dumps({"status": "cache", "items": [{"url": "https://a/3"}]}).encode()
        client = FakeClient({"https://n/3": FakeStreamResponse(200, payload)})
        ok, detail = asyncio.run(verify_newsnow_feed("https://n/3", client=client))
        assert not ok and "0 valid entries" in detail

    def test_api_error_status_fails(self):
        payload = json.dumps({"status": "error", "items": []}).encode()
        client = FakeClient({"https://n/4": FakeStreamResponse(200, payload)})
        ok, detail = asyncio.run(verify_newsnow_feed("https://n/4", client=client))
        assert not ok and "error" in detail

    def test_bad_json_fails(self):
        client = FakeClient({"https://n/5": FakeStreamResponse(200, b"<html>not json</html>")})
        ok, _ = asyncio.run(verify_newsnow_feed("https://n/5", client=client))
        assert not ok

    def test_non_200_fails(self):
        client = FakeClient({"https://n/6": FakeStreamResponse(404, b"missing")})
        ok, detail = asyncio.run(verify_newsnow_feed("https://n/6", client=client))
        assert not ok and "404" in detail


@dataclass
class FakeSource:
    id: str
    url: str


class FakeRepo:
    """Mirrors the SourceConfigRepo surface _resolve_imports uses."""

    def __init__(self, sources: list[FakeSource] | None = None):
        self._sources = sources or []

    async def list_sources(self, enabled_only: bool = True) -> list[FakeSource]:
        return self._sources


class TestResolveImports:
    async def test_existing_url_is_skipped_and_kept_untouched(self):
        repo = FakeRepo([FakeSource("rss-old", "https://a/1")])
        to_upsert, skipped = await _resolve_imports(repo, [build_rss_entry("https://a/1")])
        assert to_upsert == []
        assert skipped == ["rss-old <- https://a/1"]

    async def test_id_conflict_with_db_gets_deterministic_url_hash_suffix(self):
        repo = FakeRepo([FakeSource("rss-anyfeeder-x", "https://other/feed")])
        to_upsert, skipped = await _resolve_imports(
            repo, [build_rss_entry("https://anyfeeder.com/x")]
        )
        assert skipped == []
        expected_suffix = hashlib.sha256(b"https://anyfeeder.com/x").hexdigest()[:8]
        assert to_upsert[0]["id"] == f"rss-anyfeeder-x-{expected_suffix}"

    async def test_same_batch_slug_collision_renames_second_and_converges_on_rerun(self):
        first = build_rss_entry("https://a.com/feed?token=x")
        second = build_rss_entry("https://a.com/feed?token=y")
        assert first["id"] == second["id"]  # same slug from query-less normalization

        to_upsert, _ = await _resolve_imports(FakeRepo(), [first, second])
        assert to_upsert[0]["id"] != to_upsert[1]["id"]
        second_expected = (
            f"rss-a-feed-{hashlib.sha256(b'https://a.com/feed?token=y').hexdigest()[:8]}"
        )
        assert to_upsert[1]["id"] == second_expected

        # Rerun against a DB that already stores the first: the second converges
        # to the same suffixed id instead of ping-ponging.
        repo = FakeRepo([FakeSource(to_upsert[0]["id"], first["url"])])
        rerun, _ = await _resolve_imports(repo, [build_rss_entry(second["url"])])
        assert rerun[0]["id"] == second_expected

    async def test_id_free_url_new_source_passes_through(self):
        to_upsert, skipped = await _resolve_imports(
            FakeRepo(), [build_rss_entry("https://new.example/feed")]
        )
        assert skipped == []
        assert to_upsert[0]["id"] == "rss-new-feed"


class TestCmdImportSources:
    def test_empty_list_file_returns_1_without_touching_container(self, tmp_path):
        empty = tmp_path / "empty.txt"
        empty.write_text("# nothing here\n\n", encoding="utf-8")
        args = SimpleNamespace(file=str(empty), type="rss", api_base="", interval=30, verify=False)
        assert asyncio.run(cmd_import_sources(args)) == 1


def test_batch_import_call_sites_pass_preserve_enabled():
    """seed-sources / import-sources must never overwrite a stored enabled flag."""
    import pathlib

    import scripts.pipeline as mod

    src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
    assert re.search(r"repo\.upsert\(cfg, preserve_enabled=True\)", src)
    assert re.search(r"repo\.upsert\(SourceConfigModel\(\*\*cfg\), preserve_enabled=True\)", src)
