"""FastAPI dependency injection for simulation management."""

from pathlib import Path
from typing import Annotated

from fastapi import Depends

from simulation_harness.config.settings import get_config, get_secrets
from simulation_harness.core.simulation_host import SimulationHost
from simulation_harness.core.skill_registry import SkillRegistry
from simulation_harness.skills.generator import SkillGenerator


# Global instances (singleton pattern)
_simulation_host: SimulationHost | None = None
_skill_registry: SkillRegistry | None = None


def get_simulation_host() -> SimulationHost:
    """Get or create the global SimulationHost instance.

    Returns:
        SimulationHost instance
    """
    global _simulation_host
    if _simulation_host is None:
        _simulation_host = SimulationHost()
    return _simulation_host


def get_skill_registry() -> SkillRegistry:
    """Get or create the global SkillRegistry instance.

    Requires configuration and secrets to be loaded via load_config() and
    load_secrets() before first call.
    """
    global _skill_registry
    if _skill_registry is None:
        config = get_config()
        secrets = get_secrets()
        generator = SkillGenerator(
            api_key=secrets.llm_api_key,
            model=config.llm.skill_generation_model,
            max_tokens=config.llm.skill_generation_max_tokens,
            base_url=secrets.llm_api_base,
            generation_config=config.generation,
        )
        _skill_registry = SkillRegistry(
            skills_folder=Path(config.skills.folder),
            generator=generator,
        )
    return _skill_registry


def reset_skill_registry() -> None:
    """Clear the cached SkillRegistry so the next call rebuilds it with current credentials."""
    global _skill_registry
    _skill_registry = None


# Type aliases for dependency injection
SimulationHostDep = Annotated[SimulationHost, Depends(get_simulation_host)]
SkillRegistryDep = Annotated[SkillRegistry, Depends(get_skill_registry)]


# Made with Bob
