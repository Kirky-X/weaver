# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for Saga-related ORM models and PersistStatus state machine extension.

Design doc references:
- openspec/changes/saga-compensation-implementation/specs/saga-logging/spec.md
- openspec/changes/saga-compensation-implementation/specs/persist-status/spec.md
- Migration 20_create_saga_logs
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect

from core.db.models import PersistStatus, SagaLog

# ── SagaLog model tests ──────────────────────────────────────


class TestSagaLogModel:
    """Verify saga_logs ORM model matches design doc DDL."""

    @pytest.fixture(autouse=True)
    def _inspect_table(self):
        self.columns = {c.name for c in inspect(SagaLog).columns}
        self.table = SagaLog.__table__

    def test_has_id(self):
        assert "id" in self.columns

    def test_has_saga_id(self):
        assert "saga_id" in self.columns

    def test_has_article_id(self):
        assert "article_id" in self.columns

    def test_has_step_name(self):
        assert "step_name" in self.columns

    def test_has_step_status(self):
        assert "step_status" in self.columns

    def test_has_started_at(self):
        assert "started_at" in self.columns

    def test_has_completed_at(self):
        assert "completed_at" in self.columns

    def test_has_compensation_data(self):
        assert "compensation_data" in self.columns

    def test_has_error_message(self):
        assert "error_message" in self.columns

    def test_has_retry_count(self):
        assert "retry_count" in self.columns

    def test_has_created_at(self):
        assert "created_at" in self.columns

    def test_table_name(self):
        assert SagaLog.__tablename__ == "saga_logs"

    def test_saga_id_not_nullable(self):
        col = self.table.c["saga_id"]
        assert not col.nullable

    def test_article_id_not_nullable(self):
        col = self.table.c["article_id"]
        assert not col.nullable

    def test_step_name_not_nullable(self):
        col = self.table.c["step_name"]
        assert not col.nullable

    def test_step_status_not_nullable(self):
        col = self.table.c["step_status"]
        assert not col.nullable

    def test_started_at_not_nullable(self):
        col = self.table.c["started_at"]
        assert not col.nullable

    def test_completed_at_nullable(self):
        col = self.table.c["completed_at"]
        assert col.nullable

    def test_compensation_data_nullable(self):
        col = self.table.c["compensation_data"]
        assert col.nullable

    def test_error_message_nullable(self):
        col = self.table.c["error_message"]
        assert col.nullable

    def test_retry_count_default_zero(self):
        col = self.table.c["retry_count"]
        assert col.server_default is not None


# ── PersistStatus Saga extension tests ────────────────────────


class TestPersistStatusSagaStates:
    """Verify PersistStatus enum includes Saga states and transition rules."""

    def test_saga_started_exists(self):
        assert PersistStatus.SAGA_STARTED == "saga_started"

    def test_saga_pg_writing_exists(self):
        assert PersistStatus.SAGA_PG_WRITING == "saga_pg_writing"

    def test_saga_neo4j_writing_exists(self):
        assert PersistStatus.SAGA_NEO4J_WRITING == "saga_neo4j_writing"

    def test_saga_compensating_exists(self):
        assert PersistStatus.SAGA_COMPENSATING == "saga_compensating"

    def test_saga_compensated_exists(self):
        assert PersistStatus.SAGA_COMPENSATED == "saga_compensated"

    def test_saga_completed_exists(self):
        assert PersistStatus.SAGA_COMPLETED == "saga_completed"

    def test_enum_has_thirteen_members(self):
        assert len(list(PersistStatus)) == 13


class TestPersistStatusSagaTransitions:
    """Verify Saga state transition rules per spec."""

    @pytest.mark.parametrize(
        "from_status,to_status",
        [
            # PENDING → SAGA_STARTED
            (PersistStatus.PENDING, PersistStatus.SAGA_STARTED),
            # SAGA_STARTED → SAGA_PG_WRITING, FAILED
            (PersistStatus.SAGA_STARTED, PersistStatus.SAGA_PG_WRITING),
            (PersistStatus.SAGA_STARTED, PersistStatus.FAILED),
            # SAGA_PG_WRITING → SAGA_NEO4J_WRITING, SAGA_COMPENSATING
            (PersistStatus.SAGA_PG_WRITING, PersistStatus.SAGA_NEO4J_WRITING),
            (PersistStatus.SAGA_PG_WRITING, PersistStatus.SAGA_COMPENSATING),
            # SAGA_NEO4J_WRITING → SAGA_COMPLETED, SAGA_COMPENSATING
            (PersistStatus.SAGA_NEO4J_WRITING, PersistStatus.SAGA_COMPLETED),
            (PersistStatus.SAGA_NEO4J_WRITING, PersistStatus.SAGA_COMPENSATING),
            # SAGA_COMPENSATING → SAGA_COMPENSATED, FAILED
            (PersistStatus.SAGA_COMPENSATING, PersistStatus.SAGA_COMPENSATED),
            (PersistStatus.SAGA_COMPENSATING, PersistStatus.FAILED),
            # SAGA_COMPENSATED → PENDING (allows retry)
            (PersistStatus.SAGA_COMPENSATED, PersistStatus.PENDING),
        ],
    )
    def test_valid_saga_transitions(self, from_status, to_status):
        assert PersistStatus.is_valid_transition(from_status, to_status) is True

    @pytest.mark.parametrize(
        "from_status,to_status",
        [
            # SAGA_STARTED cannot skip to SAGA_NEO4J_WRITING
            (PersistStatus.SAGA_STARTED, PersistStatus.SAGA_NEO4J_WRITING),
            # SAGA_PG_WRITING cannot go back to SAGA_STARTED
            (PersistStatus.SAGA_PG_WRITING, PersistStatus.SAGA_STARTED),
            # SAGA_COMPLETED is terminal
            (PersistStatus.SAGA_COMPLETED, PersistStatus.PENDING),
            (PersistStatus.SAGA_COMPLETED, PersistStatus.FAILED),
            (PersistStatus.SAGA_COMPLETED, PersistStatus.SAGA_COMPENSATING),
            # SAGA_COMPENSATED cannot go to SAGA_STARTED
            (PersistStatus.SAGA_COMPENSATED, PersistStatus.SAGA_STARTED),
        ],
    )
    def test_invalid_saga_transitions(self, from_status, to_status):
        assert PersistStatus.is_valid_transition(from_status, to_status) is False

    def test_saga_completed_is_terminal(self):
        assert PersistStatus.is_terminal(PersistStatus.SAGA_COMPLETED) is True

    def test_neo4j_done_still_terminal(self):
        assert PersistStatus.is_terminal(PersistStatus.NEO4J_DONE) is True

    def test_saga_compensated_allows_retry(self):
        assert PersistStatus.allows_retry(PersistStatus.SAGA_COMPENSATED) is True

    def test_failed_allows_retry(self):
        assert PersistStatus.allows_retry(PersistStatus.FAILED) is True

    def test_neo4j_failed_allows_retry(self):
        assert PersistStatus.allows_retry(PersistStatus.NEO4J_FAILED) is True

    def test_saga_started_not_terminal(self):
        assert PersistStatus.is_terminal(PersistStatus.SAGA_STARTED) is False

    def test_saga_pg_writing_not_retryable(self):
        assert PersistStatus.allows_retry(PersistStatus.SAGA_PG_WRITING) is False

    def test_complete_saga_workflow(self):
        """Test complete Saga workflow: PENDING → SAGA_STARTED → ... → SAGA_COMPLETED."""
        assert PersistStatus.is_valid_transition(PersistStatus.PENDING, PersistStatus.SAGA_STARTED)
        assert PersistStatus.is_valid_transition(
            PersistStatus.SAGA_STARTED, PersistStatus.SAGA_PG_WRITING
        )
        assert PersistStatus.is_valid_transition(
            PersistStatus.SAGA_PG_WRITING, PersistStatus.SAGA_NEO4J_WRITING
        )
        assert PersistStatus.is_valid_transition(
            PersistStatus.SAGA_NEO4J_WRITING, PersistStatus.SAGA_COMPLETED
        )

    def test_saga_compensation_workflow(self):
        """Test Saga compensation workflow: PG_WRITING → COMPENSATING → COMPENSATED → PENDING."""
        assert PersistStatus.is_valid_transition(
            PersistStatus.SAGA_PG_WRITING, PersistStatus.SAGA_COMPENSATING
        )
        assert PersistStatus.is_valid_transition(
            PersistStatus.SAGA_COMPENSATING, PersistStatus.SAGA_COMPENSATED
        )
        assert PersistStatus.is_valid_transition(
            PersistStatus.SAGA_COMPENSATED, PersistStatus.PENDING
        )
