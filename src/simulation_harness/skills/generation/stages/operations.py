"""Stage 3: per-operation SKILL.md sections (the fan-out unit)."""

from __future__ import annotations

import json

try:
    from importlib.resources import files
except ImportError:  # pragma: no cover
    from importlib_resources import files  # type: ignore[import-not-found]

from simulation_harness.openapi.parser import OpenAPISpec
from simulation_harness.skills.generation.ir import Operation, SpecModel
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


def _op_context(spec: OpenAPISpec, ir: SpecModel, op: Operation) -> dict:
    parsed = spec.get_operation_by_id(op.operation_id)
    entity = next((e for e in ir.entities if e.name == op.entity), None)
    return {
        "operation_id": op.operation_id,
        "method": op.method,
        "path": op.path,
        "kind": op.kind.value,
        "patterns": op.patterns,
        "entity": entity.model_dump() if entity else None,
        "request_schema": parsed.get_request_schema() if parsed else None,
        "response_schema": parsed.get_response_schema() if parsed else None,
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
