"""SimulationHost - singleton holder for simulation instances."""

import asyncio
from pathlib import Path
from typing import Optional

from simulation_harness.config.settings import get_config, get_secrets
from simulation_harness.core.simulation_instance import SimulationInstance
from simulation_harness.mcp_integration.sidecar_server import SidecarMCPServer
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
        mcp_port: int | None = None,
    ) -> SimulationInstance:
        """Create a new simulation instance.

        Args:
            spec: Simulation specification
            skill_dir: Optional path to skill directory for state store
            mcp_port: Optional port to expose simulation as an MCP server

        Returns:
            Created simulation instance

        Raises:
            SimulationAlreadyExistsError: If a simulation already exists
            PortInUseError: If mcp_port is already bound by another process
        """
        async with self._lifecycle_lock:
            if self._instance is not None:
                raise SimulationAlreadyExistsError(
                    "A simulation already exists. Delete it before creating a new one."
                )

            # Get configuration and secrets
            config = get_config()
            secrets = get_secrets()

            # Create instance with configuration parameters
            instance = SimulationInstance(
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
                agent_recursion_limit=getattr(
                    config.sessions, "agent_recursion_limit", 10
                ),
                mcp_port=mcp_port,
            )

            if mcp_port is not None:
                sidecar = SidecarMCPServer(instance, mcp_port, config.mcp)
                try:
                    await sidecar.start()
                except Exception:
                    await instance.shutdown()
                    raise
                instance._sidecar = sidecar

            self._instance = instance
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
