"""Unit tests for PersistStatus state machine validation."""

import pytest

from core.db.models import PersistStatus
from core.exceptions import InvalidStateTransitionError


class TestPersistStatusStateMachine:
    """Tests for PersistStatus state machine."""

    @pytest.mark.parametrize(
        "from_status,to_status",
        [
            # PENDING → PROCESSING, FAILED
            (PersistStatus.PENDING, PersistStatus.PROCESSING),
            (PersistStatus.PENDING, PersistStatus.FAILED),
            # PROCESSING → PG_DONE, FAILED
            (PersistStatus.PROCESSING, PersistStatus.PG_DONE),
            (PersistStatus.PROCESSING, PersistStatus.FAILED),
            # PG_DONE → NEO4J_DONE, FAILED
            (PersistStatus.PG_DONE, PersistStatus.NEO4J_DONE),
            (PersistStatus.PG_DONE, PersistStatus.FAILED),
            # FAILED → PENDING (允许重试)
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
            # PENDING 跳过中间状态
            (PersistStatus.PENDING, PersistStatus.PG_DONE),
            (PersistStatus.PENDING, PersistStatus.NEO4J_DONE),
            # PROCESSING 不允许回退或跳过
            (PersistStatus.PROCESSING, PersistStatus.PENDING),
            (PersistStatus.PROCESSING, PersistStatus.NEO4J_DONE),
            # PG_DONE 不允许回退
            (PersistStatus.PG_DONE, PersistStatus.PENDING),
            (PersistStatus.PG_DONE, PersistStatus.PROCESSING),
            # NEO4J_DONE 是终态，不允许任何转换
            (PersistStatus.NEO4J_DONE, PersistStatus.PENDING),
            (PersistStatus.NEO4J_DONE, PersistStatus.PROCESSING),
            (PersistStatus.NEO4J_DONE, PersistStatus.PG_DONE),
            (PersistStatus.NEO4J_DONE, PersistStatus.FAILED),
            # FAILED 只能转换到 PENDING
            (PersistStatus.FAILED, PersistStatus.PROCESSING),
            (PersistStatus.FAILED, PersistStatus.PG_DONE),
            (PersistStatus.FAILED, PersistStatus.NEO4J_DONE),
        ],
    )
    def test_invalid_transitions(self, from_status, to_status):
        """Test invalid state transitions are rejected."""
        assert PersistStatus.is_valid_transition(from_status, to_status) is False

    def test_complete_processing_workflow(self):
        """Test complete workflow from PENDING to NEO4J_DONE."""
        # PENDING → PROCESSING
        assert PersistStatus.is_valid_transition(
            PersistStatus.PENDING, PersistStatus.PROCESSING
        )
        # PROCESSING → PG_DONE
        assert PersistStatus.is_valid_transition(
            PersistStatus.PROCESSING, PersistStatus.PG_DONE
        )
        # PG_DONE → NEO4J_DONE
        assert PersistStatus.is_valid_transition(
            PersistStatus.PG_DONE, PersistStatus.NEO4J_DONE
        )

    def test_retry_workflow_from_failed(self):
        """Test retry workflow: FAILED → PENDING → PROCESSING."""
        # FAILED → PENDING
        assert PersistStatus.is_valid_transition(
            PersistStatus.FAILED, PersistStatus.PENDING
        )
        # PENDING → PROCESSING
        assert PersistStatus.is_valid_transition(
            PersistStatus.PENDING, PersistStatus.PROCESSING
        )

    def test_failure_from_any_state(self):
        """Test that transition to FAILED is allowed from non-terminal states."""
        non_terminal_states = [
            PersistStatus.PENDING,
            PersistStatus.PROCESSING,
            PersistStatus.PG_DONE,
        ]

        for status in non_terminal_states:
            assert PersistStatus.is_valid_transition(status, PersistStatus.FAILED) is True

    def test_terminal_state_immutable(self):
        """Test that NEO4J_DONE is a terminal state with no outgoing transitions."""
        terminal_state = PersistStatus.NEO4J_DONE

        for target_status in PersistStatus:
            if target_status != terminal_state:
                assert (
                    PersistStatus.is_valid_transition(terminal_state, target_status) is False
                )

    def test_all_transition_combinations(self):
        """Test all possible transition combinations for completeness."""
        all_statuses = list(PersistStatus)

        # 定义所有合法转换
        valid_transitions = {
            (PersistStatus.PENDING, PersistStatus.PENDING),
            (PersistStatus.PENDING, PersistStatus.PROCESSING),
            (PersistStatus.PENDING, PersistStatus.FAILED),
            (PersistStatus.PROCESSING, PersistStatus.PROCESSING),
            (PersistStatus.PROCESSING, PersistStatus.PG_DONE),
            (PersistStatus.PROCESSING, PersistStatus.FAILED),
            (PersistStatus.PG_DONE, PersistStatus.PG_DONE),
            (PersistStatus.PG_DONE, PersistStatus.NEO4J_DONE),
            (PersistStatus.PG_DONE, PersistStatus.FAILED),
            (PersistStatus.NEO4J_DONE, PersistStatus.NEO4J_DONE),
            (PersistStatus.FAILED, PersistStatus.FAILED),
            (PersistStatus.FAILED, PersistStatus.PENDING),
        }

        for from_status in all_statuses:
            for to_status in all_statuses:
                transition = (from_status, to_status)
                expected_result = transition in valid_transitions
                actual_result = PersistStatus.is_valid_transition(from_status, to_status)
                assert (
                    actual_result == expected_result
                ), f"Transition {from_status} → {to_status} failed: expected {expected_result}, got {actual_result}"

    @pytest.mark.parametrize(
        "from_status,to_status",
        [
            (PersistStatus.PENDING, PersistStatus.NEO4J_DONE),
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
        error = InvalidStateTransitionError("pending", "neo4j_done")

        expected_message = "Invalid state transition: cannot transition from 'pending' to 'neo4j_done'"
        assert error.message == expected_message
        assert str(error) == expected_message

    def test_retry_scenario_after_processing_failure(self):
        """Test retry scenario when processing fails."""
        # PROCESSING → FAILED
        assert PersistStatus.is_valid_transition(
            PersistStatus.PROCESSING, PersistStatus.FAILED
        )
        # FAILED → PENDING
        assert PersistStatus.is_valid_transition(
            PersistStatus.FAILED, PersistStatus.PENDING
        )
        # PENDING → PROCESSING (retry)
        assert PersistStatus.is_valid_transition(
            PersistStatus.PENDING, PersistStatus.PROCESSING
        )

    def test_retry_scenario_after_pg_done_failure(self):
        """Test retry scenario when Neo4j persistence fails after PG_DONE."""
        # PG_DONE → FAILED
        assert PersistStatus.is_valid_transition(
            PersistStatus.PG_DONE, PersistStatus.FAILED
        )
        # FAILED → PENDING
        assert PersistStatus.is_valid_transition(
            PersistStatus.FAILED, PersistStatus.PENDING
        )
        # Full workflow must restart
        assert PersistStatus.is_valid_transition(
            PersistStatus.PENDING, PersistStatus.PROCESSING
        )

    @pytest.mark.parametrize("status", list(PersistStatus))
    def test_transition_to_itself_always_valid(self, status):
        """Test that any state can transition to itself (idempotency)."""
        assert PersistStatus.is_valid_transition(status, status) is True