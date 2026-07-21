# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for PersistStatus state machine validation."""

import pytest

from core.db import PersistStatus
from core.exceptions import InvalidStateTransitionError


class TestPersistStatusEnumSize:
    """Tests for PersistStatus enum size (12 states including saga)."""

    def test_enum_has_exactly_twelve_members(self):
        """Test that PersistStatus has exactly 12 members (excluding LADYBUG_DONE)."""
        # LADYBUG_DONE is added for LadybugDB support, total is now 13
        assert len(list(PersistStatus)) == 13

    def test_stored_not_in_enum(self):
        """Test that STORED is not a PersistStatus member."""
        with pytest.raises(AttributeError):
            _ = PersistStatus.STORED

    def test_complete_not_in_enum(self):
        """Test that COMPLETE is not a PersistStatus member."""
        with pytest.raises(AttributeError):
            _ = PersistStatus.COMPLETE

    def test_all_statuses_present(self):
        """Test that all 13 expected statuses are present."""
        expected_names = {
            "PENDING",
            "PROCESSING",
            "PG_DONE",
            "NEO4J_DONE",
            "NEO4J_FAILED",
            "LADYBUG_DONE",
            "FAILED",
            "SAGA_STARTED",
            "SAGA_PG_WRITING",
            "SAGA_NEO4J_WRITING",
            "SAGA_COMPENSATING",
            "SAGA_COMPENSATED",
            "SAGA_COMPLETED",
        }
        actual_names = {m.name for m in PersistStatus}
        assert actual_names == expected_names

    def test_enum_value_uniqueness(self):
        """Test that all enum values are unique."""
        values = [m.value for m in PersistStatus]
        assert len(values) == len(set(values))


class TestPersistStatusStateMachine:
    """Tests for PersistStatus state machine."""

    @pytest.mark.parametrize(
        "from_status,to_status",
        [
            # PENDING → PROCESSING, FAILED, SAGA_STARTED, NEO4J_DONE, LADYBUG_DONE
            (PersistStatus.PENDING, PersistStatus.PROCESSING),
            (PersistStatus.PENDING, PersistStatus.FAILED),
            (PersistStatus.PENDING, PersistStatus.SAGA_STARTED),
            (PersistStatus.PENDING, PersistStatus.NEO4J_DONE),
            (PersistStatus.PENDING, PersistStatus.LADYBUG_DONE),
            # PROCESSING → PG_DONE, FAILED
            (PersistStatus.PROCESSING, PersistStatus.PG_DONE),
            (PersistStatus.PROCESSING, PersistStatus.FAILED),
            # PG_DONE → NEO4J_DONE, NEO4J_FAILED, FAILED
            (PersistStatus.PG_DONE, PersistStatus.NEO4J_DONE),
            (PersistStatus.PG_DONE, PersistStatus.NEO4J_FAILED),
            (PersistStatus.PG_DONE, PersistStatus.FAILED),
            # NEO4J_FAILED → PENDING, PG_DONE
            (PersistStatus.NEO4J_FAILED, PersistStatus.PENDING),
            (PersistStatus.NEO4J_FAILED, PersistStatus.PG_DONE),
            # FAILED → PENDING
            (PersistStatus.FAILED, PersistStatus.PENDING),
        ],
    )
    def test_valid_transitions(self, from_status, to_status):
        """Test valid state transitions are allowed."""
        assert PersistStatus.is_valid_transition(from_status, to_status) is True

    @pytest.mark.parametrize("status", list(PersistStatus))
    def test_idempotent_transitions(self, status):
        """Test that transitioning to the same state is allowed (idempotent)."""
        assert PersistStatus.is_valid_transition(status, status) is True

    @pytest.mark.parametrize(
        "from_status,to_status",
        [
            # PENDING cannot skip to PG_DONE (must go through PROCESSING)
            (PersistStatus.PENDING, PersistStatus.PG_DONE),
            # PENDING cannot skip to NEO4J_FAILED (must go through PROCESSING → PG_DONE)
            (PersistStatus.PENDING, PersistStatus.NEO4J_FAILED),
            # PROCESSING cannot go backward or skip
            (PersistStatus.PROCESSING, PersistStatus.PENDING),
            (PersistStatus.PROCESSING, PersistStatus.NEO4J_DONE),
            (PersistStatus.PROCESSING, PersistStatus.NEO4J_FAILED),
            # PG_DONE cannot go backward
            (PersistStatus.PG_DONE, PersistStatus.PENDING),
            (PersistStatus.PG_DONE, PersistStatus.PROCESSING),
            # NEO4J_DONE is terminal
            (PersistStatus.NEO4J_DONE, PersistStatus.PENDING),
            (PersistStatus.NEO4J_DONE, PersistStatus.PROCESSING),
            (PersistStatus.NEO4J_DONE, PersistStatus.PG_DONE),
            (PersistStatus.NEO4J_DONE, PersistStatus.NEO4J_FAILED),
            (PersistStatus.NEO4J_DONE, PersistStatus.FAILED),
            # NEO4J_FAILED cannot go to PROCESSING or NEO4J_DONE
            (PersistStatus.NEO4J_FAILED, PersistStatus.PROCESSING),
            (PersistStatus.NEO4J_FAILED, PersistStatus.NEO4J_DONE),
            (PersistStatus.NEO4J_FAILED, PersistStatus.FAILED),
            # FAILED can only go to PENDING, NEO4J_DONE, LADYBUG_DONE
            (PersistStatus.FAILED, PersistStatus.PROCESSING),
            (PersistStatus.FAILED, PersistStatus.PG_DONE),
            (PersistStatus.FAILED, PersistStatus.NEO4J_FAILED),
        ],
    )
    def test_invalid_transitions(self, from_status, to_status):
        """Test invalid state transitions are rejected."""
        assert PersistStatus.is_valid_transition(from_status, to_status) is False

    def test_complete_processing_workflow(self):
        """Test complete workflow from PENDING to NEO4J_DONE."""
        assert PersistStatus.is_valid_transition(PersistStatus.PENDING, PersistStatus.PROCESSING)
        assert PersistStatus.is_valid_transition(PersistStatus.PROCESSING, PersistStatus.PG_DONE)
        assert PersistStatus.is_valid_transition(PersistStatus.PG_DONE, PersistStatus.NEO4J_DONE)

    def test_retry_workflow_from_failed(self):
        """Test retry workflow: FAILED → PENDING → PROCESSING."""
        assert PersistStatus.is_valid_transition(PersistStatus.FAILED, PersistStatus.PENDING)
        assert PersistStatus.is_valid_transition(PersistStatus.PENDING, PersistStatus.PROCESSING)

    def test_failure_from_any_non_terminal_state(self):
        """Test that transition to FAILED is allowed from non-terminal states."""
        non_terminal_states = [
            PersistStatus.PENDING,
            PersistStatus.PROCESSING,
            PersistStatus.PG_DONE,
            PersistStatus.FAILED,
        ]

        for status in non_terminal_states:
            assert PersistStatus.is_valid_transition(status, PersistStatus.FAILED) is True

    def test_neo4j_done_is_terminal(self):
        """Test that NEO4J_DONE is a terminal state with no outgoing transitions."""
        terminal_state = PersistStatus.NEO4J_DONE

        for target_status in PersistStatus:
            if target_status != terminal_state:
                assert PersistStatus.is_valid_transition(terminal_state, target_status) is False

    def test_all_transition_combinations(self):
        """Test all possible transition combinations for completeness."""
        all_statuses = list(PersistStatus)

        valid_transitions = {
            # Idempotent transitions
            (PersistStatus.PENDING, PersistStatus.PENDING),
            (PersistStatus.PROCESSING, PersistStatus.PROCESSING),
            (PersistStatus.PG_DONE, PersistStatus.PG_DONE),
            (PersistStatus.NEO4J_DONE, PersistStatus.NEO4J_DONE),
            (PersistStatus.NEO4J_FAILED, PersistStatus.NEO4J_FAILED),
            (PersistStatus.LADYBUG_DONE, PersistStatus.LADYBUG_DONE),
            (PersistStatus.FAILED, PersistStatus.FAILED),
            # Forward transitions
            (PersistStatus.PENDING, PersistStatus.PROCESSING),
            (PersistStatus.PENDING, PersistStatus.FAILED),
            (PersistStatus.PENDING, PersistStatus.SAGA_STARTED),
            (PersistStatus.PENDING, PersistStatus.NEO4J_DONE),
            (PersistStatus.PENDING, PersistStatus.LADYBUG_DONE),
            (PersistStatus.PROCESSING, PersistStatus.PG_DONE),
            (PersistStatus.PROCESSING, PersistStatus.FAILED),
            (PersistStatus.PG_DONE, PersistStatus.NEO4J_DONE),
            (PersistStatus.PG_DONE, PersistStatus.NEO4J_FAILED),
            (PersistStatus.PG_DONE, PersistStatus.LADYBUG_DONE),
            (PersistStatus.PG_DONE, PersistStatus.FAILED),
            # Saga transitions
            (PersistStatus.SAGA_STARTED, PersistStatus.SAGA_PG_WRITING),
            (PersistStatus.SAGA_STARTED, PersistStatus.FAILED),
            (PersistStatus.SAGA_PG_WRITING, PersistStatus.SAGA_NEO4J_WRITING),
            (PersistStatus.SAGA_PG_WRITING, PersistStatus.SAGA_COMPENSATING),
            (PersistStatus.SAGA_NEO4J_WRITING, PersistStatus.SAGA_COMPLETED),
            (PersistStatus.SAGA_NEO4J_WRITING, PersistStatus.SAGA_COMPENSATING),
            (PersistStatus.SAGA_COMPENSATING, PersistStatus.SAGA_COMPENSATED),
            (PersistStatus.SAGA_COMPENSATING, PersistStatus.FAILED),
            (PersistStatus.SAGA_COMPENSATED, PersistStatus.PENDING),
            # Idempotent saga transitions
            (PersistStatus.SAGA_STARTED, PersistStatus.SAGA_STARTED),
            (PersistStatus.SAGA_PG_WRITING, PersistStatus.SAGA_PG_WRITING),
            (PersistStatus.SAGA_NEO4J_WRITING, PersistStatus.SAGA_NEO4J_WRITING),
            (PersistStatus.SAGA_COMPENSATING, PersistStatus.SAGA_COMPENSATING),
            (PersistStatus.SAGA_COMPENSATED, PersistStatus.SAGA_COMPENSATED),
            (PersistStatus.SAGA_COMPLETED, PersistStatus.SAGA_COMPLETED),
            # Retry transitions
            (PersistStatus.NEO4J_FAILED, PersistStatus.PENDING),
            (PersistStatus.NEO4J_FAILED, PersistStatus.PG_DONE),
            (PersistStatus.FAILED, PersistStatus.PENDING),
            (PersistStatus.FAILED, PersistStatus.NEO4J_DONE),
            (PersistStatus.FAILED, PersistStatus.LADYBUG_DONE),
        }

        for from_status in all_statuses:
            for to_status in all_statuses:
                transition = (from_status, to_status)
                expected_result = transition in valid_transitions
                actual_result = PersistStatus.is_valid_transition(from_status, to_status)
                assert actual_result == expected_result, (
                    f"Transition {from_status} → {to_status} failed: "
                    f"expected {expected_result}, got {actual_result}"
                )

    @pytest.mark.parametrize(
        "from_status,to_status",
        [
            (PersistStatus.PENDING, PersistStatus.PG_DONE),
            (PersistStatus.PROCESSING, PersistStatus.PENDING),
            (PersistStatus.NEO4J_DONE, PersistStatus.PENDING),
        ],
    )
    def test_invalid_transition_error_message(self, from_status, to_status):
        """Test that InvalidStateTransitionError has correct error message."""
        error = InvalidStateTransitionError(from_status.value, to_status.value)

        assert error.from_status == from_status.value
        assert error.to_status == to_status.value
        assert from_status.value in error.message
        assert to_status.value in error.message
        assert "Invalid state transition" in error.message

    def test_error_message_format(self):
        """Test that error message follows expected format."""
        error = InvalidStateTransitionError("pending", "pg_done")

        expected_message = "Invalid state transition: cannot transition from 'pending' to 'pg_done'"
        assert error.message == expected_message
        assert str(error) == expected_message

    def test_retry_scenario_after_processing_failure(self):
        """Test retry scenario when processing fails."""
        assert PersistStatus.is_valid_transition(PersistStatus.PROCESSING, PersistStatus.FAILED)
        assert PersistStatus.is_valid_transition(PersistStatus.FAILED, PersistStatus.PENDING)
        assert PersistStatus.is_valid_transition(PersistStatus.PENDING, PersistStatus.PROCESSING)

    def test_retry_scenario_after_pg_done_failure(self):
        """Test retry scenario when enrichment fails after PG_DONE."""
        assert PersistStatus.is_valid_transition(PersistStatus.PG_DONE, PersistStatus.FAILED)
        assert PersistStatus.is_valid_transition(PersistStatus.FAILED, PersistStatus.PENDING)
        assert PersistStatus.is_valid_transition(PersistStatus.PENDING, PersistStatus.PROCESSING)

    def test_retry_scenario_neo4j_failed_to_pending(self):
        """Test retry scenario: NEO4J_FAILED → PENDING → PROCESSING."""
        assert PersistStatus.is_valid_transition(PersistStatus.NEO4J_FAILED, PersistStatus.PENDING)
        assert PersistStatus.is_valid_transition(PersistStatus.PENDING, PersistStatus.PROCESSING)

    def test_retry_scenario_neo4j_failed_to_pg_done(self):
        """Test retry scenario: NEO4J_FAILED → PG_DONE."""
        assert PersistStatus.is_valid_transition(PersistStatus.NEO4J_FAILED, PersistStatus.PG_DONE)

    @pytest.mark.parametrize("status", list(PersistStatus))
    def test_transition_to_itself_always_valid(self, status):
        """Test that any state can transition to itself (idempotency)."""
        assert PersistStatus.is_valid_transition(status, status) is True


class TestLadybugDoneStatus:
    """Tests for LADYBUG_DONE status added for LadybugDB support."""

    def test_ladybug_done_value(self):
        """Test that LADYBUG_DONE has the correct value."""
        assert PersistStatus.LADYBUG_DONE.value == "ladybug_done"

    def test_ladybug_done_is_valid_member(self):
        """Test that LADYBUG_DONE is a valid PersistStatus member."""
        assert PersistStatus.LADYBUG_DONE in list(PersistStatus)

    def test_pg_done_to_ladybug_done_valid_transition(self):
        """Test PG_DONE → LADYBUG_DONE is a valid transition."""
        assert (
            PersistStatus.is_valid_transition(PersistStatus.PG_DONE, PersistStatus.LADYBUG_DONE)
            is True
        )

    def test_ladybug_done_is_complete(self):
        """Test that LADYBUG_DONE is recognized as a complete (terminal) state."""
        assert PersistStatus.is_terminal(PersistStatus.LADYBUG_DONE) is True

    def test_ladybug_done_is_terminal_no_outgoing(self):
        """Test that LADYBUG_DONE has no outgoing transitions (except self)."""
        for target_status in PersistStatus:
            if target_status != PersistStatus.LADYBUG_DONE:
                assert (
                    PersistStatus.is_valid_transition(PersistStatus.LADYBUG_DONE, target_status)
                    is False
                ), f"LADYBUG_DONE should be terminal, but can transition to {target_status}"

    def test_ladybug_done_idempotent(self):
        """Test that LADYBUG_DONE → LADYBUG_DONE is valid (idempotent)."""
        assert (
            PersistStatus.is_valid_transition(
                PersistStatus.LADYBUG_DONE, PersistStatus.LADYBUG_DONE
            )
            is True
        )

    def test_neo4j_done_and_ladybug_done_both_complete(self):
        """Test that both NEO4J_DONE and LADYBUG_DONE are recognized as complete."""
        assert PersistStatus.is_terminal(PersistStatus.NEO4J_DONE) is True
        assert PersistStatus.is_terminal(PersistStatus.LADYBUG_DONE) is True

    def test_ladybug_done_not_allows_retry(self):
        """Test that LADYBUG_DONE does not allow retry."""
        assert PersistStatus.allows_retry(PersistStatus.LADYBUG_DONE) is False

    def test_complete_ladybug_workflow(self):
        """Test complete workflow: PENDING → PROCESSING → PG_DONE → LADYBUG_DONE."""
        assert PersistStatus.is_valid_transition(PersistStatus.PENDING, PersistStatus.PROCESSING)
        assert PersistStatus.is_valid_transition(PersistStatus.PROCESSING, PersistStatus.PG_DONE)
        assert PersistStatus.is_valid_transition(PersistStatus.PG_DONE, PersistStatus.LADYBUG_DONE)


class TestCompletedStatuses:
    """Tests for PersistStatus.completed_statuses() class method."""

    def test_completed_statuses_includes_pg_done(self):
        """PG_DONE is a completed status (intermediate success)."""
        assert PersistStatus.PG_DONE in PersistStatus.completed_statuses()

    def test_completed_statuses_includes_neo4j_done(self):
        """NEO4J_DONE is a completed status (terminal success for Neo4j)."""
        assert PersistStatus.NEO4J_DONE in PersistStatus.completed_statuses()

    def test_completed_statuses_includes_ladybug_done(self):
        """LADYBUG_DONE is a completed status (terminal success for LadybugDB)."""
        assert PersistStatus.LADYBUG_DONE in PersistStatus.completed_statuses()

    def test_completed_statuses_includes_saga_completed(self):
        """SAGA_COMPLETED is a completed status (terminal success for Saga)."""
        assert PersistStatus.SAGA_COMPLETED in PersistStatus.completed_statuses()

    def test_completed_statuses_excludes_non_complete(self):
        """Non-complete statuses are excluded."""
        non_complete = {
            PersistStatus.PENDING,
            PersistStatus.PROCESSING,
            PersistStatus.NEO4J_FAILED,
            PersistStatus.FAILED,
            PersistStatus.SAGA_STARTED,
            PersistStatus.SAGA_PG_WRITING,
            PersistStatus.SAGA_NEO4J_WRITING,
            PersistStatus.SAGA_COMPENSATING,
            PersistStatus.SAGA_COMPENSATED,
        }
        for status in non_complete:
            assert status not in PersistStatus.completed_statuses(), (
                f"{status} should not be in completed_statuses"
            )

    def test_completed_statuses_returns_frozenset(self):
        """completed_statuses() returns a frozenset (immutable)."""
        result = PersistStatus.completed_statuses()
        assert isinstance(result, frozenset)

    def test_completed_statuses_has_four_members(self):
        """completed_statuses() contains exactly 4 statuses."""
        assert len(PersistStatus.completed_statuses()) == 4

    def test_all_terminal_success_states_included(self):
        """All terminal success states from is_terminal are in completed_statuses."""
        terminal_success = {s for s in PersistStatus if PersistStatus.is_terminal(s)}
        # completed_statuses includes terminal success + PG_DONE
        assert terminal_success.issubset(PersistStatus.completed_statuses())
