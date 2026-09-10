"""Intermediate representation shared across generation stages."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class OperationKind(str, Enum):
    create = "create"
    read = "read"
    update = "update"
    delete = "delete"
    list = "list"
    search = "search"
    action = "action"


class ElementField(BaseModel):
    """One property of a container field's element, name and JSON type only.

    Deliberately flatter than :class:`Field`: the identity pass walks exactly one
    level into a container (see ``_nested_objects``), so there is no second level
    to describe, and a recursive model would imply a depth nothing populates.
    """

    # Frozen, with tuple collections on ElementShape, so both stay hashable:
    # DerivedEntity is a frozen dataclass and therefore hashable, and embedding
    # an unhashable model in it would silently revoke that.
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    type: str
    # Whether the element schema declared this property required. Carried so the
    # schema stage can emit `required` on the element: without it an element is
    # type-checked but its *shape* is not, and a seeded element may omit half the
    # fields the response promises while still validating.
    required: bool = False


class ElementShape(BaseModel):
    """How the elements of an ``array`` field are stored.

    Without this the storage element shape is unpinned end to end: ``_json_type``
    collapses every array to ``"array"``, so the schema stage can only emit
    ``"items": {}`` — which validates anything — and the operations, schema and
    seed stages then each choose an element shape independently. They run
    concurrently and cannot see each other, so nothing reconciles the choices;
    tau2-retail seeded ``orders[].items`` as bare id strings while the operation
    section specified it as objects.

    ``kind`` is the decision:

    - ``scalar`` — elements are a JSON primitive, given in ``type``.
    - ``embedded`` — elements are objects stored inline, described by ``fields``.
    - ``reference`` — the element clustered into its own entity during identity
      derivation, so the parent stores references. ``target_collection`` and
      ``target_key`` name where the elements live. ``link_fields`` is empty when
      the element is a pure projection of the target (store the bare identifier)
      and otherwise carries the parent-scoped leftovers that a link object must
      keep alongside the key.

    ``container`` says where the elements live, and the two differ in one way that
    matters. An ``array`` of a promoted element stores *references*, so the
    reference kind means bare identifiers (or a link object). A ``map`` is keyed by
    the referenced identifier already, so its keys carry the reference and its
    values stay an inline projection — a map is therefore never ``reference``; it
    records ``target_collection``/``target_key`` as a cross-reference annotation
    while staying ``embedded``.

    ``None`` on a field means undecidable — the element shape was not declared in
    the spec — and leaves the schema stage's ``items`` / ``additionalProperties``
    untouched rather than guessing.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["scalar", "embedded", "reference"]
    container: Literal["array", "map"] = "array"
    type: str | None = None
    fields: tuple[ElementField, ...] = ()
    target_collection: str | None = None
    target_key: str | None = None
    link_fields: tuple[ElementField, ...] = ()
    # Collections carrying element fields the target does not: a response that
    # denormalizes a grandparent's attribute onto the element needs a second read
    # to assemble it. Recorded where the hop is detected so no consumer has to
    # re-derive it. See ``_resolves_one_hop_out``.
    hop_collections: tuple[str, ...] = ()


class Field(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    type: str
    required: bool = False
    enum: list[str] | None = None
    format: str | None = None
    description: str | None = None
    # Derived in code by the identity pass and re-pinned in compose_data_model,
    # so an enrich prompt cannot move it. See ElementShape.
    element: ElementShape | None = None


class Relationship(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    target_entity: str
    target_field: str


class Scenario(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str
    intent: str
    operations: list[str] = []


class Entity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    collection: str
    primary_key: str
    fields: list[Field]
    relationships: list[Relationship] = []
    fingerprint_fields: list[str] = []
    temporal_fields: list[str] = []


class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str
    method: str
    path: str
    tag: str | None = None
    summary: str | None = None
    entity: str | None = None
    kind: OperationKind
    patterns: list[str] = []


class StoreMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    collections: list[str]
    pk_map: dict[str, str]


class OperationEvidence(BaseModel):
    """Operation-level prose and illustrative payloads carried from the spec.

    Deliberately kept out of :class:`Operation`. ``Operation`` is the *shape*
    projection used to bucket, batch, and chunk operations; this carries the
    *intent* the contract-writing stages need. Conflating the two is what caused
    the generated skill to contradict the spec (issue #28), and keeping them
    apart is what stops prose from reaching shape-only consumers —
    ``classify_batch`` dumps its stub dicts wholesale.

    ``request_example`` / ``response_example`` are declared but not yet
    populated: wiring examples needs a token-budget policy (one spec in the
    corpus carries 477 KB of them). See the design doc.
    """

    model_config = ConfigDict(extra="forbid")
    description: str | None = None
    request_example: Any | None = None
    response_example: Any | None = None


class SpecModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_name: str
    slug: str
    entities: list[Entity]
    operations: list[Operation]
    store_metadata: StoreMetadata
    # Sparse map keyed by operation_id: only operations with surviving evidence
    # get a key. validate_consistency() enforces that every key is a known
    # operation_id, since a sibling map can drift from `operations`.
    evidence: dict[str, OperationEvidence] = {}
    # Which path decided each entity's identity: "derived" (deterministic rule)
    # or "llm" (scoped fallback). Recorded so a contract that came from a
    # non-deterministic path is visible in the manifest rather than implicit.
    identity_provenance: dict[str, str] = {}

    def validate_consistency(self) -> list[str]:
        """Return human-readable cross-reference errors; empty list = consistent."""
        errors: list[str] = []
        entity_names = {e.name for e in self.entities}
        declared = set(self.store_metadata.collections)
        operation_ids = {op.operation_id for op in self.operations}

        for op in self.operations:
            if op.entity is not None and op.entity not in entity_names:
                errors.append(
                    f"operation '{op.operation_id}' references unknown entity "
                    f"'{op.entity}'"
                )
        for oid in self.evidence:
            if oid not in operation_ids:
                errors.append(f"evidence key '{oid}' is not a known operation_id")
        for coll in self.store_metadata.pk_map:
            if coll not in declared:
                errors.append(
                    f"pk_map collection '{coll}' is not in store_metadata.collections"
                )
        for e in self.entities:
            if e.collection not in declared:
                errors.append(
                    f"entity '{e.name}' collection '{e.collection}' missing from "
                    f"store_metadata.collections"
                )
        for name in self.identity_provenance:
            if name not in entity_names:
                errors.append(f"identity_provenance key '{name}' is not a known entity")
        return errors
