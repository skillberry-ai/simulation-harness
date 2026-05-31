"""SkillRegistry - manages skill generation and reuse."""

from datetime import datetime
from pathlib import Path
from typing import Any

from simulation_harness.skills.generator import SkillGenerator
from simulation_harness.utils.logging import get_logger

logger = get_logger(__name__)


class SkillRegistry:
    """Manages skill generation and reuse for simulations."""

    def __init__(self, skills_folder: Path, generator: SkillGenerator) -> None:
        """Initialize the skill registry.

        Args:
            skills_folder: Directory where skills are stored
            generator: Skill generator instance
        """
        self.skills_folder = skills_folder
        self.generator = generator

    async def ensure_skill(
        self,
        simulation_name: str,
        openapi_spec: dict[str, Any],
        regenerate: bool = False,
    ) -> Path:
        """Ensure a skill exists for the simulation.

        If the skill already exists and regenerate is False, reuses it.
        Otherwise, generates a new skill.

        Args:
            simulation_name: Name of the simulation
            openapi_spec: OpenAPI specification
            regenerate: Whether to regenerate even if skill exists

        Returns:
            Path to the SKILL.md file

        Raises:
            RuntimeError: If skill generation fails
        """
        skill_dir = self.skills_folder / simulation_name
        skill_file = skill_dir / "SKILL.md"

        # Check if skill exists
        if skill_file.exists() and not regenerate:
            # Log warning with human-readable mtime and regeneration reminder
            mtime = datetime.fromtimestamp(skill_file.stat().st_mtime)
            logger.warning(
                f"Reusing existing skill '{simulation_name}' "
                f"(SKILL.md modified: {mtime.isoformat()}). "
                f"If the OpenAPI spec has changed, pass regenerate=true to force regeneration."
            )
            return skill_file

        # Generate new skill
        logger.info(
            f"Generating skill: simulation={simulation_name}, "
            f"regenerate={regenerate}"
        )

        try:
            result_path = await self.generator.generate_skill(
                openapi_spec=openapi_spec,
                simulation_name=simulation_name,
                skills_folder=self.skills_folder,
            )
            logger.info(f"Skill generated successfully: path={result_path}")
            return result_path

        except Exception as e:
            logger.error(
                f"Skill generation failed: simulation={simulation_name}, "
                f"error={str(e)}"
            )
            raise

# Made with Bob