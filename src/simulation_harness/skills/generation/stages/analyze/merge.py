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

    That guarantee is structural, not incidental: for every derived entity, its
    ``name``/``collection``/``primary_key`` are pinned straight from ``identity``
    regardless of what ``enriched`` supplies for that name. Only the soft
    content — ``fields``, ``relationships``, ``fingerprint_fields``,
    ``temporal_fields`` — is taken from the enriched entity (falling back to the
    structural floor when there is no match). ``enrich_entities`` already
    re-asserts this same contract via ``validate_enrichment`` before compose
    ever runs; the pin here is defense-in-depth for a caller that bypasses that
    check, not the primary enforcement point — a mismatch is logged, not
    raised, since compose has no repair channel to feed a correction back into.

    A derived entity always wins a collection collision. Returns the model and
    the provenance map recording which path each entity came from.
    """
    by_name = {e.name: e for e in enriched}
    entities: list[Entity] = []
    # An enrichment that degraded to nothing still has a contract to honour.
    for d, s in zip(identity.entities, structural_entities(identity), strict=True):
        e = by_name.get(d.name)
        if e is None:
            entities.append(s)
            continue
        if e.collection != d.collection or e.primary_key != d.primary_key:
            logger.warning(
                "enriched entity '%s' returned collection=%r primary_key=%r; "
                "pinning to the derived contract collection=%r primary_key=%r",
                d.name,
                e.collection,
                e.primary_key,
                d.collection,
                d.primary_key,
            )
        entities.append(
            e.model_copy(
                update={
                    "name": d.name,
                    "collection": d.collection,
                    "primary_key": d.primary_key,
                }
            )
        )
    provenance = {e.name: "derived" for e in entities}
    # Normalized (casefolded, stripped) so a case- or whitespace-variant
    # collection name is still caught as the same collision an exact match
    # would be — aligned with validate_data_model's guard in extract.py, which
    # must not be the weaker of the two.
    reserved = {c.strip().casefold() for c in identity.collections}
    # Same normalization for entity *names*. Without this a fallback entity
    # that reuses a derived entity's name overwrites its "derived" provenance
    # record with "llm" and produces two same-named entities in the IR — the
    # collection guard alone doesn't catch that, since the fallback entity can
    # sit in a distinct collection. Dropping (not raising) mirrors the
    # collection guard: a name clash is a correct reason to discard the extra
    # entity, not to fail generation.
    reserved_names = {e.name.strip().casefold() for e in entities}
    declined: list[str] = []
    extras: list[Entity] = []
    if fallback is not None:
        declined = list(fallback.declined)
        for entity in fallback.entities:
            if entity.name.strip().casefold() in reserved_names:
                logger.warning(
                    "dropping fallback entity '%s': name is already modeled "
                    "deterministically or by an earlier fallback entity",
                    entity.name,
                )
                continue
            if entity.collection.strip().casefold() in reserved:
                logger.warning(
                    "dropping fallback entity '%s': collection '%s' is already "
                    "modeled deterministically",
                    entity.name,
                    entity.collection,
                )
                continue
            reserved.add(entity.collection.strip().casefold())
            reserved_names.add(entity.name.strip().casefold())
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
