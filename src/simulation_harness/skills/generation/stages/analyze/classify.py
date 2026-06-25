"""Stage 1b: classify operation semantics in tag-aware bin-packed batches."""

from __future__ import annotations

import json

try:
    from importlib.resources import files
except ImportError:  # pragma: no cover
    from importlib_resources import files  # type: ignore[import-not-found]

from simulation_harness.skills.generation.ir import OperationKind
from simulation_harness.skills.generation.llm import call_json
from simulation_harness.skills.generation.repair import with_repair

ALLOWED_PATTERNS = {
    "crud", "filter", "string_list", "conditional", "idempotent", "temporal"
}
ALLOWED_KINDS = {k.value for k in OperationKind}


def _load_prompt() -> str:
    assets = files("simulation_harness.skills.assets")
    return (assets / "generation" / "classify.md").read_text()


def plan_classify_batches(stubs: list[dict], *, cap: int) -> list[list[dict]]:
    """Tag-aware first-fit-decreasing bin packing into bins of capacity ``cap``.

    Operations sharing a tag stay in one batch whenever the tag fits under the
    cap. A single tag larger than ``cap`` — and nothing else — is split into
    consecutive sub-batches.
    """
    groups: dict[str, list[dict]] = {}
    for s in stubs:
        groups.setdefault(s.get("tag") or "", []).append(s)

    oversized: list[list[dict]] = []
    packable: list[list[dict]] = []
    for group in groups.values():
        if len(group) > cap:
            for i in range(0, len(group), cap):
                oversized.append(group[i : i + cap])
        else:
            packable.append(group)

    packable.sort(key=len, reverse=True)  # first-fit-decreasing
    packed: list[list[dict]] = []
    for group in packable:
        for b in packed:
            if len(b) + len(group) <= cap:
                b.extend(group)
                break
        else:
            packed.append(list(group))
    return oversized + packed


async def classify_batch(
    stubs: list[dict], entity_names: list[str], llm, *, retries: int
) -> list[dict]:
    prompt = _load_prompt()
    expected = {s["operation_id"] for s in stubs}
    base_user = (
        f"# Known entity names\n```json\n{json.dumps(entity_names)}\n```\n\n"
        f"# Operations to classify\n```json\n{json.dumps(stubs, indent=2)}\n```\n"
    )

    async def produce(feedback):
        user = base_user + (
            "\n# feedback\n" + "\n".join(feedback) + "\n" if feedback else ""
        )
        return await call_json(llm, prompt, user)

    def validate(payload) -> list[str]:
        if not isinstance(payload, list):
            return ["classify payload must be a JSON array of records"]
        errors: list[str] = []
        seen = {r["operation_id"] for r in payload if isinstance(r, dict) and "operation_id" in r}
        missing = expected - seen
        invented = seen - expected
        if missing:
            errors.append(f"missing classifications for: {sorted(missing)}")
        if invented:
            errors.append(f"invented operation_ids not in this batch: {sorted(invented)}")
        for r in payload:
            if not isinstance(r, dict):
                errors.append("each record must be a JSON object")
                continue
            oid = r.get("operation_id")
            if r.get("kind") not in ALLOWED_KINDS:
                errors.append(f"op '{oid}': invalid kind '{r.get('kind')}'")
            ent = r.get("entity")
            if ent is not None and ent not in entity_names:
                errors.append(f"op '{oid}': unknown entity '{ent}'")
            pats = r.get("patterns", [])
            if not isinstance(pats, list) or any(p not in ALLOWED_PATTERNS for p in pats):
                errors.append(f"op '{oid}': invalid patterns {pats}")
        return errors

    return await with_repair(produce, validate, stage="classify", retries=retries)
