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


def _resolve_def(schema: dict, collection: str) -> tuple[str | None, dict | None]:
    """Follow ``properties[collection].items.$ref`` into ``$defs``.

    Mirrors the resolution ``state/loader.py`` performs at runtime, so a schema
    this module accepts is one the loader can read.
    """
    prop = schema.get("properties", {}).get(collection)
    if not isinstance(prop, dict):
        return None, None
    items = prop.get("items")
    ref = items.get("$ref") if isinstance(items, dict) else None
    if not isinstance(ref, str) or not ref.startswith("#/$defs/"):
        return None, None
    def_name = ref.split("/")[-1]
    entity_def = schema.get("$defs", {}).get(def_name)
    return def_name, entity_def if isinstance(entity_def, dict) else None


def validate_schema(schema: dict, ir: SpecModel | None = None) -> list[str]:
    """Check JSON Schema validity and, when ``ir`` is given, the runtime contract.

    Without ``ir`` this is the original validity-only check, so existing callers
    are unaffected.
    """
    try:
        Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError as e:
        return [f"schema.json is not a valid JSON Schema: {e.message}"]
    if ir is None:
        return []
    errors: list[str] = []
    expected = set(ir.store_metadata.collections)
    present = set(schema.get("properties", {}))
    for missing in sorted(expected - present):
        errors.append(f"schema.json is missing a property for collection '{missing}'")
    for extra in sorted(present - expected):
        errors.append(
            f"schema.json declares collection '{extra}', which is not in "
            f"store_metadata.collections"
        )
    for collection in sorted(expected & present):
        def_name, entity_def = _resolve_def(schema, collection)
        if def_name is None:
            errors.append(
                f"collection '{collection}' must be an array whose items are a "
                f"'$ref' into '#/$defs/' — the runtime reads the primary key "
                f"from the referenced $def"
            )
            continue
        if entity_def is None:
            errors.append(
                f"collection '{collection}' references '#/$defs/{def_name}', "
                f"which is not defined"
            )
            continue
        pk = ir.store_metadata.pk_map.get(collection)
        if pk and pk not in (entity_def.get("properties") or {}):
            errors.append(
                f"$defs/{def_name} must declare the primary-key property "
                f"'{pk}' for collection '{collection}'"
            )
    return errors


def enforce_contract(schema: dict, ir: SpecModel) -> dict:
    """Stamp the derived primary keys onto the schema's ``$defs``.

    Forced rather than validated because the correct value is known: the pk map
    was derived from the spec in code. The runtime resolves the pk through
    ``properties[collection].items.$ref`` into ``$defs``, so that is where the
    annotation has to land. Assumes :func:`validate_schema` has already accepted
    the shape.
    """
    for collection, pk in ir.store_metadata.pk_map.items():
        _, entity_def = _resolve_def(schema, collection)
        if entity_def is None:
            continue
        entity_def["x-primary-key"] = pk
        required = entity_def.setdefault("required", [])
        if isinstance(required, list) and pk not in required:
            required.append(pk)
    return schema


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
        # Force what's known (the primary key) before rejecting what isn't (a
        # wrong collection set or a missing $ref) — no point re-prompting the
        # LLM about something we can simply fix.
        enforce_contract(payload["schema_json"], ir)
        return validate_schema(payload["schema_json"], ir)

    payload = await with_repair(produce, validate, stage="schema", retries=retries)
    return payload["schema_json"]
