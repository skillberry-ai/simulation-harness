"""SimulationHost - singleton holder for the active simulation record."""

import asyncio
from pathlib import Path
from typing import Any, Callable, Optional

from simulation_harness.config.settings import get_config, get_secrets
from simulation_harness.core.simulation_creator import SimulationCreator
from simulation_harness.core.simulation_instance import SimulationInstance
from simulation_harness.core.simulation_record import (
    SimulationRecord,
    SimulationStatus,
)
from simulation_harness.core.skill_registry import SkillRegistry
from simulation_harness.mcp_integration.sidecar_server import SidecarMCPServer
from simulation_harness.utils.errors import (
    SimulationAlreadyExistsError,
    SimulationArtifactsNotFoundError,
    SimulationBusyError,
    SimulationNotFoundError,
    SimulationNotReadyError,
)
from simulation_harness.utils.logging import get_logger

logger = get_logger(__name__)


def _default_instance_factory(
    *,
    simulation_name: str,
    openapi_spec: dict[str, Any],
    skill_dir: Path,
    mcp_port: int | None,
) -> SimulationInstance:
    """Build a SimulationInstance using global config + secrets."""
    from simulation_harness.models.domain import SimulationSpec

    config = get_config()
    secrets = get_secrets()
    spec = SimulationSpec(name=simulation_name, openapi_spec=openapi_spec)
    return SimulationInstance(
        spec=spec,
        max_messages=config.sessions.max_messages,
        idle_timeout_seconds=config.sessions.idle_timeout_seconds,
        max_queue_depth=config.sessions.max_concurrent_queue_depth,
        api_key=secrets.llm_api_key,
        model=config.llm.simulation_model,
        temperature=config.llm.temperature,
        max_tokens=config.llm.max_tokens,
        base_url=secrets.llm_api_base,
        skill_dir=skill_dir,
        agent_recursion_limit=config.sessions.agent_recursion_limit,
        mcp_port=mcp_port,
    )


class SimulationHost:
    """Manages at most one SimulationRecord with lifecycle serialization."""

    def __init__(self) -> None:
        self._record: Optional[SimulationRecord] = None
        self._creation_task: Optional[asyncio.Task[None]] = None
        self._lifecycle_lock = asyncio.Lock()

    async def declare_simulation(
        self,
        *,
        name: str,
        openapi_spec: dict[str, Any],
        regenerate: bool,
        mcp_port: int | None,
        skill_registry: SkillRegistry,
        instance_factory: Callable[..., SimulationInstance] = _default_instance_factory,
        max_duration_seconds: float | None = None,
    ) -> SimulationRecord:
        """Declare a new simulation. Returns immediately with status=pending.

        Raises:
            SimulationAlreadyExistsError: if any record already exists.
        """
        async with self._lifecycle_lock:
            if self._record is not None:
                raise SimulationAlreadyExistsError(
                    "A simulation already exists. Delete it before creating a new one."
                )

            if max_duration_seconds is None:
                config = get_config()
                max_duration_seconds = float(config.creation.max_duration_seconds)

            record = SimulationRecord.declare(name=name, mcp_port=mcp_port)
            self._record = record
            self._launch_creator(
                record=record,
                skill_registry=skill_registry,
                instance_factory=instance_factory,
                openapi_spec=openapi_spec,
                regenerate=regenerate,
                max_duration_seconds=max_duration_seconds,
                mcp_port=mcp_port,
                generate=True,
                start=True,
            )
            return record

    def _launch_creator(
        self,
        *,
        record: SimulationRecord,
        skill_registry: SkillRegistry,
        instance_factory: Callable[..., SimulationInstance],
        openapi_spec: dict[str, Any],
        regenerate: bool,
        max_duration_seconds: float,
        mcp_port: int | None,
        generate: bool,
        start: bool,
    ) -> None:
        """Build a SimulationCreator with explicit flags and spawn the background task.

        Caller must hold _lifecycle_lock and have already set self._record.
        """

        def _skill_exists(simulation_name: str) -> bool:
            return skill_registry.is_complete(simulation_name)

        creator = SimulationCreator(
            record=record,
            skill_registry=skill_registry,
            instance_factory=instance_factory,
            openapi_spec=openapi_spec,
            regenerate=regenerate,
            max_duration_seconds=max_duration_seconds,
            skill_exists=_skill_exists,
            mcp_port=mcp_port,
            generate=generate,
            start=start,
        )
        self._creation_task = asyncio.create_task(
            self._run_creation(creator, mcp_port if start else None)
        )

    async def setup_simulation(
        self,
        *,
        name: str,
        openapi_spec: dict[str, Any],
        regenerate: bool,
        skill_registry: SkillRegistry,
        instance_factory: Callable[..., SimulationInstance] = _default_instance_factory,
        max_duration_seconds: float | None = None,
    ) -> SimulationRecord:
        """Generate artifacts without starting an instance. Ends at GENERATED."""
        async with self._lifecycle_lock:
            if self._record is not None:
                raise SimulationAlreadyExistsError(
                    "A simulation already exists. Delete it before creating a new one."
                )
            if max_duration_seconds is None:
                max_duration_seconds = float(get_config().creation.max_duration_seconds)

            record = SimulationRecord.declare(name=name)
            self._record = record
            self._launch_creator(
                record=record,
                skill_registry=skill_registry,
                instance_factory=instance_factory,
                openapi_spec=openapi_spec,
                regenerate=regenerate,
                max_duration_seconds=max_duration_seconds,
                mcp_port=None,
                generate=True,
                start=False,
            )
            return record

    async def start_simulation(
        self,
        *,
        name: str,
        mcp_port: int | None,
        skill_registry: SkillRegistry,
        instance_factory: Callable[..., SimulationInstance] = _default_instance_factory,
        max_duration_seconds: float | None = None,
    ) -> SimulationRecord:
        """Start a session from baked artifacts. No generation.

        Raises:
            SimulationArtifactsNotFoundError: artifacts for `name` are incomplete.
            SimulationAlreadyExistsError: a READY simulation already occupies the slot.
        """
        async with self._lifecycle_lock:
            # Guard synchronously so the request path can return 404.
            if not skill_registry.is_complete(name):
                raise SimulationArtifactsNotFoundError(
                    name=name, missing=skill_registry.missing_files(name)
                )

            existing = self._record
            if existing is not None:
                if not (
                    existing.status == SimulationStatus.GENERATED
                    and existing.name == name
                ):
                    raise SimulationAlreadyExistsError(
                        "A simulation already exists. Delete it before starting a new one."
                    )
                record = existing  # consume the GENERATED record
            else:
                record = SimulationRecord.declare(name=name, mcp_port=mcp_port)
                self._record = record

            if max_duration_seconds is None:
                max_duration_seconds = float(get_config().creation.max_duration_seconds)

            openapi_spec = skill_registry.read_api(name)
            self._launch_creator(
                record=record,
                skill_registry=skill_registry,
                instance_factory=instance_factory,
                openapi_spec=openapi_spec,
                regenerate=False,
                max_duration_seconds=max_duration_seconds,
                mcp_port=mcp_port,
                generate=False,
                start=True,
            )
            return record

    async def _run_creation(
        self, creator: SimulationCreator, mcp_port: int | None
    ) -> None:
        """Drive the creator and start the sidecar (if requested) on success."""
        try:
            await creator.run()
        except asyncio.CancelledError:
            raise

        record = self._record
        if record is None:
            return

        if record.status == SimulationStatus.READY and mcp_port is not None:
            try:
                config = get_config()
                sidecar = SidecarMCPServer(
                    record.instance, mcp_port, config.mcp, config.server.host
                )
                await sidecar.start()
                record.instance._sidecar = sidecar  # type: ignore[union-attr]
            except Exception as e:
                logger.exception("Sidecar start failed; failing simulation")
                if record.instance is not None:
                    try:
                        await record.instance.shutdown()
                    except Exception:
                        logger.exception(
                            "Instance shutdown after sidecar failure failed"
                        )
                replacement = SimulationRecord.declare(name=record.name)
                replacement.fail(
                    code="sidecar_start_failed",
                    message=str(e),
                    details={"port": mcp_port},
                )
                self._record = replacement

    async def get_record(self) -> Optional[SimulationRecord]:
        """Return the current SimulationRecord, or None if no simulation declared."""
        async with self._lifecycle_lock:
            return self._record

    async def get_simulation(self) -> Optional[SimulationInstance]:
        """Return the ready SimulationInstance, or None.

        Backwards-compatible accessor: returns None until status=READY.
        """
        async with self._lifecycle_lock:
            if self._record is None:
                return None
            if self._record.status != SimulationStatus.READY:
                return None
            return self._record.instance

    async def delete_simulation(self) -> None:
        """Delete the current simulation: cancel creation if in-flight, shutdown if ready.

        Idempotent.
        """
        async with self._lifecycle_lock:
            record = self._record
            task = self._creation_task
            self._record = None
            self._creation_task = None

        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            # CancelledError derives from BaseException, not Exception, so both
            # arms are needed. Cancellation here is expected; anything else is
            # a creation failure we are already discarding, but log it so a
            # swallowed error is still traceable.
            except asyncio.CancelledError:
                logger.debug("Creation task cancelled during delete")
            except Exception:
                logger.debug("Creation task failed during delete", exc_info=True)

        if record is not None and record.instance is not None:
            try:
                await record.instance.shutdown()
            except Exception:
                logger.exception("Instance shutdown failed during delete")

    async def replace_database(
        self,
        *,
        new_db: dict[str, Any],
        skill_registry: SkillRegistry,
    ) -> None:
        """Atomically replace the active skill's db.json and reset the simulation.

        Raises:
            SimulationNotFoundError: no simulation declared
            SimulationNotReadyError: simulation not yet READY
            SimulationBusyError: tool calls are in flight (queue_depth > 0)
            DatabaseValidationError: new_db does not validate against schema.json
        """
        async with self._lifecycle_lock:
            record = self._record
            if record is None:
                raise SimulationNotFoundError("No simulation found")
            if record.status != SimulationStatus.READY or record.instance is None:
                raise SimulationNotReadyError(
                    name=record.name, status=record.status.value
                )

            session_state = record.instance.get_session_state()
            if session_state.queue_depth > 0:
                raise SimulationBusyError(queue_depth=session_state.queue_depth)

            skill_registry.write_db(record.name, new_db)

            await record.instance.reset_session()


# Made with Bob
