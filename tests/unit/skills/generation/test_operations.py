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


def _prompt_flat() -> str:
    """The prompt is hard-wrapped, so a load-bearing phrase can straddle a line
    break. Collapse whitespace so the assertions below test the wording rather
    than where the wrap happened to fall."""
    return " ".join(O._load_prompt().split())


def test_operation_prompt_makes_ownership_the_test_not_existence() -> None:
    """A write operation typically returns the whole resource, so "does the
    field exist on the entity" admits every field — including another
    operation's bookkeeping. Ownership has to be the test instead."""
    p = _prompt_flat()
    assert "A field family that names an operation belongs to that operation." in p
    assert "far too weak a test" in p
    assert "only that operation writes that group" in p


def test_operation_prompt_matches_ownership_across_naming_conventions() -> None:
    """The rule is the naming *relation* between a field group and an
    operation, not one convention for spelling it: a spec using
    `escalatedBy`/`escalatedAt`, or a nested object, has to match too."""
    p = _prompt_flat()
    assert "`<verb>By`/`<verb>At`, a nested `<verb>` object" in p
    assert "Match on the naming *relation*, not on one spelling of it." in p


def test_operation_prompt_scopes_the_workflow_to_the_operations_own_names() -> None:
    """A description that mentions another workflow in passing, or reads it to
    check a precondition, does not make this operation that workflow. And
    concluding "no family of mine exists, so I apply directly" settles only
    whether to defer — it is not permission to write someone else's fields."""
    p = _prompt_flat()
    assert (
        "implements the workflow named by its **own** path, operationId and summary"
        in p
    )
    assert "never a workflow its description merely mentions in passing" in p
    assert "A foreign family is doubly out of bounds" in p
    assert "name the foreign families your operation must not write" in p


def test_operation_prompt_separates_recording_an_intent_from_applying_effect() -> None:
    """Ownership decides which operation writes a dedicated field family.
    Whether this operation records a pending intent into it or applies the
    effect to the general-purpose collections is a second question, and doing
    both applies the effect twice. Word-for-word identical prose can
    distinguish neither, so the decision is sent to the schema."""
    p = _prompt_flat()
    assert "records an intent or applies an effect" in p
    assert "doing both would apply it twice" in p
    assert "Decide from the schema." in p


def test_operation_prompt_attributes_sentences_to_an_actor() -> None:
    """An obligation on the caller ("the agent must ask the user to confirm")
    is not a condition on the endpoint: the simulator cannot observe a
    conversation, so promoting it to a precondition or an error makes the state
    change unreachable. Nor is unobservability an excuse for not computing a
    value the stores already hold."""
    p = _prompt_flat()
    assert "Attribute every sentence to an actor before you act on it." in p
    assert "can never be a condition on this operation's behaviour" in p
    assert "`Caller expectations`" in p
    assert "**unconditionally**" in p
    assert 'Never answer that an operation "lacks the data"' in p


def test_operation_prompt_distinguishes_storage_shape_from_response_shape() -> None:
    """The entities handed to this stage are the storage model and may be
    normalized. When the response declares a nested value the entity does not
    carry, the two silent failures are answering with an empty object and
    forbidding the join the response needs."""
    p = _prompt_flat()
    assert "Storage shape and response shape are not the same shape." in p
    assert "Assemble it by joining." in p
    assert "Do not fall back to an empty object or array" in p
    assert "Do not forbid the reads the response needs." in p
