"""Intermediate representation shared across generation stages."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict


class OperationKind(str, Enum):
    create = "create"
    read = "read"
    update = "update"
    delete = "delete"
    list = "list"
    search = "search"
    action = "action"


class Field(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    type: str
    required: bool = False
    enum: list[str] | None = None
    format: str | None = None
    description: str | None = None


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
