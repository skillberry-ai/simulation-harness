"""Stage 1a fallback: schemas the identity rule could not decide → entities."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field

try:
    from importlib.resources import files
except ImportError:  # pragma: no cover
    from importlib_resources import files  # type: ignore[import-not-found]

from simulation_harness.skills.generation.ir import Entity, StoreMetadata
from simulation_harness.skills.generation.llm import call_json
from simulation_harness.skills.generation.repair import with_repair
from simulation_harness.skills.generation.stages.analyze.identity import IdentityModel
from simulation_harness.utils.logging import get_logger

logger = get_logger(__name__)


def _load_prompt() -> str:
    assets = files("simulation_harness.skills.assets")
    return (assets / "generation" / "extract.md").read_text()


@dataclass
class DataModel:
    api_name: str
    entities: list[Entity]
    store_metadata: StoreMetadata
    # Schemas the fallback judged not to be persisted entities. Recorded rather
    # than dropped so a spurious decline is visible — ``extract_data_model``
    # logs the list at INFO — instead of silently costing a collection. It is
    # deliberately *not* carried into ``manifest.json``: a decline is a fact
    # about the generation run, not part of the generated skill's contract, and
    # adding a field there would mean bumping MANIFEST_VERSION for a diagnostic.
    declined: list[str] = field(default_factory=list)


class _Invalid:
    """Sentinel carrying shape errors so repair can re-prompt (never validates clean)."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors


def validate_data_model(
    dm: DataModel, derived: IdentityModel | None = None
) -> list[str]:
    errors: list[str] = []
    declared = set(dm.store_metadata.collections)
    for e in dm.entities:
        if e.collection not in declared:
            errors.append(
                f"entity '{e.name}' collection '{e.collection}' missing from "
                f"store_metadata.collections"
            )
        # The same check ``validate_enrichment`` makes (enrich.py). Without it
        # here, a fallback entity whose pk is absent from its own fields sails
        # through compose and is only caught by ``validate_schema`` two stages
        # later — turning a one-line repair prompt the LLM can act on into
        # three wasted schema-repair attempts and a hard failure attributed to
        # stage "schema" instead of "extract".
        if not any(f.name == e.primary_key for f in e.fields):
            errors.append(
                f"entity '{e.name}' fields must include its primary key "
                f"'{e.primary_key}'"
            )
    # The same duplicate check ``validate_enrichment`` makes (enrich.py), for
    # both collection and name. Without it, a fallback payload with two
    # entities on one collection (or sharing a name) validates clean, reaches
    # ``compose_data_model``, and has every member of the colliding group
    # dropped with only a ``logger.warning`` — silently, since compose has no
    # repair channel to feed a correction back into. Sorted so the error list
    # itself does not jitter with LLM output order.
    collection_counts = Counter(e.collection for e in dm.entities)
    for coll_name, n in sorted(collection_counts.items()):
        if n > 1:
            errors.append(
                f"collection '{coll_name}' is claimed by {n} entities "
                f"(merge them or decline one)"
            )
    name_counts = Counter(e.name for e in dm.entities)
    for entity_name, n in sorted(name_counts.items()):
        if n > 1:
            errors.append(
                f"name '{entity_name}' is claimed by {n} entities "
                f"(merge them or decline one)"
            )
    for coll in dm.store_metadata.pk_map:
        if coll not in declared:
            errors.append(
                f"pk_map collection '{coll}' is not in store_metadata.collections"
            )
    if derived is not None:
        # Normalized (casefolded, stripped) so a case- or whitespace-variant
        # collection name (e.g. "Reservations", " reservations") is still
        # caught as the same collision an exact match would be. Otherwise the
        # variant slips through as a near-duplicate collection that appears on
        # some runs and not others — the same class of run-to-run drift this
        # branch exists to remove.
        reserved = {c.strip().casefold(): c for c in derived.collections}
        for e in dm.entities:
            pinned = reserved.get(e.collection.strip().casefold())
            if pinned is not None:
                errors.append(
                    f"entity '{e.name}' collection '{e.collection}' collides "
                    f"with already-modeled collection '{pinned}' — either give "
                    f"it a distinct collection or decline the schema"
                )
    return errors


def _derived_context(derived: IdentityModel | None) -> str:
    """Render the already-decided entities as read-only prompt context.

    Scoping this call to the leftovers removes the whole-spec view the LLM used
    to reason from. Without this block it cannot tell a genuine leftover entity
    from a value object it has already seen embedded elsewhere.
    """
    if derived is None or not derived.entities:
        return ""
    summary = [
        {
            "name": d.name,
            "collection": d.collection,
            "primary_key": d.primary_key,
        }
        for d in derived.entities
    ]
    return (
        "# Already-modeled entities (read-only — do not restate or collide "
        f"with these)\n```json\n{json.dumps(summary, indent=2)}\n```\n\n"
    )


async def extract_data_model(
    components: dict,
    slug: str,
    llm,
    *,
    retries: int,
    derived: IdentityModel | None = None,
) -> DataModel:
    """Ask the LLM about schemas the deterministic rule could not decide.

    Scoped fallback: ``components`` here is the *undecidable* subset, not the
    whole spec. ``derived`` is read-only context. The LLM may decline every
    schema — that is frequently the right answer.
    """
    prompt = _load_prompt()
    base_user = _derived_context(derived) + (
        f"# Leftover schemas\n```json\n{json.dumps(components, indent=2)}\n```\n"
    )

    async def produce(feedback):
        user = base_user + (
            "\n# feedback\n" + "\n".join(feedback) + "\n" if feedback else ""
        )
        payload = await call_json(llm, prompt, user)
        try:
            if not isinstance(payload, dict):
                return _Invalid(["extract payload must be a JSON object"])
            raw_declined = payload.get("declined", [])
            return DataModel(
                api_name=payload.get("api_name", slug),
                entities=[Entity(**e) for e in payload.get("entities", [])],
                store_metadata=StoreMetadata(**payload["store_metadata"]),
                declined=[d for d in raw_declined if isinstance(d, str)],
            )
        except Exception as e:  # malformed shape (missing store_metadata, bad field, …)
            return _Invalid([f"data-model shape error: {e}"])

    def validate(artifact):
        if isinstance(artifact, _Invalid):
            return artifact.errors
        return validate_data_model(artifact, derived)

    dm = await with_repair(produce, validate, stage="extract", retries=retries)
    if dm.declined:
        # A decline costs a collection the runtime will never have, and the
        # decision is made by the LLM with no validator behind it — so it has to
        # leave a trace somewhere. This log is that trace: without it, the only
        # symptom of an over-eager decline is a missing entity at simulation
        # time, with nothing in the record tying it back to this stage.
        logger.info(
            "extract declined %d of %d leftover schemas as non-entities: %s",
            len(dm.declined),
            len(components),
            sorted(dm.declined),
        )
    return dm
