"""Skill generator - delegates to the multi-step generation pipeline."""

import json
import shutil
import uuid
from pathlib import Path

from pydantic import SecretStr

from simulation_harness.config.models import GenerationConfig
from simulation_harness.skills.generation import run_pipeline

# Backward-compat re-export: these moved to skills.generation.naming, but
# tests/unit/skills/test_generator.py imports them from this module.
from simulation_harness.skills.generation.naming import (  # noqa: F401
    _FRONTMATTER_RE,
    _NAME_LINE_RE,
    _force_skill_name,
)


class SkillGenerator:
    """Generate simulation skill files from OpenAPI specifications."""

    def __init__(
        self,
        api_key: SecretStr,
        model: str = "gpt-4",
        temperature: float = 0.0,
        max_tokens: int = 20000,
        base_url: str | None = None,
        generation_config: GenerationConfig | None = None,
    ) -> None:
        """Initialize the skill generator.

        Args:
            api_key: LLM API key (wrapped in SecretStr).
            model: Model to use for generation.
            temperature: Temperature for response generation.
            max_tokens: Maximum tokens in response.
            base_url: Optional base URL for API.
            generation_config: Multi-step pipeline tuning (defaults applied).
        """
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.base_url = base_url
        self.generation_config = generation_config or GenerationConfig()

    async def generate_skill(
        self,
        openapi_spec: dict,
        simulation_name: str,
        skills_folder: Path,
        *,
        progress_cb=None,
    ) -> Path:
        """Generate a skill from an OpenAPI specification.

        Delegates content generation to the multi-step pipeline, then writes
        artifacts via the atomic temp-dir → rename pattern:
        1. Create temp dir: <skills_folder>/.<name>.tmp-<uuid>/
        2. Run the generation pipeline → SkillBundle
        3. Write SKILL.md, schema.json, db.json, api.json to temp dir
        4. Write scenarios.json to temp dir (if bundle.scenarios is non-empty)
        5. Atomic rename: temp dir → <skills_folder>/<name>/
        6. On failure: clean up temp dir

        Args:
            openapi_spec: OpenAPI specification dictionary
            simulation_name: Name for the simulation
            skills_folder: Directory to create skill in
            progress_cb: Optional callable invoked with phase strings.

        Returns:
            Path to the generated SKILL.md file

        Raises:
            RuntimeError: If skill generation fails (wraps original exception)
        """
        temp_dir = skills_folder / f".{simulation_name}.tmp-{uuid.uuid4().hex[:8]}"
        final_dir = skills_folder / simulation_name
        skill_file = final_dir / "SKILL.md"
        try:
            temp_dir.mkdir(parents=True, exist_ok=True)
            bundle = await run_pipeline(
                openapi_spec,
                simulation_name,
                api_key=self.api_key,
                base_url=self.base_url,
                gen_config=self.generation_config,
                model=self.model,
                progress_cb=progress_cb,
            )
            (temp_dir / "SKILL.md").write_text(bundle.skill_md)
            (temp_dir / "schema.json").write_text(json.dumps(bundle.schema, indent=2))
            (temp_dir / "db.json").write_text(json.dumps(bundle.db, indent=2))
            if bundle.scenarios:
                (temp_dir / "scenarios.json").write_text(
                    json.dumps(bundle.scenarios, indent=2)
                )
            (temp_dir / "api.json").write_text(json.dumps(openapi_spec, indent=2))
            try:
                temp_dir.rename(final_dir)
            except (FileExistsError, OSError):
                if final_dir.exists():
                    shutil.rmtree(final_dir)
                temp_dir.rename(final_dir)
            return skill_file
        except Exception as e:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            raise RuntimeError(
                f"Skill generation failed for '{simulation_name}'"
            ) from e
