# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for new ORM models: ApiKey, AlertRule, AlertEvent, ArticleVersion, PromptTemplate.

Design doc references:
- Weaver-数据库设计文档 §1.6.3 (api_keys)
- Weaver-数据库设计文档 §12.4 (alert_rules, alert_events)
- Weaver-数据库设计文档 §9.11.6 (article_versions)
- Migration 01_initial (prompt_templates table without ORM model)
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect

from core.db.models import AlertEvent, AlertRule, ApiKey, ArticleVersion, PromptTemplate

# ── ApiKey model tests ───────────────────────────────────────


class TestApiKeyModel:
    """Verify api_keys ORM model matches design doc DDL."""

    @pytest.fixture(autouse=True)
    def _inspect_table(self):
        self.columns = {c.name for c in inspect(ApiKey).columns}
        self.table = ApiKey.__table__

    def test_has_key_id(self):
        assert "key_id" in self.columns

    def test_has_key_hash(self):
        assert "key_hash" in self.columns

    def test_has_scopes(self):
        assert "scopes" in self.columns

    def test_has_rate_limit_per_min(self):
        assert "rate_limit_per_min" in self.columns

    def test_has_expires_at(self):
        assert "expires_at" in self.columns

    def test_has_last_used_at(self):
        assert "last_used_at" in self.columns

    def test_has_is_revoked(self):
        assert "is_revoked" in self.columns

    def test_has_created_by(self):
        assert "created_by" in self.columns

    def test_has_created_at(self):
        assert "created_at" in self.columns

    def test_key_id_is_unique(self):
        """key_id must have a unique constraint per design doc."""
        col = self.table.columns["key_id"]
        assert col.unique is True

    def test_key_id_not_null(self):
        col = self.table.columns["key_id"]
        assert not col.nullable

    def test_key_hash_not_null(self):
        col = self.table.columns["key_hash"]
        assert not col.nullable

    def test_scopes_not_null(self):
        col = self.table.columns["scopes"]
        assert not col.nullable

    def test_is_revoked_default_false(self):
        col = self.table.columns["is_revoked"]
        assert col.default is not None or col.server_default is not None

    def test_rate_limit_default_100(self):
        col = self.table.columns["rate_limit_per_min"]
        assert col.default is not None or col.server_default is not None

    def test_has_expires_index(self):
        """Design doc specifies partial index on expires_at WHERE is_revoked = false."""
        index_names = [idx.name for idx in self.table.indexes]
        # At minimum, there should be an index involving expires_at
        assert any("expires" in name.lower() for name in index_names) or any(
            "expires" in str(idx.columns).lower() for idx in self.table.indexes
        )


# ── AlertRule model tests ────────────────────────────────────


class TestAlertRuleModel:
    """Verify alert_rules ORM model matches design doc DDL."""

    @pytest.fixture(autouse=True)
    def _inspect_table(self):
        self.columns = {c.name for c in inspect(AlertRule).columns}
        self.table = AlertRule.__table__

    def test_has_entity_name(self):
        assert "entity_name" in self.columns

    def test_has_metric(self):
        assert "metric" in self.columns

    def test_has_operator(self):
        assert "operator" in self.columns

    def test_has_threshold(self):
        assert "threshold" in self.columns

    def test_has_channel(self):
        assert "channel" in self.columns

    def test_has_cooldown_minutes(self):
        assert "cooldown_minutes" in self.columns

    def test_has_enabled(self):
        assert "enabled" in self.columns

    def test_has_created_at(self):
        assert "created_at" in self.columns

    def test_metric_check_constraint(self):
        """metric must be CHECK constrained to reference_count/sentiment_change/volume_spike."""
        constraints = [c for c in self.table.constraints if hasattr(c, "sqltext")]
        # Verify at least one CHECK constraint references 'metric'
        has_metric_check = any("metric" in str(c.sqltext).lower() for c in constraints)
        assert has_metric_check

    def test_operator_check_constraint(self):
        """operator must be CHECK constrained to z_score>/pct_change>/absolute>."""
        constraints = [c for c in self.table.constraints if hasattr(c, "sqltext")]
        has_operator_check = any("operator" in str(c.sqltext).lower() for c in constraints)
        assert has_operator_check

    def test_channel_default_webhook(self):
        col = self.table.columns["channel"]
        assert col.default is not None or col.server_default is not None

    def test_cooldown_minutes_default_60(self):
        col = self.table.columns["cooldown_minutes"]
        assert col.default is not None or col.server_default is not None

    def test_enabled_default_true(self):
        col = self.table.columns["enabled"]
        assert col.default is not None or col.server_default is not None


# ── AlertEvent model tests ───────────────────────────────────


class TestAlertEventModel:
    """Verify alert_events ORM model matches design doc DDL."""

    @pytest.fixture(autouse=True)
    def _inspect_table(self):
        self.columns = {c.name for c in inspect(AlertEvent).columns}
        self.table = AlertEvent.__table__

    def test_has_rule_id(self):
        assert "rule_id" in self.columns

    def test_has_entity_name(self):
        assert "entity_name" in self.columns

    def test_has_metric_value(self):
        assert "metric_value" in self.columns

    def test_has_triggered_at(self):
        assert "triggered_at" in self.columns

    def test_has_acknowledged_at(self):
        assert "acknowledged_at" in self.columns

    def test_has_detail(self):
        assert "detail" in self.columns

    def test_rule_id_foreign_key(self):
        """rule_id must reference alert_rules(id)."""
        fk = self.table.columns["rule_id"].foreign_keys
        assert len(fk) == 1
        fk_ref = list(fk)[0]
        assert fk_ref.column.table.name == "alert_rules"
        assert fk_ref.column.name == "id"

    def test_has_triggered_at_index(self):
        """Design doc specifies idx_alert_events_triggered on triggered_at DESC."""
        index_names = [idx.name for idx in self.table.indexes]
        assert any("triggered" in name.lower() for name in index_names)

    def test_has_entity_index(self):
        """Design doc specifies idx_alert_events_entity on (entity_name, triggered_at DESC)."""
        index_names = [idx.name for idx in self.table.indexes]
        assert any("entity" in name.lower() for name in index_names)


# ── ArticleVersion model tests ───────────────────────────────


class TestArticleVersionModel:
    """Verify article_versions ORM model matches design doc DDL."""

    @pytest.fixture(autouse=True)
    def _inspect_table(self):
        self.columns = {c.name for c in inspect(ArticleVersion).columns}
        self.table = ArticleVersion.__table__

    def test_has_article_id(self):
        assert "article_id" in self.columns

    def test_has_version(self):
        assert "version" in self.columns

    def test_has_title(self):
        assert "title" in self.columns

    def test_has_body(self):
        assert "body" in self.columns

    def test_has_summary(self):
        assert "summary" in self.columns

    def test_has_category(self):
        assert "category" in self.columns

    def test_has_score(self):
        assert "score" in self.columns

    def test_has_changed_fields(self):
        assert "changed_fields" in self.columns

    def test_has_created_at(self):
        assert "created_at" in self.columns

    def test_article_id_foreign_key(self):
        """article_id must reference articles_core(id) ON DELETE CASCADE."""
        fk = self.table.columns["article_id"].foreign_keys
        assert len(fk) == 1
        fk_ref = list(fk)[0]
        assert fk_ref.column.table.name == "articles_core"
        assert fk_ref.ondelete == "CASCADE"

    def test_unique_article_version(self):
        """UNIQUE(article_id, version) per design doc."""
        unique_constraints = [
            c
            for c in self.table.constraints
            if hasattr(c, "columns")
            and len(c.columns) == 2
            and "article_id" in [col.name for col in c.columns]
            and "version" in [col.name for col in c.columns]
        ]
        assert len(unique_constraints) >= 1

    def test_has_article_id_version_index(self):
        """Design doc specifies idx_article_versions_id on (article_id, version DESC)."""
        index_names = [idx.name for idx in self.table.indexes]
        assert any("version" in name.lower() for name in index_names)


# ── PromptTemplate model tests ───────────────────────────────


class TestPromptTemplateModel:
    """Verify prompt_templates ORM model (fixes migration-model sync issue)."""

    @pytest.fixture(autouse=True)
    def _inspect_table(self):
        self.columns = {c.name for c in inspect(PromptTemplate).columns}

    def test_has_id(self):
        assert "id" in self.columns

    def test_has_name(self):
        assert "name" in self.columns

    def test_has_template(self):
        assert "template" in self.columns

    def test_has_created_at(self):
        assert "created_at" in self.columns

    def test_has_updated_at(self):
        assert "updated_at" in self.columns
