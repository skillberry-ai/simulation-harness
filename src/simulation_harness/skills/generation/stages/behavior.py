"""Stage: global behavior/realism guidance (numeric ranges + derivation rules).

Runs once over the whole IR and emits the single source-of-truth section for how
the simulator computes and keeps numeric fields consistent. Per-operation
sections defer to this. Non-fatal in the pipeline: on failure the preamble falls
back to its static invariants.
"""

from __future__ import annotations

import json
import re

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


# An unobservable actor. The behavior stage is handed each operation's
# `description`, which mixes what the endpoint computes with what its caller is
# expected to do, and only the former is computable here.
_ACTOR = r"(?:the agent|the caller|the assistant|the user)"
# An assertion that the endpoint gates on something. On its own this is ordinary
# ("a refund is only allowed up to the paid amount" is a fine numeric rule), which
# is why a violation needs BOTH halves in the same bullet.
_ENFORCEMENT = (
    r"(?:only (?:allowed|permitted|transfer|invoke|be done|be called|be invoked)"
    r"|must be enforced|may only|is allowed when"
    r"|explicitly asks|explicit confirmation|user confirmation)"
)
_CALLER_GATE = re.compile(
    rf"(?=.*\b{_ACTOR}\b)(?=.*{_ENFORCEMENT})", re.IGNORECASE | re.DOTALL
)


def _bullets(section: str) -> list[str]:
    """The section's bullets, each joined back into one string.

    Continuation lines are folded in: a rule hard-wrapped across two lines would
    otherwise hide half of itself from a per-line match, and it is the combination
    of actor and enforcement that identifies the defect.
    """
    bullets: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            bullets.append(stripped[2:].strip())
        elif stripped and bullets:
            bullets[-1] = f"{bullets[-1]} {stripped}"
    return bullets


def caller_gate_violations(section: str) -> list[str]:
    """Rules that gate on a caller obligation this simulator cannot observe.

    Detected in code rather than forbidden in the prompt. The prompt route was
    measured and rejected: adding the rule to ``behavior.md`` cut ``Derivation
    Rules`` by 31% and its numeric rules by 35% across 12 runs per arm while
    removing no caller gates at all, because the defect is rare enough that 42
    trials produced none to remove. A check here costs the output nothing, and
    ``with_repair`` gives the model a chance to fix the rare real case.

    Observed once, in a tau2-airline preamble: "`transfer_to_human_agents` is only
    allowed when the user explicitly asks for a human agent … this eligibility rule
    is deterministic and must be enforced even though no schema field encodes it."
    That is unenforceable — the endpoint cannot see the conversation — and it sat in
    the section the whole skill treats as its single source of truth.
    """
    return [
        f"rule gates on a caller obligation the simulator cannot observe, so it "
        f"cannot be deterministic — omit it rather than restating it as a rule "
        f"(the per-operation sections carry caller expectations): {bullet[:160]!r}"
        for bullet in _bullets(section)
        if _CALLER_GATE.match(bullet)
    ]


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
        errors.extend(caller_gate_violations(section))
        return errors

    return await with_repair(produce, validate, stage="behavior", retries=retries)
