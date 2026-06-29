"""Stage: design schema.json from the IR."""

from __future__ import annotations

import json

import jsonschema
from jsonschema.validators import Draft202012Validator

try:
    from importlib.resources import files
except ImportError:  # pragma: no cover
    from importlib_resources import files  # type: ignore[import-not-found]

from simulation_harness.skills.generation.ir import SpecModel
from simulation_harness.skills.generation.llm import call_json
from simulation_harness.skills.generation.repair import with_repair


def _load_prompt() -> str:
    assets = files("simulation_harness.skills.assets")
    return (assets / "generation" / "schema.md").read_text()


def entity_summary(ir: SpecModel) -> str:
    return json.dumps([e.model_dump() for e in ir.entities], indent=2)


def validate_schema(schema: dict) -> list[str]:
    try:
        Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError as e:
        return [f"schema.json is not a valid JSON Schema: {e.message}"]
    return []


async def generate_schema(ir: SpecModel, llm, *, retries: int) -> dict:
    prompt = _load_prompt()
    base_user = (
        f"# Entities\n```json\n{entity_summary(ir)}\n```\n\n"
        f"# store_metadata\n```json\n{ir.store_metadata.model_dump_json(indent=2)}\n```\n"
    )

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
        if "schema_json" not in payload:
            return ["payload must contain 'schema_json'"]
        if not isinstance(payload["schema_json"], dict):
            return ["'schema_json' must be an object"]
        return validate_schema(payload["schema_json"])

    payload = await with_repair(produce, validate, stage="schema", retries=retries)
    return payload["schema_json"]
