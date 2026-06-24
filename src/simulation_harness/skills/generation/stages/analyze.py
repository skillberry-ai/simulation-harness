"""Stage 1: turn an OpenAPI spec into the IR."""

from __future__ import annotations

import json
import re

try:
    from importlib.resources import files
except ImportError:  # pragma: no cover
    from importlib_resources import files  # type: ignore[import-not-found]

from simulation_harness.openapi.parser import OpenAPISpec
from simulation_harness.skills.generation.ir import (
    Entity,
    Operation,
    OperationKind,
    SpecModel,
    StoreMetadata,
)
from simulation_harness.skills.generation.llm import call_json
from simulation_harness.skills.generation.repair import with_repair

_NON_ALNUM = re.compile(r"[^a-zA-Z0-9]+")


def _load_prompt() -> str:
    assets = files("simulation_harness.skills.assets")
    return (assets / "generation" / "analyze.md").read_text()


def extract_operations(spec: OpenAPISpec) -> list[dict]:
    stubs: list[dict] = []
    for path, item in spec.paths.items():
        if not isinstance(item, dict):
            continue
        for method in ("get", "post", "put", "patch", "delete", "head", "options"):
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            op_id = op.get("operationId") or _NON_ALNUM.sub(
                "_", f"{method}_{path}"
            ).strip("_")
            tags = op.get("tags") or []
            stubs.append(
                {
                    "operation_id": op_id,
                    "method": method.upper(),
                    "path": path,
                    "tag": tags[0] if tags else None,
                    "summary": op.get("summary"),
                }
            )
    return stubs


def _merge(slug: str, stubs: list[dict], enrichment: dict) -> SpecModel:
    semantics = {
        s["operation_id"]: s for s in enrichment.get("operation_semantics", [])
    }
    operations = []
    for stub in stubs:
        sem = semantics.get(stub["operation_id"], {})
        operations.append(
            Operation(
                operation_id=stub["operation_id"],
                method=stub["method"],
                path=stub["path"],
                tag=stub["tag"],
                summary=stub["summary"],
                entity=sem.get("entity"),
                kind=OperationKind(sem.get("kind", "action")),
                patterns=sem.get("patterns", []),
            )
        )
    return SpecModel(
        api_name=enrichment.get("api_name", slug),
        slug=slug,
        entities=[Entity(**e) for e in enrichment.get("entities", [])],
        operations=operations,
        store_metadata=StoreMetadata(**enrichment["store_metadata"]),
    )


class _Invalid:
    """Carries shape errors when enrichment can't be merged into the IR.

    A malformed enrichment payload raises ``pydantic.ValidationError`` inside
    ``_merge``. Rather than crash, ``produce`` catches it and returns this
    sentinel so ``validate`` can report the error and trigger a repair
    iteration. ``_Invalid`` always yields non-empty errors, so it never
    validates clean and the final ``with_repair`` result is always a
    ``SpecModel``.
    """

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors


async def analyze(spec_dict: dict, slug: str, llm, *, retries: int) -> SpecModel:
    spec = OpenAPISpec(spec_dict)
    stubs = extract_operations(spec)
    components = spec_dict.get("components", {}).get("schemas", {})
    prompt = _load_prompt()
    base_user = (
        f"# Operations\n```json\n{json.dumps(stubs, indent=2)}\n```\n\n"
        f"# Component schemas\n```json\n{json.dumps(components, indent=2)}\n```\n"
    )

    async def produce(feedback):
        user = base_user + (
            "\n# feedback\n" + "\n".join(feedback) + "\n" if feedback else ""
        )
        enrichment = await call_json(llm, prompt, user)
        try:
            return _merge(slug, stubs, enrichment)
        except Exception as e:  # malformed enrichment shape
            return _Invalid([f"enrichment shape error: {e}"])

    def validate(artifact):
        if isinstance(artifact, _Invalid):
            return artifact.errors
        return artifact.validate_consistency()

    return await with_repair(produce, validate, stage="analyze", retries=retries)
