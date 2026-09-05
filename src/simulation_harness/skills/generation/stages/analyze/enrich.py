"""Stage 1a-2: fill in field detail for an entity list whose shape is pinned.

This is the *soft* half of what the old free-form extract stage did. It has no
authority over the contract — names, collections, and primary keys come from
:mod:`identity` and are re-asserted here on every attempt. That split is the
whole point: prose can jitter between runs without changing what the runtime
reads out of ``schema.json``.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

try:
    from importlib.resources import files
except ImportError:  # pragma: no cover
    from importlib_resources import files  # type: ignore[import-not-found, no-redef]

from pydantic import ValidationError

from simulation_harness.skills.generation.ir import Entity, Field
from simulation_harness.skills.generation.llm import call_json
from simulation_harness.skills.generation.repair import with_repair
from simulation_harness.skills.generation.stages.analyze.identity import IdentityModel


def _load_prompt() -> str:
    assets = files("simulation_harness.skills.assets")
    return (assets / "generation" / "enrich.md").read_text()


def structural_entities(identity: IdentityModel) -> list[Entity]:
    """Build entities from the derived structure alone, with no LLM.

    The degradation floor: field names and JSON types come straight from the
    schemas, descriptions and enums are simply absent. A skill generated from
    this is duller but still contract-correct and still runnable.
    """
    return [
        Entity(
            name=derived.name,
            collection=derived.collection,
            primary_key=derived.primary_key,
            fields=[
                Field(
                    name=field_name,
                    type=field_type,
                    required=field_name == derived.primary_key,
                )
                for field_name, field_type in derived.fields
            ],
        )
        for derived in identity.entities
    ]


def validate_enrichment(identity: IdentityModel, entities: list[Entity]) -> list[str]:
    """Re-assert the pinned contract over whatever the LLM returned."""
    pinned = {d.name: d for d in identity.entities}
    names = [e.name for e in entities]
    got = set(names)
    errors: list[str] = []
    missing = sorted(set(pinned) - got)
    if missing:
        errors.append(f"missing pinned entities (they must be returned): {missing}")
    invented = sorted(got - set(pinned))
    if invented:
        errors.append(f"entities not in the pinned list (remove them): {invented}")
    duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
    if duplicates:
        errors.append(
            f"duplicate entities returned (return each exactly once): {duplicates}"
        )
    for entity in entities:
        derived = pinned.get(entity.name)
        if derived is None:
            continue
        if entity.collection != derived.collection:
            errors.append(
                f"{entity.name}: collection must stay '{derived.collection}', "
                f"got '{entity.collection}'"
            )
        if entity.primary_key != derived.primary_key:
            errors.append(
                f"{entity.name}: primary_key must stay '{derived.primary_key}', "
                f"got '{entity.primary_key}'"
            )
        if not any(f.name == derived.primary_key for f in entity.fields):
            errors.append(
                f"{entity.name}: fields must include the primary key "
                f"'{derived.primary_key}'"
            )
    return errors


def pinned_summary(identity: IdentityModel) -> str:
    return json.dumps(
        [
            {
                "name": d.name,
                "collection": d.collection,
                "primary_key": d.primary_key,
                "observed_fields": [{"name": n, "type": t} for n, t in d.fields],
            }
            for d in identity.entities
        ],
        indent=2,
    )


class _Invalid(list[Entity]):
    """A shape/parse failure carrying its own errors, so repair can re-prompt.

    Subclasses ``list`` so it satisfies the ``list[Entity]`` slot ``with_repair``
    is generic over while never validating clean. Mirrors the ``_Invalid``
    sentinel in ``extract.py``.
    """

    def __init__(self, errors: list[str]) -> None:
        super().__init__()
        self.errors = errors


async def enrich_entities(
    identity: IdentityModel,
    schemas: dict[str, dict],
    llm: Any,
    *,
    retries: int,
) -> list[Entity]:
    prompt = _load_prompt()
    base_user = (
        f"# Pinned entities\n```json\n{pinned_summary(identity)}\n```\n\n"
        f"# Source schemas\n```json\n{json.dumps(schemas, indent=2)}\n```\n"
    )

    async def produce(feedback: list[str] | None) -> list[Entity]:
        user = base_user + (
            "\n# feedback\n" + "\n".join(feedback) + "\n" if feedback else ""
        )
        payload = await call_json(llm, prompt, user)
        if not isinstance(payload, dict):
            return _Invalid(["payload must be a JSON object"])
        raw = payload.get("entities")
        if not isinstance(raw, list):
            return _Invalid(["payload must contain an 'entities' array"])
        try:
            return [Entity.model_validate(item) for item in raw]
        except ValidationError as e:
            return _Invalid([f"entity failed validation: {e.errors()[:3]}"])

    def validate(entities: list[Entity]) -> list[str]:
        if isinstance(entities, _Invalid):
            return entities.errors
        return validate_enrichment(identity, entities)

    return await with_repair(produce, validate, stage="enrich", retries=retries)
