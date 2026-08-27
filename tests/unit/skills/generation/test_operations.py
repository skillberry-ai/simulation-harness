from unittest.mock import AsyncMock, patch

from simulation_harness.openapi.parser import OpenAPISpec
from simulation_harness.skills.generation.ir import (
    Entity,
    Field,
    Operation,
    OperationEvidence,
    OperationKind,
    SpecModel,
    StoreMetadata,
)
from simulation_harness.skills.generation.stages import operations as O
from typing import Any


def _op(oid: Any, path: Any, tag: Any = None) -> Operation:
    return Operation(
        operation_id=oid, method="GET", path=path, tag=tag, kind=OperationKind.read
    )


def _ir(ops: Any) -> SpecModel:
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


def test_plan_chunks_one_per_op_when_small() -> None:
    ir = _ir([_op("a", "/a"), _op("b", "/b")])
    chunks = O.plan_chunks(ir, threshold=40)
    assert [len(c) for c in chunks] == [1, 1]


def test_plan_chunks_groups_by_tag_when_large() -> None:
    ops = [_op(f"o{i}", f"/p{i}", tag="X" if i % 2 else "Y") for i in range(50)]
    chunks = O.plan_chunks(_ir(ops), threshold=40)
    # grouped by tag; each chunk holds a single tag
    for chunk in chunks:
        tags = {o.tag for o in chunk}
        assert len(tags) == 1
    assert sum(len(c) for c in chunks) == 50


SPEC: dict[str, Any] = {
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


CREATE_SPEC: dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {"title": "Tasks", "version": "1"},
    "paths": {
        "/tasks": {
            "post": {
                "operationId": "createTask",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/NewTask"}
                        }
                    },
                },
                "responses": {
                    "201": {
                        "description": "created",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Task"}
                            }
                        },
                    }
                },
            }
        }
    },
    "components": {
        "schemas": {
            "NewTask": {
                "type": "object",
                "required": ["title"],
                "properties": {
                    "title": {"type": "string"},
                    "completed": {"type": "boolean", "default": False},
                },
            },
            "Task": {
                "type": "object",
                "required": ["id", "title", "completed"],
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "completed": {"type": "boolean"},
                },
            },
        }
    },
}


def test_op_context_resolves_request_schema_ref() -> None:
    """The operation prompt must see the request body's own required set, not an
    opaque $ref that forces the LLM to fall back to the merged entity's required
    fields (which come from the response schema)."""
    ir = _ir([_op("createTask", "/tasks")])
    ctx = O._op_context(OpenAPISpec(CREATE_SPEC), ir, ir.operations[0])

    req = ctx["request_schema"]
    assert req is not None
    assert "$ref" not in req
    # NewTask requires only title, not completed.
    assert req.get("required") == ["title"]
    assert set(req.get("properties", {})) == {"title", "completed"}


def test_op_context_surfaces_non_200_success_response() -> None:
    """createTask responds 201, not 200 — its response shape must still reach
    the operation prompt (resolved), not be dropped by an exact-200 lookup."""
    ir = _ir([_op("createTask", "/tasks")])
    ctx = O._op_context(OpenAPISpec(CREATE_SPEC), ir, ir.operations[0])

    resp = ctx["response_schema"]
    assert resp is not None
    assert "$ref" not in resp
    assert resp.get("required") == ["id", "title", "completed"]


RESPONSE_REF_SPEC: dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {"title": "Tasks", "version": "1"},
    "paths": {
        "/tasks/{id}": {
            "get": {
                "operationId": "getTask",
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Task"}
                            }
                        },
                    }
                },
            }
        }
    },
    "components": {"schemas": {"Task": CREATE_SPEC["components"]["schemas"]["Task"]}},
}


def test_op_context_resolves_response_schema_ref() -> None:
    ir = _ir([_op("getTask", "/tasks/{id}")])
    ctx = O._op_context(OpenAPISpec(RESPONSE_REF_SPEC), ir, ir.operations[0])

    resp = ctx["response_schema"]
    assert resp is not None
    assert "$ref" not in resp
    assert resp.get("required") == ["id", "title", "completed"]


async def test_generate_section_requires_headers() -> None:
    ir = _ir([_op("getFeature", "/features/{id}")])
    good = "### /features/{id} GET\nDoes a thing."
    with patch.object(O, "call_text", AsyncMock(return_value=good)):
        section = await O.generate_section(
            OpenAPISpec(SPEC), ir, ir.operations, llm=object(), retries=0
        )
    assert "### /features/{id} GET" in section


async def test_generate_section_repairs_missing_header() -> None:
    ir = _ir([_op("getFeature", "/features/{id}")])
    bad_then_good = iter(["no header here", "### /features/{id} GET\nok"])
    with patch.object(
        O, "call_text", AsyncMock(side_effect=lambda *a, **k: next(bad_then_good))
    ):
        section = await O.generate_section(
            OpenAPISpec(SPEC), ir, ir.operations, llm=object(), retries=1
        )
    assert "### /features/{id} GET" in section


def test_operation_prompt_requests_derived_fields() -> None:
    from simulation_harness.skills.generation.stages.operations import _load_prompt

    assert "Derived fields" in _load_prompt()


def test_op_context_carries_summary_and_description() -> None:
    """Both were dropped: the contract-writing stage saw shapes only (#28)."""
    ir = _ir([_op("createTask", "/tasks")])
    ir.operations[0].summary = "Create a task."
    ir.evidence = {
        "createTask": OperationEvidence(
            description="Creates a task and appends an audit entry."
        )
    }

    ctx = O._op_context(OpenAPISpec(CREATE_SPEC), ir, ir.operations[0])

    assert ctx["summary"] == "Create a task."
    assert ctx["description"] == "Creates a task and appends an audit entry."


def test_op_context_description_none_without_evidence_entry() -> None:
    """The evidence map is sparse — a missing key is normal, not an error."""
    ir = _ir([_op("createTask", "/tasks")])
    assert ir.evidence == {}

    ctx = O._op_context(OpenAPISpec(CREATE_SPEC), ir, ir.operations[0])

    assert ctx["description"] is None


def test_operation_prompt_declares_description_normative() -> None:
    """Prose alone is not enough: the prompt also carries 'do not invent
    fields', and without this clause the model resolves the tension the
    conservative way — which is how #28 arose."""
    prompt = O._load_prompt()
    assert "behavioural contract, not commentary" in prompt
    assert "does not license inventing fields" in prompt
    assert "description" in prompt
