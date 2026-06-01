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

        A skill is considered complete only when all four files exist:
        - SKILL.md
        - schema.json
        - db.json
        - api.json

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
        schema_file = skill_dir / "schema.json"
        db_file = skill_dir / "db.json"
        api_file = skill_dir / "api.json"

        # Check if skill is complete (all 4 files exist)
        skill_complete = (
            skill_file.exists()
            and schema_file.exists()
            and db_file.exists()
            and api_file.exists()
        )

        if skill_complete and not regenerate:
            # Log warning with human-readable mtime and regeneration reminder
            mtime = datetime.fromtimestamp(skill_file.stat().st_mtime)
            logger.warning(
                f"Reusing existing skill '{simulation_name}' "
                f"(SKILL.md modified: {mtime.isoformat()}). "
                f"If the OpenAPI spec has changed, pass regenerate=true to force regeneration."
            )
            return skill_file

        # Log which files are missing if incomplete
        if not regenerate and skill_dir.exists():
            missing_files = []
            if not skill_file.exists():
                missing_files.append("SKILL.md")
            if not schema_file.exists():
                missing_files.append("schema.json")
            if not db_file.exists():
                missing_files.append("db.json")
            if not api_file.exists():
                missing_files.append("api.json")

            if missing_files:
                logger.warning(
                    f"Skill '{simulation_name}' is incomplete. "
                    f"Missing files: {', '.join(missing_files)}. "
                    f"Regenerating..."
                )

        # Generate new skill
        logger.info(
            f"Generating skill: simulation={simulation_name}, regenerate={regenerate}"
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
                f"Skill generation failed: simulation={simulation_name}, error={str(e)}"
            )
            raise


# Made with Bob
