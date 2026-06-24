"""Stage 2: design schema.json + db.json from the IR."""

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
    return (assets / "generation" / "schema_seed.md").read_text()


def validate_schema_and_db(schema: dict, db: dict) -> list[str]:
    errors: list[str] = []
    try:
        Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError as e:
        return [f"schema.json is not a valid JSON Schema: {e.message}"]
    try:
        jsonschema.validate(instance=db, schema=schema)
    except jsonschema.ValidationError as e:
        path = ".".join(str(p) for p in e.absolute_path) or "<root>"
        errors.append(f"db.json invalid at {path}: {e.message}")
    return errors


def _entity_summary(ir: SpecModel) -> str:
    return json.dumps([e.model_dump() for e in ir.entities], indent=2)


async def generate_schema_and_seed(
    ir: SpecModel, llm, *, retries: int
) -> tuple[dict, dict]:
    prompt = _load_prompt()
    base_user = (
        f"# Entities\n```json\n{_entity_summary(ir)}\n```\n\n"
        f"# store_metadata\n```json\n{ir.store_metadata.model_dump_json(indent=2)}\n```\n"
    )

    async def produce(feedback):
        user = base_user + (
            "\n# feedback\n" + "\n".join(feedback) + "\n" if feedback else ""
        )
        payload = await call_json(llm, prompt, user)
        if not isinstance(payload, dict):
            return {"schema_json": {}, "db_json": {}, "_shape_error": "not an object"}
        return payload

    def validate(payload: dict) -> list[str]:
        if "_shape_error" in payload:
            return [payload["_shape_error"]]
        if "schema_json" not in payload or "db_json" not in payload:
            return ["payload must contain 'schema_json' and 'db_json'"]
        if not isinstance(payload["schema_json"], dict) or not isinstance(
            payload["db_json"], dict
        ):
            return ["'schema_json' and 'db_json' must both be objects"]
        return validate_schema_and_db(payload["schema_json"], payload["db_json"])

    payload = await with_repair(produce, validate, stage="schema_seed", retries=retries)
    return payload["schema_json"], payload["db_json"]
