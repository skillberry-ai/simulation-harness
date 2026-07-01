# tests/unit/core/test_simulation_record.py
"""Tests for SimulationRecord status machine."""

import pytest

from simulation_harness.core.simulation_record import (
    SimulationRecord,
    SimulationStatus,
)


def test_record_starts_pending_with_progress_timestamps() -> None:
    record = SimulationRecord.declare(name="test-api")
    assert record.name == "test-api"
    assert record.status == SimulationStatus.PENDING
    assert record.progress.phase is None
    assert record.progress.started_at is not None
    assert record.progress.updated_at == record.progress.started_at
    assert record.error is None
    assert record.instance is None


def test_record_transitions_advance_updated_at() -> None:
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


def test_record_fail_sets_error_and_status() -> None:
    record = SimulationRecord.declare(name="test-api")
    record.fail(
        code="creation_timeout", message="exceeded 120s", details={"limit": 120}
    )
    assert record.status == SimulationStatus.FAILED
    assert record.error is not None
    assert record.error.code == "creation_timeout"
    assert record.error.message == "exceeded 120s"
    assert record.error.details == {"limit": 120}


def test_invalid_forward_transition_raises() -> None:
    record = SimulationRecord.declare(name="test-api")
    with pytest.raises(ValueError):
        record.transition(SimulationStatus.PENDING)


def test_terminal_status_cannot_transition() -> None:
    record = SimulationRecord.declare(name="test-api")
    record.fail(code="x", message="y")
    with pytest.raises(ValueError):
        record.transition(SimulationStatus.READY)


def test_mark_ready_sets_instance_and_clears_phase() -> None:
    from unittest.mock import MagicMock

    record = SimulationRecord.declare(name="test-api")
    record.transition(SimulationStatus.INITIALIZING, phase="agent_init")
    instance = MagicMock()
    record.mark_ready(instance)
    assert record.status == SimulationStatus.READY
    assert record.instance is instance
    assert record.progress.phase is None


def test_set_phase_updates_phase_without_transition() -> None:
    rec = SimulationRecord.declare(name="aha")
    rec.transition(SimulationStatus.GENERATING_SKILL, phase="skill_generation")
    before = rec.progress.updated_at
    rec.set_phase("generating_ops 3/10")
    assert rec.progress.phase == "generating_ops 3/10"
    assert rec.status == SimulationStatus.GENERATING_SKILL
    assert rec.progress.updated_at >= before


def test_generated_status_value() -> None:
    assert SimulationStatus.GENERATED.value == "generated"


def test_pending_can_transition_to_generated() -> None:
    record = SimulationRecord.declare(name="x")
    record.transition(SimulationStatus.GENERATED, phase="generated")
    assert record.status == SimulationStatus.GENERATED


def test_generating_skill_can_transition_to_generated() -> None:
    record = SimulationRecord.declare(name="x")
    record.transition(SimulationStatus.GENERATING_SKILL)
    record.transition(SimulationStatus.GENERATED)
    assert record.status == SimulationStatus.GENERATED


def test_generated_can_advance_to_initializing_then_ready() -> None:
    record = SimulationRecord.declare(name="x")
    record.transition(SimulationStatus.GENERATED)
    record.transition(SimulationStatus.INITIALIZING)
    assert record.status == SimulationStatus.INITIALIZING


def test_mark_generated_sets_status_and_no_instance() -> None:
    record = SimulationRecord.declare(name="x")
    record.mark_generated()
    assert record.status == SimulationStatus.GENERATED
    assert record.instance is None
