"""Merge stage-1a data model + stage-1b semantics into the IR."""

from __future__ import annotations

import collections

from simulation_harness.skills.generation.ir import (
    Entity,
    Operation,
    OperationEvidence,
    OperationKind,
    SpecModel,
    StoreMetadata,
)
from simulation_harness.skills.generation.stages.analyze.enrich import (
    structural_entities,
)
from simulation_harness.skills.generation.stages.analyze.extract import DataModel
from simulation_harness.skills.generation.stages.analyze.identity import IdentityModel
from simulation_harness.utils.logging import get_logger

logger = get_logger(__name__)


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


def compose_data_model(
    api_name: str,
    identity: IdentityModel,
    enriched: list[Entity],
    fallback: DataModel | None,
) -> tuple[DataModel, dict[str, str]]:
    """Assemble the final data model from its three sources.

    ``store_metadata`` is built **here**, from the derived identity plus any
    surviving fallback entities — never from an LLM payload. That is the whole
    point of this work: the collection list and pk map are the runtime contract
    ``state/loader.py`` reads back, so they must be a function of the spec.

    A derived entity always wins a collection collision. Returns the model and
    the provenance map recording which path each entity came from.
    """
    by_name = {e.name: e for e in enriched}
    # An enrichment that degraded to nothing still has a contract to honour.
    entities = [
        by_name.get(d.name) or s
        for d, s in zip(identity.entities, structural_entities(identity), strict=True)
    ]
    provenance = {e.name: "derived" for e in entities}
    reserved = set(identity.collections)
    declined: list[str] = []
    extras: list[Entity] = []
    if fallback is not None:
        declined = list(fallback.declined)
        for entity in fallback.entities:
            if entity.collection in reserved:
                logger.warning(
                    "dropping fallback entity '%s': collection '%s' is already "
                    "modeled deterministically",
                    entity.name,
                    entity.collection,
                )
                continue
            reserved.add(entity.collection)
            extras.append(entity)
            provenance[entity.name] = "llm"
    merged = sorted(entities + extras, key=lambda e: e.name)
    return (
        DataModel(
            api_name=api_name,
            entities=merged,
            store_metadata=StoreMetadata(
                collections=[e.collection for e in merged],
                pk_map={e.collection: e.primary_key for e in merged},
            ),
            declined=declined,
        ),
        provenance,
    )
