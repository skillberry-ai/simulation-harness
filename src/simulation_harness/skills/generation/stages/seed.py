"""Stage: design scenario-aware db.json from the IR + schema."""

from __future__ import annotations

import json

import jsonschema

try:
    from importlib.resources import files
except ImportError:  # pragma: no cover
    from importlib_resources import files  # type: ignore[import-not-found]

from simulation_harness.skills.generation.ir import SpecModel
from simulation_harness.skills.generation.llm import call_json
from simulation_harness.skills.generation.repair import with_repair
from simulation_harness.skills.generation.stages.schema import entity_summary


def _load_prompt() -> str:
    assets = files("simulation_harness.skills.assets")
    return (assets / "generation" / "seed.md").read_text()


def validate_schema_and_db(schema: dict, db: dict) -> list[str]:
    errors: list[str] = []
    try:
        jsonschema.validators.Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError as e:
        return [f"schema.json is not a valid JSON Schema: {e.message}"]
    try:
        jsonschema.validate(instance=db, schema=schema)
    except jsonschema.ValidationError as e:
        path = ".".join(str(p) for p in e.absolute_path) or "<root>"
        errors.append(f"db.json invalid at {path}: {e.message}")
    return errors


async def generate_seed(
    ir: SpecModel, schema: dict, scenarios: list[dict], llm, *, retries: int
) -> dict:
    prompt = _load_prompt()
    blocks = [
        f"# Entities\n```json\n{entity_summary(ir)}\n```\n",
        f"# store_metadata\n```json\n{ir.store_metadata.model_dump_json(indent=2)}\n```\n",
        f"# schema_json\n```json\n{json.dumps(schema, indent=2)}\n```\n",
    ]
    if scenarios:
        blocks.append(f"# scenarios\n```json\n{json.dumps(scenarios, indent=2)}\n```\n")
    base_user = "\n".join(blocks)

    async def produce(feedback):
        user = base_user + (
            "\n# feedback\n" + "\n".join(feedback) + "\n" if feedback else ""
        )
        payload = await call_json(llm, prompt, user)
        if not isinstance(payload, dict):
            return {"_shape_error": "not an object"}
        return payload

    def validate(payload: dict) -> list[str]:
        if "_shape_error" in payload:
            return [payload["_shape_error"]]
        if "db_json" not in payload:
            return ["payload must contain 'db_json'"]
        if not isinstance(payload["db_json"], dict):
            return ["'db_json' must be an object"]
        return validate_schema_and_db(schema, payload["db_json"])

    payload = await with_repair(produce, validate, stage="seed", retries=retries)
    return payload["db_json"]
