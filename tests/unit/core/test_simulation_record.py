# tests/unit/core/test_simulation_record.py
"""Tests for SimulationRecord status machine."""

import pytest

from simulation_harness.core.simulation_record import (
    SimulationRecord,
    SimulationStatus,
)


def test_record_starts_pending_with_progress_timestamps():
    record = SimulationRecord.declare(name="test-api")
    assert record.name == "test-api"
    assert record.status == SimulationStatus.PENDING
    assert record.progress.phase is None
    assert record.progress.started_at is not None
    assert record.progress.updated_at == record.progress.started_at
    assert record.error is None
    assert record.instance is None


def test_record_transitions_advance_updated_at():
    record = SimulationRecord.declare(name="test-api")
    started = record.progress.started_at

    record.transition(SimulationStatus.GENERATING_SKILL, phase="skill_generation")
    assert record.status == SimulationStatus.GENERATING_SKILL
    assert record.progress.phase == "skill_generation"
    assert record.progress.updated_at >= started
    assert record.progress.started_at == started

    record.transition(SimulationStatus.INITIALIZING, phase="agent_init")
    assert record.status == SimulationStatus.INITIALIZING
    assert record.progress.phase == "agent_init"


def test_record_fail_sets_error_and_status():
    record = SimulationRecord.declare(name="test-api")
    record.fail(
        code="creation_timeout", message="exceeded 120s", details={"limit": 120}
    )
    assert record.status == SimulationStatus.FAILED
    assert record.error is not None
    assert record.error.code == "creation_timeout"
    assert record.error.message == "exceeded 120s"
    assert record.error.details == {"limit": 120}


def test_invalid_forward_transition_raises():
    record = SimulationRecord.declare(name="test-api")
    with pytest.raises(ValueError):
        record.transition(SimulationStatus.PENDING)


def test_terminal_status_cannot_transition():
    record = SimulationRecord.declare(name="test-api")
    record.fail(code="x", message="y")
    with pytest.raises(ValueError):
        record.transition(SimulationStatus.READY)


def test_mark_ready_sets_instance_and_clears_phase():
    from unittest.mock import MagicMock

    record = SimulationRecord.declare(name="test-api")
    record.transition(SimulationStatus.INITIALIZING, phase="agent_init")
    instance = MagicMock()
    record.mark_ready(instance)
    assert record.status == SimulationStatus.READY
    assert record.instance is instance
    assert record.progress.phase is None
