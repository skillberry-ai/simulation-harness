"""Intermediate representation shared across generation stages."""

from __future__ import annotations

from enum import Enum

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


class SpecModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_name: str
    slug: str
    entities: list[Entity]
    operations: list[Operation]
    store_metadata: StoreMetadata

    def validate_consistency(self) -> list[str]:
        """Return human-readable cross-reference errors; empty list = consistent."""
        errors: list[str] = []
        entity_names = {e.name for e in self.entities}
        declared = set(self.store_metadata.collections)

        for op in self.operations:
            if op.entity is not None and op.entity not in entity_names:
                errors.append(
                    f"operation '{op.operation_id}' references unknown entity "
                    f"'{op.entity}'"
                )
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
        return errors
