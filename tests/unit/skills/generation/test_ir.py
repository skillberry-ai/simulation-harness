import pytest
from pydantic import ValidationError
from typing import Any

from simulation_harness.skills.generation.ir import (
    Entity,
    Field,
    Operation,
    OperationEvidence,
    OperationKind,
    Scenario,
    SpecModel,
    StoreMetadata,
)


def _entity(name: Any = "Feature", coll: Any = "features", pk: Any = "id") -> Entity:
    return Entity(
        name=name,
        collection=coll,
        primary_key=pk,
        fields=[Field(name="id", type="string", required=True)],
    )


def _ir(**over: Any) -> SpecModel:
    base = dict(
        api_name="Aha",
        slug="aha",
        entities=[_entity()],
        operations=[
            Operation(
                operation_id="getFeature",
                method="GET",
                path="/features/{id}",
                entity="Feature",
                kind=OperationKind.read,
            )
        ],
        store_metadata=StoreMetadata(
            collections=["features"], pk_map={"features": "id"}
        ),
    )
    base.update(over)
    return SpecModel(**base)


def test_valid_ir_has_no_consistency_errors() -> None:
    assert _ir().validate_consistency() == []


def test_dangling_operation_entity_is_flagged() -> None:
    ir = _ir(
        operations=[
            Operation(
                operation_id="x",
                method="GET",
                path="/x",
                entity="Ghost",
                kind=OperationKind.read,
            )
        ]
    )
    errs = ir.validate_consistency()
    assert any("Ghost" in e for e in errs)


def test_pk_map_collection_must_be_a_known_collection() -> None:
    ir = _ir(
        store_metadata=StoreMetadata(collections=["features"], pk_map={"widgets": "id"})
    )
    errs = ir.validate_consistency()
    assert any("widgets" in e for e in errs)


def test_entity_collection_must_appear_in_store_metadata() -> None:
    ir = _ir(store_metadata=StoreMetadata(collections=[], pk_map={}))
    errs = ir.validate_consistency()
    assert any("features" in e for e in errs)


def test_scenario_defaults_operations_to_empty_list() -> None:
    s = Scenario(title="Book a room", intent="Find and book an available room.")
    assert s.operations == []
    assert s.title == "Book a room"


def test_spec_model_evidence_defaults_to_empty() -> None:
    """Existing SpecModel(...) constructions must keep working untouched."""
    assert _ir().evidence == {}


def test_operation_evidence_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        OperationEvidence(description="ok", bogus="nope")  # type: ignore[call-arg]


def test_operation_evidence_fields_default_to_none() -> None:
    ev = OperationEvidence()
    assert ev.description is None
    assert ev.request_example is None
    assert ev.response_example is None


def test_validate_consistency_accepts_known_evidence_key() -> None:
    ir = _ir(evidence={"getFeature": OperationEvidence(description="Reads it.")})
    assert ir.validate_consistency() == []


def test_validate_consistency_flags_unknown_evidence_key() -> None:
    """Evidence is a sibling map, so it can drift from operations; catch it."""
    ir = _ir(evidence={"ghostOp": OperationEvidence(description="Nobody's op.")})
    errors = ir.validate_consistency()
    assert any("ghostOp" in e and "operation_id" in e for e in errors)


def test_spec_model_round_trips_evidence() -> None:
    ir = _ir(evidence={"getFeature": OperationEvidence(description="Reads it.")})
    restored = SpecModel.model_validate(ir.model_dump())
    assert restored.evidence["getFeature"].description == "Reads it."


def test_identity_provenance_defaults_to_empty() -> None:
    ir = SpecModel(
        api_name="A",
        slug="a",
        entities=[],
        operations=[],
        store_metadata=StoreMetadata(collections=[], pk_map={}),
    )
    assert ir.identity_provenance == {}


def test_validate_consistency_rejects_unknown_provenance_entity() -> None:
    ir = SpecModel(
        api_name="A",
        slug="a",
        entities=[],
        operations=[],
        store_metadata=StoreMetadata(collections=[], pk_map={}),
        identity_provenance={"Ghost": "derived"},
    )
    assert any("Ghost" in e for e in ir.validate_consistency())
