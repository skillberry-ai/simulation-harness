"""Skill generator - delegates to the multi-step generation pipeline."""

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import SecretStr

from simulation_harness import __version__
from simulation_harness.config.models import GenerationConfig
from simulation_harness.skills.generation import run_pipeline
from simulation_harness.skills.generation.repair import StageTimeoutError
from simulation_harness.skills.manifest import MANIFEST_FILENAME, build_manifest

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
        base_url: str | None = None,
        generation_config: GenerationConfig | None = None,
    ) -> None:
        """Initialize the skill generator.

        Args:
            api_key: LLM API key (wrapped in SecretStr).
            model: Model to use for generation.
            base_url: Optional base URL for API.
            generation_config: Multi-step pipeline tuning (defaults applied).

        Per-call temperature and output-token limits are not set here: the
        pipeline reads them per stage from ``generation_config``, so a single
        generator-wide value would have no effect.
        """
        self.api_key = api_key
        self.model = model
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
        5. Write manifest.json last, digesting the artifacts above off disk
        6. Atomic rename: temp dir → <skills_folder>/<name>/
        7. On failure: clean up temp dir

        Args:
            openapi_spec: OpenAPI specification dictionary
            simulation_name: Name for the simulation
            skills_folder: Directory to create skill in
            progress_cb: Optional callable invoked with phase strings.

        Returns:
            Path to the generated SKILL.md file

        Raises:
            StageTimeoutError: If a generation stage exceeds its per-stage
                timeout (propagated unwrapped so the cause is preserved).
            RuntimeError: If skill generation otherwise fails (wraps the
                original exception via ``__cause__``).
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
            # Last write: build_manifest digests its siblings off disk, so every
            # other artifact must already exist. Being inside this try block
            # means a failure here removes the whole temp dir — a published
            # bundle is never half-described.
            manifest = build_manifest(
                temp_dir,
                skill_name=simulation_name,
                openapi_spec=openapi_spec,
                model=self.model,
                harness_version=__version__,
                generated_at=datetime.now(timezone.utc),
            )
            (temp_dir / MANIFEST_FILENAME).write_text(json.dumps(manifest, indent=2))
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
            # Preserve the stage-timeout signal — flattening it into a generic
            # RuntimeError would erase which stage stalled and prevent the
            # creator from classifying it as a timeout (see issue #19).
            if isinstance(e, StageTimeoutError):
                raise
            raise RuntimeError(
                f"Skill generation failed for '{simulation_name}'"
            ) from e
