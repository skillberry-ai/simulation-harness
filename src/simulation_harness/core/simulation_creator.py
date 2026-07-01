# src/simulation_harness/core/simulation_creator.py
"""SimulationCreator — runs the async creation pipeline for a SimulationRecord."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, TYPE_CHECKING

from simulation_harness.core.simulation_record import (
    SimulationRecord,
    SimulationStatus,
)
from simulation_harness.utils.errors import SimulationArtifactsNotFoundError
from simulation_harness.utils.logging import get_logger

if TYPE_CHECKING:
    from simulation_harness.core.simulation_instance import SimulationInstance
    from simulation_harness.core.skill_registry import SkillRegistry


logger = get_logger(__name__)


class SimulationCreator:
    """Drives skill generation + instance build for one SimulationRecord."""

    def __init__(
        self,
        record: SimulationRecord,
        skill_registry: "SkillRegistry",
        instance_factory: Callable[..., "SimulationInstance"],
        openapi_spec: dict[str, Any],
        regenerate: bool,
        max_duration_seconds: float,
        skill_exists: Callable[[str], bool],
        mcp_port: int | None = None,
        generate: bool = True,
        start: bool = True,
    ) -> None:
        self._record = record
        self._skill_registry = skill_registry
        self._instance_factory = instance_factory
        self._openapi_spec = openapi_spec
        self._regenerate = regenerate
        self._max_duration_seconds = max_duration_seconds
        self._skill_exists = skill_exists
        self._mcp_port = mcp_port
        self._generate = generate
        self._start = start

    async def run(self) -> None:
        """Run the creation pipeline; mutates the record in place.

        On `asyncio.CancelledError`, the exception is re-raised AFTER the record
        is left in its current non-terminal state so that the host can decide to
        evict it. Other failures land the record in `failed`.
        """
        try:
            await asyncio.wait_for(self._pipeline(), timeout=self._max_duration_seconds)
        except asyncio.TimeoutError:
            logger.warning(
                "Simulation creation timed out for %s after %.1fs",
                self._record.name,
                self._max_duration_seconds,
            )
            self._record.fail(
                code="creation_timeout",
                message=f"Simulation creation exceeded {self._max_duration_seconds}s budget.",
                details={"limit_seconds": self._max_duration_seconds},
            )
        except asyncio.CancelledError:
            logger.info("Simulation creation cancelled for %s", self._record.name)
            raise
        except Exception as e:
            logger.exception("Simulation creation failed for %s", self._record.name)
            # Distinguish skill-generation failures from instance-build failures
            # by inspecting the current phase the record is in.
            code = (
                "skill_generation_failed"
                if self._generate
                and self._record.status
                in (SimulationStatus.PENDING, SimulationStatus.GENERATING_SKILL)
                else "instance_init_failed"
            )
            cause = e.__cause__
            self._record.fail(
                code=code,
                message=str(e),
                details={
                    "exception": type(e).__name__,
                    "cause": str(cause) if cause else None,
                    "cause_type": type(cause).__name__ if cause else None,
                },
            )

    async def _pipeline(self) -> None:
        skill_dir = self._skill_registry.skills_folder / self._record.name

        if self._generate:
            # If the skill is already complete on disk and we are not regenerating,
            # collapse the status sequence: pending -> initializing -> ready.
            # Otherwise: pending -> generating_skill -> initializing -> ready.
            reuse = self._skill_exists(self._record.name) and not self._regenerate
            if not reuse:
                self._record.transition(
                    SimulationStatus.GENERATING_SKILL, phase="skill_generation"
                )
            await self._skill_registry.ensure_skill(
                simulation_name=self._record.name,
                openapi_spec=self._openapi_spec,
                regenerate=self._regenerate,
                progress_cb=self._record.set_phase,
            )
        else:
            # Start-only: never generate. Guard on complete artifacts.
            if not self._skill_registry.is_complete(self._record.name):
                raise SimulationArtifactsNotFoundError(
                    name=self._record.name,
                    missing=self._skill_registry.missing_files(self._record.name),
                )

        if not self._start:
            self._record.mark_generated()
            return

        self._record.transition(SimulationStatus.INITIALIZING, phase="agent_init")

        instance = self._instance_factory(
            simulation_name=self._record.name,
            openapi_spec=self._openapi_spec,
            skill_dir=skill_dir,
            mcp_port=self._mcp_port,
        )

        self._record.mark_ready(instance)


# Made with Bob
