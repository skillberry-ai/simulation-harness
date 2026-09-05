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


def _key(value: str) -> str:
    """Collision key for a collection or entity name.

    Casefolded and stripped so a case- or whitespace-variant (``"Reservations"``,
    ``" reservations"``) collides the same way an exact match does. Otherwise the
    variant slips through as a near-duplicate that appears on some runs and not
    others — the run-to-run drift this work exists to remove.
    """
    return value.strip().casefold()


def _surviving_fallback_entities(
    candidates: list[Entity],
    derived_collections: set[str],
    derived_names: set[str],
) -> list[Entity]:
    """The fallback entities that keep their place, colliding groups dropped whole.

    Two collision rules, different on purpose:

    * Against the **derived** set, the derived entity wins and the fallback one
      is dropped. The rule's contract is authoritative and its provenance record
      must not be overwritten with ``"llm"``.
    * Against **each other**, *every* member of a colliding group is dropped —
      never the first, and never auto-suffixed. Neither LLM-authored claim is
      more trustworthy than the other, so keeping the first would make the
      surviving primary key a function of LLM output order, and suffixing would
      invent a collection the spec never described. Dropping both loses a
      collection; keeping one silently installs a coin-flip in the runtime
      contract.

    Names collide as well as collections: two same-named entities in the IR share
    one provenance key, so the map would record only one of them.
    """
    contested: list[Entity] = []
    for entity in candidates:
        if _key(entity.name) in derived_names:
            logger.warning(
                "dropping fallback entity '%s': name is already modeled "
                "deterministically",
                entity.name,
            )
        elif _key(entity.collection) in derived_collections:
            logger.warning(
                "dropping fallback entity '%s': collection '%s' is already "
                "modeled deterministically",
                entity.name,
                entity.collection,
            )
        else:
            contested.append(entity)
    collection_counts = collections.Counter(_key(e.collection) for e in contested)
    name_counts = collections.Counter(_key(e.name) for e in contested)
    survivors: list[Entity] = []
    for entity in contested:
        if collection_counts[_key(entity.collection)] > 1:
            logger.warning(
                "dropping fallback entity '%s': collection '%s' is claimed by "
                "more than one fallback entity, and neither claim can be "
                "trusted over the other",
                entity.name,
                entity.collection,
            )
            continue
        if name_counts[_key(entity.name)] > 1:
            logger.warning(
                "dropping fallback entity '%s': the name is claimed by more "
                "than one fallback entity, and neither claim can be trusted "
                "over the other",
                entity.name,
            )
            continue
        survivors.append(entity)
    return survivors


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

    A derived entity always wins a collision with a fallback entity; two fallback
    entities colliding with each other are both dropped. See
    :func:`_surviving_fallback_entities`. Returns the model and the provenance map
    recording which path each entity came from.
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
    # The derived contract, normalized for collision comparison — aligned with
    # validate_data_model's guard in extract.py, which must not be the weaker of
    # the two. Names are reserved as well as collections: a fallback entity that
    # reuses a derived entity's *name* can still sit in a distinct collection, so
    # the collection guard alone would let it overwrite that entity's "derived"
    # provenance record with "llm" and put two same-named entities in the IR.
    reserved = {_key(c) for c in identity.collections}
    reserved_names = {_key(e.name) for e in entities}
    declined: list[str] = []
    extras: list[Entity] = []
    if fallback is not None:
        declined = list(fallback.declined)
        extras = _surviving_fallback_entities(
            fallback.entities, reserved, reserved_names
        )
        for entity in extras:
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
