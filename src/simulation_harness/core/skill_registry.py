"""SkillRegistry - manages skill generation and reuse."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import jsonschema

from simulation_harness.skills.generator import SkillGenerator
from simulation_harness.utils.errors import DatabaseValidationError
from simulation_harness.utils.logging import get_logger

logger = get_logger(__name__)

_REQUIRED_FILES = ("SKILL.md", "schema.json", "db.json", "api.json")
# Keep in sync with `_SUBJECTS` in skills/manifest.py: that list is the
# authority on what the manifest digests, this one on what belongs to a bundle.
_BUNDLE_FILES = (
    "SKILL.md",
    "schema.json",
    "db.json",
    "scenarios.json",
    "api.json",
    "manifest.json",
)
# Bundle files that may legitimately be absent. scenarios.json is written only
# when the scenarios stage produced output; manifest.json exists only for skills
# generated after provenance was introduced. Neither is in _REQUIRED_FILES, so
# neither absence makes a skill incomplete.
_OPTIONAL_BUNDLE_FILES = frozenset({"scenarios.json", "manifest.json"})


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
        progress_cb=None,
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

        # Check if skill is complete (all 4 files exist)
        skill_complete = self.is_complete(simulation_name)

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
            missing_files = self.missing_files(simulation_name)
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
                progress_cb=progress_cb,
            )
            logger.info(f"Skill generated successfully: path={result_path}")
            return result_path

        except Exception as e:
            logger.error(
                f"Skill generation failed: simulation={simulation_name}, error={str(e)}"
            )
            raise

    def _skill_path(self, simulation_name: str, filename: str) -> Path:
        return self.skills_folder / simulation_name / filename

    def read_schema(self, simulation_name: str) -> dict[str, Any]:
        """Read schema.json for a skill. Raises FileNotFoundError if missing."""
        path = self._skill_path(simulation_name, "schema.json")
        if not path.exists():
            raise FileNotFoundError(
                f"schema.json not found for skill '{simulation_name}'"
            )
        return json.loads(path.read_text())

    def read_db(self, simulation_name: str) -> dict[str, Any]:
        """Read db.json for a skill. Raises FileNotFoundError if missing."""
        path = self._skill_path(simulation_name, "db.json")
        if not path.exists():
            raise FileNotFoundError(f"db.json not found for skill '{simulation_name}'")
        return json.loads(path.read_text())

    def read_api(self, simulation_name: str) -> dict[str, Any]:
        """Read api.json (the raw OpenAPI spec) for a skill. Raises FileNotFoundError if missing."""
        path = self._skill_path(simulation_name, "api.json")
        if not path.exists():
            raise FileNotFoundError(f"api.json not found for skill '{simulation_name}'")
        return json.loads(path.read_text())

    def read_bundle(self, simulation_name: str) -> dict[str, str]:
        """Return verbatim contents of all bundle files for a skill.

        Required files (SKILL.md, schema.json, db.json, api.json) must exist;
        scenarios.json and manifest.json are included only when present. Values
        are the exact on-disk text, so writing them back reproduces the files
        byte-for-byte.

        Raises:
            FileNotFoundError: if a required file is missing.
        """
        files: dict[str, str] = {}
        for fname in _BUNDLE_FILES:
            path = self._skill_path(simulation_name, fname)
            if not path.exists():
                if fname in _OPTIONAL_BUNDLE_FILES:
                    continue
                raise FileNotFoundError(
                    f"{fname} not found for skill '{simulation_name}'"
                )
            files[fname] = path.read_text()
        return files

    def missing_files(self, simulation_name: str) -> list[str]:
        """Return the required artifact files that are absent for this skill."""
        skill_dir = self.skills_folder / simulation_name
        return [f for f in _REQUIRED_FILES if not (skill_dir / f).exists()]

    def is_complete(self, simulation_name: str) -> bool:
        """True when all four required artifacts exist for this skill."""
        return not self.missing_files(simulation_name)

    def list_complete_skills(self) -> list[str]:
        """Names of skill directories that contain all four required artifacts."""
        if not self.skills_folder.exists():
            return []
        return [
            d.name
            for d in self.skills_folder.iterdir()
            if d.is_dir() and not d.name.startswith(".") and self.is_complete(d.name)
        ]

    def most_recent_complete_skill(self) -> str | None:
        """The complete skill with the newest SKILL.md mtime, or None if none exist."""
        complete = self.list_complete_skills()
        if not complete:
            return None
        return max(
            complete,
            key=lambda name: (self.skills_folder / name / "SKILL.md").stat().st_mtime,
        )

    def write_db(self, simulation_name: str, db: dict[str, Any]) -> None:
        """Validate db against the skill's schema.json, then atomically replace db.json.

        Raises:
            FileNotFoundError: if schema.json is missing for this skill.
            DatabaseValidationError: if db does not validate against the schema.
        """
        schema = self.read_schema(simulation_name)  # raises FileNotFoundError

        try:
            jsonschema.validate(instance=db, schema=schema)
        except jsonschema.ValidationError as e:
            json_path = ".".join(str(p) for p in e.absolute_path) or "<root>"
            raise DatabaseValidationError(message=e.message, json_path=json_path) from e
        except jsonschema.SchemaError as e:
            raise DatabaseValidationError(
                message=f"schema is not a valid JSON Schema: {e.message}"
            ) from e

        target = self._skill_path(simulation_name, "db.json")
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(db, indent=2))
        os.replace(tmp, target)


# Made with Bob
