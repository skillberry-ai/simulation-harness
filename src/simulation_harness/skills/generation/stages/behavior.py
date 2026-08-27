"""Stage: global behavior/realism guidance (numeric ranges + derivation rules).

Runs once over the whole IR and emits the single source-of-truth section for how
the simulator computes and keeps numeric fields consistent. Per-operation
sections defer to this. Non-fatal in the pipeline: on failure the preamble falls
back to its static invariants.
"""

from __future__ import annotations

import json

try:
    from importlib.resources import files
except ImportError:  # pragma: no cover
    from importlib_resources import files  # type: ignore[import-not-found, no-redef]

from simulation_harness.skills.generation.ir import SpecModel
from simulation_harness.skills.generation.llm import call_text
from simulation_harness.skills.generation.repair import with_repair
from simulation_harness.skills.generation.stages.schema import entity_summary

REQUIRED_HEADINGS: tuple[str, ...] = (
    "### Numeric Ranges and Ordering",
    "### Derivation Rules",
    "### On-Demand Generation Rules",
)


def _load_prompt() -> str:
    assets = files("simulation_harness.skills.assets")
    return (assets / "generation" / "behavior.md").read_text()


def _ops_summary(ir: SpecModel) -> str:
    records = []
    for op in ir.operations:
        # Numeric relationships are often stated only in prose (a refund amount,
        # a fee). Derivation Rules is the declared single source of truth for
        # numbers, so it needs the description. The map is sparse — a missing key
        # is normal.
        evidence = ir.evidence.get(op.operation_id)
        records.append(
            {
                "operation_id": op.operation_id,
                "kind": op.kind.value,
                "summary": op.summary,
                "description": evidence.description if evidence else None,
                "entity": op.entity,
            }
        )
    return json.dumps(records, indent=2)


async def generate_behavior(ir: SpecModel, llm, *, retries: int) -> str:
    prompt = _load_prompt()
    base_user = (
        f"# API name\n{ir.api_name}\n\n"
        f"# Entities\n```json\n{entity_summary(ir)}\n```\n\n"
        f"# Operations\n```json\n{_ops_summary(ir)}\n```\n"
    )

    async def produce(feedback: list[str] | None) -> str:
        user = base_user + (
            "\n# feedback\n" + "\n".join(feedback) + "\n" if feedback else ""
        )
        return await call_text(llm, prompt, user)

    def validate(section: str) -> list[str]:
        errors = [
            f"missing required subsection heading: '{h}'"
            for h in REQUIRED_HEADINGS
            if h not in section
        ]
        if not section.strip():
            errors.append("behavior section must not be empty")
        return errors

    return await with_repair(produce, validate, stage="behavior", retries=retries)
