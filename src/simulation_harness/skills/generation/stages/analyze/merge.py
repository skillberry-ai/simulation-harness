"""Merge stage-1a data model + stage-1b semantics into the IR."""

from __future__ import annotations

import collections

from simulation_harness.skills.generation.ir import (
    Operation,
    OperationEvidence,
    OperationKind,
    SpecModel,
)
from simulation_harness.skills.generation.stages.analyze.extract import DataModel


def validate_coverage(stubs: list[dict], semantics: list[dict]) -> list[str]:
    expected = {s["operation_id"] for s in stubs}
    seen = [
        r["operation_id"]
        for r in semantics
        if isinstance(r, dict) and "operation_id" in r
    ]
    counts = collections.Counter(seen)
    errors: list[str] = []
    missing = expected - set(seen)
    if missing:
        errors.append(f"unclassified operations: {sorted(missing)}")
    invented = set(seen) - expected
    if invented:
        errors.append(f"classified unknown operations: {sorted(invented)}")
    dups = sorted(oid for oid, c in counts.items() if c > 1)
    if dups:
        errors.append(f"operations classified more than once: {dups}")
    return errors


def build_spec_model(
    slug: str,
    stubs: list[dict],
    dm: DataModel,
    semantics: list[dict],
    evidence: dict[str, OperationEvidence] | None = None,
) -> SpecModel:
    sem_by_id = {r["operation_id"]: r for r in semantics}
    operations = [
        Operation(
            operation_id=stub["operation_id"],
            method=stub["method"],
            path=stub["path"],
            tag=stub["tag"],
            summary=stub["summary"],
            entity=sem_by_id[stub["operation_id"]].get("entity"),
            kind=OperationKind(sem_by_id[stub["operation_id"]]["kind"]),
            patterns=sem_by_id[stub["operation_id"]].get("patterns", []),
        )
        for stub in stubs
    ]
    return SpecModel(
        api_name=dm.api_name,
        slug=slug,
        entities=dm.entities,
        operations=operations,
        store_metadata=dm.store_metadata,
        evidence=evidence or {},
    )
