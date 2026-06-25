# src/simulation_harness/core/simulation_record.py
"""SimulationRecord — the lifecycle state object held by SimulationHost."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from simulation_harness.core.simulation_instance import SimulationInstance


class SimulationStatus(str, Enum):
    PENDING = "pending"
    GENERATING_SKILL = "generating_skill"
    INITIALIZING = "initializing"
    READY = "ready"
    FAILED = "failed"


_TERMINAL = {SimulationStatus.READY, SimulationStatus.FAILED}

# Allowed forward transitions. PENDING may skip GENERATING_SKILL when skill is reused.
_NEXT: dict[SimulationStatus, set[SimulationStatus]] = {
    SimulationStatus.PENDING: {
        SimulationStatus.GENERATING_SKILL,
        SimulationStatus.INITIALIZING,
        SimulationStatus.FAILED,
    },
    SimulationStatus.GENERATING_SKILL: {
        SimulationStatus.INITIALIZING,
        SimulationStatus.FAILED,
    },
    SimulationStatus.INITIALIZING: {
        SimulationStatus.READY,
        SimulationStatus.FAILED,
    },
    SimulationStatus.READY: set(),
    SimulationStatus.FAILED: set(),
}


@dataclass
class SimulationProgress:
    started_at: datetime
    updated_at: datetime
    phase: Optional[str] = None


@dataclass
class SimulationError:
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class SimulationRecord:
    name: str
    status: SimulationStatus
    progress: SimulationProgress
    mcp_port: Optional[int] = None
    error: Optional[SimulationError] = None
    instance: Optional["SimulationInstance"] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def declare(cls, name: str, mcp_port: int | None = None) -> "SimulationRecord":
        now = datetime.now(timezone.utc)
        return cls(
            name=name,
            status=SimulationStatus.PENDING,
            progress=SimulationProgress(started_at=now, updated_at=now, phase=None),
            mcp_port=mcp_port,
        )

    def transition(
        self, new_status: SimulationStatus, phase: str | None = None
    ) -> None:
        if self.status in _TERMINAL:
            raise ValueError(
                f"Cannot transition from terminal status {self.status.value}"
            )
        if new_status not in _NEXT[self.status]:
            raise ValueError(
                f"Invalid transition {self.status.value} -> {new_status.value}"
            )
        self.status = new_status
        self.progress.updated_at = datetime.now(timezone.utc)
        if phase is not None:
            self.progress.phase = phase

    def set_phase(self, phase: str) -> None:
        """Update the progress phase label without a status transition."""
        self.progress.phase = phase
        self.progress.updated_at = datetime.now(timezone.utc)

    def mark_ready(self, instance: "SimulationInstance") -> None:
        self.transition(SimulationStatus.READY)
        self.progress.phase = None  # clear phase on completion
        self.instance = instance

    def fail(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.transition(SimulationStatus.FAILED)  # raises ValueError on terminal state
        self.error = SimulationError(
            code=code, message=message, details=dict(details or {})
        )


# Made with Bob
