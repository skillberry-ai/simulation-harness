"""Stage: enumerate representative user scenarios from the IR."""

from __future__ import annotations

import json

try:
    from importlib.resources import files
except ImportError:  # pragma: no cover
    from importlib_resources import files  # type: ignore[import-not-found]

from pydantic import ValidationError

from simulation_harness.skills.generation.ir import Scenario, SpecModel
from simulation_harness.skills.generation.llm import call_json
from simulation_harness.skills.generation.repair import with_repair
from simulation_harness.skills.generation.stages.schema import entity_summary


def _load_prompt() -> str:
    assets = files("simulation_harness.skills.assets")
    return (assets / "generation" / "scenarios.md").read_text()


def _ops_summary(ir: SpecModel) -> str:
    return json.dumps(
        [
            {
                "operation_id": op.operation_id,
                "method": op.method,
                "path": op.path,
                "summary": op.summary,
                "kind": op.kind.value,
                "entity": op.entity,
            }
            for op in ir.operations
        ],
        indent=2,
    )


async def generate_scenarios(
    ir: SpecModel, llm, *, count: int, retries: int
) -> list[Scenario]:
    prompt = _load_prompt()
    valid_ops = {op.operation_id for op in ir.operations}
    base_user = (
        f"# Target count\n{count}\n\n"
        f"# Entities\n```json\n{entity_summary(ir)}\n```\n\n"
        f"# Operations\n```json\n{_ops_summary(ir)}\n```\n"
    )

    async def produce(feedback):
        user = base_user + (
            "\n# feedback\n" + "\n".join(feedback) + "\n" if feedback else ""
        )
        payload = await call_json(llm, prompt, user)
        items = payload.get("scenarios") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            return {"_error": "payload must contain a 'scenarios' array"}
        parsed: list[Scenario] = []
        for item in items:
            try:
                sc = Scenario(**item)
            except (TypeError, ValidationError):
                continue
            sc.operations = [o for o in sc.operations if o in valid_ops]
            parsed.append(sc)
        return parsed

    def validate(result) -> list[str]:
        if isinstance(result, dict) and "_error" in result:
            return [result["_error"]]
        if not result:
            return ["must return at least one valid scenario"]
        return []

    return await with_repair(produce, validate, stage="scenarios", retries=retries)
