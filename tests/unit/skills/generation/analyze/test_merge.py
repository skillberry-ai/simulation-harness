from typing import Any

from simulation_harness.skills.generation.ir import (
    Entity,
    Field as IRField,
    OperationEvidence,
    StoreMetadata,
)
from simulation_harness.skills.generation.stages.analyze import merge as M
from simulation_harness.skills.generation.stages.analyze.extract import DataModel
from simulation_harness.skills.generation.stages.analyze.identity import (
    DerivedEntity,
    IdentityModel,
)
from simulation_harness.skills.generation.stages.analyze.merge import (
    compose_data_model,
)


def _stub(oid: Any) -> dict[str, Any]:
    return {
        "operation_id": oid,
        "method": "GET",
        "path": f"/{oid}",
        "tag": "T",
        "summary": None,
    }


def _sem(oid: Any, kind: Any = "read", entity: Any = "Feature") -> dict[str, Any]:
    return {"operation_id": oid, "entity": entity, "kind": kind, "patterns": ["crud"]}


def _dm() -> DataModel:
    return DataModel(
        api_name="Aha",
        entities=[
            Entity(name="Feature", collection="features", primary_key="id", fields=[])
        ],
        store_metadata=StoreMetadata(
            collections=["features"], pk_map={"features": "id"}
        ),
    )


def test_validate_coverage_clean() -> None:
    stubs = [_stub("a"), _stub("b")]
    assert M.validate_coverage(stubs, [_sem("a"), _sem("b")]) == []


def test_validate_coverage_flags_missing_and_invented() -> None:
    stubs = [_stub("a"), _stub("b")]
    errors = M.validate_coverage(stubs, [_sem("a"), _sem("zzz")])
    assert any("b" in e for e in errors)  # missing
    assert any("zzz" in e for e in errors)  # invented


def test_validate_coverage_flags_duplicate() -> None:
    stubs = [_stub("a")]
    errors = M.validate_coverage(stubs, [_sem("a"), _sem("a")])
    assert any("more than once" in e for e in errors)


def test_build_spec_model_stitches_stub_and_semantics() -> None:
    stubs = [_stub("getFeature")]
    ir = M.build_spec_model("aha", stubs, _dm(), [_sem("getFeature")])
    assert ir.slug == "aha"
    assert ir.api_name == "Aha"
    op = ir.operations[0]
    assert op.operation_id == "getFeature"
    assert op.path == "/getFeature"  # mechanical fact from the stub
    assert op.kind.value == "read"
    assert op.entity == "Feature"
    assert ir.validate_consistency() == []


def test_build_spec_model_attaches_evidence() -> None:
    stubs = [_stub("getFeature")]
    semantics = [_sem("getFeature")]
    evidence = {"getFeature": OperationEvidence(description="Reads one feature.")}

    ir = M.build_spec_model("aha", stubs, _dm(), semantics, evidence=evidence)

    assert ir.evidence["getFeature"].description == "Reads one feature."
    assert ir.validate_consistency() == []


def test_build_spec_model_defaults_evidence_to_empty() -> None:
    """Omitting evidence must keep the existing call signature working."""
    stubs = [_stub("getFeature")]
    semantics = [_sem("getFeature")]

    ir = M.build_spec_model("aha", stubs, _dm(), semantics)

    assert ir.evidence == {}


# Tests for compose_data_model
IDENTITY = IdentityModel(
    entities=(
        DerivedEntity(
            name="Order",
            collection="orders",
            primary_key="order_id",
            fields=(("order_id", "string"),),
            sources=("get_order__response",),
        ),
    ),
    undecidable=("Error",),
)


def _entity(name: str, collection: str, pk: str) -> Entity:
    return Entity(
        name=name,
        collection=collection,
        primary_key=pk,
        fields=[IRField(name=pk, type="string", required=True)],
    )


def test_compose_uses_enriched_entities_and_derived_store_metadata() -> None:
    enriched = [_entity("Order", "orders", "order_id")]
    dm, provenance = compose_data_model("Shop", IDENTITY, enriched, None)
    assert dm.api_name == "Shop"
    assert [e.name for e in dm.entities] == ["Order"]
    assert dm.store_metadata.collections == ["orders"]
    assert dm.store_metadata.pk_map == {"orders": "order_id"}
    assert provenance == {"Order": "derived"}


def test_compose_appends_fallback_entities_and_marks_them_llm() -> None:
    fallback = DataModel(
        api_name="Shop",
        entities=[_entity("Coupon", "coupons", "coupon_id")],
        store_metadata=StoreMetadata(
            collections=["coupons"], pk_map={"coupons": "coupon_id"}
        ),
        declined=["Error"],
    )
    dm, provenance = compose_data_model(
        "Shop", IDENTITY, [_entity("Order", "orders", "order_id")], fallback
    )
    assert [e.name for e in dm.entities] == ["Coupon", "Order"]
    assert dm.store_metadata.collections == ["coupons", "orders"]
    assert dm.store_metadata.pk_map == {"coupons": "coupon_id", "orders": "order_id"}
    assert provenance == {"Coupon": "llm", "Order": "derived"}
    assert dm.declined == ["Error"]


def test_compose_lets_the_derived_entity_win_a_collision() -> None:
    fallback = DataModel(
        api_name="Shop",
        entities=[_entity("OrderRecord", "orders", "id")],
        store_metadata=StoreMetadata(collections=["orders"], pk_map={"orders": "id"}),
    )
    dm, provenance = compose_data_model(
        "Shop", IDENTITY, [_entity("Order", "orders", "order_id")], fallback
    )
    assert [e.name for e in dm.entities] == ["Order"]
    assert dm.store_metadata.pk_map == {"orders": "order_id"}
    assert provenance == {"Order": "derived"}


def test_compose_drops_a_case_or_whitespace_variant_colliding_fallback() -> None:
    fallback = DataModel(
        api_name="Shop",
        entities=[_entity("OrderRecord", " Orders ", "id")],
        store_metadata=StoreMetadata(
            collections=[" Orders "], pk_map={" Orders ": "id"}
        ),
    )
    dm, provenance = compose_data_model(
        "Shop", IDENTITY, [_entity("Order", "orders", "order_id")], fallback
    )
    assert [e.name for e in dm.entities] == ["Order"]
    assert dm.store_metadata.pk_map == {"orders": "order_id"}
    assert provenance == {"Order": "derived"}


def test_compose_lets_the_derived_entity_win_a_name_collision() -> None:
    """A fallback entity can pass validate_data_model (distinct collection)
    while still reusing a derived entity's *name*. Without a name guard this
    silently overwrites the derived entity's "derived" provenance record
    with "llm" and produces two same-named entities in the IR."""
    fallback = DataModel(
        api_name="Shop",
        entities=[_entity("Order", "order_archive", "aid")],
        store_metadata=StoreMetadata(
            collections=["order_archive"], pk_map={"order_archive": "aid"}
        ),
    )
    dm, provenance = compose_data_model(
        "Shop", IDENTITY, [_entity("Order", "orders", "order_id")], fallback
    )
    names = [e.name for e in dm.entities]
    assert names == ["Order"]
    assert names.count("Order") == 1
    assert dm.store_metadata.pk_map == {"orders": "order_id"}
    assert provenance == {"Order": "derived"}


def test_compose_falls_back_to_structural_entities_when_enrichment_is_empty() -> None:
    dm, provenance = compose_data_model("Shop", IDENTITY, [], None)
    assert [e.name for e in dm.entities] == ["Order"]
    assert provenance == {"Order": "derived"}
