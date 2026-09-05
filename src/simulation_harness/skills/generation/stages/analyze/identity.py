"""Deterministic derivation of entity identity from OpenAPI schemas.

Pure: no LLM, no I/O, no clock, no randomness. This module owns the *contract*
half of the analyze stage — the entity set, its collections, and its primary
keys — which ``state/loader.py`` reads back out of the generated
``schema.json`` at runtime. Because the contract is load-bearing at runtime, it
must not vary between two generations of the same spec; that is why it is code
and not a prompt.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from simulation_harness.skills.generation.repair import GenerationStageError

_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")

# Nouns ending in these are singular despite the trailing "s", so they still
# need pluralizing: address -> addresses, status -> statuses, axis -> axises.
_SINGULAR_S_ENDINGS = ("ss", "us", "is")


def snake(name: str) -> str:
    """``OrderItem`` -> ``order_item``. Already-snake names pass through."""
    return _CAMEL_BOUNDARY.sub("_", name).lower()


def camel(noun: str) -> str:
    """``payment_method`` -> ``PaymentMethod``."""
    return "".join(part.capitalize() for part in noun.split("_") if part)


def pluralize(noun: str) -> str:
    """English-ish pluralizer for collection names.

    A noun already ending in ``s`` (other than the singular ``ss``/``us``/``is``
    endings) is treated as already plural and returned unchanged, so
    ``attachments`` does not become ``attachmentses``.
    """
    if noun.endswith("s") and not noun.endswith(_SINGULAR_S_ENDINGS):
        return noun
    if noun.endswith(("s", "x", "z", "ch", "sh")):
        return noun + "es"
    if noun.endswith("y") and noun[-2:-1] not in "aeiou":
        return noun[:-1] + "ies"
    return noun + "s"


def identity_key(name: str, schema: dict, *, synthetic: bool) -> str | None:
    """The property that identifies instances of ``schema``, or ``None``.

    ``None`` means **undecidable**: the caller must route the schema to the
    scoped LLM fallback rather than guess. Guessing is what the old free-form
    extract stage did, and it is the source of the run-to-run contract drift
    this work removes.

    ``synthetic`` marks a schema whose key is a generated operation id
    (``get_order_details__response``) rather than a spec-declared type name.
    Only those get rule 4 (sole ``<noun>_id``): a synthetic key can never
    name-match, so its single ``*_id`` is the only signal available, whereas a
    *named* schema carrying one foreign-looking id is genuinely ambiguous.
    """
    declared = schema.get("x-primary-key")
    if isinstance(declared, str) and declared:
        return declared
    props = schema.get("properties")
    if not isinstance(props, dict):
        return None
    candidates = [p for p in props if isinstance(p, str) and p.endswith("_id")]
    own = snake(name)
    # Longest noun first so "order_item_id" beats "item_id" for OrderItem, and
    # so the outcome does not depend on property declaration order.
    for candidate in sorted(candidates, key=lambda c: (-len(c), c)):
        noun = candidate[:-3]
        if noun and (own == noun or own.endswith(noun) or pluralize(noun) == own):
            return candidate
    if "id" in props:
        return "id"
    if synthetic and len(candidates) == 1:
        return candidates[0]
    return None


def noun_for(key: str, schema_name: str) -> str:
    """The entity noun implied by an identity key.

    The noun comes from the **key**, not the schema name — that is what makes
    ``get_order_details__response`` and ``get_order__response`` collapse into
    one ``orders`` collection. Only a bare ``id`` has to fall back to the schema
    name, which is exactly why a bare ``id`` never clusters across names.
    """
    if key.endswith("_id") and len(key) > 3:
        return snake(key[:-3])
    if key == "id":
        return snake(schema_name)
    return snake(key)


@dataclass(frozen=True)
class DerivedEntity:
    """One entity whose identity was decided in code.

    ``fields`` is a sorted tuple of ``(name, json_type)`` pairs — enough to
    build a structurally correct Entity without an LLM, which is
    what the enrich stage degrades to when it fails.
    """

    name: str
    collection: str
    primary_key: str
    fields: tuple[tuple[str, str], ...]
    sources: tuple[str, ...]


@dataclass(frozen=True)
class IdentityModel:
    entities: tuple[DerivedEntity, ...]
    undecidable: tuple[str, ...]

    @property
    def collections(self) -> list[str]:
        return [e.collection for e in self.entities]

    @property
    def pk_map(self) -> dict[str, str]:
        return {e.collection: e.primary_key for e in self.entities}


@dataclass
class _Cluster:
    primary_key: str
    fields: dict[str, str] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)


def _json_type(prop: dict) -> str:
    declared = prop.get("type")
    if isinstance(declared, str):
        return declared
    if isinstance(prop.get("properties"), dict):
        return "object"
    return "string"


def _nested_objects(prop: dict) -> Iterator[dict]:
    """Yield object schemas reachable one level below ``prop``.

    Covers the three shapes a child entity actually appears in: a direct
    object, an ``array.items`` object, and a map modelled as
    ``additionalProperties``.
    """
    inner = prop.get("items") if prop.get("type") == "array" else prop
    if not isinstance(inner, dict):
        return
    extra = inner.get("additionalProperties")
    if isinstance(extra, dict) and isinstance(extra.get("properties"), dict):
        yield extra
    elif isinstance(inner.get("properties"), dict):
        yield inner


def _absorb(
    clusters: dict[str, _Cluster],
    noun: str,
    key: str,
    schema: dict,
    source: str,
) -> None:
    cluster = clusters.get(noun)
    if cluster is None:
        cluster = clusters[noun] = _Cluster(primary_key=key)
    props = schema.get("properties")
    if isinstance(props, dict):
        for prop_name in sorted(props):
            prop = props[prop_name]
            if isinstance(prop_name, str):
                cluster.fields.setdefault(
                    prop_name, _json_type(prop if isinstance(prop, dict) else {})
                )
    cluster.sources.append(source)


def _reject_colliding_collections(clusters: dict[str, _Cluster]) -> None:
    """Fail immediately when two nouns pluralize onto one collection name.

    :func:`pluralize` is not injective: ``address``/``addresses``,
    ``status``/``statuses`` and ``box``/``boxes`` each collapse to a single
    string, and a spec carrying both members of such a pair is ordinary (an
    ``Address`` entity beside an ``Addresses`` wrapper). Two clusters then claim
    one collection, and because ``pk_map`` is keyed by collection one primary key
    is silently lost — which ``SpecModel.validate_consistency`` does not notice.

    Raised here rather than left to a later stage because the failure downstream
    is both misattributed and unrepairable: ``enforce_contract`` emits a
    top-level ``required`` list with a duplicate entry, jsonschema rejects it as
    non-unique, and the run burns all three LLM repair attempts on a defect no
    LLM authored before hard-failing under stage "schema". The run dies either
    way; this way the message names the cause.
    """
    by_collection: dict[str, list[str]] = {}
    for noun in sorted(clusters):
        by_collection.setdefault(pluralize(noun), []).append(noun)
    errors = [
        f"collection '{collection}' is claimed by {len(nouns)} derived entities "
        f"(nouns {nouns}, from schemas "
        f"{sorted({s for n in nouns for s in clusters[n].sources})}): these nouns "
        f"pluralize to the same collection, so all but one primary key would be "
        f"lost from the runtime contract"
        for collection, nouns in sorted(by_collection.items())
        if len(nouns) > 1
    ]
    if errors:
        raise GenerationStageError("identity", errors)


def derive_identity(schemas: dict[str, dict], *, synthetic: bool) -> IdentityModel:
    """Cluster ``schemas`` into entities by identity key.

    Schemas sharing an identity key are the same entity and their fields are
    unioned. Schemas whose key is undecidable are reported in
    :attr:`IdentityModel.undecidable` for the scoped LLM fallback; they never
    contribute a collection here.

    Iteration is over sorted names throughout so the result cannot depend on
    the order the schema map happened to be built in.

    Raises:
        GenerationStageError: stage ``"identity"``, when two nouns pluralize onto
            the same collection name. See :func:`_reject_colliding_collections`.
    """
    clusters: dict[str, _Cluster] = {}
    undecidable: list[str] = []
    for name in sorted(schemas):
        schema = schemas[name]
        if not isinstance(schema, dict):
            undecidable.append(name)
            continue
        key = identity_key(name, schema, synthetic=synthetic)
        if key is None:
            undecidable.append(name)
            continue
        _absorb(clusters, noun_for(key, name), key, schema, name)
        props = schema.get("properties")
        if not isinstance(props, dict):
            continue
        for prop_name in sorted(props):
            prop = props[prop_name]
            if not isinstance(prop, dict):
                continue
            for target in _nested_objects(prop):
                nested = identity_key(prop_name, target, synthetic=synthetic)
                if nested is None or nested == key:
                    continue
                _absorb(
                    clusters,
                    noun_for(nested, prop_name),
                    nested,
                    target,
                    f"{name}.{prop_name}",
                )
    _reject_colliding_collections(clusters)
    entities = tuple(
        DerivedEntity(
            name=camel(noun),
            collection=pluralize(noun),
            primary_key=clusters[noun].primary_key,
            fields=tuple(sorted(clusters[noun].fields.items())),
            sources=tuple(clusters[noun].sources),
        )
        for noun in sorted(clusters)
    )
    return IdentityModel(entities=entities, undecidable=tuple(sorted(undecidable)))
