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

from simulation_harness.skills.generation.ir import ElementField, ElementShape
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


def _scalar_candidate(prop: object) -> bool:
    """Whether ``prop`` could hold a primary-key value.

    A primary key has to be one value: ``state/store.py`` keys rows by
    ``str(pk_value)``, so a list-valued key becomes the stringified list rather
    than failing. Only *declared* evidence disqualifies a candidate — an absent
    type is the common case in these specs and is not evidence of a problem.
    """
    if not isinstance(prop, dict):
        return True
    if prop.get("type") in ("array", "object"):
        return False
    return not (
        isinstance(prop.get("items"), dict) or isinstance(prop.get("properties"), dict)
    )


def _singular_segment(segment: str) -> str:
    """One path segment reduced to singular, conservatively.

    Two guards, both needed. Segments ending in ``_SINGULAR_S_ENDINGS`` are
    singular despite the trailing ``s`` and are returned untouched — without this
    ``status`` reduces to ``statu``, because ``pluralize("statu")`` really is
    ``status`` and the round-trip check below is satisfied. Otherwise a reduction
    is accepted only when ``pluralize`` round-trips back to the original, so an
    irregular segment is left exactly as it was.
    """
    if segment.endswith(_SINGULAR_S_ENDINGS):
        return segment
    for candidate in (
        segment[:-3] + "y" if segment.endswith("ies") else "",
        segment[:-2] if segment.endswith("es") else "",
        segment[:-1] if segment.endswith("s") else "",
    ):
        if candidate and pluralize(candidate) == segment:
            return candidate
    return segment


def singularize(noun: str) -> str:
    """Inverse of :func:`pluralize`, per underscore-separated segment.

    Conservative by construction: :func:`_singular_segment` only reduces a
    segment when ``pluralize`` round-trips back to it, so ``status`` and ``axis``
    (which ``pluralize`` treats as singular) are returned unchanged and no
    collection name can move.
    """
    return "_".join(_singular_segment(s) for s in noun.split("_") if s)


def _noun_is_stem(noun: str, holder: str) -> bool:
    """Whether ``noun`` names the thing ``holder`` holds, rather than something else.

    A sole ``*_id`` on an element is the element's own identity when its noun is a
    **prefix** of the holder's name (``payment_history`` holds ``payment``
    entries), and a foreign key when it is not (``payment_history`` holding
    ``payment_method_id``, ``fulfillments`` holding ``tracking_id``).

    Prefix, not subset: sharing a segment is not enough, or ``payment_history``
    and ``payment_method`` would still match on ``payment``.
    """
    want = [_singular_segment(s) for s in noun.split("_") if s]
    have = [_singular_segment(s) for s in holder.split("_") if s]
    return bool(want) and have[: len(want)] == want


def identity_key(
    name: str, schema: dict, *, synthetic: bool, nested: bool = False
) -> str | None:
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

    ``nested`` marks an element-level decision, where ``name`` is the holder
    property rather than a schema name. There rule 4 additionally requires the
    noun to be a stem of the holder (:func:`_noun_is_stem`): a line item's sole
    ``*_id`` is usually a foreign key, and adopting it coins a collection named
    after the entity it references.

    Note that a bare ``id`` is returned here on both paths — it is a correct
    *key* either way. What a synthetic name cannot supply is a usable **noun**
    for it, so :func:`derive_identity` treats a bare ``id`` on a top-level
    synthetic schema as undecidable. That decision belongs there, next to
    :func:`noun_for`, not here.
    """
    declared = schema.get("x-primary-key")
    if isinstance(declared, str) and declared:
        return declared
    props = schema.get("properties")
    if not isinstance(props, dict):
        # A union of objects is an entity described in variants; flatten it so the
        # rules below see one property set. Anything else is genuinely undecidable.
        flattened = _flatten_union(schema)
        if flattened is None:
            return None
        props = flattened["properties"]
    candidates = [
        p
        for p in sorted(props)
        if isinstance(p, str) and p.endswith("_id") and _scalar_candidate(props[p])
    ]
    own = snake(name)
    # Longest noun first so "order_item_id" beats "item_id" for OrderItem, and
    # so the outcome does not depend on property declaration order.
    for candidate in sorted(candidates, key=lambda c: (-len(c), c)):
        noun = candidate[:-3]
        if noun and (own == noun or own.endswith(noun) or pluralize(noun) == own):
            return candidate
    if "id" in props and _scalar_candidate(props["id"]):
        return "id"
    if synthetic and len(candidates) == 1:
        if not nested or _noun_is_stem(candidates[0][:-3], name):
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
        return singularize(snake(schema_name))
    return snake(key)


@dataclass(frozen=True)
class DerivedEntity:
    """One entity whose identity was decided in code.

    ``fields`` is a sorted tuple of ``(name, json_type)`` pairs — enough to
    build a structurally correct Entity without an LLM, which is
    what the enrich stage degrades to when it fails.

    ``elements`` is the subset of those fields that are arrays whose element
    shape could be decided, as sorted ``(field_name, ElementShape)`` pairs. A
    field absent from it is either not an array or an array whose element shape
    the spec never declared.
    """

    name: str
    collection: str
    primary_key: str
    fields: tuple[tuple[str, str], ...]
    sources: tuple[str, ...]
    elements: tuple[tuple[str, ElementShape], ...] = ()


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
    # Raw element schema per container property, as ``(container, schema)`` —
    # ``items`` for an array, ``additionalProperties`` for a map. Kept so element
    # shapes can be decided in a second pass: the reference/embedded call needs the
    # final cluster set, which does not exist while clustering is still running.
    element_schemas: dict[str, tuple[str, dict]] = field(default_factory=dict)
    # Which source schemas contributed each field. Needed because promoting a
    # nested element absorbs that element's own fields into the target cluster:
    # without provenance, "is this element a subset of its target?" is circular
    # and trivially true, so a link object could never be detected.
    field_sources: dict[str, set[str]] = field(default_factory=dict)


def _json_type(prop: dict) -> str:
    declared = prop.get("type")
    if isinstance(declared, str):
        return declared
    if isinstance(prop.get("properties"), dict):
        return "object"
    return "string"


def _merge_props(into: dict, incoming: dict) -> None:
    """Merge one union variant's properties into the accumulator.

    Differing ``const`` values across variants fold into an ``enum``: that is the
    discriminator (``source`` on tau2-retail's payment methods), and a plain
    ``dict.update`` would keep only whichever variant sorted last, silently
    asserting that every row is a gift card. Any other conflict keeps the first
    definition seen — shape validation belongs to the schema stage, not here.
    """
    for name in sorted(incoming):
        if not isinstance(name, str):
            continue
        prop = incoming[name]
        existing = into.get(name)
        if existing is None:
            into[name] = prop
            continue
        if not (isinstance(existing, dict) and isinstance(prop, dict)):
            continue
        old, new = existing.get("const"), prop.get("const")
        if old is not None and new is not None and old != new:
            into[name] = {"enum": [old, new]}
        elif "enum" in existing and new is not None and new not in existing["enum"]:
            into[name] = {"enum": [*existing["enum"], new]}


def _flatten_union(schema: dict) -> dict | None:
    """One object schema equivalent to an ``anyOf``/``oneOf`` of objects, or ``None``.

    Properties are unioned and ``required`` intersected, so a field required by
    only some variants comes out optional. ``None`` means this is not a union of
    objects — a union with a scalar variant stays undecidable exactly as it was,
    rather than being coerced into an entity.
    """
    variants = schema.get("anyOf") or schema.get("oneOf")
    if not isinstance(variants, list) or not variants:
        return None
    props: dict = {}
    reqs: list[set[str]] = []
    for variant in variants:
        if not isinstance(variant, dict) or not isinstance(
            variant.get("properties"), dict
        ):
            return None
        _merge_props(props, variant["properties"])
        required = variant.get("required")
        reqs.append(set(required) if isinstance(required, list) else set())
    return {
        "type": "object",
        "properties": props,
        "required": sorted(set.intersection(*reqs)) if reqs else [],
    }


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
    if isinstance(extra, dict):
        if isinstance(extra.get("properties"), dict):
            yield extra
            return
        flattened = _flatten_union(extra)
        if flattened is not None:
            yield flattened
            return
    if isinstance(inner.get("properties"), dict):
        yield inner
        return
    flattened = _flatten_union(inner)
    if flattened is not None:
        yield flattened


def _container_element(prop: dict) -> tuple[str, dict] | None:
    """``(container, element schema)`` for an array or map property, else ``None``.

    A map is an object whose ``additionalProperties`` is itself a schema — the
    shape ``_nested_objects`` already walks for promotion. A plain nested object
    with declared ``properties`` is neither: it is one value, not a collection of
    them, so it is left out of scope here.
    """
    if prop.get("type") == "array":
        items = prop.get("items")
        return ("array", items) if isinstance(items, dict) and items else None
    extra = prop.get("additionalProperties")
    if prop.get("type") == "object" and isinstance(extra, dict) and extra:
        return ("map", extra)
    return None


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
                cluster.field_sources.setdefault(prop_name, set()).add(source)
                if isinstance(prop, dict):
                    # setdefault, and iteration over sorted names, so a property
                    # described by two source schemas resolves the same way every
                    # run rather than by whichever was absorbed last.
                    captured = _container_element(prop)
                    if captured is not None:
                        cluster.element_schemas.setdefault(prop_name, captured)
    cluster.sources.append(source)


def _element_fields(element: dict) -> tuple[ElementField, ...]:
    props = element.get("properties")
    if not isinstance(props, dict):
        return ()
    declared = element.get("required")
    required = (
        {r for r in declared if isinstance(r, str)}
        if isinstance(declared, list)
        else set()
    )
    return tuple(
        ElementField(
            name=name,
            type=_json_type(props[name] if isinstance(props[name], dict) else {}),
            required=name in required,
        )
        for name in sorted(props)
        if isinstance(name, str)
    )


def _foreign_key(
    element: dict, clusters: dict[str, _Cluster]
) -> tuple[str, str, str] | None:
    """``(local_key, target_collection, target_key)`` for an inlined element, or ``None``.

    A sole scalar ``*_id`` whose noun names an existing entity is a reference:
    the element has no identity of its own, so it stays inline, but the join is
    still worth recording. Without this, declining the key in rule 4 would lose
    the link entirely.
    """
    props = element.get("properties")
    if not isinstance(props, dict):
        return None
    candidates = [
        p
        for p in sorted(props)
        if isinstance(p, str) and p.endswith("_id") and _scalar_candidate(props[p])
    ]
    if len(candidates) != 1:
        return None
    noun = noun_for(candidates[0], "")
    target = clusters.get(noun)
    if target is None:
        return None
    return candidates[0], pluralize(noun), target.primary_key


def _holds_reference_to(
    holder: _Cluster, collection: str, clusters: dict[str, _Cluster]
) -> bool:
    """Whether one of ``holder``'s container elements is a foreign key into ``collection``.

    This is the structural relationship "``collection``'s rows hang off this
    holder", read off the foreign key rather than off provenance: a product's
    ``variants`` element carries ``item_id``, so items hang off products. It used
    to be visible in ``target.sources`` because such an element was also
    *absorbed* into the target cluster — but absorbing it coined a collection out
    of a foreign key, which is the defect rule 4's stem test now refuses. The key
    the element carries says the same thing without coining anything.

    Deliberately narrow: it is the same sole-scalar-``*_id`` test
    :func:`_foreign_key` applies, so a holder that merely shares a field *name*
    with the element (``User.name`` beside an order line's ``name``) is not a
    hop — see :func:`_resolves_one_hop_out`.
    """
    for prop_name in sorted(holder.element_schemas):
        _, element_schema = holder.element_schemas[prop_name]
        element = next(
            _nested_objects({"type": "array", "items": element_schema}), None
        )
        if element is None:
            continue
        fk = _foreign_key(element, clusters)
        if fk is not None and fk[1] == collection:
            return True
    return False


def _resolves_one_hop_out(
    clusters: dict[str, _Cluster],
    target: _Cluster,
    target_collection: str,
    field_name: str,
    own_sources: set[str],
) -> str | None:
    """True when ``field_name`` belongs to an entity the target hangs off.

    A response often denormalizes a grandparent's attribute down onto a nested
    element: tau2-retail's order line carries ``name`` and ``product_id``, which
    are ``Product`` attributes reached through ``Product.variants``, not columns
    of the ``Item`` the line references. Such a field is neither carried by the
    target nor parent-scoped — it is one hop further out, so the parent still
    stores a bare identifier and the response is assembled by a two-hop read.

    Requiring the target to be *nested inside* the holder is what keeps this from
    matching on a coincidence: ``User`` also carries a ``name``, and without the
    nesting test that alone would excuse the leftover.

    Nesting shows up two ways, and both count. Provenance: one of the target's
    source schemas is a property of a schema the holder was built from
    (``"Product.variants"`` against a holder sourced from ``"Product"``). Or a
    foreign key: the holder has a container element pointing at the target's
    collection (:func:`_holds_reference_to`). The second is needed because an
    element whose sole ``*_id`` is a foreign key is no longer absorbed into the
    target, so it contributes no source for the first test to see.

    Returns the holder's collection name, so the extra read the response needs can
    be recorded rather than merely permitted.
    """
    for noun in sorted(clusters):
        holder = clusters[noun]
        if holder is target:
            continue
        if not (holder.field_sources.get(field_name, set()) - own_sources):
            continue
        holder_sources = set(holder.sources)
        if any(
            source.rsplit(".", 1)[0] in holder_sources
            for source in target.sources
            if "." in source
        ) or _holds_reference_to(holder, target_collection, clusters):
            return pluralize(noun)
    return None


def _element_shape(
    clusters: dict[str, _Cluster],
    parent: _Cluster,
    prop_name: str,
    container: str,
    element_schema: dict,
    *,
    synthetic: bool,
) -> ElementShape | None:
    """Decide how one container property's elements are stored, or ``None``.

    Mirrors the promotion test in :func:`derive_identity` rather than inventing a
    second rule: an element is a ``reference`` exactly when that pass would have
    clustered it into an entity of its own. Reading the promotion back out is the
    point — the normalization decision is already made there, and today it is
    made and then discarded.

    A map never comes back ``reference``. Its keys already are the referenced
    identifiers, so the values stay an inline projection; the promotion is recorded
    as a cross-reference annotation instead. Pinning the value shape is still worth
    doing — tau2-retail seeded ``products[].variants`` as a third, flattened shape
    matching neither the spec's variant nor the ``items`` row it duplicates.

    ``None`` means the spec declared no element shape, so nothing downstream should
    constrain it.
    """
    if not element_schema:
        return None
    element = next(_nested_objects({"type": "array", "items": element_schema}), None)
    if element is None:
        declared = element_schema.get("type")
        # A typed primitive is worth pinning (this is the field where the schema
        # stage flip-flopped between `{}` and `{"type": "string"}` run to run);
        # an untyped or non-string type annotation is not decidable here.
        return (
            ElementShape(kind="scalar", container=container, type=declared)
            if isinstance(declared, str)
            else None
        )

    fields = _element_fields(element)
    embedded = ElementShape(kind="embedded", container=container, fields=fields)
    nested = identity_key(prop_name, element, synthetic=synthetic, nested=True)
    if nested is None or nested == parent.primary_key:
        fk = _foreign_key(element, clusters)
        if fk is None:
            return embedded
        local_key, target_collection, target_key = fk
        return embedded.model_copy(
            update={
                "local_key": local_key,
                "target_collection": target_collection,
                "target_key": target_key,
            }
        )
    noun = noun_for(nested, prop_name)
    target = clusters.get(noun)
    if target is None:
        # The nested schema names an identity but never became an entity, so
        # there is no collection to reference. Stored inline.
        return embedded
    if container == "map":
        return embedded.model_copy(
            update={
                "target_collection": pluralize(noun),
                "target_key": target.primary_key,
            }
        )

    # Fork 1: a pure projection of the target keeps nothing of its own, so the
    # parent stores the bare identifier. Anything the target does not carry is
    # parent-scoped and has to survive in a link object beside the key.
    #
    # "Carry" means carried *independently*: this element's own promotion put its
    # fields into the target cluster, so comparing against target.fields alone
    # would compare the element with itself.
    # One absorb path per parent source schema, so exclude them all — a cluster
    # built from several response schemas absorbed this element once per schema.
    own_sources = {f"{s}.{prop_name}" for s in parent.sources}
    leftovers: list[ElementField] = []
    hops: list[str] = []
    for f in fields:
        if target.field_sources.get(f.name, set()) - own_sources:
            continue  # the target carries it independently
        hop = _resolves_one_hop_out(
            clusters, target, pluralize(noun), f.name, own_sources
        )
        if hop is None:
            leftovers.append(f)
        elif hop not in hops:
            hops.append(hop)
    link_fields: tuple[ElementField, ...] = ()
    if leftovers:
        key_field = tuple(f for f in fields if f.name == nested)
        link_fields = key_field + tuple(f for f in leftovers if f.name != nested)
    return ElementShape(
        kind="reference",
        container=container,
        target_collection=pluralize(noun),
        target_key=target.primary_key,
        link_fields=link_fields,
        hop_collections=tuple(sorted(hops)),
    )


def _derive_element_shapes(
    clusters: dict[str, _Cluster], *, synthetic: bool
) -> dict[str, dict[str, ElementShape]]:
    """Element shapes per cluster noun, decided once clustering is complete."""
    out: dict[str, dict[str, ElementShape]] = {}
    for noun in sorted(clusters):
        cluster = clusters[noun]
        shapes: dict[str, ElementShape] = {}
        for prop_name in sorted(cluster.element_schemas):
            container, element_schema = cluster.element_schemas[prop_name]
            shape = _element_shape(
                clusters,
                cluster,
                prop_name,
                container,
                element_schema,
                synthetic=synthetic,
            )
            if shape is not None:
                shapes[prop_name] = shape
        out[noun] = shapes
    return out


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


def derive_identity(
    schemas: dict[str, dict],
    *,
    synthetic: bool,
    deferred: frozenset[str] = frozenset(),
) -> IdentityModel:
    """Cluster ``schemas`` into entities by identity key.

    Schemas sharing an identity key are the same entity and their fields are
    unioned. Schemas whose key is undecidable are reported in
    :attr:`IdentityModel.undecidable` for the scoped LLM fallback; they never
    contribute a collection here.

    ``deferred`` names schemas the caller has already judged out of the rule's
    reach (see :func:`~...sources._identity_responses`). They are reported
    undecidable **without the rule being run on them**, and that skip is
    load-bearing rather than a shortcut: an array-of-objects would decline on its
    own, but an object that merely omitted ``"type": "object"`` while carrying a
    sole ``*_id`` would satisfy rule 1.4 and be *derived* into a brand-new
    collection tagged ``"derived"`` — a contract entry invented by making the
    schema visible. Routing instead of widening exists precisely to prevent that,
    so deleting this branch silently reintroduces it.

    Iteration is over sorted names throughout so the result cannot depend on
    the order the schema map happened to be built in.

    Raises:
        GenerationStageError: stage ``"identity"``, when two nouns pluralize onto
            the same collection name. See :func:`_reject_colliding_collections`.
    """
    clusters: dict[str, _Cluster] = {}
    undecidable: list[str] = []
    for name in sorted(schemas):
        if name in deferred:
            undecidable.append(name)
            continue
        schema = schemas[name]
        if not isinstance(schema, dict):
            undecidable.append(name)
            continue
        key = identity_key(name, schema, synthetic=synthetic)
        if key is None or (synthetic and key == "id"):
            # A bare `id` is undecidable on the synthetic path. The key itself is
            # fine; the *noun* is not — `noun_for("id", name)` falls back to the
            # schema name, which on this path is a generated operation id, so
            # three operations returning `{id, name}` would coin the collections
            # `create_things`, `get_thing_details` and `list_things` and tag each
            # one "derived", leaking operation ids into the runtime contract. The
            # scoped fallback sees the whole operation set and can name the
            # entity once; provenance then honestly records "llm". On the named
            # path the schema name is a spec-declared type, so keying a bare `id`
            # by it stays exactly as it was.
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
                # A bare `id` *is* decidable here even on the synthetic path:
                # the name in hand is a property name, which is a real noun,
                # not the enclosing operation id.
                nested = identity_key(
                    prop_name, target, synthetic=synthetic, nested=True
                )
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
    element_shapes = _derive_element_shapes(clusters, synthetic=synthetic)
    entities = tuple(
        DerivedEntity(
            name=camel(noun),
            collection=pluralize(noun),
            primary_key=clusters[noun].primary_key,
            fields=tuple(sorted(clusters[noun].fields.items())),
            sources=tuple(clusters[noun].sources),
            elements=tuple(
                sorted(element_shapes.get(noun, {}).items(), key=lambda kv: kv[0])
            ),
        )
        for noun in sorted(clusters)
    )
    return IdentityModel(entities=entities, undecidable=tuple(sorted(undecidable)))
