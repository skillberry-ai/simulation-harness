# tests/unit/core/test_simulation_creator.py
"""Tests for SimulationCreator background task."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from simulation_harness.core.simulation_creator import SimulationCreator
from simulation_harness.core.simulation_record import (
    SimulationRecord,
    SimulationStatus,
)
from typing import Any


@pytest.fixture
def record() -> Any:
    return SimulationRecord.declare(name="test-api")


@pytest.fixture
def skill_registry() -> MagicMock:
    reg = MagicMock()
    reg.ensure_skill = AsyncMock(return_value=Path("/tmp/skills/test-api/SKILL.md"))
    return reg


@pytest.fixture
def instance_factory() -> Any:
    """Synchronous callable returning a fake SimulationInstance."""
    instance = MagicMock()
    instance.shutdown = AsyncMock()
    factory = MagicMock(return_value=instance)
    return factory, instance


async def test_run_advances_through_to_ready(
    record: Any, skill_registry: MagicMock, instance_factory: Any
) -> None:
    factory, instance = instance_factory
    creator = SimulationCreator(
        record=record,
        skill_registry=skill_registry,
        instance_factory=factory,
        openapi_spec={"openapi": "3.0.0", "info": {"title": "x", "version": "1"}},
        regenerate=False,
        max_duration_seconds=10,
        skill_exists=lambda name: False,
    )

    await creator.run()

    assert record.status == SimulationStatus.READY
    assert record.instance is instance
    skill_registry.ensure_skill.assert_awaited_once()
    factory.assert_called_once()


async def test_skill_reuse_skips_generating_skill_phase(
    record: Any, skill_registry: MagicMock, instance_factory: Any
) -> None:
    factory, instance = instance_factory
    creator = SimulationCreator(
        record=record,
        skill_registry=skill_registry,
        instance_factory=factory,
        openapi_spec={"openapi": "3.0.0", "info": {"title": "x", "version": "1"}},
        regenerate=False,
        max_duration_seconds=10,
        skill_exists=lambda name: True,
    )

    statuses_seen: list[SimulationStatus] = []
    original_transition = record.transition

    def spy(new_status: Any, phase: Any = None) -> Any:
        statuses_seen.append(new_status)
        return original_transition(new_status, phase=phase)

    record.transition = spy  # type: ignore[method-assign]

    await creator.run()

    assert SimulationStatus.GENERATING_SKILL not in statuses_seen
    assert SimulationStatus.INITIALIZING in statuses_seen
    assert record.status == SimulationStatus.READY


async def test_skill_generation_failure_marks_failed(
    record: Any, skill_registry: MagicMock, instance_factory: Any
) -> None:
    factory, _ = instance_factory
    skill_registry.ensure_skill.side_effect = RuntimeError("boom")

    creator = SimulationCreator(
        record=record,
        skill_registry=skill_registry,
        instance_factory=factory,
        openapi_spec={"openapi": "3.0.0", "info": {"title": "x", "version": "1"}},
        regenerate=False,
        max_duration_seconds=10,
        skill_exists=lambda name: False,
    )

    await creator.run()

    assert record.status == SimulationStatus.FAILED
    assert record.error is not None
    assert record.error.code == "skill_generation_failed"
    assert "boom" in record.error.message


async def test_cancellation_during_skill_generation_propagates(
    record: Any, skill_registry: MagicMock, instance_factory: Any
) -> None:
    factory, _ = instance_factory
    started = asyncio.Event()
    cancelled_inside = asyncio.Event()

    async def slow_ensure_skill(*args: Any, **kwargs: Any) -> Any:
        started.set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled_inside.set()
            raise
        return Path("/tmp/x/SKILL.md")

    skill_registry.ensure_skill = AsyncMock(side_effect=slow_ensure_skill)

    creator = SimulationCreator(
        record=record,
        skill_registry=skill_registry,
        instance_factory=factory,
        openapi_spec={"openapi": "3.0.0", "info": {"title": "x", "version": "1"}},
        regenerate=False,
        max_duration_seconds=30,
        skill_exists=lambda name: False,
    )

    task = asyncio.create_task(creator.run())
    await asyncio.wait_for(started.wait(), timeout=1.0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert cancelled_inside.is_set()


async def test_timeout_marks_failed_with_creation_timeout(
    record: Any, skill_registry: MagicMock, instance_factory: Any
) -> None:
    factory, _ = instance_factory

    async def hang(*args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(10)
        return Path("/tmp/x/SKILL.md")

    skill_registry.ensure_skill = AsyncMock(side_effect=hang)

    creator = SimulationCreator(
        record=record,
        skill_registry=skill_registry,
        instance_factory=factory,
        openapi_spec={"openapi": "3.0.0", "info": {"title": "x", "version": "1"}},
        regenerate=False,
        max_duration_seconds=0.1,  # 100ms budget
        skill_exists=lambda name: False,
    )

    await creator.run()

    assert record.status == SimulationStatus.FAILED
    assert record.error is not None
    assert record.error.code == "creation_timeout"
