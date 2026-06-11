"""SimulationHost - singleton holder for simulation instances."""

import asyncio
from pathlib import Path
from typing import Optional

from simulation_harness.config.settings import get_config
from simulation_harness.core.simulation_instance import SimulationInstance
from simulation_harness.models.domain import SimulationSpec
from simulation_harness.utils.errors import SimulationAlreadyExistsError


class SimulationHost:
    """Manages at most one SimulationInstance with lifecycle serialization."""

    def __init__(self) -> None:
        """Initialize the simulation host."""
        self._instance: Optional[SimulationInstance] = None
        self._lifecycle_lock = asyncio.Lock()

    async def create_simulation(
        self,
        spec: SimulationSpec,
        skill_dir: Path | None = None,
    ) -> SimulationInstance:
        """Create a new simulation instance.

        Args:
            spec: Simulation specification
            skill_dir: Optional path to skill directory for state store

        Returns:
            Created simulation instance

        Raises:
            SimulationAlreadyExistsError: If a simulation already exists
        """
        async with self._lifecycle_lock:
            if self._instance is not None:
                raise SimulationAlreadyExistsError(
                    "A simulation already exists. Delete it before creating a new one."
                )

            # Get configuration
            config = get_config()

            # Create instance with configuration parameters
            self._instance = SimulationInstance(
                spec=spec,
                max_messages=config.sessions.max_messages,
                idle_timeout_seconds=config.sessions.idle_timeout_seconds,
                max_queue_depth=config.sessions.max_concurrent_queue_depth,
                api_key=config.llm._resolved_api_key,
                model=config.llm.simulation_model,
                temperature=config.llm.temperature,
                max_tokens=config.llm.max_tokens,
                skill_dir=skill_dir,
                agent_recursion_limit=getattr(
                    config.sessions, "agent_recursion_limit", 10
                ),
            )
            return self._instance

    async def get_simulation(self) -> Optional[SimulationInstance]:
        """Get the current simulation instance.

        Returns:
            Current simulation instance or None if no simulation exists
        """
        async with self._lifecycle_lock:
            return self._instance

    async def delete_simulation(self) -> None:
        """Delete the current simulation instance.

        This operation is idempotent - calling it when no simulation exists is safe.
        """
        async with self._lifecycle_lock:
            if self._instance is not None:
                await self._instance.shutdown()
                self._instance = None


# Made with Bob
