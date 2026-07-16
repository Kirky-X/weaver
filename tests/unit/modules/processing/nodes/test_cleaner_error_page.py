# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for cleaner error-page detection (R1 fix).

Verifies that _is_error_page correctly identifies 404/login/redirect pages
that slip past the crawler HTTP status check, preventing garbage content
from being persisted as articles.
"""

from __future__ import annotations

import pytest

from modules.processing.nodes.quality.cleaner import _is_error_page


class TestIsErrorPage:
    """Tests for _is_error_page function (R1 fix)."""

    def test_weibo_login_page_detected(self):
        """Weibo login page (L5745-5750 data) must be detected."""
        body = "扫描二维码登录\n打开微博手机APP\n账号密码登录\n短信验证登录"
        assert _is_error_page(body) is True

    def test_chinanews_404_page_detected(self):
        """Chinanews 404 redirect page (L5769-5774 data) must be detected."""
        body = "10秒后 页面自动跳转至\n中新网首页"
        assert _is_error_page(body) is True

    def test_404_english_page_detected(self):
        """English 404 page with 'not found' marker."""
        body = "404 - Page not found. The page you are looking for does not exist."
        assert _is_error_page(body) is True

    def test_real_article_not_flagged(self):
        """Genuine article body must NOT be flagged as error page."""
        body = (
            "This is a real news article about technology and innovation. "
            "The company announced a new product that will revolutionize the industry. "
            "Experts say this represents a significant breakthrough in the field. "
            "The product will be available next quarter at major retailers nationwide. "
            "Industry analysts have praised the move as strategically important."
        )
        assert _is_error_page(body) is False

    def test_long_body_with_markers_not_flagged(self):
        """Body >= 500 chars with markers should NOT be flagged (real article may quote 404)."""
        body = "404 not found " * 100  # > 500 chars, contains markers
        assert _is_error_page(body) is False

    def test_single_marker_not_flagged(self):
        """Single marker hit (< 2) should NOT be flagged — low confidence."""
        body = "扫码登录"
        assert _is_error_page(body) is False

    def test_empty_body_not_flagged(self):
        """Empty body should not be flagged (handled elsewhere)."""
        assert _is_error_page("") is False

    def test_none_body_not_flagged(self):
        """None body should not be flagged."""
        assert _is_error_page(None) is False  # type: ignore[arg-type]

    def test_chinanews_404_with_recommendations(self):
        """404 page with recommended links (L10936-10959 data) must be detected.

        The 404 page has entity-like text (推荐列表) that was incorrectly
        extracted as entities. Error page detection stops this.
        """
        body = (
            "页面未找到\n404\n您访问的页面不存在\n自动跳转至首页\n"
            "推荐阅读：南海局势、三支一扶、最高人民法院"
        )
        assert _is_error_page(body) is True
