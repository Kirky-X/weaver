# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X

"""Tests for the log_format switch in configure_logging (text | json)."""

from __future__ import annotations

import json

import pytest


class TestLogFormatSwitch:
    """log_format="json" 输出逐行可解析 JSON；默认 text 保持现状模板。"""

    def _log_one_warning(self, tmp_path, **kwargs) -> str:
        from core.observability.logging import configure_logging, logger

        log_file = tmp_path / "test.log"
        configure_logging(log_file=str(log_file), **kwargs)
        logger.warning("test_event", foo="bar", password="secret-value")
        logger.complete()
        return log_file.read_text(encoding="utf-8")

    def test_json_format_produces_parseable_lines(self, tmp_path) -> None:
        content = self._log_one_warning(tmp_path, log_format="json")

        lines = [line for line in content.splitlines() if line.strip()]
        assert lines, "json 格式下应有日志输出"
        for line in lines:
            parsed = json.loads(line)  # 每行都是合法 JSON
            assert parsed["record"]["message"] == "test_event"

        record = json.loads(lines[-1])["record"]
        assert record["extra"]["foo"] == "bar"
        assert record["level"]["name"] == "WARNING"

    def test_default_text_format_unchanged(self, tmp_path) -> None:
        content = self._log_one_warning(tmp_path)

        lines = [line for line in content.splitlines() if line.strip()]
        assert lines
        for line in lines:
            with pytest.raises(json.JSONDecodeError):
                json.loads(line)  # text 格式不是 JSON
            assert " | " in line
            assert "req=" in line
        assert "test_event" in lines[-1]
        assert "foo=bar" in lines[-1]

    def test_invalid_format_fails_fast(self, tmp_path) -> None:
        from core.observability.logging import configure_logging

        with pytest.raises(ValueError, match="log_format"):
            configure_logging(log_file=str(tmp_path / "x.log"), log_format="xml")

    def test_json_format_redacts_sensitive_extra(self, tmp_path) -> None:
        from core.observability.logging import configure_logging, logger

        log_file = tmp_path / "redact.log"
        configure_logging(log_file=str(log_file), log_format="json")
        logger.warning("login_attempt", password="super-secret")
        logger.complete()

        content = log_file.read_text(encoding="utf-8")
        assert "super-secret" not in content  # 脱敏在 JSON 模式下依然生效

    def test_sensitive_key_name_variants_redacted(self) -> None:
        """H1 回归：键名变体必须命中——包含语义（凭据词）与词边界（token）。"""
        from core.observability.logging import _SENSITIVE_EXTRA_KEY_RE

        for key in (
            "password",
            "db_password",
            "my_password_value",
            "Password1",
            "api_key",
            "openai_api_key",
            "client_secret",
            "authorization",
            "token",
            "id_token",
            "jwt_token",
            "access_token",
            "auth-token",
        ):
            assert _SENSITIVE_EXTRA_KEY_RE.search(key), f"{key} 应命中脱敏"

        # 包含语义的既定权衡：password_policy/secret_sauce 等非凭据键也会
        # 被脱敏（过度脱敏是安全方向）；token 家族靠词边界保持精确
        for key in ("token_count", "tokens_used", "tokenizer", "url"):
            assert not _SENSITIVE_EXTRA_KEY_RE.search(key), f"{key} 不应命中脱敏"

    def test_non_string_sensitive_extra_redacted(self, tmp_path) -> None:
        import json as _json

        from core.observability.logging import configure_logging, logger

        log_file = tmp_path / "nonstr.log"
        configure_logging(log_file=str(log_file), log_format="json")
        logger.warning("cfg_dump", api_key=12345678, retries=3)
        logger.complete()

        content = log_file.read_text(encoding="utf-8")
        assert "12345678" not in content  # 非 str 的敏感键值同样整体替换
        assert "retries" in content  # 非敏感键不受影响

    def test_connection_string_schemes_redacted(self) -> None:
        """M1 回归：postgresql:// 与无用户名 redis:// 形态必须脱敏。"""
        from core.observability.logging import redact_sensitive_data

        redacted = redact_sensitive_data(
            "connect failed for postgresql://user:secretpw@db:5432/weaver"
            " and redis://:secretpw@redis:6379/0"
        )
        assert "secretpw" not in redacted
        assert "postgresql://user:" in redacted
        assert "redis://:" in redacted
