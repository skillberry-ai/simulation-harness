"""Stage: design schema.json from the IR."""

from __future__ import annotations

import json

import jsonschema
from jsonschema.validators import Draft202012Validator

try:
    from importlib.resources import files
except ImportError:  # pragma: no cover
    from importlib_resources import files  # type: ignore[import-not-found]

from simulation_harness.skills.generation.ir import (
    ElementField,
    ElementShape,
    Entity,
    SpecModel,
)
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
    this module accepts is one the loader can read. Every level is
    isinstance-guarded rather than assumed to be a dict: this runs on schemas
    an LLM produced, before (or without) ``validate_schema`` having accepted
    their shape, so ``properties`` or ``$defs`` being a string or a list (not
    just missing) has to fail closed instead of raising.
    """
    if not isinstance(schema, dict):
        return None, None
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return None, None
    prop = properties.get(collection)
    if not isinstance(prop, dict):
        return None, None
    items = prop.get("items")
    ref = items.get("$ref") if isinstance(items, dict) else None
    if not isinstance(ref, str) or not ref.startswith("#/$defs/"):
        return None, None
    def_name = ref.split("/")[-1]
    defs = schema.get("$defs")
    entity_def = defs.get(def_name) if isinstance(defs, dict) else None
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
    # `True`/`False` are valid Draft 2020-12 schemas (check_schema above passed
    # them), but there is nothing further to compare against the IR.
    if not isinstance(schema, dict):
        return ["schema.json must be a JSON object to check against store_metadata"]
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return [
            "schema.json's top-level 'properties' must be an object mapping "
            "collection names to their array schemas"
        ]
    errors: list[str] = []
    expected = set(ir.store_metadata.collections)
    present = set(properties)
    for missing in sorted(expected - present):
        errors.append(f"schema.json is missing a property for collection '{missing}'")
    for extra in sorted(present - expected):
        errors.append(
            f"schema.json declares collection '{extra}', which is not in "
            f"store_metadata.collections"
        )
    # Collections sharing a $def with different derived primary keys: only one
    # of the pk_map entries can win when enforce_contract stamps the $def, so
    # this has to be rejected rather than forced. Same pk is harmless — don't
    # reject that, or with_repair asks the LLM to fix something it can't.
    def_collections: dict[str, list[str]] = {}
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
        pk_prop = (entity_def.get("properties") or {}).get(pk) if pk else None
        if isinstance(pk_prop, dict) and (
            pk_prop.get("type") in ("array", "object")
            or isinstance(pk_prop.get("items"), dict)
            or isinstance(pk_prop.get("properties"), dict)
        ):
            errors.append(
                f"$defs/{def_name} declares primary key '{pk}' for collection "
                f"'{collection}', but that property is not scalar. The runtime keys "
                f"rows by str(pk_value), so a list- or object-valued key silently "
                f"becomes a stringified value."
            )
        def_collections.setdefault(def_name, []).append(collection)
    for def_name, collections in def_collections.items():
        pks = {ir.store_metadata.pk_map.get(c) for c in collections}
        if len(pks) > 1:
            errors.append(
                f"$defs/{def_name} is shared by collections {sorted(collections)} "
                f"whose derived primary keys differ ({sorted(p for p in pks if p)}); "
                f"each needs its own $def, or the primary keys must match"
            )
    return errors


def _object_element(fields: tuple[ElementField, ...]) -> dict:
    """An object subschema for the element, with `required` where declared.

    `required` is what turns a type check into a shape check. Without it a seeded
    element may omit fields the response promises and still validate — retail's
    `products[].variants` was seeded as a flattened `{color, size, price,
    available}`, matching neither the spec's variant nor the `items` row it
    duplicates, and passed. `additionalProperties` stays open: an element may carry
    storage bookkeeping no response declares, and unlike a top-level entity there
    is no union across sources to make closing it safe.
    """
    subschema: dict = {
        "type": "object",
        "properties": {f.name: {"type": f.type} for f in fields},
    }
    required = [f.name for f in fields if f.required]
    if required:
        subschema["required"] = required
    return subschema


def _element_items(shape: ElementShape) -> dict | None:
    """The ``items`` subschema for one derived element shape, or ``None``.

    ``additionalProperties`` is deliberately left open on object elements. The
    fix this supports only needs the element's *type* pinned — a bare id string
    where an object is required fails on ``"type"`` alone — and storage may
    legitimately carry bookkeeping fields no response declares, which for a
    nested element there is no union-across-sources to make safe.
    """
    if shape.kind == "scalar":
        return {"type": shape.type} if shape.type else None
    if shape.kind == "embedded":
        return _object_element(shape.fields)
    if shape.kind == "reference":
        if not shape.link_fields:
            # A pure projection of the target: the parent stores identifiers, and
            # a primary key is a string by the schema stage's own contract.
            return {"type": "string"}
        return _object_element(shape.link_fields)
    return None


# Where a container's element subschema belongs, and the declared `type` that has
# to be there for the stamp to apply.
_CONTAINER_KEYWORD = {
    "array": ("items", "array"),
    "map": ("additionalProperties", "object"),
}


def _stamp_element_shapes(entity_def: dict, entity: Entity) -> None:
    """Write each derived element shape onto its container property.

    ``items`` for an array, ``additionalProperties`` for a map. Skips a property
    whose declared type does not match the container the shape was derived from:
    getting that wrong is a pre-existing shape problem for ``validate_schema`` to
    report, and stamping over it would bury the real problem.
    """
    props = entity_def.get("properties")
    if not isinstance(props, dict):
        return
    for field in entity.fields:
        if field.element is None:
            continue
        keyword_type = _CONTAINER_KEYWORD.get(field.element.container)
        if keyword_type is None:
            continue
        keyword, declared = keyword_type
        prop = props.get(field.name)
        if not isinstance(prop, dict) or prop.get("type") != declared:
            continue
        items = _element_items(field.element)
        if items is None:
            continue
        prop[keyword] = items
        element = field.element
        if element.target_collection is not None:
            # Recorded so the operation stage can see which collection an
            # identifier points at; validators ignore `x-` keywords. `field` is
            # present when the element's own key name differs from the target's.
            ref: dict = {
                "collection": element.target_collection,
                "key": element.target_key,
            }
            if element.local_key is not None:
                ref["field"] = element.local_key
            prop["x-element-ref"] = ref


def enforce_contract(schema: dict, ir: SpecModel) -> dict:
    """Stamp the derived contract onto the schema.

    Forced rather than validated because the correct values are known: the
    collection set and pk map were derived from the spec in code, not
    invented by the LLM that wrote ``schema``. Safe to call on a schema that
    hasn't passed :func:`validate_schema` yet — every lookup is
    isinstance-guarded via :func:`_resolve_def`, so a collection or ``$def``
    this can't resolve is left alone rather than raising, and the malformed
    shape falls through to ``validate_schema`` as repair feedback instead of
    an exception escaping the repair loop.

    Stamps three things:
    - Top level: ``required`` is set to exactly ``store_metadata.collections``
      and ``additionalProperties`` to ``False``, so ``db.json``'s collection
      set is checked against the IR too (via ``validate_schema_and_db``, in
      the seed stage's own repair loop) — closing the drift `state/loader.py`
      would otherwise take from ``db.json``'s keys rather than the schema.
    - Per collection: the primary key is written onto the ``$def`` the
      collection's items ``$ref`` resolves to (where the runtime reads it
      from), and added to that ``$def``'s ``required`` list.
    - Per array field with a derived element shape: that field's ``items``. The
      prompt cannot transcribe an element shape it was never given, and until it
      is stamped ``items`` stays ``{}``, which accepts anything — so the seed
      stage is free to populate an array in a shape no other stage agreed to.
      Stamping it makes ``validate_schema_and_db`` reject the mismatch and feed
      it back as repair feedback, with no seed-prompt change at all.
    """
    if isinstance(schema, dict):
        schema["required"] = list(ir.store_metadata.collections)
        schema["additionalProperties"] = False
    entities = {e.collection: e for e in ir.entities}
    for collection, pk in ir.store_metadata.pk_map.items():
        _, entity_def = _resolve_def(schema, collection)
        if entity_def is None:
            continue
        entity_def["x-primary-key"] = pk
        required = entity_def.setdefault("required", [])
        if isinstance(required, list) and pk not in required:
            required.append(pk)
        entity = entities.get(collection)
        if entity is not None:
            _stamp_element_shapes(entity_def, entity)
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
