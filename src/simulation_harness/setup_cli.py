"""Offline CLI: generate simulation artifacts from an OpenAPI spec (no server)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from simulation_harness.config.env_overrides import apply_env_overrides
from simulation_harness.config.settings import load_config, load_secrets
from simulation_harness.core.skill_registry import SkillRegistry
from simulation_harness.openapi.parser import OpenAPISpec, validate_openapi_dict
from simulation_harness.skills.generation.naming import sanitize_skill_name
from simulation_harness.skills.generator import SkillGenerator
from simulation_harness.utils.errors import OpenAPIValidationError
from simulation_harness.utils.logging import get_logger

logger = get_logger(__name__)


def _load_spec(spec_path: Path) -> dict[str, Any]:
    text = spec_path.read_text()
    if spec_path.suffix.lower() in (".yaml", ".yml"):
        return yaml.safe_load(text)
    return json.loads(text)


async def run_setup(
    *, spec_path: Path, name: str | None, regenerate: bool, config_path: str
) -> Path:
    config = apply_env_overrides(load_config(config_path))
    load_secrets()
    from simulation_harness.config.settings import get_secrets

    secrets = get_secrets()

    spec = _load_spec(spec_path)
    validate_openapi_dict(spec)
    OpenAPISpec(spec)

    simulation_name = sanitize_skill_name(
        name or spec.get("info", {}).get("title", "simulation")
    )

    generator = SkillGenerator(
        api_key=secrets.llm_api_key,
        model=config.llm.skill_generation_model,
        max_tokens=config.llm.skill_generation_max_tokens,
        base_url=secrets.llm_api_base,
        generation_config=config.generation,
    )
    registry = SkillRegistry(
        skills_folder=Path(config.skills.folder), generator=generator
    )
    skill_file = await registry.ensure_skill(
        simulation_name=simulation_name, openapi_spec=spec, regenerate=regenerate
    )
    return skill_file.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m simulation_harness.setup_cli",
        description="Generate simulation artifacts from an OpenAPI spec (offline).",
    )
    parser.add_argument("spec", help="Path to the OpenAPI spec (.json/.yaml)")
    parser.add_argument(
        "--name", default=None, help="Skill name override (defaults to info.title)"
    )
    parser.add_argument(
        "--regenerate",
        action="store_true",
        help="Regenerate even if artifacts exist",
    )
    parser.add_argument(
        "--config", default="config/harness.yaml", help="Path to harness.yaml"
    )
    args = parser.parse_args(argv)

    spec_path = Path(args.spec)
    if not spec_path.exists():
        print(f"ERROR: spec file not found: {spec_path}", file=sys.stderr)
        return 2

    try:
        artifact_dir = asyncio.run(
            run_setup(
                spec_path=spec_path,
                name=args.name,
                regenerate=args.regenerate,
                config_path=args.config,
            )
        )
    except OpenAPIValidationError as e:
        print(f"ERROR: invalid OpenAPI spec: {e}", file=sys.stderr)
        return 3
    except Exception as e:  # generation / config / secrets failure
        print(f"ERROR: setup failed: {e}", file=sys.stderr)
        return 1

    print(str(artifact_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
