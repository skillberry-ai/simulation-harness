from simulation_harness.skills.generation.ir import Entity, StoreMetadata
from simulation_harness.skills.generation.stages.analyze import merge as M
from simulation_harness.skills.generation.stages.analyze.extract import DataModel


def _stub(oid):
    return {
        "operation_id": oid,
        "method": "GET",
        "path": f"/{oid}",
        "tag": "T",
        "summary": None,
    }


def _sem(oid, kind="read", entity="Feature"):
    return {"operation_id": oid, "entity": entity, "kind": kind, "patterns": ["crud"]}


def _dm():
    return DataModel(
        api_name="Aha",
        entities=[
            Entity(name="Feature", collection="features", primary_key="id", fields=[])
        ],
        store_metadata=StoreMetadata(
            collections=["features"], pk_map={"features": "id"}
        ),
    )


def test_validate_coverage_clean():
    stubs = [_stub("a"), _stub("b")]
    assert M.validate_coverage(stubs, [_sem("a"), _sem("b")]) == []


def test_validate_coverage_flags_missing_and_invented():
    stubs = [_stub("a"), _stub("b")]
    errors = M.validate_coverage(stubs, [_sem("a"), _sem("zzz")])
    assert any("b" in e for e in errors)  # missing
    assert any("zzz" in e for e in errors)  # invented


def test_validate_coverage_flags_duplicate():
    stubs = [_stub("a")]
    errors = M.validate_coverage(stubs, [_sem("a"), _sem("a")])
    assert any("more than once" in e for e in errors)


def test_build_spec_model_stitches_stub_and_semantics():
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
