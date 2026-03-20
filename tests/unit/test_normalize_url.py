"""Unit tests for URL normalization with urllib.parse."""

import sys

import pytest

sys.path.insert(0, "/home/dev/projects/weaver-enhance-libs/src")

from modules.collector.deduplicator import Deduplicator


class TestNormalizeUrl:
    """Tests for Deduplicator.normalize_url()."""

    # --- Basic normalization ---

    def test_removes_www_prefix(self):
        result = Deduplicator.normalize_url("https://www.36kr.com/p/123")
        assert result == "https://36kr.com/p/123"

    def test_clears_query_string(self):
        result = Deduplicator.normalize_url("https://36kr.com/p/123?f=rss&source=foo")
        assert result == "https://36kr.com/p/123"

    def test_removes_fragment(self):
        result = Deduplicator.normalize_url("https://36kr.com/p/123#section")
        assert result == "https://36kr.com/p/123"

    def test_lowercase_domain(self):
        result = Deduplicator.normalize_url("https://EXAMPLE.COM/Article/123")
        assert result == "https://example.com/Article/123"

    # --- Protocol handling ---

    def test_http_to_https(self):
        result = Deduplicator.normalize_url("http://example.com/path")
        assert result == "https://example.com/path"

    def test_protocol_relative_url(self):
        result = Deduplicator.normalize_url("//example.com/path")
        assert result == "https://example.com/path"

    def test_protocol_relative_with_www(self):
        result = Deduplicator.normalize_url("//www.example.com/path")
        assert result == "https://example.com/path"

    # --- Port handling ---

    def test_removes_default_https_port(self):
        result = Deduplicator.normalize_url("https://example.com:443/path")
        assert result == "https://example.com/path"

    def test_removes_default_http_port(self):
        # HTTP upgraded to HTTPS, port 80 should be removed
        result = Deduplicator.normalize_url("http://example.com:80/path")
        assert result == "https://example.com/path"

    def test_preserves_non_default_port(self):
        result = Deduplicator.normalize_url("https://example.com:8443/path")
        assert result == "https://example.com:8443/path"

    # --- Path normalization ---

    def test_normalizes_relative_path_dots(self):
        result = Deduplicator.normalize_url("https://example.com/a/../b/./c")
        assert result == "https://example.com/b/c"

    def test_removes_trailing_slash(self):
        result = Deduplicator.normalize_url("https://example.com/path/")
        assert result == "https://example.com/path"

    def test_removes_root_trailing_slash(self):
        result = Deduplicator.normalize_url("https://example.com/")
        assert result == "https://example.com"

    # --- URL encoding handling ---

    def test_percent_encoded_and_decoded_deduplicate(self):
        """Both percent-encoded and decoded URLs should produce same normalized form."""
        result1 = Deduplicator.normalize_url("https://example.com/path/%E4%B8%AD%E6%96%87")
        result2 = Deduplicator.normalize_url("https://example.com/path/中文")
        # Both should produce the same result for deduplication purposes
        assert result1 == result2

    def test_handles_percent_encoding_chinese(self):
        """Percent-encoded Chinese should be handled correctly."""
        result = Deduplicator.normalize_url("https://example.com/path/%E4%B8%AD%E6%96%87")
        # Should be a valid URL
        assert result.startswith("https://example.com/path/")

    def test_handles_already_decoded_chinese(self):
        """Already decoded Chinese should be handled correctly."""
        result = Deduplicator.normalize_url("https://example.com/path/中文")
        assert result.startswith("https://example.com/path/")

    # --- Comprehensive tests ---

    def test_full_normalization(self):
        """Full normalization with all transformations."""
        result = Deduplicator.normalize_url("http://www.EXAMPLE.COM:80/a/../b/./c?f=rss#anchor")
        assert result == "https://example.com/b/c"

    def test_www_and_non_www_deduplicate(self):
        result1 = Deduplicator.normalize_url("https://www.36kr.com/p/123")
        result2 = Deduplicator.normalize_url("https://36kr.com/p/123")
        assert result1 == result2

    def test_query_params_deduplicate(self):
        result1 = Deduplicator.normalize_url("https://36kr.com/p/123")
        result2 = Deduplicator.normalize_url("https://36kr.com/p/123?f=rss")
        assert result1 == result2
