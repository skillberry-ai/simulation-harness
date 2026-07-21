"""Stage 4: assemble SKILL.md from the preamble + per-op sections, and validate."""

from __future__ import annotations

try:
    from importlib.resources import files
except ImportError:  # pragma: no cover
    from importlib_resources import files  # type: ignore[import-not-found]

from jinja2 import Template

from simulation_harness.skills.generation.ir import SpecModel
from simulation_harness.skills.generation.naming import _force_skill_name
from simulation_harness.skills.generation.stages.operations import section_header
from simulation_harness.skills.generation.stages.seed import (
    validate_schema_and_db,
)


def _template() -> Template:
    assets = files("simulation_harness.skills.assets")
    return Template((assets / "generation" / "skill_preamble.jinja2").read_text())


def render_preamble(
    ir: SpecModel, scenarios: list[dict], behavior_section: str = ""
) -> str:
    return _template().render(
        slug=ir.slug,
        api_name=ir.api_name,
        collections=ir.store_metadata.collections,
        scenarios=scenarios,
        behavior_section=behavior_section.strip(),
    )


def assemble_skill(ir: SpecModel, preamble: str, sections: list[str]) -> str:
    body = preamble.rstrip() + "\n\n" + "\n\n".join(s.strip() for s in sections) + "\n"
    return _force_skill_name(body, ir.slug)


def validate_bundle(ir: SpecModel, skill_md: str, schema: dict, db: dict) -> list[str]:
    errors: list[str] = []
    for op in ir.operations:
        if section_header(op) not in skill_md:
            errors.append(
                f"SKILL.md missing operation section for '{op.operation_id}' "
                f"({section_header(op)})"
            )
    if f"name: {ir.slug}" not in skill_md:
        errors.append(f"frontmatter name must be '{ir.slug}'")
    errors.extend(validate_schema_and_db(schema, db))
    return errors
