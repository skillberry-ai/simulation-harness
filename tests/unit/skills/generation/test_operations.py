from unittest.mock import AsyncMock, patch

from simulation_harness.openapi.parser import OpenAPISpec
from simulation_harness.skills.generation.ir import (
    Entity,
    Field,
    Operation,
    OperationKind,
    SpecModel,
    StoreMetadata,
)
from simulation_harness.skills.generation.stages import operations as O


def _op(oid, path, tag=None):
    return Operation(
        operation_id=oid, method="GET", path=path, tag=tag, kind=OperationKind.read
    )


def _ir(ops):
    return SpecModel(
        api_name="Aha",
        slug="aha",
        entities=[
            Entity(
                name="Feature",
                collection="features",
                primary_key="id",
                fields=[Field(name="id", type="string", required=True)],
            )
        ],
        operations=ops,
        store_metadata=StoreMetadata(
            collections=["features"], pk_map={"features": "id"}
        ),
    )


def test_plan_chunks_one_per_op_when_small():
    ir = _ir([_op("a", "/a"), _op("b", "/b")])
    chunks = O.plan_chunks(ir, threshold=40)
    assert [len(c) for c in chunks] == [1, 1]


def test_plan_chunks_groups_by_tag_when_large():
    ops = [_op(f"o{i}", f"/p{i}", tag="X" if i % 2 else "Y") for i in range(50)]
    chunks = O.plan_chunks(_ir(ops), threshold=40)
    # grouped by tag; each chunk holds a single tag
    for chunk in chunks:
        tags = {o.tag for o in chunk}
        assert len(tags) == 1
    assert sum(len(c) for c in chunks) == 50


SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Aha", "version": "1"},
    "paths": {
        "/features/{id}": {
            "get": {
                "operationId": "getFeature",
                "responses": {"200": {"description": "ok"}},
            }
        }
    },
}


async def test_generate_section_requires_headers():
    ir = _ir([_op("getFeature", "/features/{id}")])
    good = "### /features/{id} GET\nDoes a thing."
    with patch.object(O, "call_text", AsyncMock(return_value=good)):
        section = await O.generate_section(
            OpenAPISpec(SPEC), ir, ir.operations, llm=object(), retries=0
        )
    assert "### /features/{id} GET" in section


async def test_generate_section_repairs_missing_header():
    ir = _ir([_op("getFeature", "/features/{id}")])
    bad_then_good = iter(["no header here", "### /features/{id} GET\nok"])
    with patch.object(
        O, "call_text", AsyncMock(side_effect=lambda *a, **k: next(bad_then_good))
    ):
        section = await O.generate_section(
            OpenAPISpec(SPEC), ir, ir.operations, llm=object(), retries=1
        )
    assert "### /features/{id} GET" in section
