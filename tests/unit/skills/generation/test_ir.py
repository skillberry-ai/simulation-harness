from simulation_harness.skills.generation.ir import (
    Entity,
    Field,
    Operation,
    OperationKind,
    SpecModel,
    StoreMetadata,
)


def _entity(name="Feature", coll="features", pk="id"):
    return Entity(
        name=name,
        collection=coll,
        primary_key=pk,
        fields=[Field(name="id", type="string", required=True)],
    )


def _ir(**over):
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


def test_valid_ir_has_no_consistency_errors():
    assert _ir().validate_consistency() == []


def test_dangling_operation_entity_is_flagged():
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


def test_pk_map_collection_must_be_a_known_collection():
    ir = _ir(
        store_metadata=StoreMetadata(collections=["features"], pk_map={"widgets": "id"})
    )
    errs = ir.validate_consistency()
    assert any("widgets" in e for e in errs)


def test_entity_collection_must_appear_in_store_metadata():
    ir = _ir(store_metadata=StoreMetadata(collections=[], pk_map={}))
    errs = ir.validate_consistency()
    assert any("features" in e for e in errs)
