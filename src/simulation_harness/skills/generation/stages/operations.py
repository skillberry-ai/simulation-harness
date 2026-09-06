"""Stage 3: per-operation SKILL.md sections (the fan-out unit)."""

from __future__ import annotations

import json
from typing import Any

try:
    from importlib.resources import files
except ImportError:  # pragma: no cover
    from importlib_resources import files  # type: ignore[import-not-found]

from simulation_harness.openapi.parser import OpenAPISpec
from simulation_harness.skills.generation.ir import Entity, Operation, SpecModel
from simulation_harness.skills.generation.llm import call_text
from simulation_harness.skills.generation.repair import with_repair


def _load_prompt() -> str:
    assets = files("simulation_harness.skills.assets")
    return (assets / "generation" / "operation.md").read_text()


def section_header(op: Operation) -> str:
    return f"### {op.path} {op.method}"


def plan_chunks(ir: SpecModel, *, threshold: int) -> list[list[Operation]]:
    ops = ir.operations
    if len(ops) <= threshold:
        return [[op] for op in ops]
    # group by tag, order-preserving
    groups: dict[str, list[Operation]] = {}
    for op in ops:
        groups.setdefault(op.tag or "", []).append(op)
    chunks: list[list[Operation]] = []
    for group in groups.values():
        for i in range(0, len(group), threshold):
            chunks.append(group[i : i + threshold])
    return chunks


def _resolve_refs(
    spec: OpenAPISpec, schema: Any, _seen: frozenset = frozenset()
) -> Any:
    """Resolve ``$ref`` pointers so the operation prompt sees concrete request /
    response shapes — their own ``required`` arrays and property types — instead
    of an opaque ``{"$ref": ...}``.

    Without this the LLM cannot read (for example) a request body's required
    fields and falls back to the merged entity's ``required`` set, which is
    derived from the response schema — wrongly marking response-only fields as
    required inputs. Mirrors the request-body resolution in ``tool_generator``.
    Recurses into ``properties`` and array ``items``; guards against ref cycles.
    """
    if not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        ref = schema["$ref"]
        if ref in _seen:
            return schema  # cyclic ref: stop unrolling
        resolved = spec.resolve_ref(ref)
        if resolved is None:
            return schema
        return _resolve_refs(spec, resolved, _seen | {ref})
    result: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "properties" and isinstance(value, dict):
            result[key] = {k: _resolve_refs(spec, v, _seen) for k, v in value.items()}
        elif key == "items":
            result[key] = _resolve_refs(spec, value, _seen)
        else:
            result[key] = value
    return result


def _linked_entities(ir: SpecModel, entity: Entity | None) -> list[dict]:
    """The entities this operation's own entity points at through its arrays.

    A ``reference`` element shape says the parent stores identifiers, so both the
    read side and the write side need the target: projecting the response means
    reading it, and creating one of these elements means inserting into it. The
    entity alone is not enough — without this the stage can see that
    ``orders[].items`` holds ``items`` identifiers but not what an ``Item``
    carries, so it cannot say which fields the projection yields.

    ``hop_collections`` is included for the same reason one level further out: a
    response that denormalizes a grandparent attribute onto the element (retail's
    order line carries ``Product.name``) needs that collection too, and naming it
    here is what stops the stage from inventing a field or giving up on the value.

    Scoped to what this operation's entity actually references rather than the
    whole model, to keep a chunk's prompt from carrying the entire data model.
    """
    if entity is None:
        return []
    wanted: list[str] = []
    for field in entity.fields:
        shape = field.element
        if shape is None or shape.kind != "reference":
            continue
        for collection in (shape.target_collection, *shape.hop_collections):
            if collection and collection not in wanted:
                wanted.append(collection)
    by_collection = {e.collection: e for e in ir.entities}
    return [
        by_collection[c].model_dump()
        for c in wanted
        if c in by_collection and by_collection[c] is not entity
    ]


def _op_context(spec: OpenAPISpec, ir: SpecModel, op: Operation) -> dict:
    parsed = spec.get_operation_by_id(op.operation_id)
    entity = next((e for e in ir.entities if e.name == op.entity), None)
    request_schema = parsed.get_request_schema() if parsed else None
    response_schema = parsed.get_success_response_schema() if parsed else None
    # `summary` and `description` are the operation's *intent*. Without them this
    # stage wrote behavioural contracts from shapes alone and emitted the
    # conservative default — which actively contradicted prose-only state
    # changes (#28). `description` comes from the sparse evidence map, so a
    # missing key is normal.
    evidence = ir.evidence.get(op.operation_id)
    return {
        "operation_id": op.operation_id,
        "method": op.method,
        "path": op.path,
        "summary": op.summary,
        "description": evidence.description if evidence else None,
        "kind": op.kind.value,
        "patterns": op.patterns,
        "entity": entity.model_dump() if entity else None,
        # Targets of this entity's reference arrays: needed to project a joined
        # response and to insert on the write side. See _linked_entities.
        "linked_entities": _linked_entities(ir, entity),
        "request_schema": _resolve_refs(spec, request_schema)
        if request_schema
        else None,
        "response_schema": _resolve_refs(spec, response_schema)
        if response_schema
        else None,
        "required_parameters": parsed.get_required_parameters() if parsed else [],
        "optional_parameters": parsed.get_optional_parameters() if parsed else [],
    }


async def generate_section(
    spec: OpenAPISpec, ir: SpecModel, chunk: list[Operation], llm, *, retries: int
) -> str:
    prompt = _load_prompt()
    contexts = [_op_context(spec, ir, op) for op in chunk]
    base_user = (
        f"# Operations to document\n```json\n{json.dumps(contexts, indent=2)}\n```\n"
    )
    required_headers = [section_header(op) for op in chunk]

    async def produce(feedback):
        user = base_user + (
            "\n# feedback\n" + "\n".join(feedback) + "\n" if feedback else ""
        )
        return await call_text(llm, prompt, user)

    def validate(section: str) -> list[str]:
        return [
            f"missing required header line: '{h}'"
            for h in required_headers
            if h not in section
        ]

    return await with_repair(produce, validate, stage="operations", retries=retries)
