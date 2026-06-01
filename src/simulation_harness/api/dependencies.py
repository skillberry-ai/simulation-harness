"""FastAPI dependency injection for simulation management."""

import os
from pathlib import Path
from typing import Annotated

from fastapi import Depends

from simulation_harness.config.settings import get_config
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

    Uses configuration from the loaded config file. If config is not loaded,
    falls back to environment variables for backward compatibility:
    - SKILLS_FOLDER
    - OPENAI_API_KEY
    - SKILL_GENERATOR_MODEL
    - OPENAI_API_BASE

    Returns:
        SkillRegistry instance
    """
    global _skill_registry
    if _skill_registry is None:
        # Try to get configuration from loaded config
        try:
            config = get_config()
            skills_folder = Path(config.skills.folder)
            api_key = config.llm.api_key or "dummy-key"
            model = config.llm.skill_generation_model
            base_url = config.llm.api_base
        except RuntimeError:
            # Fallback to environment variables if config not loaded
            skills_folder = Path(os.getenv("SKILLS_FOLDER", "./skills"))
            api_key = os.getenv("OPENAI_API_KEY", "dummy-key")
            model = os.getenv("SKILL_GENERATOR_MODEL", "gpt-4")
            base_url = os.getenv("OPENAI_API_BASE")

        generator = SkillGenerator(
            api_key=api_key,
            model=model,
            base_url=base_url,
        )
        _skill_registry = SkillRegistry(
            skills_folder=skills_folder,
            generator=generator,
        )
    return _skill_registry


# Type aliases for dependency injection
SimulationHostDep = Annotated[SimulationHost, Depends(get_simulation_host)]
SkillRegistryDep = Annotated[SkillRegistry, Depends(get_skill_registry)]


# Made with Bob
